"""
TDD tests for the Review-all surface (kb-wz8m.6).

Acceptance items covered:
RA1. Page is reachable (200) for a co-claimant user.
RA2. Non-claimant (logged-in stranger) is gated (403 or redirect, not 200).
RA3. Renders exactly one preview per projection for an event with ≥2 projections.
RA4. Divergent variants are both present — customized projection body AND canonical
     body appear in the rendered HTML side-by-side.
RA5. Board-fragment tests still pass after partial extraction (no regressions).
RA6. Render errors surface as visible error panels (fail-loud ADR-008 D3),
     not blank/silent cells.

Route name: syndication:review-all  (event_pk kwarg)
URL shape:  /syndication/events/<int:event_pk>/review-all/
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirror the pattern from test_projection_board.py)
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name="Test Organizer", slug="test-organizer", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(slug="ra-test-event", **kwargs):
    defaults = {
        "title": "Review-All Test Event",
        "slug": slug,
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_connection(profile, platform="telegram", destination_id="tg-channel", kinds=None, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds or ["listing", "promotion"],
        enabled=enabled,
    )


def _make_content_version(event, name="canonical", body=None, provenance="rule_template"):
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name=name,
        defaults={"provenance": provenance, "body": body},
    )
    if body is not None and cv.body != body:
        cv.body = body
        cv.save(update_fields=["body"])
    return cv


def _make_listing_projection(connection, event, status="draft", content_version=None, provenance="rule_template"):
    if content_version is None:
        content_version = _make_content_version(event, provenance=provenance)
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        connection=connection,
        source_event=event,
        content_version=content_version,
    )


# ---------------------------------------------------------------------------
# RA1/RA2. Access control
# ---------------------------------------------------------------------------


class ReviewAllAccessTest(TestCase):
    """
    RA1. Co-claimant gets 200.
    RA2. Non-claimant (logged-in) is gated (not 200).
    """

    def setUp(self):
        # Organizer (co-claimant)
        self.owner = _make_vouched_user(username="ra_owner", email="ra_owner@test.com", password="pw")
        self.profile = _make_profile(name="RA Org", slug="ra-org", user=self.owner)
        self.event = _make_event(slug="ra-access-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)

        # Stranger
        self.stranger = _make_vouched_user(username="ra_stranger", email="ra_stranger@test.com", password="pw")

        self.owner_client = Client()
        self.owner_client.force_login(self.owner)

        self.stranger_client = Client()
        self.stranger_client.force_login(self.stranger)

    def _url(self):
        from django.urls import reverse

        return reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})

    def test_co_claimant_gets_200(self):
        """RA1: co-claimant must get a 200 response."""
        response = self.owner_client.get(self._url())
        self.assertEqual(response.status_code, 200)

    def test_non_claimant_is_gated(self):
        """RA2: a logged-in user with no claim on the event must get 403."""
        response = self.stranger_client.get(self._url())
        self.assertEqual(
            response.status_code, 403, "Non-claimant must be rejected with 403, not silently redirected or let through"
        )


# ---------------------------------------------------------------------------
# RA3. One preview per projection
# ---------------------------------------------------------------------------


class ReviewAllOnePreviewPerProjectionTest(TestCase):
    """
    RA3: review-all renders exactly one preview per projection for an event with ≥2 projections.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="ra_proj_user", email="ra_proj@test.com", password="pw")
        self.profile = _make_profile(name="RA Proj Org", slug="ra-proj-org", user=self.user)
        self.event = _make_event(slug="ra-proj-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)

        # Two different platform connections
        self.conn_tg = _make_connection(self.profile, platform="telegram", destination_id="tg-ra")
        self.conn_fl = _make_connection(self.profile, platform="fetlife", destination_id="fl-ra")

        self.client = Client()
        self.client.force_login(self.user)

    def _url(self):
        from django.urls import reverse

        return reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})

    def test_renders_one_preview_per_projection(self):
        """
        With 2 projections on the event, review-all must render exactly 2 <article> panels
        in the HTML — one per projection. Fails if the {% for %} loop silently drops a row.
        """
        cv = _make_content_version(self.event)
        _make_listing_projection(self.conn_tg, self.event, content_version=cv)
        _make_listing_projection(self.conn_fl, self.event, content_version=cv)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        # review_all.html emits one <article …> per projection row (the platform-tinted card panel).
        # Count opening <article tags as the per-preview sentinel.
        article_count = html.count("<article")
        self.assertEqual(
            article_count, 2, f"Expected 2 <article> panels in rendered HTML (one per projection), got {article_count}"
        )


