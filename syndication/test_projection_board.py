"""
TDD tests for the projection review board (kb-a4u.5).

Acceptance items covered:
A1. Board renders one row per eager-created projection with correct status-chip
    + provenance-tag.
A2. Inline override-edit persists to override_data AND flips provenance to
    "manual" (PlatformProjection.Provenance.MANUAL).
A3. Approve (draft→ready) works via service and freezes content.
A4. Explicit publish (ready→published) works via service AND board action URL.
A5. mark-published: API verb and UI path hit the same service function.
A6. Five empty/error states render their specified affordances.
A7. mark-published is a co-equal API verb (in api.py), not UI-only.
A8. Fragment view includes both listing AND promotion projections (not just
    source_event projections).

Co-equal seam: all service functions are called from both API handlers and
HTMX view actions — no duplicate logic.

ADR-008 D3: fail loud — no silent zero-fill, provenance always explicit.
ADR-016 D5: lifecycle actions go through transition_status exclusively.
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
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


def _make_event(slug="test-event", **kwargs):
    defaults = {
        "title": "Test Event",
        "slug": slug,
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, **kwargs):
    defaults = {"headline": "Come join us!", "body": "Great event."}
    defaults.update(kwargs)
    return Post.objects.create(event=event, **defaults)


def _make_connection(profile, platform="fetlife", destination_id="fl-user", kinds=None, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds or ["listing", "promotion"],
        enabled=enabled,
    )


def _make_listing_projection(connection, event, status="draft", provenance="rule_template"):
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        connection=connection,
        source_event=event,
        provenance=provenance,
    )


def _make_promotion_projection(connection, post, status="draft", provenance="rule_template"):
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.PROMOTION,
        status=status,
        connection=connection,
        source_post=post,
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# A1. Board fragment: one row per projection, status-chip + provenance-tag
# ---------------------------------------------------------------------------


class BoardFragmentRenderTest(TestCase):
    """
    The event_syndication fragment renders one row per projection with
    correct status-chip and provenance-tag.

    These tests check context data (not the exact HTML text) to avoid
    template coupling, while asserting on actual values.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="board_user", email="board@test.com", password="pw")
        self.profile = _make_profile(name="Board Org", slug="board-org", user=self.user)
        self.event = _make_event(slug="board-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-board")
        self.client = Client()
        self.client.force_login(self.user)

    def test_fragment_renders_one_row_per_projection(self):
        """
        Board must show exactly one row per projection that exists for the event.
        """
        proj1 = _make_listing_projection(self.conn, self.event)
        post = _make_post(self.event)
        proj2 = _make_promotion_projection(self.conn, post)

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        # Context must contain both projections
        projections = list(response.context["projections"])
        self.assertEqual(len(projections), 2)
        pk_set = {p.pk for p in projections}
        self.assertIn(proj1.pk, pk_set)
        self.assertIn(proj2.pk, pk_set)

    def test_fragment_includes_promotion_projections(self):
        """
        The fragment must show promotion projections (source_post-linked),
        not only listing projections (source_event-linked).
        """
        post = _make_post(self.event)
        promo_proj = _make_promotion_projection(self.conn, post)

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        pk_set = {p.pk for p in projections}
        self.assertIn(promo_proj.pk, pk_set, "Promotion projection must appear in board")

    def test_fragment_projection_carries_status(self):
        """Each projection in context has the correct status value."""
        proj = _make_listing_projection(self.conn, self.event, status="draft")

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        proj_in_ctx = next(p for p in projections if p.pk == proj.pk)
        self.assertEqual(proj_in_ctx.status, "draft")

    def test_fragment_projection_carries_provenance(self):
        """Each projection in context has the correct provenance value."""
        proj = _make_listing_projection(
            self.conn, self.event, provenance="agent_supplied"
        )

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        proj_in_ctx = next(p for p in projections if p.pk == proj.pk)
        self.assertEqual(proj_in_ctx.provenance, "agent_supplied")

    def test_fragment_projection_carries_connection_info(self):
        """Each projection carries connection (platform, destination_id)."""
        _make_listing_projection(self.conn, self.event)

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        self.assertTrue(len(projections) >= 1)
        proj_in_ctx = projections[0]
        self.assertEqual(proj_in_ctx.connection.platform, "fetlife")

    def test_fragment_carries_effective_copy(self):
        """
        Fragment context includes rendered_body for each projection
        (the effective copy preview per the board spec).
        """
        _make_listing_projection(self.conn, self.event)

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        # rendered_rows must exist in context, keyed by projection PK
        self.assertIn("rendered_rows", response.context)
        rendered_rows = response.context["rendered_rows"]
        # At least one entry, and each value is a string (rendered body)
        self.assertTrue(len(rendered_rows) >= 1)
        for pk, body in rendered_rows.items():
            self.assertIsInstance(body, str)


# ---------------------------------------------------------------------------
# A2. Override-edit: persists to override_data AND flips provenance to manual
# ---------------------------------------------------------------------------


