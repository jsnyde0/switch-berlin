"""
Regression-guard integration test: syndication is visibility-tier-agnostic.

ADR-016 carried-forward (REVISED 2026-05-27): There is NO visibility write-gate.
Event.visibility governs read-side rendering on switch.berlin (visible_to) only —
it does NOT gate outbound syndication. Eager creation is uniform across all
visibility tiers (unlisted/semi_public/public produce the same draft set).

This file guards against a future dev re-adding something like:
    if event.visibility == "unlisted": skip

in the eager-creation, generation, or adapter path.

Guards:
G1. Eager-create path (services._eager_create_listing_projections):
    For each visibility tier, the SAME set of draft projections is created
    (one per enabled listing-capable PlatformConnection). Count and connection
    coverage are identical regardless of visibility.

G2. Lifecycle path (engine.transition_status):
    Each visibility tier can be advanced draft→ready→published without
    any tier-based suppression. Status is verified at each step.

Test design:
- One organizer with two enabled PlatformConnections of differing kinds:
    conn_listing: platform="switch", kinds=["listing"]
    conn_both:    platform="fetlife", kinds=["listing", "promotion"]
- Three events at visibility public / semi_public / unlisted (all else equal).
- All three events are created via create_event (the service seam).
- Assertions are parametrized over all three visibility tiers.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers (mirrors patterns from test_authoring.py / test_projection_board.py)
# ---------------------------------------------------------------------------

VISIBILITY_TIERS = ["public", "semi_public", "unlisted"]


def _make_vouched_user(**kwargs):
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


def _make_connection(profile, platform, destination_id, kinds, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# G1 — Eager-create path: visibility does NOT affect the draft projection set
# ---------------------------------------------------------------------------


class VisibilityAgnosticEagerCreateTest(TestCase):
    """
    G1: services.create_event eager-creates the SAME draft projection set for
    public, semi_public, and unlisted events.

    Failure mode guarded: if a future dev adds:
        if event.visibility == "unlisted": return
    in _eager_create_listing_projections (or similar), this test will fail
    because the unlisted event will have 0 projections while public has 2.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="vis_eager_user", email="vis_eager@test.com", password="x"
        )
        self.profile = _make_profile(
            name="Vis Eager Profile", slug="vis-eager-profile", user=self.user
        )
        # Two enabled listing-capable connections — the expected eager count is 2.
        self.conn_switch = _make_connection(
            self.profile,
            platform="switch",
            destination_id="vis-switch",
            kinds=["listing"],
        )
        self.conn_fetlife = _make_connection(
            self.profile,
            platform="fetlife",
            destination_id="vis-fetlife",
            kinds=["listing", "promotion"],
        )
        # Expected eager projection count per event (listing connections only)
        self.expected_listing_count = 2

    def _create_event_for_tier(self, visibility, slug_suffix):
        from syndication.services import create_event
        return create_event(
            user=self.user,
            title=f"Visibility Test Event ({visibility})",
            slug=f"vis-test-event-{slug_suffix}",
            start=timezone.now(),
            visibility=visibility,
        )

    def test_public_event_eager_creates_expected_listing_projections(self):
        """public event produces expected draft listing projections."""
        event = self._create_event_for_tier("public", "pub")
        count = PlatformProjection.objects.filter(
            source_event=event,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
        ).count()
        self.assertEqual(
            count,
            self.expected_listing_count,
            f"public event: expected {self.expected_listing_count} listing projections, got {count}",
        )

    def test_semi_public_event_eager_creates_expected_listing_projections(self):
        """semi_public event produces the SAME draft listing projections as public."""
        event = self._create_event_for_tier("semi_public", "semi")
        count = PlatformProjection.objects.filter(
            source_event=event,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
        ).count()
        self.assertEqual(
            count,
            self.expected_listing_count,
            f"semi_public event: expected {self.expected_listing_count} listing projections, got {count}. "
            "Visibility must NOT suppress eager creation.",
        )

    def test_unlisted_event_eager_creates_expected_listing_projections(self):
        """unlisted event produces the SAME draft listing projections as public."""
        event = self._create_event_for_tier("unlisted", "unl")
        count = PlatformProjection.objects.filter(
            source_event=event,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
        ).count()
        self.assertEqual(
            count,
            self.expected_listing_count,
            f"unlisted event: expected {self.expected_listing_count} listing projections, got {count}. "
            "Visibility must NOT suppress eager creation.",
        )

    def test_all_three_tiers_produce_identical_projection_count(self):
        """
        The count of eager-created listing projections is IDENTICAL for all three
        visibility tiers. This is the canonical regression guard assertion.

        If any tier were gated, its count would diverge from the others.
        """
        events = {}
        for visibility in VISIBILITY_TIERS:
            events[visibility] = self._create_event_for_tier(visibility, visibility)

        counts = {}
        for visibility, event in events.items():
            counts[visibility] = PlatformProjection.objects.filter(
                source_event=event,
                kind=PlatformProjection.Kind.LISTING,
                status=PlatformProjection.Status.DRAFT,
            ).count()

        # All counts must be equal to the expected count
        for visibility, count in counts.items():
            self.assertEqual(
                count,
                self.expected_listing_count,
                f"visibility={visibility!r}: count={count} != expected={self.expected_listing_count}. "
                "Visibility must NOT gate eager projection creation.",
            )

        # Cross-tier: all counts must be equal to each other
        unique_counts = set(counts.values())
        self.assertEqual(
            len(unique_counts),
            1,
            f"Projection counts diverge across tiers: {counts}. "
            "All tiers must produce the same number of eager projections.",
        )

    def test_all_three_tiers_cover_same_connection_set(self):
        """
        Each visibility tier's eager-created projections cover the SAME set of
        enabled listing-capable connections (conn_switch + conn_fetlife).

        A tier-gating bug could produce the right count but wrong connections,
        so we verify the connection set identity explicitly.
        """
        expected_conn_ids = {self.conn_switch.pk, self.conn_fetlife.pk}

        for visibility in VISIBILITY_TIERS:
            event = self._create_event_for_tier(visibility, f"conn-{visibility}")
            conn_ids = set(
                PlatformProjection.objects.filter(
                    source_event=event,
                    kind=PlatformProjection.Kind.LISTING,
                    status=PlatformProjection.Status.DRAFT,
                ).values_list("connection_id", flat=True)
            )
            self.assertEqual(
                conn_ids,
                expected_conn_ids,
                f"visibility={visibility!r}: connection set {conn_ids} != expected {expected_conn_ids}. "
                "All enabled listing-capable connections must be covered regardless of visibility.",
            )


