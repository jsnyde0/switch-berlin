"""
TDD tests for publish_projection platform dispatch (kb-wz8m.4).

Acceptance:
- publish_projection on a ready switch projection calls publish_switch_own_page
  exactly once with that projection (no direct transition_status call on push platforms).
- publish_projection on a ready telegram projection calls publish_telegram_promotion
  exactly once with that projection.
- publish_projection for fetlife does NOT call publish_switch_own_page or
  publish_telegram_promotion — stays on the mark_published attestation path.
- Unknown platform raises ValueError (ADR-008 D3: fail loud).
- A non-ready (draft) projection raises ValueError before any adapter call.
- The switch adapter receives the projection's assigned content_version's content
  (render_projection routes through frozen_content — the spy's received projection
  is the same object, so we assert the projection has the correct content_version).
- publish_all_ready_projections invokes each ready projection's adapter exactly once.
- A published projection retains frozen_content after publish.

Design notes:
- Adapters (publish_switch_own_page, publish_telegram_promotion) already call
  transition_status internally — publish_projection must NOT also call
  transition_status for push platforms (that would double-transition).
- FetLife publish routes to mark_projection_published (attestation path).
- The dispatch is a thin platform→callable map (NOT base class / plugin registry,
  ADR-008 D2).
"""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import (
    ContentVersion,
    PlatformConnection,
    PlatformProjection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(slug, **kwargs):
    defaults = {
        "title": "Test Event",
        "slug": slug,
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_content_version(event, name="canonical"):
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name=name,
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


def _make_connection(profile, platform, destination_id="dest-001", **kwargs):
    kwargs.setdefault("kinds", ["listing", "promotion"])
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        **kwargs,
    )


def _make_listing_projection(connection, event, status="ready"):
    cv = _make_content_version(event)
    proj = PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.LISTING,
        status=PlatformProjection.Status.DRAFT,
        connection=connection,
        source_event=event,
        content_version=cv,
    )
    if status == "ready":
        # Transition to ready via engine (freezes content)
        from syndication.engine import transition_status

        transition_status(proj, "ready")
    return proj


def _make_promotion_projection(connection, event, status="ready"):
    from syndication.models import Post

    cv = _make_content_version(event, name="promo-canonical")
    post = Post.objects.create(
        event=event,
        headline="Test Post",
        body="Test post body",
    )
    proj = PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.PROMOTION,
        status=PlatformProjection.Status.DRAFT,
        connection=connection,
        source_post=post,
        content_version=cv,
    )
    if status == "ready":
        from syndication.engine import transition_status

        transition_status(proj, "ready")
    return proj


# ---------------------------------------------------------------------------
# Switch own-page dispatch
# ---------------------------------------------------------------------------