class OverrideEditServiceTest(TestCase):
    """
    save_projection_override service: persists override_data fields AND
    flips provenance to manual (PlatformProjection.Provenance.MANUAL).

    ADR-008 D3: no silent zero-fill — raise if projection not found.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="edit_user", email="edit@test.com", password="pw")
        self.profile = _make_profile(name="Edit Org", slug="edit-org", user=self.user)
        self.event = _make_event(slug="edit-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-edit")

    def test_save_override_persists_body_to_override_data(self):
        """
        Calling save_projection_override with body="edited copy" stores
        override_data["body"] = "edited copy" on the projection.
        """
        from syndication.services import save_projection_override

        proj = _make_listing_projection(self.conn, self.event)
        save_projection_override(user=self.user, projection=proj, body="edited copy")
        proj.refresh_from_db()
        self.assertEqual(proj.override_data.get("body"), "edited copy")

    def test_save_override_flips_provenance_to_manual(self):
        """
        After save_projection_override, provenance must be 'manual'
        regardless of its prior value (rule_template or agent_supplied).
        """
        from syndication.services import save_projection_override

        proj = _make_listing_projection(self.conn, self.event, provenance="rule_template")
        save_projection_override(user=self.user, projection=proj, body="human edit")
        proj.refresh_from_db()
        self.assertEqual(
            proj.provenance,
            "manual",
            "save_projection_override must flip provenance to 'manual'",
        )

    def test_save_override_from_agent_supplied_also_flips_to_manual(self):
        """
        Editing an agent_supplied projection also flips to manual.
        Human edit always wins provenance.
        """
        from syndication.services import save_projection_override

        proj = _make_listing_projection(self.conn, self.event, provenance="agent_supplied")
        save_projection_override(user=self.user, projection=proj, body="overriding agent")
        proj.refresh_from_db()
        self.assertEqual(proj.provenance, "manual")

    def test_save_override_gated_by_can_edit(self):
        """
        save_projection_override raises PermissionError if user cannot edit the event.
        """
        from syndication.services import save_projection_override

        other_user = _make_vouched_user(
            username="stranger", email="stranger@test.com", password="pw"
        )
        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(PermissionError):
            save_projection_override(user=other_user, projection=proj, body="not allowed")


class OverrideEditViewTest(TestCase):
    """
    HTMX view for override-edit POSTs through to save_projection_override service.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="editview_user", email="editview@test.com", password="pw"
        )
        self.profile = _make_profile(name="EditView Org", slug="editview-org", user=self.user)
        self.event = _make_event(slug="editview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-editview")
        self.client = Client()
        self.client.force_login(self.user)

    def test_override_edit_view_persists_body(self):
        """
        POST to the override-edit view stores override_data["body"] on the projection.
        """
        proj = _make_listing_projection(self.conn, self.event)
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/override/",
            data={"body": "view-driven edit"},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.override_data.get("body"), "view-driven edit")

    def test_override_edit_view_flips_provenance(self):
        """
        POST to override-edit view also flips provenance to manual.
        """
        proj = _make_listing_projection(self.conn, self.event, provenance="rule_template")
        self.client.post(
            f"/syndication/projections/{proj.pk}/override/",
            data={"body": "manual override"},
            HTTP_HX_REQUEST="true",
        )
        proj.refresh_from_db()
        self.assertEqual(proj.provenance, "manual")


# ---------------------------------------------------------------------------
# A3. Approve (draft→ready) service + view
# ---------------------------------------------------------------------------


class ApproveProjectionServiceTest(TestCase):
    """
    approve_projection service: transitions draft→ready, freezes content.
    Uses transition_status exclusively (ADR-016 D5).
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="approve_user", email="approve@test.com", password="pw"
        )
        self.profile = _make_profile(name="Approve Org", slug="approve-org", user=self.user)
        self.event = _make_event(slug="approve-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-approve")

    def test_approve_transitions_draft_to_ready(self):
        """approve_projection transitions projection from draft to ready."""
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "ready")

    def test_approve_freezes_content(self):
        """
        After approve_projection, frozen_content is populated (not None).
        The freeze captures the effective body at approval time.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertIsNotNone(
            proj.frozen_content,
            "frozen_content must be set after approve (draft→ready)",
        )
        self.assertIn("body", proj.frozen_content)

    def test_approve_gated_by_can_edit(self):
        """
        approve_projection raises PermissionError if user cannot edit the event.
        """
        from syndication.services import approve_projection

        other_user = _make_vouched_user(
            username="approve_stranger", email="apstrange@test.com", password="pw"
        )
        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(PermissionError):
            approve_projection(user=other_user, projection=proj)

    def test_approve_on_already_ready_raises(self):
        """
        Approving a non-draft projection raises ValueError (illegal transition).
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event, status="draft")
        # First approve → ready
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        # Second approve → already ready, illegal
        with self.assertRaises(ValueError):
            approve_projection(user=self.user, projection=proj)


class ApproveProjectionViewTest(TestCase):
    """
    HTMX view for approve action calls through to approve_projection service.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="apprvview_user", email="apprvview@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="ApproveView Org", slug="approveview-org", user=self.user
        )
        self.event = _make_event(slug="approveview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-approveview")
        self.client = Client()
        self.client.force_login(self.user)

    def test_approve_view_transitions_to_ready(self):
        """POST to approve view transitions projection to ready."""
        proj = _make_listing_projection(self.conn, self.event)
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "ready")