# ---------------------------------------------------------------------------
# RA4. Divergent variants both visible
# ---------------------------------------------------------------------------


class ReviewAllDivergentVariantsTest(TestCase):
    """
    RA4: Customize one projection to a distinct body — BOTH the canonical body
    AND the customized body appear in the rendered HTML.
    """

    CANONICAL_BODY = "Canonical event body for review-all test"
    CUSTOM_BODY = "Custom channel-specific body DIVERGENT variant"

    def setUp(self):
        self.user = _make_vouched_user(username="ra_div_user", email="ra_div@test.com", password="pw")
        self.profile = _make_profile(name="RA Div Org", slug="ra-div-org", user=self.user)
        self.event = _make_event(slug="ra-div-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)

        self.conn_tg = _make_connection(self.profile, platform="telegram", destination_id="tg-div")
        self.conn_fl = _make_connection(self.profile, platform="fetlife", destination_id="fl-div")

        self.client = Client()
        self.client.force_login(self.user)

    def _url(self):
        from django.urls import reverse

        return reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})

    def test_both_canonical_and_custom_body_in_html(self):
        """
        RA4: canonical body and custom body are both rendered in the HTML.
        """
        # Projection 1: canonical body
        canonical_cv = _make_content_version(self.event, name="canonical", body=self.CANONICAL_BODY)
        _make_listing_projection(self.conn_tg, self.event, content_version=canonical_cv)

        # Projection 2: separate content version with custom body
        custom_cv = _make_content_version(self.event, name="custom-fl", body=self.CUSTOM_BODY)
        _make_listing_projection(self.conn_fl, self.event, content_version=custom_cv)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        self.assertIn(self.CANONICAL_BODY, html, "Canonical body must appear in the rendered HTML")
        self.assertIn(self.CUSTOM_BODY, html, "Custom/divergent body must appear in the rendered HTML")


# ---------------------------------------------------------------------------
# RA6. Render errors surface visibly (fail-loud ADR-008 D3)
# ---------------------------------------------------------------------------


class ReviewAllRenderErrorTest(TestCase):
    """
    RA6: A projection whose render fails must surface a visible error panel,
    not a blank/silent cell.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="ra_err_user", email="ra_err@test.com", password="pw")
        self.profile = _make_profile(name="RA Err Org", slug="ra-err-org", user=self.user)
        self.event = _make_event(slug="ra-err-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="telegram", destination_id="tg-err")
        self.client = Client()
        self.client.force_login(self.user)

    def _url(self):
        from django.urls import reverse

        return reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})

    def test_render_error_is_visible_in_html(self):
        """
        RA6 (ADR-008 D3 fail-loud): when the engine raises ValueError, the rendered HTML
        must contain the visible error panel markup that _channel_preview.html emits.
        Fails if the {% if render_error %} branch were removed from the partial.
        """
        from unittest.mock import patch

        cv = _make_content_version(self.event, name="canonical")
        _make_listing_projection(self.conn, self.event, content_version=cv)

        with patch("syndication.engine.render_projection", side_effect=ValueError("forced error")):
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # _channel_preview.html emits `kb-tag-error` inside the error panel branch.
        # Asserting on rendered HTML ensures the error is actually visible, not just stored in context.
        self.assertIn(
            "kb-tag-error",
            html,
            "Error panel markup (kb-tag-error) must appear in rendered HTML when render fails (ADR-008 D3)",
        )


# ---------------------------------------------------------------------------
# RA5. Back-link to board is present in the HTML
# ---------------------------------------------------------------------------


class ReviewAllBackLinkTest(TestCase):
    """
    RA5: The review-all page must contain a clear way back to the board (event hub).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="ra_back_user", email="ra_back@test.com", password="pw")
        self.profile = _make_profile(name="RA Back Org", slug="ra-back-org", user=self.user)
        self.event = _make_event(slug="ra-back-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def _url(self):
        from django.urls import reverse

        return reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})

    def test_back_link_to_board_present(self):
        """
        The rendered HTML must include a link back to the event hub (board).
        """
        from django.urls import reverse

        hub_url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(hub_url, html, f"Expected hub URL {hub_url!r} to appear in the review-all HTML (back-link)")