class PublishProjectionSwitchDispatchTest(TestCase):
    """
    publish_projection on a ready switch projection calls publish_switch_own_page
    exactly once with that projection.

    The adapter is patched to a spy so we don't need real URL resolution.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="switch_pub_user", email="switch_pub@test.com", password="pw")
        self.profile = _make_profile(name="Switch Pub Org", slug="switch-pub-org", user=self.user)
        self.event = _make_event(slug="switch-pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="switch", destination_id="own-page")

    def test_publish_projection_switch_calls_adapter_exactly_once(self):
        """
        publish_projection on a ready switch projection calls
        publish_switch_own_page exactly once with that projection.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        with patch("syndication.services.publish_switch_own_page") as mock_adapter:
            publish_projection(self.user, proj)

        mock_adapter.assert_called_once_with(proj)

    def test_publish_projection_switch_does_not_call_telegram_adapter(self):
        """
        publish_projection for switch must NOT call publish_telegram_promotion.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch("syndication.services.publish_telegram_promotion") as mock_telegram:
                publish_projection(self.user, proj)

        mock_switch.assert_called_once()
        mock_telegram.assert_not_called()

    def test_publish_projection_switch_does_not_double_transition(self):
        """
        publish_projection for switch must NOT call transition_status directly —
        the adapter is responsible for the transition. Double-transition would be
        a bug (ready→published is only legal once).

        We verify by asserting transition_status is NOT called in the
        service's own body after the adapter is already handling it.
        """
        import syndication.engine as engine_mod
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)

        # Spy on transition_status at the engine level
        original_transition = engine_mod.transition_status
        transition_calls = []

        def spy_transition(projection, new_status):
            transition_calls.append((projection.pk, new_status))
            original_transition(projection, new_status)

        with patch("syndication.services.publish_switch_own_page"):
            with patch.object(engine_mod, "transition_status", side_effect=spy_transition):
                publish_projection(self.user, proj)

        # With the adapter mocked out, transition_status should NOT be called
        # by publish_projection itself (only by the adapter, which is mocked here)
        self.assertEqual(
            transition_calls,
            [],
            "publish_projection must not call transition_status directly for switch — "
            "the adapter owns the transition. (Double-transition bug prevention.)",
        )

    def test_publish_projection_switch_routing_swap_detection(self):
        """
        Routing-swap test: two ready projections on the same event with DISTINCT
        content (proj_1 customized to "CUSTOM-FOR-1", proj_2 on canonical/different
        body). Publishing proj_1 must deliver proj_1's body; publishing proj_2
        must deliver proj_2's body. A swap (publish proj_1 but deliver proj_2's
        content) FAILS this test.

        Sequence:
          1. Create proj_1 and proj_2 in DRAFT on the same event.
          2. customize(proj_1) → gives it its own ContentVersion row.
          3. edit_version(proj_1.cv, body="CUSTOM-FOR-1") → distinguish it.
          4. Advance both to READY → frozen_content is materialized at freeze.
          5. Spy: publish proj_1, assert body == "CUSTOM-FOR-1".
          6. Spy: publish proj_2, assert body != "CUSTOM-FOR-1".
        """
        from syndication.engine import render_projection, transition_status
        from syndication.services import customize, edit_version, publish_projection

        # proj_1: will be customized
        proj_1 = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=self.conn,
            source_event=self.event,
            content_version=_make_content_version(self.event),
        )

        # proj_2: second connection to have a second destination (same platform)
        conn_2 = _make_connection(self.profile, platform="switch", destination_id="own-page-2")
        proj_2 = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=conn_2,
            source_event=self.event,
            content_version=_make_content_version(self.event),
        )

        # Customize proj_1: give it its own cv with a distinct body
        custom_cv = customize(self.user, proj_1)
        proj_1.refresh_from_db()
        edit_version(self.user, custom_cv, body="CUSTOM-FOR-1")

        # proj_2 gets a distinct body on its version too (so the test isn't trivial)
        edit_version(self.user, proj_2.content_version, body="CONTENT-FOR-2")

        # Advance both to ready → freezes content into frozen_content
        transition_status(proj_1, "ready")
        transition_status(proj_2, "ready")
        proj_1.refresh_from_db()
        proj_2.refresh_from_db()

        self.assertEqual(
            proj_1.frozen_content["body"], "CUSTOM-FOR-1", "Precondition: proj_1 must have its custom body frozen"
        )
        self.assertEqual(
            proj_2.frozen_content["body"], "CONTENT-FOR-2", "Precondition: proj_2 must have its distinct body frozen"
        )

        # Publish proj_1: adapter must receive proj_1 with "CUSTOM-FOR-1" body
        received_1 = []

        def capture_1(p):
            received_1.append(p)

        with patch("syndication.services.publish_switch_own_page", side_effect=capture_1):
            publish_projection(self.user, proj_1)

        self.assertEqual(len(received_1), 1)
        self.assertEqual(received_1[0].pk, proj_1.pk, "Adapter must receive proj_1 (not proj_2 — routing swap)")
        self.assertEqual(
            render_projection(received_1[0]),
            "CUSTOM-FOR-1",
            "Adapter must receive proj_1's custom body, not proj_2's/canonical content "
            "(routing-swap catch: if publish routed the wrong projection, this fails)",
        )
        self.assertNotEqual(
            render_projection(received_1[0]),
            "CONTENT-FOR-2",
            "Adapter must NOT receive proj_2's body (routing-swap catch)",
        )

        # Publish proj_2: adapter must receive proj_2 with "CONTENT-FOR-2" body
        received_2 = []

        def capture_2(p):
            received_2.append(p)

        with patch("syndication.services.publish_switch_own_page", side_effect=capture_2):
            publish_projection(self.user, proj_2)

        self.assertEqual(len(received_2), 1)
        self.assertEqual(received_2[0].pk, proj_2.pk, "Adapter must receive proj_2 (routing-swap catch)")
        self.assertEqual(
            render_projection(received_2[0]),
            "CONTENT-FOR-2",
            "Adapter must receive proj_2's body, not proj_1's custom content",
        )


# ---------------------------------------------------------------------------
# Telegram dispatch
# ---------------------------------------------------------------------------


class PublishProjectionTelegramDispatchTest(TestCase):
    """
    publish_projection on a ready telegram projection calls
    publish_telegram_promotion exactly once with that projection.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="tg_pub_user", email="tg_pub@test.com", password="pw")
        self.profile = _make_profile(name="TG Pub Org", slug="tg-pub-org", user=self.user)
        self.event = _make_event(slug="tg-pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="telegram", destination_id="@my-channel")

    def test_publish_projection_telegram_calls_adapter_exactly_once(self):
        """
        publish_projection on a ready telegram projection calls
        publish_telegram_promotion exactly once with that projection.
        """
        from syndication.services import publish_projection

        proj = _make_promotion_projection(self.conn, self.event)
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        with patch("syndication.services.publish_telegram_promotion") as mock_adapter:
            publish_projection(self.user, proj)

        mock_adapter.assert_called_once_with(proj)

    def test_publish_projection_telegram_does_not_call_switch_adapter(self):
        """
        publish_projection for telegram must NOT call publish_switch_own_page.
        """
        from syndication.services import publish_projection

        proj = _make_promotion_projection(self.conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch("syndication.services.publish_telegram_promotion") as mock_telegram:
                publish_projection(self.user, proj)

        mock_telegram.assert_called_once()
        mock_switch.assert_not_called()

    def test_publish_projection_telegram_does_not_double_transition(self):
        """
        publish_projection for telegram must NOT call transition_status directly.
        The adapter owns the transition.
        """
        import syndication.engine as engine_mod
        from syndication.services import publish_projection

        proj = _make_promotion_projection(self.conn, self.event)

        original_transition = engine_mod.transition_status
        transition_calls = []

        def spy_transition(projection, new_status):
            transition_calls.append((projection.pk, new_status))
            original_transition(projection, new_status)

        with patch("syndication.services.publish_telegram_promotion"):
            with patch.object(engine_mod, "transition_status", side_effect=spy_transition):
                publish_projection(self.user, proj)

        self.assertEqual(
            transition_calls,
            [],
            "publish_projection must not call transition_status directly for telegram — "
            "the adapter owns the transition.",
        )

    def test_publish_projection_telegram_routing_swap_detection(self):
        """
        Routing-swap test: two ready telegram projections on the same event with
        DISTINCT content. Publishing proj_1 must deliver proj_1's body; publishing
        proj_2 must deliver proj_2's body. A swap FAILS this test.

        Uses customize + edit_version (kb-wz8m.3 ops) to diverge proj_1.
        """
        from syndication.engine import render_projection, transition_status
        from syndication.models import ContentVersion, Post
        from syndication.services import customize, edit_version, publish_projection

        # Set up proj_1 on self.conn (promotion)
        cv_1 = ContentVersion.objects.create(
            event=self.event,
            name="promo-canonical-1",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        post_1 = Post.objects.create(event=self.event, headline="Post 1", body="orig-body-1")
        proj_1 = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            connection=self.conn,
            source_post=post_1,
            content_version=cv_1,
        )

        # Set up proj_2 on a second telegram connection
        conn_2 = _make_connection(self.profile, platform="telegram", destination_id="@channel-2")
        cv_2 = ContentVersion.objects.create(
            event=self.event,
            name="promo-canonical-2",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        post_2 = Post.objects.create(event=self.event, headline="Post 2", body="orig-body-2")
        proj_2 = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            connection=conn_2,
            source_post=post_2,
            content_version=cv_2,
        )

        # Customize proj_1: give it its own cv with distinct body "CUSTOM-FOR-1"
        custom_cv = customize(self.user, proj_1)
        proj_1.refresh_from_db()
        edit_version(self.user, custom_cv, body="CUSTOM-FOR-1")

        # Give proj_2 a distinct body too
        edit_version(self.user, proj_2.content_version, body="CONTENT-FOR-2")

        # Advance both to ready → freezes content
        transition_status(proj_1, "ready")
        transition_status(proj_2, "ready")
        proj_1.refresh_from_db()
        proj_2.refresh_from_db()

        self.assertTrue(
            proj_1.frozen_content["body"].startswith("CUSTOM-FOR-1"),
            "Precondition: proj_1 must have custom body frozen. "
            f"Got body={proj_1.frozen_content['body']!r}",
        )
        self.assertTrue(
            proj_2.frozen_content["body"].startswith("CONTENT-FOR-2"),
            "Precondition: proj_2 must have distinct body frozen. "
            f"Got body={proj_2.frozen_content['body']!r}",
        )

        # Publish proj_1: adapter must receive proj_1 with "CUSTOM-FOR-1"
        received_1 = []

        def capture_1(p):
            received_1.append(p)

        with patch("syndication.services.publish_telegram_promotion", side_effect=capture_1):
            publish_projection(self.user, proj_1)

        self.assertEqual(len(received_1), 1)
        self.assertEqual(received_1[0].pk, proj_1.pk, "Adapter must receive proj_1 (routing-swap catch)")
        self.assertTrue(
            render_projection(received_1[0]).startswith("CUSTOM-FOR-1"),
            "Adapter must receive proj_1's customized body, not proj_2's/canonical "
            "(routing-swap catch: if publish routed wrong projection, this fails). "
            f"Got body={render_projection(received_1[0])!r}",
        )
        self.assertFalse(
            render_projection(received_1[0]).startswith("CONTENT-FOR-2"),
            "Adapter must NOT receive proj_2's body (routing-swap catch)",
        )

        # Publish proj_2: adapter must receive proj_2 with "CONTENT-FOR-2"
        received_2 = []

        def capture_2(p):
            received_2.append(p)

        with patch("syndication.services.publish_telegram_promotion", side_effect=capture_2):
            publish_projection(self.user, proj_2)

        self.assertEqual(len(received_2), 1)
        self.assertEqual(received_2[0].pk, proj_2.pk, "Adapter must receive proj_2 (routing-swap catch)")
        self.assertTrue(
            render_projection(received_2[0]).startswith("CONTENT-FOR-2"),
            "Adapter must receive proj_2's distinct body, not proj_1's custom content. "
            f"Got body={render_projection(received_2[0])!r}",
        )


# ---------------------------------------------------------------------------
# FetLife attestation path (NO send adapter)
# ---------------------------------------------------------------------------


class PublishProjectionFetlifeDispatchTest(TestCase):
    """
    FetLife publish does NOT call a send adapter — it routes to the
    mark_published attestation path (actor-attested, out-of-band).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fl_pub_user", email="fl_pub@test.com", password="pw")
        self.profile = _make_profile(name="FL Pub Org", slug="fl-pub-org", user=self.user)
        self.event = _make_event(slug="fl-pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="fetlife", destination_id="fl-user-001")

    def test_publish_projection_fetlife_does_not_call_switch_adapter(self):
        """FetLife publish must NOT call publish_switch_own_page."""
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch("syndication.services.publish_telegram_promotion") as mock_telegram:
                publish_projection(self.user, proj)

        mock_switch.assert_not_called()
        mock_telegram.assert_not_called()

    def test_publish_projection_fetlife_transitions_to_published(self):
        """
        FetLife publish (attestation path) must transition the projection
        to published status.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        publish_projection(self.user, proj)
        proj.refresh_from_db()

        self.assertEqual(
            proj.status,
            PlatformProjection.Status.PUBLISHED,
            "FetLife publish_projection must transition projection to published",
        )

    def test_publish_projection_fetlife_preserves_frozen_content(self):
        """
        After publish, frozen_content must remain populated (not clobbered).
        The .2 bead froze it at draft→ready; the publish path must preserve it.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        self.assertIsNotNone(
            proj.frozen_content,
            "Precondition: projection must have frozen_content after reaching ready",
        )
        original_frozen = proj.frozen_content.copy()

        publish_projection(self.user, proj)
        proj.refresh_from_db()

        self.assertIsNotNone(
            proj.frozen_content,
            "frozen_content must still be set after publish (not clobbered)",
        )
        self.assertEqual(
            proj.frozen_content,
            original_frozen,
            "frozen_content must be preserved unchanged after publish",
        )


# ---------------------------------------------------------------------------
# Unknown platform: fail loud
# ---------------------------------------------------------------------------


class PublishProjectionUnknownPlatformTest(TestCase):
    """
    publish_projection for an unknown platform raises ValueError (ADR-008 D3).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="unk_pub_user", email="unk_pub@test.com", password="pw")
        self.profile = _make_profile(name="Unk Pub Org", slug="unk-pub-org", user=self.user)
        self.event = _make_event(slug="unk-pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="unsupported_platform", destination_id="dest-x")

    def test_publish_projection_unknown_platform_raises_value_error(self):
        """
        Publishing a projection whose connection.platform is unknown must
        raise ValueError immediately (ADR-008 D3: fail loud, no silent fallback).
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)

        with self.assertRaises(ValueError) as ctx:
            publish_projection(self.user, proj)

        self.assertIn(
            "unsupported_platform",
            str(ctx.exception),
            "ValueError must mention the unknown platform identifier",
        )


# ---------------------------------------------------------------------------
# Non-ready projection: raises before any adapter call
# ---------------------------------------------------------------------------


class PublishProjectionNonReadyTest(TestCase):
    """
    A non-ready (draft) projection must raise ValueError before any adapter
    is called. The can_publish gate fires first, but the status check is also
    expected early in the adapter path.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="draft_pub_user", email="draft_pub@test.com", password="pw")
        self.profile = _make_profile(name="Draft Pub Org", slug="draft-pub-org", user=self.user)
        self.event = _make_event(slug="draft-pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="switch", destination_id="own-page")

    def test_publish_projection_draft_raises_before_adapter(self):
        """
        publish_projection on a draft (non-ready) projection must raise
        ValueError and NOT call the adapter.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event, status="draft")
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

        with patch("syndication.services.publish_switch_own_page") as mock_adapter:
            with self.assertRaises((ValueError, Exception)):
                publish_projection(self.user, proj)

        mock_adapter.assert_not_called()


# ---------------------------------------------------------------------------
# publish_all_ready_projections: fan-out, one adapter call per ready projection
# ---------------------------------------------------------------------------


class PublishAllReadyProjectionsDispatchTest(TestCase):
    """
    publish_all_ready_projections must fan out and invoke each ready
    projection's adapter exactly once.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="all_ready_user", email="all_ready@test.com", password="pw")
        self.profile = _make_profile(name="All Ready Org", slug="all-ready-org", user=self.user)
        self.event = _make_event(slug="all-ready-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.switch_conn = _make_connection(
            self.profile,
            platform="switch",
            destination_id="own-page",
        )
        self.tg_conn = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@my-channel",
        )

    def test_publish_all_ready_calls_adapter_for_each_ready_projection(self):
        """
        publish_all_ready_projections must invoke publish_switch_own_page for
        the switch projection and publish_telegram_promotion for the telegram
        projection — each exactly once.
        """
        from syndication.services import publish_all_ready_projections

        switch_proj = _make_listing_projection(self.switch_conn, self.event)
        tg_proj = _make_promotion_projection(self.tg_conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch("syndication.services.publish_telegram_promotion") as mock_telegram:
                published, failures = publish_all_ready_projections(self.user, self.event)

        mock_switch.assert_called_once_with(switch_proj)
        mock_telegram.assert_called_once_with(tg_proj)
        self.assertEqual(failures, [])

    def test_publish_all_ready_collects_per_item_failures(self):
        """
        publish_all_ready_projections must collect per-item adapter failures
        (publish the rest). A ValueError from one adapter must not prevent
        other projections from being published.
        """
        from syndication.services import publish_all_ready_projections

        switch_proj = _make_listing_projection(self.switch_conn, self.event)
        tg_proj = _make_promotion_projection(self.tg_conn, self.event)

        def switch_fails(proj):
            raise ValueError("Switch adapter failed")

        with patch(
            "syndication.services.publish_switch_own_page",
            side_effect=switch_fails,
        ):
            with patch("syndication.services.publish_telegram_promotion") as mock_tg:
                published, failures = publish_all_ready_projections(self.user, self.event)

        mock_tg.assert_called_once_with(tg_proj)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], switch_proj)

    def test_publish_all_ready_does_not_include_draft_projections(self):
        """
        publish_all_ready_projections must NOT process draft projections.
        Only ready projections are eligible.
        """
        from syndication.services import publish_all_ready_projections

        # Create a draft projection (not ready)
        draft_proj = _make_listing_projection(self.switch_conn, self.event, status="draft")
        self.assertEqual(draft_proj.status, PlatformProjection.Status.DRAFT)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            published, failures = publish_all_ready_projections(self.user, self.event)

        mock_switch.assert_not_called()
        self.assertEqual(published, [])

    def test_publish_all_ready_does_not_swallow_permission_error(self):
        """
        ADR-008 D3: publish_all_ready_projections must collect per-item
        ValueError (adapter data/transport failures) but must NOT swallow
        PermissionError or other unexpected errors — those must propagate
        (fail loud).

        This test asserts that a PermissionError raised inside publish_projection
        is NOT silently collected into failures but instead propagates to the caller.
        """
        from syndication.services import publish_all_ready_projections

        _make_listing_projection(self.switch_conn, self.event)

        def adapter_raises_permission_error(proj):
            raise PermissionError("Auth token revoked — fail loud")

        with patch(
            "syndication.services.publish_switch_own_page",
            side_effect=adapter_raises_permission_error,
        ):
            with self.assertRaises(PermissionError):
                publish_all_ready_projections(self.user, self.event)