# ---------------------------------------------------------------------------
# A4. Publish (ready→published) service + view
# ---------------------------------------------------------------------------


class PublishProjectionServiceTest(TestCase):
    """
    publish_projection service: transitions ready→published.
    EXPLICIT action only — never auto-triggers on approve.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="pub_user", email="pub@test.com", password="pw"
        )
        self.profile = _make_profile(name="Pub Org", slug="pub-org", user=self.user)
        self.event = _make_event(slug="pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-pub")

    def _make_ready_projection(self):
        """Helper: create a projection and advance it to ready status."""
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_publish_transitions_ready_to_published(self):
        """publish_projection transitions projection from ready to published."""
        from syndication.services import publish_projection

        proj = self._make_ready_projection()
        publish_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

    def test_approve_does_NOT_auto_publish(self):
        """
        Approving a projection must NOT auto-publish it.
        After approve, status must be 'ready', NOT 'published'.
        ADR-016 D5: publish is always an explicit action.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(
            proj.status,
            "ready",
            "Approve must land on 'ready', not 'published' (publish is always explicit)",
        )

    def test_publish_gated_by_can_publish(self):
        """publish_projection raises PermissionError for non-organizer."""
        from syndication.services import publish_projection

        proj = self._make_ready_projection()
        other_user = _make_vouched_user(
            username="pub_stranger", email="pubstrange@test.com", password="pw"
        )
        with self.assertRaises(PermissionError):
            publish_projection(user=other_user, projection=proj)

    def test_publish_draft_raises(self):
        """Cannot publish a draft projection (must approve first)."""
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(ValueError):
            publish_projection(user=self.user, projection=proj)


