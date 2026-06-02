"""
TDD tests for the FetLife listing adapter (kb-a4u.15).

Acceptance items covered:
F1. _compose_listing_body includes date (start) and location (venue) — fix for all adapters.
F2. FetLife listing projection reaches status=ready with dress_code surfaced in body.
    NOTE: The listing body is platform-agnostic at v0. FetLife-specific shaping is
    deferred to the clean_for_platform cleaning seam (kb-o0j), currently an identity
    stub. A FetLife body is byte-identical to a switch body at v0. The tests here
    verify the FetLife listing reaches ready with dress_code + date in the body —
    NOT platform-divergent markdown.
F3. Copy-to-clipboard affordance renders on the board for FetLife projections.
F4. FetLife lifecycle: draft → ready (frozen body) — NO auto-confirm.
F5. Visibility-agnostic: FetLife adapter publish path does NOT gate on Event.visibility.

Platform shape: FetLife is manual-assisted (NO API). The adapter composes a
formatted body for copy-paste, surfaces it via a copy affordance, and the
actor attests publication via mark-published.

ADR-008 D2: no speculative adapter framework — FetLife diverges enough from
Switch own-page to warrant its own adapter function. _compose_listing_body is
intentionally platform-agnostic; platform-specific shaping belongs in the
clean_for_platform seam (kb-o0j bead), not here.
ADR-008 D3: fail loud — missing required fields → visible error, never silent.
ADR-016 carried-forward (REVISED): NO visibility write-gate.
"""

import datetime as dt

from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection

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


def _make_fetlife_connection(profile, destination_id="fl-user-001", **kwargs):
    kwargs.setdefault("kinds", ["listing", "promotion"])
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        **kwargs,
    )


def _make_event(slug="fl-test-event", **kwargs):
    defaults = {
        "title": "Kinky Bubbles Party",
        "slug": slug,
        "start": timezone.now(),
        "visibility": "public",
        "dress_code": "Leather & latex welcome",
        "description": "A fabulous BDSM party.",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_listing_projection(connection, event, status="draft"):
    """
    Create a listing projection with a canonical ContentVersion.
    kb-wz8m.2: provenance is on ContentVersion, not PlatformProjection.
    """
    from syndication.models import ContentVersion

    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        connection=connection,
        source_event=event,
        content_version=cv,
    )


# ---------------------------------------------------------------------------
# F1. _compose_listing_body fix: includes date and location for ALL adapters
# ---------------------------------------------------------------------------


class ComposeListingBodyDateLocationTest(TestCase):
    """
    Fix #1 (carried-forward gap): _compose_listing_body must include
    start datetime and venue/location in the composed body string.

    This fix benefits ALL listing adapters (Switch own-page, FetLife, etc.)
    because _compose_listing_body is the shared composition function.
    """

    def test_compose_listing_body_includes_start_date(self):
        """
        The composed body must include the event start datetime.
        A listing without a date is a broken listing.
        The composer formats dates as YYYY-MM-DD HH:MM (strftime '%Y-%m-%d %H:%M').
        """
        from syndication.engine import _compose_listing_body

        start = dt.datetime(2026, 8, 15, 20, 0, tzinfo=dt.UTC)
        event = _make_event(slug="fl-date-test", start=start)
        body = _compose_listing_body(event, "fetlife")
        self.assertIn(
            "2026-08-15 20:00",
            body,
            "_compose_listing_body must include the formatted start datetime in the body",
        )

    def test_compose_listing_body_includes_end_date_when_present(self):
        """When event.end is set, the body must include both start and end dates."""
        from syndication.engine import _compose_listing_body

        start = dt.datetime(2026, 8, 15, 20, 0, tzinfo=dt.UTC)
        end = dt.datetime(2026, 8, 16, 2, 0, tzinfo=dt.UTC)
        event = _make_event(slug="fl-end-test", start=start, end=end)
        body = _compose_listing_body(event, "fetlife")
        self.assertIn(
            "2026-08-15 20:00",
            body,
            "_compose_listing_body must include the formatted start datetime",
        )
        self.assertIn(
            "2026-08-16 02:00",
            body,
            "_compose_listing_body must include the formatted end datetime when present",
        )

    def test_compose_listing_body_omits_end_when_absent(self):
        """When event.end is None, the body must not blow up or include garbage."""
        from syndication.engine import _compose_listing_body

        event = _make_event(slug="fl-noend-test")
        event.end = None
        event.save(update_fields=["end"])
        # Must not raise
        body = _compose_listing_body(event, "fetlife")
        self.assertIsInstance(body, str)

    def test_compose_listing_body_includes_venue_name_when_set(self):
        """When event.venue is set, the body must include the venue name."""
        from syndication.engine import _compose_listing_body
        from venues.models import Venue

        venue = Venue.objects.create(name="The Dungeon", address="Dark Alley 1")
        event = _make_event(slug="fl-venue-test", venue=venue)
        body = _compose_listing_body(event, "fetlife")
        self.assertIn(
            "The Dungeon",
            body,
            "_compose_listing_body must include venue name when event has a venue",
        )

    def test_compose_listing_body_no_venue_does_not_crash(self):
        """When event.venue is None, the body must not raise."""
        from syndication.engine import _compose_listing_body

        event = _make_event(slug="fl-novenue-test")
        # No venue set (default is None)
        body = _compose_listing_body(event, "fetlife")
        self.assertIsInstance(body, str)


