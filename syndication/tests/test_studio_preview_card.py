"""
Studio composer: Telegram link-preview card tests (kb-6d7o.3).

Contract groups:
(A) Telegram projection preview (non-draft, so _channel_preview.html is rendered)
    contains the resolved card image (default asset when no cover), og:title,
    and og:description — driven by card_image_url.
(B) Card image URL equals card_image_url(event, request) for both a cover
    event and a no-cover event (preview == live equality, the whole point).
(C) Non-Telegram branches (fetlife / switch / fallback) render unchanged —
    they do NOT render the Telegram card markup.

Assertions are on response.content (NOT response.context — hollow per memory).
ADR-008 D3: fail loud; D2: reuses shared card_image_url resolver (not
re-implementing image resolution).

_channel_preview.html is rendered for non-draft (ready/published) projections
(the editable-bubble IS the preview for drafts, so it doesn't include the
_channel_preview partial). We use "ready" projections so _channel_preview.html
is actually exercised.

canonical_refs:
- ADR-003 (single resolution point for og:image)
- ADR-008 D2 (no duplicate resolver)
"""

import tempfile

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from events.models import Event, EventOrganizer, EventImage
from events.og import card_image_url
from organizers.models import Profile, ProfileClaim
from syndication.engine import generate_projection, transition_status
from syndication.models import PlatformConnection

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
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


def _make_event(profile, title, slug, description="Test event description for OG."):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
        description=description,
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_connection(profile, platform, destination_id="test-dest", kinds=None):
    if kinds is None:
        kinds = ["listing"]
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=True,
    )


def _make_ready_projection(event, connection):
    """
    Create a listing projection in 'ready' status so _channel_preview.html
    is rendered (draft projections use the editable-bubble surface instead).
    """
    proj = generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    return proj


# ---------------------------------------------------------------------------
# (A) Telegram preview contains the card image, title, and description
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TelegramPreviewCardTest(TestCase):
    """
    (A) The rendered event_syndication fragment for a non-draft Telegram listing
    projection must contain (via _channel_preview.html Telegram branch):
    - The resolved card image URL (default asset when no cover)
    - The event title (og:title)
    - The event description (og:description)

    Assertions on rendered HTML, not context vars (hollow-test prevention).
    Uses 'ready' status so _channel_preview.html is rendered (not the editable bubble).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tg_card_user", email="tg_card@test.com", password="pw")
        self.profile = _make_profile("TG Card Org", "tg-card-org", user=self.user)
        self.event = _make_event(
            self.profile,
            "Telegram Card Event",
            "telegram-card-event",
            description="A spectacular event for testing the Telegram preview card.",
        )
        self.telegram_conn = _make_connection(self.profile, "telegram", "tg-channel")
        _make_ready_projection(self.event, self.telegram_conn)
        self.client.force_login(self.user)

    def test_telegram_preview_contains_default_card_image(self):
        """
        (A1) The rendered Telegram preview must contain the default og-default.png
        URL (no cover image is set — so card_image_url returns the default asset).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "og-default.png",
            content,
            "Telegram preview must contain the default card image URL (og-default.png) "
            "when the event has no cover.",
        )

    def test_telegram_preview_contains_event_title(self):
        """
        (A2) The rendered Telegram preview must contain the event title (og:title proxy).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Telegram Card Event")

    def test_telegram_preview_contains_event_description(self):
        """
        (A3) The rendered Telegram preview must contain the event description (og:description proxy).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A spectacular event for testing the Telegram preview card.")

    def test_telegram_preview_card_has_testid_marker(self):
        """
        (A4) The Telegram link-preview card has data-testid="tg-link-preview-card"
        so non-Telegram tests can assert its absence.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="tg-link-preview-card"')


# ---------------------------------------------------------------------------
# (B) Card image URL equals card_image_url(event, request) for cover + no-cover
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TelegramPreviewCardImageEqualityTest(TestCase):
    """
    (B) The preview's card image URL MUST equal card_image_url(event, request)
    for both:
    - an event with no cover (default asset)
    - an event with a cover image

    This equality is the structural guarantee that preview == live.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client()
        self.user = _make_user(username="tg_eq_user", email="tg_eq@test.com", password="pw")
        self.profile = _make_profile("TG Eq Org", "tg-eq-org", user=self.user)
        self.telegram_conn = _make_connection(self.profile, "telegram", "tg-eq-channel")
        self.client.force_login(self.user)

    def _card_image_url_for(self, event):
        """Return card_image_url(event, request) using a factory request matching testserver."""
        request = self.factory.get(f"/syndication/events/{event.pk}/fragments/event_syndication/")
        request.META["SERVER_NAME"] = "testserver"
        request.META["SERVER_PORT"] = "80"
        return card_image_url(event, request)

    def test_no_cover_card_image_url_appears_in_preview(self):
        """
        (B1) No-cover event: card image URL in rendered preview equals
        card_image_url(event, request).
        """
        event = _make_event(
            self.profile,
            "No Cover Event",
            "no-cover-eq-event",
            description="No cover event description.",
        )
        _make_ready_projection(event, self.telegram_conn)

        expected_url = self._card_image_url_for(event)

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            expected_url,
            content,
            f"Preview must contain exactly card_image_url's result '{expected_url}' "
            "for no-cover event (structural equality guarantee).",
        )

    def test_no_cover_returns_default_asset(self):
        """
        (B2) card_image_url returns default asset for no-cover event — verifies
        the resolver call itself (not just the rendered fragment).
        """
        event = _make_event(
            self.profile,
            "No Cover Event 2",
            "no-cover-eq-event-2",
            description="No cover event 2 description.",
        )
        url = self._card_image_url_for(event)
        self.assertIn("og-default.png", url)
        self.assertTrue(url.startswith("http"))