class PublishProjectionViewTest(TestCase):
    """
    HTMX view for publish action calls through to publish_projection service.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="pubview_user", email="pubview@test.com", password="pw"
        )
        self.profile = _make_profile(name="PubView Org", slug="pubview-org", user=self.user)
        self.event = _make_event(slug="pubview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-pubview")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_publish_view_transitions_to_published(self):
        """POST to publish view transitions projection to published."""
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/publish/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")


# ---------------------------------------------------------------------------
# A5. mark-published: co-equal API verb + UI path hit the same service function
# ---------------------------------------------------------------------------


class MarkPublishedServiceTest(TestCase):
    """
    mark_projection_published service: transitions a projection to published
    for no-API platforms (actor-attested, out-of-band posting).

    The service must be the shared implementation called by both the API verb
    and the HTMX view action (co-equal seam, ADR-016 D6).
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="markpub_user", email="markpub@test.com", password="pw"
        )
        self.profile = _make_profile(name="MarkPub Org", slug="markpub-org", user=self.user)
        self.event = _make_event(slug="markpub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-markpub")

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_mark_published_transitions_to_published(self):
        """mark_projection_published service transitions ready→published."""
        from syndication.services import mark_projection_published

        proj = self._make_ready_projection()
        mark_projection_published(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

    def test_mark_published_gated_by_can_publish(self):
        """mark_projection_published raises PermissionError for non-organizer."""
        from syndication.services import mark_projection_published

        proj = self._make_ready_projection()
        other_user = _make_vouched_user(
            username="markpub_stranger", email="markpubst@test.com", password="pw"
        )
        with self.assertRaises(PermissionError):
            mark_projection_published(user=other_user, projection=proj)

    def test_mark_published_draft_raises(self):
        """Cannot mark-published a draft (must be ready first)."""
        from syndication.services import mark_projection_published

        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(ValueError):
            mark_projection_published(user=self.user, projection=proj)


class MarkPublishedAPITest(TestCase):
    """
    API verb for mark-published: must be a co-equal endpoint in api.py,
    not a UI-only button.

    ADR-016 D6: the API verb and UI path both call mark_projection_published service.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="markpub_api_user",
            email="markpub_api@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="MarkPub API Org", slug="markpub-api-org", user=self.user
        )
        self.event = _make_event(slug="markpub-api-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-markpub-api")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_api_mark_published_endpoint_exists(self):
        """
        POST /api/projections/{id}/mark-published/ must return 200 (not 404/405).
        This verifies the endpoint is registered as a co-equal API verb.
        """
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/api/projections/{proj.pk}/mark-published/",
            content_type="application/json",
        )
        # Must not be 404 (endpoint exists) and not 405 (method allowed)
        self.assertNotEqual(response.status_code, 404, "mark-published API endpoint missing")
        self.assertNotEqual(response.status_code, 405, "mark-published API endpoint not POST")
        self.assertIn(
            response.status_code, [200, 201, 204],
            f"Expected success status, got {response.status_code}",
        )

    def test_api_mark_published_transitions_to_published(self):
        """POST to API mark-published endpoint transitions projection to published."""
        proj = self._make_ready_projection()
        self.client.post(
            f"/api/projections/{proj.pk}/mark-published/",
            content_type="application/json",
        )
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")



class MarkPublishedViewTest(TestCase):
    """HTMX view path for mark-published calls mark_projection_published service."""

    def setUp(self):
        self.user = _make_vouched_user(
            username="markpub_view_user", email="markpubview@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="MarkPub View Org", slug="markpubview-org", user=self.user
        )
        self.event = _make_event(slug="markpubview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-markpubview")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_view_mark_published_transitions_to_published(self):
        """POST to HTMX mark-published view transitions projection to published."""
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/mark-published/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")


# ---------------------------------------------------------------------------
# A6. Empty/error states
# ---------------------------------------------------------------------------


class EmptyStatesTest(TestCase):
    """
    Five empty/error states per the board spec (priority order):
    1. No connections configured → "Connect platforms in settings to start syndicating →"
    2. No promo Posts yet → "No promo posts yet" + [Add promo message] CTA
    3. Connection broken/expired → surfaced at affected projection row (not implemented at v0, skip)
    4. Seed/generation failure → row shows "couldn't generate — missing X" (NOT blank body)
    5. Content-policy flag → pre-publish warning on row (not implemented at v0, skip)

    Tests 1 and 2 are verified here. Tests 3 and 5 are deferred to live-browser
    (require platform-specific adapter state). Test 4 is covered by ADR-008 D3
    (ValueError on render when body cannot be derived).
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="empty_user", email="empty@test.com", password="pw"
        )
        self.profile = _make_profile(name="Empty Org", slug="empty-org", user=self.user)
        self.event = _make_event(slug="empty-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_no_connections_state_shows_connect_platforms_message(self):
        """
        When no connections exist, the board must show a "Connect platforms" CTA,
        NOT an empty/broken panel.

        State 1: No connections configured.
        """
        # Ensure no connections, no projections for this event
        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The board must show something actionable, not a blank panel
        # Looking for the connect-platforms CTA text
        self.assertIn(
            "connect",
            content.lower(),
            "Empty board without connections must show a 'Connect platforms' CTA",
        )

    def test_no_connections_state_shows_settings_link(self):
        """State 1: The 'connect platforms' state must include a link to settings/connections."""
        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        content = response.content.decode()
        # Must have a link to the connections management page
        self.assertIn(
            "/connections/",
            content,
            "No-connections state must include link to connections management",
        )

    def test_has_connections_context_flag(self):
        """
        Fragment context must carry has_connections flag to distinguish
        state 1 (no connections) from state 2 (connections but no posts).
        """
        # No connections
        response_no_conn = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertIn("has_connections", response_no_conn.context)
        self.assertFalse(response_no_conn.context["has_connections"])

        # Add a connection
        _make_connection(self.profile, destination_id="fl-has-conn", kinds=["listing"])
        response_with_conn = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertIn("has_connections", response_with_conn.context)
        self.assertTrue(response_with_conn.context["has_connections"])


# ---------------------------------------------------------------------------
# A7. Verify mark-published is a co-equal API verb (structural check)
# ---------------------------------------------------------------------------


class MarkPublishedAPIVerbStructureTest(TestCase):
    """
    Structural verification: mark_projection_published must be importable from
    syndication.services (co-equal seam requirement).
    """

    def test_mark_projection_published_importable_from_services(self):
        """mark_projection_published must exist in syndication.services."""
        from syndication import services
        self.assertTrue(
            hasattr(services, "mark_projection_published"),
            "mark_projection_published must be in syndication.services (co-equal seam)",
        )

    def test_approve_projection_importable_from_services(self):
        """approve_projection must exist in syndication.services."""
        from syndication import services
        self.assertTrue(
            hasattr(services, "approve_projection"),
            "approve_projection must be in syndication.services",
        )

    def test_publish_projection_importable_from_services(self):
        """publish_projection must exist in syndication.services."""
        from syndication import services
        self.assertTrue(
            hasattr(services, "publish_projection"),
            "publish_projection must be in syndication.services",
        )

    def test_save_projection_override_importable_from_services(self):
        """save_projection_override must exist in syndication.services."""
        from syndication import services
        self.assertTrue(
            hasattr(services, "save_projection_override"),
            "save_projection_override must be in syndication.services",
        )


# ---------------------------------------------------------------------------
# Item 1: ValueError swallow — views must surface illegal-transition error
# ---------------------------------------------------------------------------


class IllegalTransitionViewErrorTest(TestCase):
    """
    ADR-008 D3 fail-loud: approving/publishing/mark-publishing an already-done
    projection raises ValueError. The views must NOT swallow this — they must
    render a visible error state, not return a success-shaped fragment.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="err_user", email="err@test.com", password="pw")
        self.profile = _make_profile(name="Err Org", slug="err-org", user=self.user)
        self.event = _make_event(slug="err-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-err")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection
        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_approve_already_ready_returns_error_state_not_success(self):
        """
        POSTing approve on an already-ready projection must return an error response,
        not a success-shaped fragment. The response body must contain the error reason.
        """
        proj = self._make_ready_projection()  # status=ready
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must NOT silently return success — must surface the error
        self.assertIn(
            "error",
            content.lower(),
            "Approve on already-ready projection must surface an error, not silently succeed",
        )

    def test_publish_draft_view_returns_error_state_not_success(self):
        """
        POSTing publish on a draft projection must return an error response
        (publish requires ready state first).
        """
        proj = _make_listing_projection(self.conn, self.event)  # status=draft
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/publish/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "error",
            content.lower(),
            "Publish on draft projection must surface an error, not silently succeed",
        )

    def test_mark_published_draft_view_returns_error_state_not_success(self):
        """
        POSTing mark-published on a draft projection must return an error response.
        """
        proj = _make_listing_projection(self.conn, self.event)  # status=draft
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/mark-published/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "error",
            content.lower(),
            "Mark-published on draft projection must surface an error, not silently succeed",
        )


# ---------------------------------------------------------------------------
# Item 3: No duplicate _get_projection_event helpers — views/api use services
# ---------------------------------------------------------------------------


class ResolvProjectionEventSingleSourceTest(TestCase):
    """
    ADR-008 D2 one-clear-path: views and api must NOT define their own
    _get_projection_event / _projection_event helpers.
    They must import and call _resolve_projection_event from syndication.services.
    """

    def test_views_has_no_private_get_projection_event(self):
        """views.py must not define _get_projection_event (use services version)."""
        import syndication.views as views_mod
        self.assertFalse(
            hasattr(views_mod, "_get_projection_event"),
            "_get_projection_event must be removed from views.py; use services._resolve_projection_event",
        )

    def test_api_has_no_private_projection_event(self):
        """api.py must not define _projection_event (use services version)."""
        import syndication.api as api_mod
        self.assertFalse(
            hasattr(api_mod, "_projection_event"),
            "_projection_event must be removed from api.py; use services._resolve_projection_event",
        )

    def test_resolve_projection_event_raises_on_missing_source_event(self):
        """
        _resolve_projection_event (services) must raise ValueError when a listing
        projection has no source_event (ADR-008 D3 fail-loud).
        """
        from syndication.services import _resolve_projection_event
        from syndication.models import PlatformProjection

        class FakeListing:
            kind = PlatformProjection.Kind.LISTING
            pk = 99
            source_event = None

        with self.assertRaises(ValueError):
            _resolve_projection_event(FakeListing())


# ---------------------------------------------------------------------------
# Item 4: Render-failure structural flag in context/template
# ---------------------------------------------------------------------------


class RenderErrorStructuralFlagTest(TestCase):
    """
    ADR-008 D3: render failure must be structurally distinct, not a magic string.
    The view must pass an explicit per-row error flag so the template can render
    a visually-distinct error treatment.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="renerr_user", email="renerr@test.com", password="pw")
        self.profile = _make_profile(name="RenErr Org", slug="renerr-org", user=self.user)
        self.event = _make_event(slug="renerr-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-renerr")
        self.client = Client()
        self.client.force_login(self.user)

    def test_projection_row_carries_render_error_flag(self):
        """
        When render_projection raises ValueError, the projection_rows entry must
        carry render_error=True so the template can render a distinct error state.
        """
        from unittest.mock import patch
        _make_listing_projection(self.conn, self.event)

        with patch("syndication.engine.render_projection", side_effect=ValueError("missing field")):
            response = self.client.get(
                f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
            )
        self.assertEqual(response.status_code, 200)
        projection_rows = response.context["projection_rows"]
        self.assertTrue(len(projection_rows) >= 1)
        row = projection_rows[0]
        self.assertIn("render_error", row, "projection_rows must have render_error key")
        self.assertTrue(row["render_error"], "render_error must be True when render raises ValueError")

    def test_render_error_template_renders_distinct_error_class(self):
        """
        When render_error=True, the template must render the error body with a
        distinct error CSS class (not as normal body copy).
        """
        from unittest.mock import patch
        _make_listing_projection(self.conn, self.event)

        with patch("syndication.engine.render_projection", side_effect=ValueError("missing field")):
            response = self.client.get(
                f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
            )
        content = response.content.decode()
        # Error must use a distinct error class/treatment
        self.assertIn(
            "kb-tag-error",
            content,
            "Render failure must render with kb-tag-error class, not normal copy",
        )


