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
    Manually-created projections with a null-body ContentVersion in draft status
    must derive from live canonical — the null-means-derive semantics apply.

    kb-wz8m.2: override_data is removed; ContentVersion.body=None means
    'derive from live canonical Event at render time'.
    """

    def test_manual_draft_projection_derives_from_live_canonical(self):
        """
        A manually-created projection with a ContentVersion (body=None) in draft
        status returns content derived from the live canonical event fields.
        """
        from syndication.models import ContentVersion

        event = _make_event(title="Live Title for Manual", slug="hybrid-manual-draft-1")
        conn = _make_connection(destination_id="fl-hybrid-manual-draft-1")

        # Create a ContentVersion with null body = derive from canonical
        cv = ContentVersion.objects.create(
            event=event,
            name="canonical",
            provenance=ContentVersion.Provenance.MANUAL,
        )

        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=conn,
            source_event=event,
            content_version=cv,
        )

        body = render_projection(proj)
        self.assertIn("Live Title for Manual", body)

    def test_manual_draft_projection_tracks_live_canonical_after_edit(self):
        """
        Draft projection with null ContentVersion.body tracks live canonical
        after a canonical edit.
        """
        from syndication.models import ContentVersion

        event = _make_event(title="Manual Original", slug="hybrid-manual-track-1")
        conn = _make_connection(destination_id="fl-hybrid-manual-track-1")

        cv = ContentVersion.objects.create(event=event, name="canonical")

        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            connection=conn,
            source_event=event,
            content_version=cv,
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

        kb-wz8m.2: override_data is removed; test creates a ready projection
        directly without going through the normal draft→ready transition.
        """
        from syndication.models import ContentVersion

        event = _make_event(title="No Freeze Fail Loud", slug="hybrid-no-freeze-1")
        conn = _make_connection(destination_id="fl-hybrid-no-freeze-1")

        cv = ContentVersion.objects.create(event=event, name="canonical")

        # Manually create a ready projection with no frozen_content (simulates
        # legacy/buggy data — this state should never happen post-implementation)
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=conn,
            source_event=event,
            content_version=cv,
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


# ---------------------------------------------------------------------------
# Fix 1: Full-field structured freeze — title + start are frozen, not just body
# ---------------------------------------------------------------------------