# ---------------------------------------------------------------------------
# F2. FetLife listing body composition: dress_code surfaced, markdown formatting
# ---------------------------------------------------------------------------


class FetLifeListingBodyTest(TestCase):
    """
    FetLife listing body composition via rule_based generation.

    The listing body is platform-agnostic at v0: _compose_listing_body does NOT
    apply FetLife-specific formatting. Platform-specific shaping is deferred to the
    clean_for_platform cleaning seam (kb-o0j), which is currently an identity stub.
    These tests verify that dress_code and date appear in the body — NOT that the
    body uses FetLife-divergent markdown vs. other platforms.
    """

    def setUp(self):
        self.profile = Profile.objects.create(name="FL Listing Org", slug="fl-listing-org")
        self.conn = _make_fetlife_connection(self.profile)

    def test_fetlife_listing_body_includes_dress_code(self):
        """
        The harness assertion: a FetLife listing projection body must include
        the dress_code text. This is a key FetLife-audience content element.
        """
        from syndication.engine import generate_projection, render_projection

        event = _make_event(
            slug="fl-dresscode-test",
            dress_code="Leather & latex welcome",
        )
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=event,
            mode="rule_based",
        )
        body = render_projection(proj)
        self.assertIn(
            "Leather & latex welcome",
            body,
            "FetLife listing body must include dress_code",
        )

    def test_fetlife_listing_body_includes_event_title(self):
        """The body must include the event title."""
        from syndication.engine import generate_projection, render_projection

        event = _make_event(slug="fl-title-test", title="Kinky Bubbles Party")
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=event,
            mode="rule_based",
        )
        body = render_projection(proj)
        self.assertIn("Kinky Bubbles Party", body)

    def test_fetlife_listing_body_includes_description(self):
        """The body must include event.description."""
        from syndication.engine import generate_projection, render_projection

        event = _make_event(slug="fl-desc-test", description="A fabulous BDSM party.")
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=event,
            mode="rule_based",
        )
        body = render_projection(proj)
        self.assertIn("A fabulous BDSM party.", body)

    def test_fetlife_listing_body_includes_date(self):
        """The body must include the start date (fix #1 propagated to FetLife)."""
        from syndication.engine import generate_projection, render_projection

        start = dt.datetime(2026, 9, 20, 21, 0, tzinfo=dt.UTC)
        event = _make_event(slug="fl-datecheck-test", start=start)
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=event,
            mode="rule_based",
        )
        body = render_projection(proj)
        self.assertIn(
            "2026-09-20 21:00",
            body,
            "FetLife listing body must include the formatted start datetime",
        )