# ---------------------------------------------------------------------------
# Item 5: has_promotion_connections must filter by kinds containing "promotion"
# ---------------------------------------------------------------------------


class HasPromotionConnectionsFilterTest(TestCase):
    """
    has_promotion_connections must filter for connections whose kinds JSON list
    contains "promotion". A listing-only connection must not set it True.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="promoconn_user", email="promoconn@test.com", password="pw")
        self.profile = _make_profile(name="PromConn Org", slug="promconn-org", user=self.user)
        self.event = _make_event(slug="promconn-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_listing_only_connection_does_not_set_has_promotion_connections(self):
        """
        A connection with kinds=["listing"] must NOT set has_promotion_connections=True.
        """
        _make_connection(self.profile, destination_id="fl-listing-only", kinds=["listing"])
        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        # has_promotion_connections must be False because no promotion-capable connections
        # The test checks no_promo_posts is False because the connection doesn't support promotion
        self.assertFalse(
            response.context["no_promo_posts"],
            "no_promo_posts must be False when only listing connections exist",
        )

    def test_promotion_connection_sets_has_promotion_connections(self):
        """
        A connection with kinds=["promotion"] and no posts must set no_promo_posts=True.
        """
        _make_connection(self.profile, destination_id="fl-promo-only", kinds=["promotion"])
        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.context["no_promo_posts"],
            "no_promo_posts must be True when promotion connection exists but no posts",
        )


# ---------------------------------------------------------------------------
# Item 6: Batch "publish all ready"
# ---------------------------------------------------------------------------


class BatchPublishAllReadyServiceTest(TestCase):
    """
    publish_all_ready_projections service: publishes every ready projection
    for an event in a single call. Skips non-ready rows. Gated by can_publish.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="batch_user", email="batch@test.com", password="pw")
        self.profile = _make_profile(name="Batch Org", slug="batch-org", user=self.user)
        self.event = _make_event(slug="batch-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-batch")

    def _make_ready_projection(self, event=None, **kwargs):
        from syndication.services import approve_projection
        proj = _make_listing_projection(self.conn, event or self.event, **kwargs)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_batch_publishes_all_ready_rows(self):
        """publish_all_ready_projections publishes every ready projection."""
        from syndication.services import publish_all_ready_projections

        proj1 = self._make_ready_projection()
        proj2 = self._make_ready_projection()
        publish_all_ready_projections(user=self.user, event=self.event)
        proj1.refresh_from_db()
        proj2.refresh_from_db()
        self.assertEqual(proj1.status, "published")
        self.assertEqual(proj2.status, "published")

    def test_batch_skips_non_ready_rows(self):
        """publish_all_ready_projections skips draft/published projections."""
        from syndication.services import publish_all_ready_projections

        draft_proj = _make_listing_projection(self.conn, self.event)  # stays draft
        ready_proj = self._make_ready_projection()
        publish_all_ready_projections(user=self.user, event=self.event)
        draft_proj.refresh_from_db()
        ready_proj.refresh_from_db()
        self.assertEqual(draft_proj.status, "draft", "Draft projection must not be touched by batch publish")
        self.assertEqual(ready_proj.status, "published")

    def test_batch_publish_gated_by_can_publish(self):
        """publish_all_ready_projections raises PermissionError for non-organizer."""
        from syndication.services import publish_all_ready_projections

        self._make_ready_projection()
        other_user = _make_vouched_user(username="batch_stranger", email="batchst@test.com", password="pw")
        with self.assertRaises(PermissionError):
            publish_all_ready_projections(user=other_user, event=self.event)

    def test_batch_returns_list_of_published_projections(self):
        """publish_all_ready_projections returns (published, failures) where published has the published projections."""
        from syndication.services import publish_all_ready_projections

        proj1 = self._make_ready_projection()
        proj2 = self._make_ready_projection()
        published, failures = publish_all_ready_projections(user=self.user, event=self.event)
        published_pks = {p.pk for p in published}
        self.assertIn(proj1.pk, published_pks)
        self.assertIn(proj2.pk, published_pks)
        self.assertEqual(failures, [], "No failures expected in happy path")


