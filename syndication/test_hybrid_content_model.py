"""
TDD tests for the hybrid content model (kb-a4u.20).

ADR-016 D2 (revised 2026-05-27): A projection's effective content TRACKS the
live canonical (Event/Post fields + per-field override_data deltas) while it
is in draft. At the draft→ready transition, the effective content FREEZES:
materialize the then-current effective content into a stored snapshot. From
ready onward (ready, published, failed), reads return the frozen snapshot.

Two-part stability test per bead acceptance (parent acceptance #4 reframe):
  (i)  Draft tracks live canonical.
  (ii) Ready returns frozen snapshot — immune to subsequent canonical edits.

Additional tests:
  - render_projection on manually-created (no override_data) projection in
    draft still derives from live canonical (live-fallback follows same rule).
  - render_projection on a frozen projection with NO live canonical still works
    (uses the snapshot).
  - Re-open transition: ready→draft is a legal edge (re-approval path).
  - render_projection raises loud if projection is not draft and has no frozen
    snapshot (fail loud per ADR-008 D3).
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from syndication.engine import generate_projection, render_projection, transition_status
from syndication.models import PlatformConnection, PlatformProjection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs):
    defaults = {
        "title": "Hybrid Test Party",
        "slug": "hybrid-test-party",
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_connection(destination_id="fl-hybrid-001", **kwargs):
    profile = Profile.objects.create(
        name=f"Hybrid Organizer ({destination_id})",
        slug=f"hybrid-organizer-{destination_id}".replace(":", "-"),
    )
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Core stability test: two-part hybrid rule
# ---------------------------------------------------------------------------

class HybridContentModelStabilityTest(TestCase):
    """
    Two-part stability test per parent acceptance #4 reframe (kb-a4u comment
    2026-05-27).

    (i)  Draft projection TRACKS live canonical — an edit to a canonical Event
         field IS visible in render_projection while status==draft.
    (ii) Ready projection FREEZES at transition — a subsequent canonical edit
         does NOT propagate into render_projection when status==ready.
    """

    def test_draft_projection_tracks_live_canonical_after_canonical_edit(self):
        """
        (i) LIVE TRACKING IN DRAFT.

        Generate a projection (lands in draft). Edit the canonical Event title.
        The draft projection's rendered body MUST reflect the edited title —
        draft projections track the live canonical.

        This requires draft render to derive body from live canonical fields,
        not from a stale snapshot.
        """
        event = _make_event(title="Original Title", slug="hybrid-draft-track-1")
        conn = _make_connection(destination_id="fl-hybrid-draft-track-1")

        # Generate: projection lands in draft, override_data["body"] is the
        # initial snapshot of the canonical at generation time.
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

        # Edit canonical AFTER generation
        event.title = "Edited Title After Generation"
        event.save()
        # Re-fetch event to confirm DB write
        event.refresh_from_db()

        # Draft must reflect the edit (live canonical tracking in draft)
        body = render_projection(proj)
        self.assertIn(
            "Edited Title After Generation",
            body,
            "Draft projection must track live canonical: edited title must appear",
        )
        self.assertNotIn(
            "Original Title",
            body,
            "Draft projection must NOT return the stale pre-edit title",
        )

    def test_ready_projection_body_frozen_at_transition_immune_to_subsequent_canonical_edit(self):
        """
        (ii) FROZEN SNAPSHOT AT READY.

        Generate a projection (draft). Flip to ready (freeze). Edit the
        canonical Event title again. The ready projection's rendered body
        MUST NOT reflect the post-freeze edit — the snapshot is frozen.
        """
        event = _make_event(title="Pre-Freeze Title", slug="hybrid-ready-freeze-1")
        conn = _make_connection(destination_id="fl-hybrid-ready-freeze-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

        # Flip to ready — this must materialize (freeze) the effective content
        transition_status(proj, "ready")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        # Edit canonical AFTER freezing
        event.title = "Post-Freeze Canonical Edit"
        event.save()

        # Ready projection must return the frozen (pre-edit) snapshot
        body = render_projection(proj)
        self.assertIn(
            "Pre-Freeze Title",
            body,
            "Ready projection must return the frozen snapshot: pre-freeze title must appear",
        )
        self.assertNotIn(
            "Post-Freeze Canonical Edit",
            body,
            "Ready projection must NOT reflect post-freeze canonical edits",
        )


# ---------------------------------------------------------------------------
# Draft manual-projection: live-fallback follows the same draft rule
# ---------------------------------------------------------------------------

class DraftManualProjectionLiveFallbackTest(TestCase):
    """
    Manually-created projections (no override_data["body"]) in draft status
    must also derive from live canonical — the live-fallback removal means the
    draft path handles this, not a special-case hidden fallback.
    """

    def test_manual_draft_projection_derives_from_live_canonical(self):
        """
        A manually-created projection (provenance=manual, no override_data["body"])
        in draft status returns content derived from the live canonical event fields.
        """
        event = _make_event(title="Live Title for Manual", slug="hybrid-manual-draft-1")
        conn = _make_connection(destination_id="fl-hybrid-manual-draft-1")

        # Manually create — no body in override_data
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=conn,
            source_event=event,
            override_data={},  # no "body" key
            provenance=PlatformProjection.Provenance.MANUAL,
        )

        body = render_projection(proj)
        self.assertIn("Live Title for Manual", body)

    def test_manual_draft_projection_tracks_live_canonical_after_edit(self):
        """
        Manually-created draft projection tracks live canonical after a canonical edit.
        """
        event = _make_event(title="Manual Original", slug="hybrid-manual-track-1")
        conn = _make_connection(destination_id="fl-hybrid-manual-track-1")

        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=conn,
            source_event=event,
            override_data={},
            provenance=PlatformProjection.Provenance.MANUAL,
        )

        # Edit canonical
        event.title = "Manual Edited"
        event.save()

        body = render_projection(proj)
        self.assertIn("Manual Edited", body)
        self.assertNotIn("Manual Original", body)


# ---------------------------------------------------------------------------
# Frozen snapshot survives even if canonical source is unavailable
# ---------------------------------------------------------------------------

class FrozenSnapshotIndependenceTest(TestCase):
    """
    The frozen snapshot must be self-contained: render_projection on a ready/
    published projection returns the snapshot regardless of the live canonical.
    """

    def test_ready_projection_frozen_snapshot_field_is_set_at_transition(self):
        """
        After draft→ready transition, the projection's frozen_content field
        must contain the effective content materialized at freeze time.
        """
        event = _make_event(title="Freeze Check Title", slug="hybrid-freeze-check-1")
        conn = _make_connection(destination_id="fl-hybrid-freeze-check-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        # Sanity: no frozen content yet in draft
        self.assertIsNone(proj.frozen_content)

        transition_status(proj, "ready")
        proj.refresh_from_db()

        # frozen_content must be set now
        self.assertIsNotNone(proj.frozen_content)
        self.assertIn("body", proj.frozen_content)
        self.assertIn("Freeze Check Title", proj.frozen_content["body"])

    def test_published_projection_also_returns_frozen_snapshot(self):
        """
        Published projections (status=published) also return the frozen snapshot.
        """
        event = _make_event(title="Published Freeze Title", slug="hybrid-pub-freeze-1")
        conn = _make_connection(destination_id="fl-hybrid-pub-freeze-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        transition_status(proj, "published")
        proj.refresh_from_db()

        # Edit canonical after publishing
        event.title = "Post-Publish Canonical Edit"
        event.save()

        body = render_projection(proj)
        self.assertIn("Published Freeze Title", body)
        self.assertNotIn("Post-Publish Canonical Edit", body)


# ---------------------------------------------------------------------------
# Fail loud: non-draft projection with no frozen snapshot
# ---------------------------------------------------------------------------

class FrozenContentFailLoudTest(TestCase):
    """
    ADR-008 D3: fail loud.

    If a projection is in ready/published/failed status but has no
    frozen_content (e.g. legacy data or bug), render_projection must raise
    ValueError — not silently fall back to live canonical.
    """

    def test_render_raises_for_ready_projection_with_no_frozen_content(self):
        """
        A ready projection without frozen_content must raise ValueError.
        No silent fallback to live canonical for non-draft projections.
        """
        event = _make_event(title="No Freeze Fail Loud", slug="hybrid-no-freeze-1")
        conn = _make_connection(destination_id="fl-hybrid-no-freeze-1")

        # Manually create a ready projection with no frozen_content (simulates
        # legacy/buggy data — this state should never happen post-implementation)
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=conn,
            source_event=event,
            override_data={"body": "some body"},
            frozen_content=None,  # deliberately missing
        )

        with self.assertRaises(ValueError) as ctx:
            render_projection(proj)

        self.assertIn("frozen", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Re-open transition: ready→draft is a legal edge
# ---------------------------------------------------------------------------

class ReOpenTransitionTest(TestCase):
    """
    To propagate a later canonical edit into an already-ready projection,
    the facilitator re-opens it (ready→draft), edits the canonical, then
    re-approves (draft→ready), which freezes a fresh snapshot.

    The ready→draft transition edge must exist in _LEGAL_TRANSITIONS.
    """

    def test_ready_to_draft_is_a_legal_transition(self):
        """
        ready→draft must be a legal transition (re-open for re-approval).
        """
        event = _make_event(title="Re-Open Test", slug="hybrid-reopen-1")
        conn = _make_connection(destination_id="fl-hybrid-reopen-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.READY)

        # Re-open: ready→draft
        transition_status(proj, "draft")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

    def test_reopen_then_reapprove_freezes_fresh_snapshot(self):
        """
        After re-open (ready→draft), a canonical edit becomes visible in draft,
        and re-approving (draft→ready) freezes the updated content.
        """
        event = _make_event(title="Pre-Reopen Title", slug="hybrid-reopen-cycle-1")
        conn = _make_connection(destination_id="fl-hybrid-reopen-cycle-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        # First approval cycle
        transition_status(proj, "ready")
        proj.refresh_from_db()

        body_at_first_ready = render_projection(proj)
        self.assertIn("Pre-Reopen Title", body_at_first_ready)

        # Re-open
        transition_status(proj, "draft")
        proj.refresh_from_db()

        # Edit canonical while in draft
        event.title = "Post-Reopen Canonical Edit"
        event.save()

        # In draft: must track live canonical
        body_in_draft = render_projection(proj)
        self.assertIn("Post-Reopen Canonical Edit", body_in_draft)

        # Re-approve: freeze the new canonical
        transition_status(proj, "ready")
        proj.refresh_from_db()

        # After re-freeze: edit canonical again — must NOT propagate
        event.title = "After Second Freeze Edit"
        event.save()

        body_at_second_ready = render_projection(proj)
        self.assertIn("Post-Reopen Canonical Edit", body_at_second_ready)
        self.assertNotIn("After Second Freeze Edit", body_at_second_ready)
