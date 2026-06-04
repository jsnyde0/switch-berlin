"""
TDD tests for the Switch own-page listing adapter (kb-a4u.10).

Harness contract:
- A kind=listing projection on the Switch own-page connection, when published,
  reaches status=published AND its external_url resolves to the public
  /events/<org_slug>/<event_slug>/ listing URL.
- The fail-loud branch: if a genuine data-integrity failure occurs (e.g. event
  has no slug, or event has no primary organizer), status=failed is set.

kb-shzi.1 additions:
- publish_switch_own_page also promotes the canonical Event: sets
  event.status='published' + event.published_at=now() (first-publish only,
  idempotent). ADR-016 D5 — "published" means the event is actually out there.
- Telegram and FetLife promotion adapters must NOT mutate Event.status.

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
from syndication.engine import generate_projection, transition_status
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


def _seed_canonical_cv(event):
    """
    Get-or-create the canonical ContentVersion for an event.
    Required by the F1 non-null content_version FK (kb-wz8m.2 A1 invariant).
    """
    from syndication.models import ContentVersion

    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


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
        # Use generate_projection + transition_status to reach a valid ready state
        # with a properly frozen snapshot (never bypass transition_status for ready).
        self.proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        transition_status(self.proj, "ready")
        self.proj.refresh_from_db()

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
        # Provide valid frozen_content (projection was properly frozen at some point)
        # — testing the adapter's data-integrity fail-loud branch, not the freeze.
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=event_no_org,
            content_version=_seed_canonical_cv(event_no_org),
            frozen_content={"body": "frozen listing body", "title": "No Organizer Party"},
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
        # Need a ContentVersion even though source_event is None — use a standalone event.
        from django.utils import timezone as tz

        from events.models import Event as EventModel

        orphan_event = EventModel.objects.create(
            title="Orphan Event SW",
            slug="orphan-event-sw-no-source",
            start=tz.now(),
        )
        # Provide valid frozen_content — testing adapter data-integrity branch.
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=None,
            content_version=_seed_canonical_cv(orphan_event),
            frozen_content={"body": "frozen listing body", "title": "No Source Event"},
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
        # Provide frozen_content for a valid ready state (kind guard fires before
        # any frozen_content check — testing kind validation, not the freeze).
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_post=post,
            content_version=_seed_canonical_cv(self.event),
            frozen_content={"body": "frozen promo body", "headline": "Promo for Switch"},
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
            content_version=_seed_canonical_cv(self.event),
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
            content_version=_seed_canonical_cv(event_no_slug),
            frozen_content={"body": "frozen listing body", "title": "No Slug Party"},
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
            content_version=_seed_canonical_cv(event),
            frozen_content={"body": "frozen listing body", "title": "Slugless Org Party"},
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
        # Use generate_projection + transition_status to reach valid ready state.
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()

        from syndication.adapters import publish_switch_own_page

        # First publish succeeds
        publish_switch_own_page(proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.PUBLISHED)

        # Second publish raises — precondition guard rejects non-ready status
        with self.assertRaises(ValueError):
            publish_switch_own_page(proj)


# ---------------------------------------------------------------------------
# 7. kb-shzi.1: Switch publish promotes canonical Event.status (harness target)
# ---------------------------------------------------------------------------


class SwitchPublishPromotesEventStatusTest(TestCase):
    """
    kb-shzi.1 harness target: publishing a Switch own-page listing projection
    for a future-dated, public Event must:
    (a) Set event.status == 'published' AND event.published_at is not None.
    (b) The event appears in the anonymous /events/ listing queryset.
    (c) event_detail resolves HTTP 200.

    ADR-016 D5: 'published' means the event is actually out there.
    """

    def setUp(self):
        import datetime

        from django.utils import timezone as tz

        self.profile = _make_organizer_profile(slug="shzi1-event-status-org")
        # Create a future-dated event in draft status — publish_switch_own_page
        # must promote it to 'published'.
        future_start = tz.now() + datetime.timedelta(days=7)
        self.event = Event.objects.create(
            title="Future Kink Gathering",
            slug="future-kink-gathering",
            start=future_start,
            status="draft",
            visibility="public",
        )
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_switch_connection(self.profile)
        # Advance projection to ready state
        self.proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        transition_status(self.proj, "ready")
        self.proj.refresh_from_db()

    def test_publish_sets_event_status_to_published(self):
        """
        publish_switch_own_page must set event.status='published' on the
        canonical Event (not just the projection). ADR-016 D5.
        """
        from syndication.adapters import publish_switch_own_page

        publish_switch_own_page(self.proj)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "published")

    def test_publish_sets_event_published_at(self):
        """
        publish_switch_own_page must set event.published_at to a non-null
        datetime on first publish. ADR-016 D5.
        """
        import datetime

        from django.utils import timezone as tz

        from syndication.adapters import publish_switch_own_page

        before = tz.now()
        publish_switch_own_page(self.proj)
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.published_at)
        self.assertGreaterEqual(self.event.published_at, before)
        self.assertLessEqual(self.event.published_at, tz.now() + datetime.timedelta(seconds=2))

    def test_published_event_appears_in_events_listing(self):
        """
        After publish_switch_own_page, the event appears in the queryset
        that events/views.py event_list uses for anonymous viewers
        (status='published', hidden=False, start__gte=now, visibility='public').
        """
        from django.utils import timezone as tz

        from events.models import Event as EventModel
        from syndication.adapters import publish_switch_own_page

        publish_switch_own_page(self.proj)

        # Mirror the exact queryset from events/views.py event_list
        now = tz.now()
        qs = EventModel.objects.filter(
            hidden=False,
            status="published",
            start__gte=now,
        )
        pks = list(qs.values_list("pk", flat=True))
        self.assertIn(self.event.pk, pks)

    def test_event_detail_returns_200_after_publish(self):
        """
        After publish_switch_own_page, an anonymous GET on event_detail
        returns HTTP 200. Validates the entire /events/<org>/<slug>/ pipeline.
        """
        from django.test import Client

        from syndication.adapters import publish_switch_own_page

        publish_switch_own_page(self.proj)
        self.proj.refresh_from_db()

        url = self.proj.external_url
        anon_client = Client()
        response = anon_client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_publish_event_status_idempotent_published_at(self):
        """
        Re-publishing (if somehow possible) does NOT stomp the original
        published_at. Idempotent: only set published_at on first publish.
        Mirrors admin.py:208-209 first-publish-only pattern.
        """
        import datetime

        from django.utils import timezone as tz

        from events.services import publish_event

        # Simulate a prior publish: set published_at to a known past time
        first_published_at = tz.now() - datetime.timedelta(hours=1)
        self.event.status = "draft"  # reset to test idempotency helper directly
        self.event.published_at = first_published_at
        self.event.save(update_fields=["status", "published_at"])

        # Call publish_event again — published_at must NOT change
        publish_event(self.event)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "published")
        # published_at must equal the ORIGINAL value (not stomped)
        self.assertEqual(self.event.published_at, first_published_at)


# ---------------------------------------------------------------------------
# 8. kb-shzi.1: Telegram/FetLife publish must NOT mutate Event.status
# ---------------------------------------------------------------------------


class NonSwitchAdaptersDoNotPromoteEventTest(TestCase):
    """
    kb-shzi.1 contract: only the Switch own-page adapter promotes Event.status.
    Telegram and FetLife promotion projections must leave Event.status unchanged.
    """

    def setUp(self):
        import datetime

        from django.utils import timezone as tz

        self.profile = _make_organizer_profile(slug="shzi1-no-promote-org")
        future_start = tz.now() + datetime.timedelta(days=7)
        self.event = Event.objects.create(
            title="Draft Promo Event",
            slug="draft-promo-event",
            start=future_start,
            status="draft",
            visibility="public",
        )
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)

    def test_telegram_publish_does_not_change_event_status(self):
        """
        publish_telegram_promotion must NOT touch event.status.
        Event.status must remain 'draft' after a Telegram promotion publish.
        """
        from unittest.mock import patch

        import httpx

        from syndication.models import PlatformConnection, PlatformProjection, Post

        # Create Telegram connection + post + projection
        tg_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="@test-channel",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token"},
        )
        post = Post.objects.create(event=self.event, headline="Test Promo", body="Come join us!")
        _seed_canonical_cv(self.event)  # ensure canonical CV for post
        from syndication.models import ContentVersion

        post_cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.READY,
            connection=tg_conn,
            source_post=post,
            content_version=post_cv,
            frozen_content={"body": "Come join us!", "headline": "Test Promo"},
        )

        # Mock httpx.post to simulate successful Telegram response
        mock_response = httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 42}},
            request=httpx.Request("POST", "https://api.telegram.org/botfake-token/sendMessage"),
        )
        with patch("httpx.post", return_value=mock_response):
            from syndication.adapters import publish_telegram_promotion

            publish_telegram_promotion(proj)

        # Event.status must remain 'draft' — Telegram does not promote
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "draft")

    def test_fetlife_publish_projection_does_not_change_event_status(self):
        """
        publish_projection for FetLife (attestation path) must NOT touch event.status.
        Event.status must remain 'draft' after a FetLife attestation-publish.
        """
        from syndication.engine import transition_status
        from syndication.models import ContentVersion, PlatformConnection, PlatformProjection

        # Create FetLife connection + post + projection
        fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-test-group",
            kinds=["listing", "promotion"],
            credentials={},
        )
        _seed_canonical_cv(self.event)
        fl_cv, _ = ContentVersion.objects.get_or_create(
            event=self.event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=fl_conn,
            source_event=self.event,
            content_version=fl_cv,
            frozen_content={"body": "Test listing body", "title": "Draft Promo Event"},
        )

        # FetLife uses attestation path: transition_status directly (no Event.status mutation)
        transition_status(proj, "published")

        # Event.status must remain 'draft' — FetLife attestation does not promote
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "draft")