class BatchPublishViewTest(TestCase):
    """HTMX view for batch publish calls publish_all_ready_projections service."""

    def setUp(self):
        self.user = _make_vouched_user(username="batchview_user", email="batchview@test.com", password="pw")
        self.profile = _make_profile(name="BatchView Org", slug="batchview-org", user=self.user)
        self.event = _make_event(slug="batchview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-batchview")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection
        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_batch_publish_view_publishes_all_ready(self):
        """POST to batch-publish view transitions all ready projections to published."""
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/syndication/events/{self.event.pk}/projections/publish-all-ready/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

    def test_batch_publish_view_authz_gated(self):
        """POST to batch-publish view by non-organizer returns 403."""
        self._make_ready_projection()
        other_client = Client()
        other_user = _make_vouched_user(username="batchview_stranger", email="bvst@test.com", password="pw")
        other_client.force_login(other_user)
        response = other_client.post(
            f"/syndication/events/{self.event.pk}/projections/publish-all-ready/",
        )
        self.assertEqual(response.status_code, 403)

    def test_batch_publish_view_and_api_call_same_service(self):
        """
        Both the HTMX batch-publish view and the API batch endpoint must import
        publish_all_ready_projections from syndication.services — the same object.
        This verifies the co-equal seam (ADR-016 D6) at import time.
        """
        import syndication.api as api_mod
        import syndication.views as views_mod
        import syndication.services as services_mod

        self.assertIs(
            api_mod.publish_all_ready_projections,
            services_mod.publish_all_ready_projections,
            "syndication.api.publish_all_ready_projections must be the same object as syndication.services.publish_all_ready_projections",
        )
        self.assertIs(
            views_mod.publish_all_ready_projections,
            services_mod.publish_all_ready_projections,
            "syndication.views.publish_all_ready_projections must be the same object as syndication.services.publish_all_ready_projections",
        )