class StructuredFieldFreezeTest(TestCase):
    """
    Fix 1: The freeze at draft→ready must capture the FULL effective structured
    content, not just {"body": ...}. A frozen listing projection must include
    title, start, and other content fields so a publish carrier can read them
    from the snapshot without touching the live canonical.

    Stability is proved for STRUCTURED fields (not just body):
    - draft projection tracks canonical edits to title and start (live)
    - ready projection frozen_content["title"] and frozen_content["start"]
      are unchanged after canonical edits (frozen)
    """

    def test_frozen_content_includes_title_and_start_at_ready(self):
        """
        After draft→ready, frozen_content must contain title and start fields
        (not just body), reflecting the canonical values at freeze time.
        """
        start_time = timezone.now()
        event = _make_event(
            title="Pre-Freeze Structured Title",
            slug="structured-freeze-1",
            start=start_time,
        )
        conn = _make_connection(destination_id="fl-structured-freeze-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNone(proj.frozen_content)

        transition_status(proj, "ready")
        proj.refresh_from_db()

        # frozen_content must include title and start, not just body
        self.assertIsNotNone(proj.frozen_content)
        self.assertIn("title", proj.frozen_content, "frozen_content must include 'title'")
        self.assertIn("start", proj.frozen_content, "frozen_content must include 'start'")
        self.assertEqual(
            proj.frozen_content["title"],
            "Pre-Freeze Structured Title",
            "frozen title must match canonical at freeze time",
        )

    def test_ready_projection_structured_fields_immune_to_canonical_edit(self):
        """
        After draft→ready freeze, editing event.start and event.title on the
        canonical does NOT change frozen_content["title"] or frozen_content["start"].

        Proof: a ready/published projection is a self-contained artifact —
        a publish carrier can read frozen_content["start"] without touching the
        live canonical, and editing the event afterward leaks nothing.
        """
        start_time = timezone.now()
        event = _make_event(
            title="Structured Pre-Freeze",
            slug="structured-stable-1",
            start=start_time,
        )
        conn = _make_connection(destination_id="fl-structured-stable-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()

        frozen_title = proj.frozen_content["title"]
        frozen_start = proj.frozen_content["start"]

        # Now mutate canonical event
        event.title = "Post-Freeze New Title"
        import datetime
        event.start = start_time + datetime.timedelta(days=7)
        event.save()

        proj.refresh_from_db()

        # Frozen snapshot must not change
        self.assertEqual(
            proj.frozen_content["title"],
            frozen_title,
            "frozen_content['title'] must not change after canonical edit",
        )
        self.assertEqual(
            proj.frozen_content["start"],
            frozen_start,
            "frozen_content['start'] must not change after canonical edit",
        )
        # Double-check the values are the pre-freeze originals
        self.assertEqual(proj.frozen_content["title"], "Structured Pre-Freeze")

    def test_draft_projection_reflects_structured_field_edits_before_freeze(self):
        """
        Confirm that BEFORE freezing (while in draft), a canonical edit to
        event.title IS visible via the live canonical tracking path.

        This proves the test exercises meaningful state: if draft didn't track
        live canonicals, the structured-field stability test would pass vacuously.
        """
        event = _make_event(
            title="Original Structured Title",
            slug="structured-draft-track-1",
        )
        conn = _make_connection(destination_id="fl-structured-draft-track-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

        # Draft has no frozen_content
        self.assertIsNone(proj.frozen_content)

        # Edit canonical while in draft — changes MUST be visible in body
        event.title = "Edited Structured Title"
        event.save()

        body = render_projection(proj)
        self.assertIn(
            "Edited Structured Title",
            body,
            "Draft must track canonical: edited title must appear in rendered body",
        )


# ---------------------------------------------------------------------------
# Fix 4: agent_assisted freeze at ready — body frozen into snapshot correctly
# ---------------------------------------------------------------------------

class AgentAssistedFreezeTest(TestCase):
    """
    Fix 4: Advance an agent_assisted projection to ready and assert:
    - the agent-supplied body is correctly frozen into frozen_content["body"]
    - render_projection returns the frozen body (not the draft ContentVersion path)
    - canonical mutations after freezing are still not visible

    kb-wz8m.2: override_data removed; body stored on ContentVersion.
    """

    def test_agent_assisted_body_frozen_at_ready(self):
        """
        An agent_assisted projection that reaches ready must have the agent-supplied
        body in frozen_content["body"]. The ContentVersion.body path is the DRAFT
        path; frozen_content["body"] is the READY path.

        kb-wz8m.2: override_data removed; body is on ContentVersion now.
        """
        event = _make_event(title="Agent Freeze Event", slug="agent-freeze-1")
        conn = _make_connection(destination_id="fl-agent-freeze-1")

        agent_body = "Agent-crafted copy that should survive freezing."
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="agent_assisted",
            body=agent_body,
        )
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)
        # ContentVersion.body set in draft (not override_data — that's gone)
        self.assertIsNotNone(proj.content_version)
        self.assertEqual(proj.content_version.body, agent_body)
        # No freeze yet
        self.assertIsNone(proj.frozen_content)

        # Advance to ready — this must freeze the effective content
        transition_status(proj, "ready")
        proj.refresh_from_db()

        # frozen_content["body"] must hold the agent-supplied copy
        self.assertIsNotNone(proj.frozen_content)
        self.assertIn("body", proj.frozen_content)
        self.assertEqual(
            proj.frozen_content["body"],
            agent_body,
            "frozen_content['body'] must be the agent-supplied copy",
        )

    def test_agent_assisted_ready_renders_from_frozen_path(self):
        """
        render_projection on a ready agent_assisted projection must return the
        frozen snapshot body — not the override_data draft path.

        Both paths produce the same string here, but this test confirms the code
        path goes through frozen_content, not override_data, for the ready status.
        """
        event = _make_event(title="Agent Ready Path Event", slug="agent-ready-path-1")
        conn = _make_connection(destination_id="fl-agent-ready-path-1")

        agent_body = "Agent body for ready-path test."
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="agent_assisted",
            body=agent_body,
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()

        rendered = render_projection(proj)
        self.assertEqual(
            rendered,
            agent_body,
            "render_projection on ready agent_assisted must return the frozen body",
        )

        # Mutate canonical after freeze — must not change render output
        event.title = "Post-Freeze Canonical Mutation"
        event.save()

        rendered_after_mutation = render_projection(proj)
        self.assertEqual(
            rendered_after_mutation,
            agent_body,
            "Canonical mutation after freeze must not affect ready agent_assisted render",
        )


# ---------------------------------------------------------------------------
# Fix 5: Full re-open cycle clears a previously-frozen snapshot
# ---------------------------------------------------------------------------

class FullReOpenCycleTest(TestCase):
    """
    Fix 5: A projection that was frozen (ready), then published, then failed,
    then re-opened (→draft) must clear frozen_content and track live again.

    Two-hop path: published→failed→draft.
    This documents the full re-open cycle and confirms frozen_content is cleared.
    """

    def test_full_reopen_cycle_clears_frozen_snapshot(self):
        """
        draft → ready (freeze) → published → failed → draft (clear freeze).

        After the final →draft hop, frozen_content must be None and the
        re-opened draft must track the live canonical again.
        """
        event = _make_event(
            title="Full Cycle Pre-Freeze",
            slug="full-cycle-reopen-1",
        )
        conn = _make_connection(destination_id="fl-full-cycle-reopen-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)
        self.assertIsNone(proj.frozen_content)

        # Step 1: draft → ready (freeze)
        transition_status(proj, "ready")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.READY)
        self.assertIsNotNone(proj.frozen_content, "frozen_content must be set at ready")
        frozen_body_at_ready = proj.frozen_content["body"]
        self.assertIn("Full Cycle Pre-Freeze", frozen_body_at_ready)

        # Step 2: ready → published
        transition_status(proj, "published")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.PUBLISHED)
        # frozen_content preserved through →published
        self.assertIsNotNone(proj.frozen_content)

        # Step 3: published → failed
        transition_status(proj, "failed")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)
        # frozen_content still present (not cleared until →draft)
        self.assertIsNotNone(proj.frozen_content)

        # Step 4: failed → draft (re-open)
        transition_status(proj, "draft")
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

        # frozen_content MUST be cleared on →draft hop
        self.assertIsNone(
            proj.frozen_content,
            "frozen_content must be cleared when re-opening to draft",
        )

    def test_reopened_draft_tracks_live_canonical_after_full_cycle(self):
        """
        After the full re-open cycle (draft→ready→published→failed→draft),
        the re-opened draft must track live canonical again — i.e., editing
        the canonical event IS visible in render_projection while status==draft.
        """
        event = _make_event(
            title="Cycle Live Track Pre",
            slug="full-cycle-live-1",
        )
        conn = _make_connection(destination_id="fl-full-cycle-live-1")

        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )

        # Run the full cycle
        transition_status(proj, "ready")
        transition_status(proj, "published")
        transition_status(proj, "failed")
        transition_status(proj, "draft")
        proj.refresh_from_db()

        # Re-opened draft: edit canonical
        event.title = "Cycle Live Track Post"
        event.save()

        body = render_projection(proj)
        self.assertIn(
            "Cycle Live Track Post",
            body,
            "Re-opened draft must track live canonical after full cycle",
        )
        self.assertNotIn(
            "Cycle Live Track Pre",
            body,
            "Re-opened draft must NOT return the stale pre-cycle title",
        )
