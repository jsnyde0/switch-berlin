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

from unittest.mock import MagicMock, call, patch

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
        self.user = _make_vouched_user(
            username="switch_pub_user", email="switch_pub@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="Switch Pub Org", slug="switch-pub-org", user=self.user
        )
        self.event = _make_event(slug="switch-pub-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
        self.conn = _make_connection(
            self.profile, platform="switch", destination_id="own-page"
        )

    def test_publish_projection_switch_calls_adapter_exactly_once(self):
        """
        publish_projection on a ready switch projection calls
        publish_switch_own_page exactly once with that projection.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        with patch(
            "syndication.services.publish_switch_own_page"
        ) as mock_adapter:
            publish_projection(self.user, proj)

        mock_adapter.assert_called_once_with(proj)

    def test_publish_projection_switch_does_not_call_telegram_adapter(self):
        """
        publish_projection for switch must NOT call publish_telegram_promotion.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch(
                "syndication.services.publish_telegram_promotion"
            ) as mock_telegram:
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
        from syndication.services import publish_projection
        import syndication.engine as engine_mod

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

    def test_publish_projection_switch_projection_has_correct_content_version(self):
        """
        The adapter receives a projection whose content_version is the one
        assigned at projection creation. This ensures the adapter will post
        the projection's assigned-version content (not some other version).
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        expected_cv = proj.content_version

        received_projections = []

        def capture_projection(p):
            received_projections.append(p)

        with patch(
            "syndication.services.publish_switch_own_page",
            side_effect=capture_projection,
        ):
            publish_projection(self.user, proj)

        self.assertEqual(len(received_projections), 1)
        received = received_projections[0]
        self.assertEqual(
            received.content_version_id,
            expected_cv.pk,
            "Adapter must receive the projection with its assigned content_version "
            "(per-channel content routing — a customized projection posts ITS content)",
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
        self.user = _make_vouched_user(
            username="tg_pub_user", email="tg_pub@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="TG Pub Org", slug="tg-pub-org", user=self.user
        )
        self.event = _make_event(slug="tg-pub-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
        self.conn = _make_connection(
            self.profile, platform="telegram", destination_id="@my-channel"
        )

    def test_publish_projection_telegram_calls_adapter_exactly_once(self):
        """
        publish_projection on a ready telegram projection calls
        publish_telegram_promotion exactly once with that projection.
        """
        from syndication.services import publish_projection

        proj = _make_promotion_projection(self.conn, self.event)
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        with patch(
            "syndication.services.publish_telegram_promotion"
        ) as mock_adapter:
            publish_projection(self.user, proj)

        mock_adapter.assert_called_once_with(proj)

    def test_publish_projection_telegram_does_not_call_switch_adapter(self):
        """
        publish_projection for telegram must NOT call publish_switch_own_page.
        """
        from syndication.services import publish_projection

        proj = _make_promotion_projection(self.conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch(
                "syndication.services.publish_telegram_promotion"
            ) as mock_telegram:
                publish_projection(self.user, proj)

        mock_telegram.assert_called_once()
        mock_switch.assert_not_called()

    def test_publish_projection_telegram_does_not_double_transition(self):
        """
        publish_projection for telegram must NOT call transition_status directly.
        The adapter owns the transition.
        """
        from syndication.services import publish_projection
        import syndication.engine as engine_mod

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

    def test_publish_projection_telegram_projection_has_correct_content_version(self):
        """
        The adapter receives a projection whose content_version is the assigned one.
        A customized projection (custom content_version) must post ITS content,
        not canonical's — this test catches routing swaps.
        """
        from syndication.services import publish_projection

        proj = _make_promotion_projection(self.conn, self.event)
        expected_cv_id = proj.content_version_id

        received = []

        def capture(p):
            received.append(p)

        with patch("syndication.services.publish_telegram_promotion", side_effect=capture):
            publish_projection(self.user, proj)

        self.assertEqual(len(received), 1)
        self.assertEqual(
            received[0].content_version_id,
            expected_cv_id,
            "Adapter must receive projection with its assigned content_version",
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
        self.user = _make_vouched_user(
            username="fl_pub_user", email="fl_pub@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="FL Pub Org", slug="fl-pub-org", user=self.user
        )
        self.event = _make_event(slug="fl-pub-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
        self.conn = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user-001"
        )

    def test_publish_projection_fetlife_does_not_call_switch_adapter(self):
        """FetLife publish must NOT call publish_switch_own_page."""
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)

        with patch("syndication.services.publish_switch_own_page") as mock_switch:
            with patch(
                "syndication.services.publish_telegram_promotion"
            ) as mock_telegram:
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
        self.user = _make_vouched_user(
            username="unk_pub_user", email="unk_pub@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="Unk Pub Org", slug="unk-pub-org", user=self.user
        )
        self.event = _make_event(slug="unk-pub-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
        self.conn = _make_connection(
            self.profile, platform="unsupported_platform", destination_id="dest-x"
        )

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
        self.user = _make_vouched_user(
            username="draft_pub_user", email="draft_pub@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="Draft Pub Org", slug="draft-pub-org", user=self.user
        )
        self.event = _make_event(slug="draft-pub-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
        self.conn = _make_connection(
            self.profile, platform="switch", destination_id="own-page"
        )

    def test_publish_projection_draft_raises_before_adapter(self):
        """
        publish_projection on a draft (non-ready) projection must raise
        ValueError and NOT call the adapter.
        """
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event, status="draft")
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

        with patch(
            "syndication.services.publish_switch_own_page"
        ) as mock_adapter:
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
        self.user = _make_vouched_user(
            username="all_ready_user", email="all_ready@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="All Ready Org", slug="all-ready-org", user=self.user
        )
        self.event = _make_event(slug="all-ready-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
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
            with patch(
                "syndication.services.publish_telegram_promotion"
            ) as mock_telegram:
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
            with patch(
                "syndication.services.publish_telegram_promotion"
            ) as mock_tg:
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