# ---------------------------------------------------------------------------
# Item 7: Patch the SOURCE (syndication.services) not import aliases
# ---------------------------------------------------------------------------


class MarkPublishedSharedSourceTest(TestCase):
    """
    The co-equal seam test must patch syndication.services.mark_projection_published
    (the SOURCE), not the import-alias in each module. This proves both paths
    route through the SAME source function.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="sharedsr_user", email="sharedsr@test.com", password="pw")
        self.profile = _make_profile(name="SharedSrc Org", slug="sharedsrc-org", user=self.user)
        self.event = _make_event(slug="sharedsrc-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-sharedsrc")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection
        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_api_and_ui_both_route_through_services_source(self):
        """
        Both api.py and views.py must import mark_projection_published from
        syndication.services and the imported symbol must be the same object as
        the one defined in services — proving they share a single source.

        When modules use `from syndication.services import mark_projection_published`,
        patching the source module after import does NOT intercept local copies
        (Python import semantics). The correct structural check is to verify
        that both call-site symbols are identical to the services definition.
        """
        import syndication.api as api_mod
        import syndication.views as views_mod
        import syndication.services as services_mod

        # Both modules must reference the same function object from services
        self.assertIs(
            api_mod.mark_projection_published,
            services_mod.mark_projection_published,
            "syndication.api.mark_projection_published must be the same object as syndication.services.mark_projection_published",
        )
        self.assertIs(
            views_mod.mark_projection_published,
            services_mod.mark_projection_published,
            "syndication.views.mark_projection_published must be the same object as syndication.services.mark_projection_published",
        )


# ---------------------------------------------------------------------------
# Item 8: no_promo_posts rendered text assertions
# ---------------------------------------------------------------------------


class NoPromoPostsRenderedTextTest(TestCase):
    """
    The no_promo_posts state must render the actual text 'No promo posts yet'
    and the 'Add promo message' CTA in the response body.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="nopromo_user", email="nopromo@test.com", password="pw")
        self.profile = _make_profile(name="NoPromo Org", slug="nopromo-org", user=self.user)
        self.event = _make_event(slug="nopromo-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_no_promo_posts_state_renders_text_and_cta(self):
        """
        When no_promo_posts=True, the response body must contain:
        - "No promo posts yet" text
        - "Add promo message" CTA
        """
        _make_connection(self.profile, destination_id="fl-nopromo", kinds=["promotion"])
        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "No promo posts yet",
            content,
            "Template must render 'No promo posts yet' when no_promo_posts=True",
        )
        self.assertIn(
            "Add promo message",
            content,
            "Template must render 'Add promo message' CTA when no_promo_posts=True",
        )


# ---------------------------------------------------------------------------
# Item 9: rendered body non-empty and contains event content
# ---------------------------------------------------------------------------


