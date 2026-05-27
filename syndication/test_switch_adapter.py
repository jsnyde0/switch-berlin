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
        Harness item (additional): an ANONYMOUS GET on the resolved external_url
        returns 200 for a public, published event. Validates:
        - The URL resolves in Django (not 404/NoReverseMatch)
        - Anonymous users can access the page (genuine public accessibility)
        The event is explicitly set to visibility=public to make the contract clear.
        URL-to-event binding is covered by test_publish_external_url_matches_reverse.
        """
        from django.test import Client
        from syndication.adapters import publish_switch_own_page

        # Confirm the event is public (explicit — don't rely on setUp default)
        self.event.visibility = "public"
        self.event.save(update_fields=["visibility"])

        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()

        # Use anonymous client — proves public accessibility, not just auth-gated
        anon_client = Client()
        response = anon_client.get(self.proj.external_url)
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


# ---------------------------------------------------------------------------
# 4. Draft-precondition guard (Fix 1+2 — kb-a4u.10 review)
# ---------------------------------------------------------------------------

class SwitchPublishDraftPreconditionTest(TestCase):
    """
    publish_switch_own_page requires status=ready at entry.

    Without the guard, a draft projection hits the data-integrity fail-loud
    branch which calls transition_status(proj, "failed") — but "draft→failed"
    is not a legal transition, so an opaque illegal-transition error is raised
    instead of the real data-integrity error (ADR-008 D3 violation: wrong
    error surfaces, masking the real problem).

    The precondition guard surfaces the right error early AND ensures the
    ready→failed transitions in data-integrity branches are always legal.
    """

    def setUp(self):
        self.profile = _make_organizer_profile(slug="switch-draft-precond-org")
        self.event = _make_event_with_organizer(self.profile, slug="switch-draft-precond-event")
        self.conn = _make_switch_connection(self.profile)

    def test_publish_on_draft_projection_raises_clear_precondition_error(self):
        """
        Calling publish_switch_own_page on a status=draft projection must raise
        a clear ValueError naming the status precondition (requires ready) —
        NOT an opaque "Illegal status transition draft→failed" error.
        """
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=self.conn,
            source_event=self.event,
        )

        from syndication.adapters import publish_switch_own_page
        with self.assertRaises(ValueError) as ctx:
            publish_switch_own_page(proj)

        error_msg = str(ctx.exception)
        # Must name the precondition (ready) and the actual status (draft)
        self.assertIn("ready", error_msg.lower())
        self.assertIn("draft", error_msg.lower())
        # Must NOT be the masked illegal-transition error from the state machine
        self.assertNotIn("Illegal status transition", error_msg)


# ---------------------------------------------------------------------------
# 5. Missing-slug fail-loud (Fix 3 — kb-a4u.10 review)
# ---------------------------------------------------------------------------

class SwitchPublishMissingSlugTest(TestCase):
    """
    Before calling reverse(), the adapter must guard that event.slug and
    organizer.slug are present. Missing slugs produce NoReverseMatch or
    malformed URLs, bypassing the fail-loud-to-failed pattern and leaving the
    projection in ready with an opaque error.

    Fix 3: guard slugs before reverse(); on missing slug → set status=failed
    then raise ValueError (ADR-008 D3 — fail loud, consistent with other branches).
    """

    def setUp(self):
        self.profile = _make_organizer_profile(slug="switch-slug-guard-org")
        self.conn = _make_switch_connection(self.profile)

    def test_publish_fails_loud_when_event_slug_is_empty(self):
        """
        An event with an empty slug cannot produce a resolvable external_url.
        publish_switch_own_page must set status=failed and raise ValueError
        naming the slug data-integrity problem (not a raw NoReverseMatch).
        """
        event_no_slug = Event.objects.create(
            title="No Slug Party",
            slug="",  # deliberately empty
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=event_no_slug,
            profile=self.profile,
            is_primary=True,
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=event_no_slug,
        )

        from syndication.adapters import publish_switch_own_page
        with self.assertRaises(ValueError) as ctx:
            publish_switch_own_page(proj)

        # Projection must be failed, not left in ready
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)
        # Error must name the data-integrity problem
        self.assertIn("slug", str(ctx.exception).lower())

    def test_publish_fails_loud_when_organizer_slug_is_empty(self):
        """
        An organizer with an empty slug cannot produce a resolvable external_url.
        publish_switch_own_page must set status=failed and raise ValueError.
        """
        profile_no_slug = Profile.objects.create(name="No Slug Organizer", slug="")
        conn_no_slug = PlatformConnection.objects.create(
            organizer=profile_no_slug,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
            credentials={},
        )
        event = Event.objects.create(
            title="Slugless Org Party",
            slug="slugless-org-party",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=event,
            profile=profile_no_slug,
            is_primary=True,
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=conn_no_slug,
            source_event=event,
        )

        from syndication.adapters import publish_switch_own_page
        with self.assertRaises(ValueError) as ctx:
            publish_switch_own_page(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)
        self.assertIn("slug", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# 6. Double-publish contract (Fix 7 — kb-a4u.10 review)
# ---------------------------------------------------------------------------

class SwitchPublishDoublePublishTest(TestCase):
    """
    Re-publishing an already-published projection raises. This is acceptable
    fail-loud behavior — edit+re-publish is deferred per ADR-016. This test
    locks the contract so the behavior is explicit and doesn't accidentally
    change.
    """

    def setUp(self):
        self.profile = _make_organizer_profile(slug="switch-double-pub-org")
        self.event = _make_event_with_organizer(self.profile, slug="switch-double-pub-event")
        self.conn = _make_switch_connection(self.profile)

    def test_double_publish_raises(self):
        """
        Publishing an already-published projection raises ValueError.
        The precondition guard (status must be ready) rejects published→? cleanly.
        Edit+re-publish is deferred per ADR-016; this test locks the contract.
        """
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=self.event,
        )

        from syndication.adapters import publish_switch_own_page
        # First publish succeeds
        publish_switch_own_page(proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.PUBLISHED)

        # Second publish raises — precondition guard rejects non-ready status
        with self.assertRaises(ValueError):
            publish_switch_own_page(proj)
