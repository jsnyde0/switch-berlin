"""
TDD tests for the Switch own-page listing adapter (kb-a4u.10).

Harness contract:
- A kind=listing projection on the Switch own-page connection, when published,
  reaches status=published AND its external_url resolves to the public
  /events/<org_slug>/<event_slug>/ listing URL.
- The fail-loud branch: if a genuine data-integrity failure occurs (e.g. event
  has no slug, or event has no primary organizer), status=failed is set.

Per bead NOTES (ADR-016 D5, ADR-008 D3):
- Switch own-page is a push-API-style platform: publish verb performs the
  in-app render/list and AUTO-CONFIRMS → status=published.
- No external API call, no content-policy cleaning.
- external_url = Django reverse('event-detail', kwargs={...}) for the event's
  public URL.
- No per-platform adapter abstraction — this is a direct implementation.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile
from syndication.models import PlatformConnection, PlatformProjection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_organizer_profile(slug="test-org-switch"):
    return Profile.objects.create(name="Switch Test Organizer", slug=slug)


def _make_event_with_organizer(profile, slug="switch-test-event"):
    """Create an Event with a primary organizer (required for event-detail URL)."""
    event = Event.objects.create(
        title="Switch Test Party",
        slug=slug,
        start=timezone.now(),
        status="published",
        visibility="public",
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_switch_connection(profile):
    """Create a Switch own-page PlatformConnection."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing"],
        credentials={},
    )


# ---------------------------------------------------------------------------
# 1. Successful publish: status=published + external_url resolved
# ---------------------------------------------------------------------------

class SwitchOwnPagePublishTest(TestCase):
    """
    Harness target: publish a kind=listing projection on Switch own-page connection.
    After publish: status=published, external_url = reverse('event-detail', ...).
    """

    def setUp(self):
        self.profile = _make_organizer_profile()
        self.event = _make_event_with_organizer(self.profile)
        self.conn = _make_switch_connection(self.profile)
        self.proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=self.event,
        )

    def test_publish_reaches_status_published(self):
        """
        Harness item (primary): publish sets projection status=published.
        """
        from syndication.adapters import publish_switch_own_page
        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.PUBLISHED)

    def test_publish_sets_external_url_to_event_detail_url(self):
        """
        Harness item (primary): external_url = the public /events/<org_slug>/<event_slug>/ URL.
        Resolved via reverse('event-detail'), not hardcoded.
        """
        from syndication.adapters import publish_switch_own_page
        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()

        expected_url = reverse(
            "event-detail",
            kwargs={
                "org_slug": self.profile.slug,
                "event_slug": self.event.slug,
            },
        )
        self.assertEqual(self.proj.external_url, expected_url)

    def test_published_external_url_returns_200_for_public_event(self):
        """
        Harness item (additional): a GET on the resolved external_url returns 200
        for a public, published event. Validates the URL actually resolves in Django.
        """
        from syndication.adapters import publish_switch_own_page
        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()

        # Confirm the URL is navigable (not a 404 / NoReverseMatch)
        response = self.client.get(self.proj.external_url)
        # 200 or redirect (302) — both indicate the URL resolves.
        # event_detail is an HTMX page; accept 200.
        self.assertEqual(response.status_code, 200)

    def test_publish_sets_syndicated_at(self):
        """syndicated_at is stamped on successful publish."""
        from syndication.adapters import publish_switch_own_page
        before = timezone.now()
        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()
        self.assertIsNotNone(self.proj.syndicated_at)
        self.assertGreaterEqual(self.proj.syndicated_at, before)

    def test_publish_external_url_matches_reverse(self):
        """
        Explicit: external_url equals reverse('event-detail') — not a hardcoded path.
        """
        from syndication.adapters import publish_switch_own_page
        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()

        via_reverse = reverse(
            "event-detail",
            kwargs={
                "org_slug": self.profile.slug,
                "event_slug": self.event.slug,
            },
        )
        self.assertEqual(self.proj.external_url, via_reverse)


# ---------------------------------------------------------------------------
# 2. Fail-loud: event has no primary organizer → status=failed
# ---------------------------------------------------------------------------

class SwitchPublishFailLoudTest(TestCase):
    """
    ADR-008 D3: fail loud on genuine data-integrity failures.
    If the event has no primary organizer (cannot resolve org_slug for URL),
    the projection must reach status=failed — no silent fallback.
    """

    def setUp(self):
        self.profile = _make_organizer_profile(slug="switch-fail-org")
        self.conn = _make_switch_connection(self.profile)

    def test_publish_fails_loud_when_event_has_no_organizer(self):
        """
        Event with no primary organizer cannot produce a resolvable external_url.
        publish_switch_own_page must set status=failed (not silently succeed).
        """
        # Create event WITHOUT an organizer
        event_no_org = Event.objects.create(
            title="No Organizer Party",
            slug="no-org-party",
            start=timezone.now(),
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=event_no_org,
        )

        from syndication.adapters import publish_switch_own_page
        with self.assertRaises(ValueError):
            publish_switch_own_page(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)

    def test_publish_fails_loud_when_projection_has_no_source_event(self):
        """
        A listing projection with no source_event cannot publish.
        publish_switch_own_page must set status=failed.
        """
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=None,
        )

        from syndication.adapters import publish_switch_own_page
        with self.assertRaises(ValueError):
            publish_switch_own_page(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)


# ---------------------------------------------------------------------------
# 3. Only accepts kind=listing; promotion is not Switch own-page's domain
# ---------------------------------------------------------------------------

class SwitchPublishKindGuardTest(TestCase):
    """
    publish_switch_own_page must reject non-listing projections immediately.
    ADR-008 D3: fail loud — no silent coercions.
    """

    def setUp(self):
        self.profile = _make_organizer_profile(slug="switch-kind-guard-org")
        self.event = _make_event_with_organizer(self.profile, slug="switch-kind-guard-event")
        self.conn = _make_switch_connection(self.profile)

    def test_publish_raises_for_promotion_kind(self):
        """
        Promotion-kind projections are not valid for Switch own-page listing publish.
        Must raise ValueError (fail loud).
        """
        from syndication.models import Post
        post = Post.objects.create(
            event=self.event,
            headline="Promo for Switch",
            body="Come join us.",
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_post=post,
        )

        from syndication.adapters import publish_switch_own_page
        with self.assertRaises(ValueError):
            publish_switch_own_page(proj)