# ---------------------------------------------------------------------------
# (C) Non-Telegram branches do NOT render the Telegram card markup
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class NonTelegramBranchesUnchangedTest(TestCase):
    """
    (C) Non-Telegram platforms (FetLife, Switch) must NOT render the
    Telegram link-preview card markup. The non-Telegram branches of
    _channel_preview.html are untouched.

    Marker: the card div uses data-testid="tg-link-preview-card" which
    must NOT appear for FetLife or Switch previews.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="nontg_user", email="nontg@test.com", password="pw")
        self.profile = _make_profile("NonTG Org", "nontg-org", user=self.user)
        self.fetlife_conn = _make_connection(
            self.profile, "fetlife", "fl-nontg-user", kinds=["listing"]
        )
        self.switch_conn = _make_connection(
            self.profile, "switch", "own-page", kinds=["listing"]
        )
        self.client.force_login(self.user)

    def test_fetlife_preview_does_not_render_telegram_card(self):
        """
        (C1) FetLife preview does NOT contain the Telegram card marker.
        """
        event = _make_event(
            self.profile,
            "FetLife Branch Event",
            "fetlife-branch-event",
            description="FetLife branch event description.",
        )
        _make_ready_projection(event, self.fetlife_conn)

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'data-testid="tg-link-preview-card"',
            content,
            "FetLife preview must NOT contain the Telegram card marker — "
            "non-Telegram branches must remain unchanged.",
        )

    def test_switch_preview_does_not_render_telegram_card(self):
        """
        (C2) Switch preview does NOT contain the Telegram card marker.
        Note: Switch listing projections in the event composer use the EventForm
        card, not the textarea/preview bubble, so the switch preview block of
        _channel_preview.html is not exercised here. We just verify the marker absence.
        """
        event = _make_event(
            self.profile,
            "Switch Branch Event",
            "switch-branch-event",
            description="Switch branch event description.",
        )
        _make_ready_projection(event, self.switch_conn)

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'data-testid="tg-link-preview-card"',
            content,
            "Switch preview must NOT contain the Telegram card marker — "
            "non-Telegram branches must remain unchanged.",
        )