# ---------------------------------------------------------------------------
# Platform-agnostic body: documented-current-behavior guard (Fix 2)
# ---------------------------------------------------------------------------


class ListingBodyPlatformAgnosticTest(TestCase):
    """
    Documented-current-behavior guard: at v0, _compose_listing_body produces
    IDENTICAL output for "fetlife" and "switch" because clean_for_platform is
    an identity stub. This test will change (and fail as a falsifying guard)
    when kb-o0j implements per-platform cleaning rules.
    """

    def test_listing_body_is_platform_agnostic_until_cleaning_seam(self):
        """
        _compose_listing_body(event, "fetlife") == _compose_listing_body(event, "switch")
        at v0 because clean_for_platform is an identity stub (kb-o0j).

        This test WILL fail when kb-o0j adds per-platform cleaning — at that
        point the test should be updated to reflect the new real behaviour.
        It currently guards the documented deferral claim.
        """
        from syndication.engine import _compose_listing_body

        start = dt.datetime(2026, 8, 15, 20, 0, tzinfo=dt.UTC)
        event = _make_event(slug="platform-agnostic-test", start=start)

        fetlife_body = _compose_listing_body(event, "fetlife")
        switch_body = _compose_listing_body(event, "switch")

        self.assertEqual(
            fetlife_body,
            switch_body,
            "_compose_listing_body must produce identical output for 'fetlife' and 'switch' "
            "at v0 (clean_for_platform is an identity stub — kb-o0j owns real rules). "
            "If this fails, kb-o0j has been implemented and this test needs updating.",
        )


# ---------------------------------------------------------------------------
# F3. Copy-to-clipboard affordance on the projection board
# ---------------------------------------------------------------------------