class RenderedBodyContentTest(TestCase):
    """
    Rendered body for a successfully-rendered projection must be non-empty
    and contain content derived from the event (not empty string or error string).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="rendcont_user", email="rendcont@test.com", password="pw")
        self.profile = _make_profile(name="RendCont Org", slug="rendcont-org", user=self.user)
        self.event = _make_event(slug="rendcont-event", title="Awesome Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-rendcont")
        self.client = Client()
        self.client.force_login(self.user)

    def test_rendered_body_is_non_empty_and_contains_event_content(self):
        """
        The rendered body for a successfully-rendered projection must be
        non-empty AND contain the event title (proving it's real content).
        """
        _make_listing_projection(self.conn, self.event)
        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        )
        self.assertEqual(response.status_code, 200)
        rendered_rows = response.context["rendered_rows"]
        self.assertTrue(len(rendered_rows) >= 1)
        for pk, body in rendered_rows.items():
            self.assertIsInstance(body, str)
            self.assertTrue(len(body) > 0, "Rendered body must not be empty for a valid projection")
            self.assertNotIn(
                "[render error",
                body,
                "Successfully-rendered body must not be an error string",
            )
            self.assertIn(
                "Awesome Test Event",
                body,
                "Rendered body must contain event title (proving real event content)",
            )


# ---------------------------------------------------------------------------
# Item 10: API F12 risk — verify force_login actually authenticates
# ---------------------------------------------------------------------------


class NinjaSessionAuthTest(TestCase):
    """
    Verify Ninja SessionMarkerAuth honors Django test-client force_login.
    The API tests must exercise a real authenticated 2xx path, not silently 401.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="sessionauth_user", email="sessionauth@test.com", password="pw")
        self.profile = _make_profile(name="SessionAuth Org", slug="sessionauth-org", user=self.user)
        self.event = _make_event(slug="sessionauth-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-sessionauth")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection
        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_mark_published_api_with_force_login_returns_200_not_401(self):
        """
        POST to /api/projections/{id}/mark-published/ with force_login must
        return 200, not 401/403 (proving session auth works for Ninja endpoints).
        """
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/api/projections/{proj.pk}/mark-published/",
            content_type="application/json",
        )
        self.assertEqual(
            response.status_code,
            200,
            f"API mark-published with force_login must return 200. Got {response.status_code}: {response.content.decode()[:200]}",
        )


# ---------------------------------------------------------------------------
# Item 11: batch publish partial-failure path (ADR-008 D3 fail-loud)
# ---------------------------------------------------------------------------


class BatchPublishPartialFailureTest(TestCase):
    """
    publish_all_ready_projections must handle per-projection ValueError without
    raising an unhandled 500.  When one ready projection fails (concurrent state
    change), the others must still publish AND the failure must be surfaced as a
    visible error, not swallowed or propagated as an unhandled exception.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="batchfail_user", email="batchfail@test.com", password="pw"
        )
        self.profile = _make_profile(name="BatchFail Org", slug="batchfail-org", user=self.user)
        self.event = _make_event(slug="batchfail-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-batchfail")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self, destination_id_suffix=""):
        from syndication.services import approve_projection
        conn = _make_connection(
            self.profile,
            destination_id=f"fl-batchfail-{destination_id_suffix}",
        )
        proj = _make_listing_projection(conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_service_partial_failure_publishes_rest_and_returns_failures(self):
        """
        publish_all_ready_projections: if one projection raises ValueError during
        transition, the others still publish and the return value includes the
        failure — no unhandled exception propagates.
        """
        from unittest.mock import patch
        from syndication.services import publish_all_ready_projections

        proj_ok = self._make_ready_projection("ok")
        proj_fail = self._make_ready_projection("fail")

        original_transition = None

        def failing_transition(projection, target_status):
            if projection.pk == proj_fail.pk:
                raise ValueError("Simulated concurrent state change")
            original_transition(projection, target_status)

        import syndication.engine as engine_mod
        original_transition = engine_mod.transition_status

        with patch.object(engine_mod, "transition_status", side_effect=failing_transition):
            result = publish_all_ready_projections(user=self.user, event=self.event)

        # The successful projection must have been published
        proj_ok.refresh_from_db()
        self.assertEqual(proj_ok.status, "published", "Non-failing projection must be published")

        # The failing one must NOT have been published
        proj_fail.refresh_from_db()
        self.assertNotEqual(proj_fail.status, "published", "Failed projection must not be published")

        # The return value must surface the failure (published list + failures)
        published, failures = result
        self.assertIn(proj_ok, published, "proj_ok must be in published list")
        self.assertEqual(len(failures), 1, "Exactly one failure expected")
        failed_proj, exc = failures[0]
        self.assertEqual(failed_proj.pk, proj_fail.pk)
        self.assertIsInstance(exc, ValueError)

    def test_batch_publish_view_partial_failure_surfaces_error_not_500(self):
        """
        POST to batch-publish with one failing projection must return 200 with
        visible error state, not an unhandled 500.
        """
        from unittest.mock import patch

        proj_ok = self._make_ready_projection("view-ok")
        proj_fail = self._make_ready_projection("view-fail")

        import syndication.engine as engine_mod
        original_transition = engine_mod.transition_status

        def failing_transition(projection, target_status):
            if projection.pk == proj_fail.pk:
                raise ValueError("Simulated concurrent state change")
            original_transition(projection, target_status)

        with patch.object(engine_mod, "transition_status", side_effect=failing_transition):
            response = self.client.post(
                f"/syndication/events/{self.event.pk}/projections/publish-all-ready/",
                HTTP_HX_REQUEST="true",
            )

        self.assertNotEqual(response.status_code, 500, "Partial failure must not produce 500")
        self.assertEqual(response.status_code, 200, "Partial failure must return 200 with error state")
        content = response.content.decode()
        self.assertIn(
            "Action failed",
            content,
            "Response must contain visible error state when batch publish has failures",
        )