# ---------------------------------------------------------------------------
# G2 — Lifecycle path: visibility does NOT suppress draft→ready→published
# ---------------------------------------------------------------------------


class VisibilityAgnosticLifecycleTest(TestCase):
    """
    G2: The draft→ready→published lifecycle succeeds identically for all three
    visibility tiers — no tier-based suppression at any generation or adapter step.

    Failure mode guarded: if a future dev adds:
        if event.visibility != "public": raise ...  # or silently skips
    in transition_status or a generation helper, the non-public tiers would
    fail to advance and this test would catch it.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="vis_lifecycle_user", email="vis_lifecycle@test.com", password="x"
        )
        self.profile = _make_profile(
            name="Vis Lifecycle Profile", slug="vis-lifecycle-profile", user=self.user
        )
        self.conn = _make_connection(
            self.profile,
            platform="switch",
            destination_id="vis-lifecycle-conn",
            kinds=["listing"],
        )

    def _create_event_for_tier(self, visibility, slug_suffix):
        from syndication.services import create_event
        return create_event(
            user=self.user,
            title=f"Lifecycle Test Event ({visibility})",
            slug=f"vis-lifecycle-{slug_suffix}",
            start=timezone.now(),
            visibility=visibility,
        )

    def _get_listing_projection(self, event):
        """Return the single eager-created listing projection for this event."""
        projs = list(
            PlatformProjection.objects.filter(
                source_event=event,
                kind=PlatformProjection.Kind.LISTING,
                connection=self.conn,
            )
        )
        self.assertEqual(
            len(projs),
            1,
            f"Expected exactly 1 listing projection for event (visibility={event.visibility!r}), "
            f"got {len(projs)}. Eager creation may be gated.",
        )
        return projs[0]

    def _advance_lifecycle(self, proj):
        """Drive projection through draft→ready→published, return final status."""
        from syndication.engine import transition_status
        # draft → ready (freezes content)
        transition_status(proj, "ready")
        proj.refresh_from_db()
        self.assertEqual(
            proj.status,
            PlatformProjection.Status.READY,
            f"Projection for event (connection={proj.connection.platform!r}) "
            f"did not reach 'ready'. Current status: {proj.status!r}",
        )
        # ready → published
        transition_status(proj, "published")
        proj.refresh_from_db()
        return proj.status

    def test_public_event_projection_advances_draft_to_published(self):
        """public event: listing projection can be advanced draft→ready→published."""
        event = self._create_event_for_tier("public", "pub")
        proj = self._get_listing_projection(event)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)
        final_status = self._advance_lifecycle(proj)
        self.assertEqual(
            final_status,
            PlatformProjection.Status.PUBLISHED,
            "public event: projection did not reach 'published'",
        )

    def test_semi_public_event_projection_advances_draft_to_published(self):
        """semi_public event: listing projection advances identically to public."""
        event = self._create_event_for_tier("semi_public", "semi")
        proj = self._get_listing_projection(event)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)
        final_status = self._advance_lifecycle(proj)
        self.assertEqual(
            final_status,
            PlatformProjection.Status.PUBLISHED,
            "semi_public event: visibility must NOT suppress lifecycle advancement",
        )

    def test_unlisted_event_projection_advances_draft_to_published(self):
        """unlisted event: listing projection advances identically to public."""
        event = self._create_event_for_tier("unlisted", "unl")
        proj = self._get_listing_projection(event)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)
        final_status = self._advance_lifecycle(proj)
        self.assertEqual(
            final_status,
            PlatformProjection.Status.PUBLISHED,
            "unlisted event: visibility must NOT suppress lifecycle advancement",
        )

    def test_all_three_tiers_reach_published_status(self):
        """
        All three visibility tiers reach 'published' via the normal lifecycle.
        This is the canonical lifecycle regression guard — if any tier were gated,
        it would not reach 'published' and this assertion would fail.
        """
        final_statuses = {}
        for visibility in VISIBILITY_TIERS:
            event = self._create_event_for_tier(visibility, f"all-{visibility}")
            proj = self._get_listing_projection(event)
            self.assertEqual(
                proj.status,
                PlatformProjection.Status.DRAFT,
                f"visibility={visibility!r}: expected initial DRAFT status",
            )
            final_statuses[visibility] = self._advance_lifecycle(proj)

        for visibility, status in final_statuses.items():
            self.assertEqual(
                status,
                PlatformProjection.Status.PUBLISHED,
                f"visibility={visibility!r}: expected PUBLISHED, got {status!r}. "
                "Visibility must NOT gate the lifecycle.",
            )

    def test_frozen_content_materialized_at_ready_for_all_tiers(self):
        """
        At draft→ready, frozen_content is materialized for ALL visibility tiers.
        The frozen snapshot must be a non-empty dict regardless of visibility.

        Guards against a future dev that materializes frozen_content only for
        public events (e.g. "only public events need syndication snapshots").
        """
        for visibility in VISIBILITY_TIERS:
            event = self._create_event_for_tier(visibility, f"frozen-{visibility}")
            proj = self._get_listing_projection(event)

            from syndication.engine import transition_status
            transition_status(proj, "ready")
            proj.refresh_from_db()

            self.assertIsNotNone(
                proj.frozen_content,
                f"visibility={visibility!r}: frozen_content is None after draft→ready. "
                "Content must be materialized regardless of visibility.",
            )
            self.assertIn(
                "body",
                proj.frozen_content,
                f"visibility={visibility!r}: frozen_content missing 'body' key. "
                "Full effective content must be frozen at ready regardless of visibility.",
            )