class FetLifeCopyAffordanceTest(TestCase):
    """
    For a FetLife (manual-assisted) listing projection in status=ready,
    the board must render a copy-to-clipboard affordance for the body.

    The clipboard mechanism is Alpine/JS (browser-only). What pytest verifies:
    - The affordance HTML is rendered (data-copy-body attribute or button).
    - The affordance contains the correct body content.
    - The mark-published path is accessible from the row.

    What is browser-only (cannot be verified in pytest):
    - The Alpine x-on:click handler actually calls navigator.clipboard.writeText().
    - The copy animation/feedback.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fl_copy_user", email="fl_copy@test.com", password="pw")
        self.profile = _make_profile(name="FL Copy Org", slug="fl-copy-org", user=self.user)
        self.event = _make_event(
            slug="fl-copy-event",
            dress_code="Fetish attire required",
            description="FetLife copy test event.",
        )
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_fetlife_connection(self.profile, destination_id="fl-copy-conn")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_fetlife_projection(self):
        """Create a FetLife listing projection and advance to ready."""
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_copy_affordance_renders_for_ready_fetlife_projection(self):
        """
        The board must render a copy affordance (clipboard button) for a
        FetLife listing projection in status=ready.

        pytest-verifiable: the affordance HTML is present in the response
        (data-copy-body attribute or recognizable copy button text).
        Browser-only: the actual clipboard copy operation via Alpine/JS.
        """
        _proj = self._make_ready_fetlife_projection()
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The copy affordance must use a specific, recognizable mechanism:
        # either a data-copy-body attribute or a "Copy" button text.
        # This is more specific than just "copy" to distinguish from template comments.
        has_copy_button = "Copy to clipboard" in content or "data-copy-body" in content
        self.assertTrue(
            has_copy_button,
            "FetLife ready projection board row must contain a copy-to-clipboard affordance "
            "('Copy to clipboard' button text or data-copy-body attribute). "
            "Browser-only: the Alpine @click clipboard action.",
        )

    def test_copy_affordance_carries_body_content(self):
        """
        The copy affordance must carry the composed body content so it can be
        put in the clipboard. The body content must be embeddable in the HTML.

        pytest-verifiable: the projection body (frozen_content) is rendered in
        the affordance. dress_code must appear since it's a required harness assertion.
        """
        _proj = self._make_ready_fetlife_projection()
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        content = response.content.decode()

        # The frozen body content must appear in the HTML
        # (so the clipboard mechanism can access it)
        self.assertIn(
            "Fetish attire required",
            content,
            "Board must render dress_code in the copy affordance content",
        )

    def test_mark_published_action_present_for_ready_fetlife_projection(self):
        """
        The board must show the mark-published action for FetLife ready projections.
        This is the actor-attestation path after out-of-band posting.
        """
        _proj = self._make_ready_fetlife_projection()
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        content = response.content.decode()
        self.assertIn(
            "Mark published",
            content,
            "Board must show 'Mark published' action for FetLife ready projection",
        )


# ---------------------------------------------------------------------------
# F4. FetLife lifecycle: draft → ready with frozen body; NO auto-confirm
# ---------------------------------------------------------------------------


class FetLifeLifecycleTest(TestCase):
    """
    FetLife listing projection lifecycle:
    - Eager-created as draft.
    - Transitioned to ready (frozen_content populated).
    - NO auto-confirm — status stays ready until actor attests mark-published.
    - Actor attestation via mark-published transitions to published.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fl_lifecycle_user", email="fl_lifecycle@test.com", password="pw")
        self.profile = _make_profile(name="FL Lifecycle Org", slug="fl-lifecycle-org", user=self.user)
        self.event = _make_event(
            slug="fl-lifecycle-event",
            dress_code="Fetish encouraged",
            description="FetLife lifecycle test.",
        )
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_fetlife_connection(self.profile, destination_id="fl-lifecycle-conn")

    def test_fetlife_listing_eager_creates_as_draft(self):
        """FetLife listing projection is created in draft status."""
        proj = _make_listing_projection(self.conn, self.event)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

    def test_fetlife_listing_reaches_ready_with_frozen_body(self):
        """
        After approve (draft→ready), frozen_content is set and contains 'body'.
        The harness assertion: the frozen body includes dress_code.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertEqual(proj.status, PlatformProjection.Status.READY)
        self.assertIsNotNone(
            proj.frozen_content,
            "FetLife projection must have frozen_content after reaching ready",
        )
        self.assertIn(
            "body",
            proj.frozen_content,
            "frozen_content must include 'body' key",
        )
        self.assertIsInstance(
            proj.frozen_content["body"],
            str,
            "frozen_content['body'] must be a string",
        )
        self.assertTrue(
            proj.frozen_content["body"],
            "frozen_content['body'] must be a non-empty string",
        )

    def test_fetlife_listing_frozen_body_includes_dress_code(self):
        """
        The harness acceptance assertion: FetLife frozen body includes dress_code.
        This is the canonical acceptance check for the bead.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertIn(
            "Fetish encouraged",
            proj.frozen_content["body"],
            "FetLife frozen body must include dress_code (harness acceptance assertion)",
        )

    def test_fetlife_listing_frozen_body_includes_date(self):
        """
        Fix #1 propagated to lifecycle: frozen body must include date.
        """
        from syndication.services import approve_projection

        start = dt.datetime(2026, 11, 5, 20, 0, tzinfo=dt.UTC)
        event = _make_event(slug="fl-frozen-date", start=start)
        EventOrganizer.objects.create(event=event, profile=self.profile, is_primary=True)
        proj = _make_listing_projection(self.conn, event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertIn(
            "2026-11-05 20:00",
            proj.frozen_content["body"],
            "FetLife frozen body must include the formatted start datetime",
        )

    def test_fetlife_listing_does_NOT_auto_confirm(self):
        """
        FetLife is manual-assisted — there is NO auto-confirm.
        After approve, status must be 'ready', NOT 'published'.
        Auto-confirm is only for Switch own-page (push-API platform).
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertEqual(
            proj.status,
            PlatformProjection.Status.READY,
            "FetLife projection must land on 'ready' after approve — no auto-confirm for manual-assisted platforms",
        )

    def test_fetlife_listing_actor_attestation_via_mark_published(self):
        """
        After the actor posts out-of-band and calls mark-published, the
        projection transitions to published.
        """
        from syndication.services import approve_projection, mark_projection_published

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        mark_projection_published(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertEqual(
            proj.status,
            PlatformProjection.Status.PUBLISHED,
            "FetLife projection must reach published after mark-published attestation",
        )

    def test_fetlife_listing_status_writes_go_via_transition_status(self):
        """
        ADR-016 D5: status writes go exclusively via transition_status.
        Verify that calling approve and mark-published do not directly set
        projection.status — they must go through the engine's transition_status.
        """
        from unittest.mock import patch

        import syndication.engine as engine_mod
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        call_count = {"n": 0}
        original_transition = engine_mod.transition_status

        def tracking_transition(projection, new_status):
            call_count["n"] += 1
            original_transition(projection, new_status)

        with patch.object(engine_mod, "transition_status", side_effect=tracking_transition):
            approve_projection(user=self.user, projection=proj)

        self.assertGreater(
            call_count["n"],
            0,
            "approve_projection must call transition_status (ADR-016 D5)",
        )

    def test_frozen_snapshot_carries_structured_venue_when_event_has_one(self):
        """
        F6 (structured snapshot gap): frozen_content must expose a structured
        'venue' key (venue name or None) so a publish carrier can read location
        without parsing the body string.

        The doc comment on _materialize_listing_fields promises 'a publish carrier
        can fill structured date/location fields from the snapshot without touching
        the live canonical' — but location is only embedded in the body string
        unless a structured key is added here.
        """
        from syndication.services import approve_projection
        from venues.models import Venue

        venue = Venue.objects.create(name="The Dungeon", address="Dark Alley 1")
        event = _make_event(
            slug="fl-frozen-venue",
            dress_code="Leather required",
            description="Venue snapshot test.",
            venue=venue,
        )
        EventOrganizer.objects.create(event=event, profile=self.profile, is_primary=True)
        proj = _make_listing_projection(self.conn, event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertIn(
            "venue",
            proj.frozen_content,
            "frozen_content must include a structured 'venue' key (F6 snapshot gap)",
        )
        self.assertEqual(
            proj.frozen_content["venue"],
            "The Dungeon",
            "frozen_content['venue'] must be the venue name string",
        )

    def test_frozen_snapshot_venue_is_none_when_event_has_no_venue(self):
        """
        F6 (structured snapshot gap): when event.venue is None, frozen_content
        must still carry 'venue': None (not omit the key).
        A carrier should be able to do frozen_content.get('venue') without
        branching on key presence.
        """
        from syndication.services import approve_projection

        event = _make_event(
            slug="fl-frozen-novenue",
            dress_code="Fetish encouraged",
            description="No venue snapshot test.",
        )
        # event.venue is None by default
        EventOrganizer.objects.create(event=event, profile=self.profile, is_primary=True)
        proj = _make_listing_projection(self.conn, event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertIn(
            "venue",
            proj.frozen_content,
            "frozen_content must include 'venue' key even when event has no venue",
        )
        self.assertIsNone(
            proj.frozen_content["venue"],
            "frozen_content['venue'] must be None when event has no venue",
        )


# ---------------------------------------------------------------------------
# F5. Visibility-agnostic: FetLife adapter publish path does NOT gate on visibility
# ---------------------------------------------------------------------------


class FetLifeVisibilityAgnosticTest(TestCase):
    """
    Adapter-level visibility-agnostic assertion (carried from kb-a4u.16).

    The FetLife adapter's publish path must NOT gate on Event.visibility.
    An unlisted/semi_public event syndicates to FetLife identically to a
    public event.

    ADR-016 carried-forward (REVISED 2026-05-27): NO visibility write-gate.
    Event.visibility governs read-side rendering on switch.berlin only.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fl_vis_user", email="fl_vis@test.com", password="pw")
        self.profile = _make_profile(name="FL Vis Org", slug="fl-vis-org", user=self.user)
        self.conn = _make_fetlife_connection(self.profile, destination_id="fl-vis-conn")

    def _create_and_advance_to_ready(self, visibility, slug_suffix):
        """
        Helper: create an event with given visibility, create FetLife listing
        projection, advance to ready, return the projection.
        """
        from syndication.services import approve_projection

        event = _make_event(
            slug=f"fl-vis-{slug_suffix}",
            visibility=visibility,
            dress_code="Fetish attire",
            description="Visibility test event.",
        )
        EventOrganizer.objects.create(event=event, profile=self.profile, is_primary=True)
        proj = _make_listing_projection(self.conn, event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_public_event_fetlife_projection_reaches_ready(self):
        """public event: FetLife projection reaches ready normally."""
        proj = self._create_and_advance_to_ready("public", "pub")
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

    def test_unlisted_event_fetlife_projection_reaches_ready(self):
        """
        unlisted event: FetLife projection reaches ready identically to public.
        Visibility must NOT suppress or gate the FetLife syndication path.
        """
        proj = self._create_and_advance_to_ready("unlisted", "unl")
        self.assertEqual(
            proj.status,
            PlatformProjection.Status.READY,
            "unlisted event: FetLife projection must reach ready — no visibility gate",
        )

    def test_semi_public_event_fetlife_projection_reaches_ready(self):
        """semi_public event: FetLife projection reaches ready identically to public."""
        proj = self._create_and_advance_to_ready("semi_public", "semi")
        self.assertEqual(
            proj.status,
            PlatformProjection.Status.READY,
            "semi_public event: FetLife projection must reach ready — no visibility gate",
        )

    def test_all_visibility_tiers_produce_same_dress_code_body(self):
        """
        All three visibility tiers produce a FetLife body that includes dress_code.
        This is the combined acceptance + visibility-agnostic assertion.
        """
        for visibility in ["public", "semi_public", "unlisted"]:
            proj = self._create_and_advance_to_ready(visibility, f"combined-{visibility}")
            self.assertIsNotNone(proj.frozen_content)
            self.assertIn(
                "Fetish attire",
                proj.frozen_content["body"],
                f"visibility={visibility!r}: FetLife body must include dress_code",
            )

    def test_unlisted_fetlife_projection_can_be_actor_attested(self):
        """
        unlisted event: the actor can mark the FetLife projection as published
        (out-of-band attestation). Visibility must not block this.
        """
        from syndication.services import mark_projection_published

        proj = self._create_and_advance_to_ready("unlisted", "attest-unl")
        mark_projection_published(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(
            proj.status,
            PlatformProjection.Status.PUBLISHED,
            "unlisted event: FetLife projection must reach published via mark-published",
        )

    def test_visibility_does_not_affect_fetlife_frozen_body(self):
        """
        The FetLife frozen body is EQUAL across visibility tiers — visibility
        must NOT alter the body at all (no tier-specific content suppression).

        Uses a fixed start time so all three events produce byte-identical bodies
        (barring visibility-driven divergence, which this test would catch).
        """
        from syndication.services import approve_projection

        fixed_start = dt.datetime(2026, 10, 10, 20, 0, tzinfo=dt.UTC)
        bodies = {}
        for visibility in ["public", "semi_public", "unlisted"]:
            event = _make_event(
                slug=f"fl-vis-eq-{visibility}",
                visibility=visibility,
                dress_code="Fetish attire",
                description="Visibility body equality test.",
                title="Kinky Bubbles Party",
                start=fixed_start,
            )
            EventOrganizer.objects.create(event=event, profile=self.profile, is_primary=True)
            proj = _make_listing_projection(self.conn, event)
            approve_projection(user=self.user, projection=proj)
            proj.refresh_from_db()
            bodies[visibility] = proj.frozen_content["body"]

        # All three bodies must be byte-identical — visibility must not alter the body
        self.assertEqual(
            bodies["public"],
            bodies["semi_public"],
            "Body for 'public' and 'semi_public' must be identical (visibility must not alter body)",
        )
        self.assertEqual(
            bodies["public"],
            bodies["unlisted"],
            "Body for 'public' and 'unlisted' must be identical (visibility must not alter body)",
        )
