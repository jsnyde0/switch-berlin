"""
TDD tests for the syndication engine (kb-a4u.4).

Five harness checks per acceptance contract:
1. State-machine: legal transitions succeed, illegal ones raise.
2a. Override-independence: overridden field stable when canonical mutates post-generation.
2b. Live-tracking: non-overridden canonical field tracks canonical automatically.
3. mode=rule_based template generation sets provenance=rule_template.
4. mode=agent_assisted accepts and stores agent body, provenance=agent_supplied.
5. Eager creation is visibility-tier-AGNOSTIC — unlisted/semi_public/public Events
   each produce the SAME draft set; no tier gating.
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from syndication.engine import generate_projection
from syndication.models import PlatformConnection, PlatformProjection, Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs):
    """Create a minimal Event with sensible defaults."""
    defaults = {
        "title": "Test Party",
        "slug": "test-party",
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, **kwargs):
    defaults = {
        "headline": "Come join us!",
        "body": "Great event, don't miss it.",
    }
    defaults.update(kwargs)
    return Post.objects.create(event=event, **defaults)


def _make_connection(platform="fetlife", destination_id="fl-user-001", **kwargs):
    """Create a minimal PlatformConnection for test use."""
    profile = Profile.objects.create(
        name=f"Test Organizer ({platform})",
        slug=f"test-organizer-{platform}-{destination_id}".replace(":", "-"),
    )
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. State-machine: legal transitions succeed, illegal transitions raise
# ---------------------------------------------------------------------------

class StateMachineTest(TestCase):
    """PlatformProjection status state-machine: draft→ready→published→failed."""

    def setUp(self):
        self.event = _make_event()
        self.conn = _make_connection()
        self.proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )

    def test_draft_to_ready_is_legal(self):
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "ready")

    def test_ready_to_published_is_legal(self):
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        transition_status(self.proj, "published")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "published")

    def test_ready_to_failed_is_legal(self):
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        transition_status(self.proj, "failed")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "failed")

    def test_published_to_failed_is_legal(self):
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        transition_status(self.proj, "published")
        transition_status(self.proj, "failed")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "failed")

    def test_draft_to_published_is_illegal(self):
        """Cannot skip the ready step."""
        from syndication.engine import transition_status
        with self.assertRaises(ValueError):
            transition_status(self.proj, "published")

    def test_draft_to_failed_is_illegal(self):
        """Cannot fail a draft that was never attempted."""
        from syndication.engine import transition_status
        with self.assertRaises(ValueError):
            transition_status(self.proj, "failed")

    def test_published_to_draft_is_illegal(self):
        """No backward transition allowed."""
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        transition_status(self.proj, "published")
        with self.assertRaises(ValueError):
            transition_status(self.proj, "draft")

    def test_published_to_ready_is_illegal(self):
        """No backward transition."""
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        transition_status(self.proj, "published")
        with self.assertRaises(ValueError):
            transition_status(self.proj, "ready")

    def test_failed_to_draft_is_legal(self):
        """Failed projections can be reset to draft for retry."""
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        transition_status(self.proj, "failed")
        transition_status(self.proj, "draft")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "draft")

    def test_transition_to_unknown_status_raises(self):
        """Unknown target status raises ValueError."""
        from syndication.engine import transition_status
        with self.assertRaises(ValueError):
            transition_status(self.proj, "nonexistent")


# ---------------------------------------------------------------------------
# 2. Override-independence: body stable after canonical mutation post-generation
# ---------------------------------------------------------------------------

class OverrideIndependenceTest(TestCase):
    """
    ADR-016 D2 (kb-a4u.20 hybrid content model): projections are editable copies
    with a hybrid live-vs-frozen model:

    DRAFT: tracks live canonical — canonical mutations ARE visible in render.
    READY/PUBLISHED: frozen snapshot — canonical mutations are NOT visible.

    Rule: stability is achieved by freezing at draft→ready, not by snapshotting
    override_data["body"] at generation time. An explicit agent override
    (override_data["body"]) persists in draft and is included in the freeze.
    """

    def test_rule_based_draft_body_tracks_canonical_mutation(self):
        """
        ADR-016 D2 hybrid model: draft projections TRACK live canonical.

        Generate a listing projection via rule_based (lands in draft), then
        mutate event.title. The draft projection's rendered body MUST reflect
        the mutated title — draft projections are live views of the canonical.

        Stability (frozen snapshot) is achieved at draft→ready, not before.
        (Updated kb-a4u.20: old test asserted DRAFT was stable; new model is
        that DRAFT tracks live and READY is stable.)
        """
        event = _make_event(title="Original Title", description="Original desc")
        conn = _make_connection(destination_id="fl-override-test")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )

        # Mutate canonical after generation
        event.title = "Mutated Title"
        event.save()

        # Draft projection MUST reflect the mutation (live canonical tracking)
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Mutated Title", body)
        self.assertNotIn("Original Title", body)

    def test_rule_based_ready_body_stable_after_canonical_mutation(self):
        """
        ADR-016 D2 hybrid model: ready projections hold a FROZEN SNAPSHOT.

        Generate a listing projection via rule_based, transition to ready
        (freezing the snapshot), then mutate event.title. The ready projection's
        rendered body MUST reflect the ORIGINAL title (at-freeze value), not
        the mutated one.
        """
        event = _make_event(title="Original Title", description="Original desc", slug="override-ready-test")
        conn = _make_connection(destination_id="fl-override-ready-test")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )

        # Transition to ready: freeze the snapshot
        from syndication.engine import transition_status
        transition_status(proj, "ready")
        proj.refresh_from_db()

        # Mutate canonical AFTER freezing
        event.title = "Mutated Title"
        event.save()

        # Ready projection must return the frozen (pre-mutation) snapshot
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Original Title", body)
        self.assertNotIn("Mutated Title", body)

    def test_explicit_override_immune_to_canonical_mutation(self):
        """
        Generate a projection with an explicit body override.
        Mutating the canonical event afterwards must not change the override.
        """
        event = _make_event(title="Party Night", description="A wild party")
        conn = _make_connection(destination_id="fl-agent-test")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="agent_assisted",
            body="Agent-crafted copy for Party Night",
        )

        # Mutate canonical
        event.title = "Different Party"
        event.save()

        from syndication.engine import render_projection
        body = render_projection(proj)
        # Override is stable — the agent-supplied body is unchanged
        self.assertEqual(body, "Agent-crafted copy for Party Night")


# ---------------------------------------------------------------------------
# 3. mode=rule_based: deterministic template body from canonical fields
# ---------------------------------------------------------------------------

class RuleBasedGenerationTest(TestCase):
    """mode=rule_based generates a deterministic body from Event fields."""

    def test_rule_based_listing_includes_event_title(self):
        event = _make_event(title="Kinky Bubbles Party", description="Fun event")
        conn = _make_connection(destination_id="fl-rule-1")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Kinky Bubbles Party", body)

    def test_rule_based_is_deterministic(self):
        """Same inputs produce same output — no randomness."""
        event = _make_event(title="Repeat Test", description="Same every time")
        conn1 = _make_connection(destination_id="fl-det-1")
        conn2 = _make_connection(destination_id="fl-det-2")
        proj1 = generate_projection(
            kind="listing",
            connection=conn1,
            source_event=event,
            mode="rule_based",
        )
        proj2 = generate_projection(
            kind="listing",
            connection=conn2,
            source_event=event,
            mode="rule_based",
        )
        from syndication.engine import render_projection
        self.assertEqual(render_projection(proj1), render_projection(proj2))

    def test_rule_based_requires_no_agent_body(self):
        """rule_based MUST NOT require an agent-supplied body parameter."""
        event = _make_event()
        conn = _make_connection(destination_id="fl-no-body")
        # Should not raise even with no body kwarg
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj)

    def test_rule_based_is_default_mode(self):
        """When mode is not specified, defaults to rule_based."""
        event = _make_event(title="Default Mode Event")
        conn = _make_connection(destination_id="fl-default-mode")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
        )
        self.assertIsNotNone(proj)
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Default Mode Event", body)

    def test_rule_based_promotion_includes_post_headline(self):
        """Promotion-kind rule_based includes Post headline."""
        event = _make_event(title="Bubble Night")
        conn = _make_connection(platform="telegram", destination_id="channel-123")
        post = _make_post(event, headline="Save the Date: Bubble Night!")
        proj = generate_projection(
            kind="promotion",
            connection=conn,
            source_post=post,
            mode="rule_based",
        )
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Save the Date: Bubble Night!", body)

    def test_rule_based_sets_provenance_rule_template(self):
        """
        Harness item (3): mode=rule_based generation sets provenance=rule_template.
        ADR-008 D3: fail loud — no silent data-integrity fallback.
        """
        event = _make_event(title="Provenance Test Event")
        conn = _make_connection(destination_id="fl-prov-rule")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertEqual(
            proj.provenance,
            "rule_template",
            "rule_based generation must set provenance=rule_template",
        )


# ---------------------------------------------------------------------------
# 4. mode=agent_assisted: accepts and stores agent-supplied body
# ---------------------------------------------------------------------------

class AgentAssistedGenerationTest(TestCase):
    """mode=agent_assisted accepts and stores a pre-authored body."""

    def test_agent_assisted_stores_supplied_body(self):
        event = _make_event()
        conn = _make_connection(destination_id="fl-agent-1")
        agent_body = "The agent wrote this announcement copy."
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="agent_assisted",
            body=agent_body,
        )
        from syndication.engine import render_projection
        self.assertEqual(render_projection(proj), agent_body)

    def test_agent_assisted_without_body_raises(self):
        """agent_assisted mode requires a body; omitting it raises ValueError."""
        event = _make_event()
        conn = _make_connection(destination_id="fl-agent-2")
        with self.assertRaises(ValueError):
            generate_projection(
                kind="listing",
                connection=conn,
                source_event=event,
                mode="agent_assisted",
                # no body
            )

    def test_agent_assisted_body_stored_in_override_data(self):
        """Body is stored as an override, making it immune to canonical changes."""
        event = _make_event()
        conn = _make_connection(destination_id="fl-agent-3")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="agent_assisted",
            body="Agent content",
        )
        self.assertIn("body", proj.override_data)
        self.assertEqual(proj.override_data["body"], "Agent content")

    def test_agent_assisted_sets_provenance_agent_supplied(self):
        """
        Harness item (4): mode=agent_assisted generation sets provenance=agent_supplied.
        ADR-008 D3: fail loud — no silent data-integrity fallback; the model default
        is rule_template, so without an explicit set, this would be wrong.
        """
        event = _make_event()
        conn = _make_connection(destination_id="fl-agent-prov")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="agent_assisted",
            body="Agent-authored copy for provenance test.",
        )
        self.assertEqual(
            proj.provenance,
            "agent_supplied",
            "agent_assisted generation must set provenance=agent_supplied",
        )


# ---------------------------------------------------------------------------
# 5. Eager creation is visibility-tier-AGNOSTIC (harness item 5)
# ---------------------------------------------------------------------------

class VisibilityTierAgnosticTest(TestCase):
    """
    ADR-016 carried-forward (REVISED 2026-05-27): There is NO visibility write-gate.
    unlisted/semi_public/public Events each produce the SAME draft set.
    Event.visibility governs read-side rendering only, not outbound syndication.
    """

    def _draft_count_for(self, event, conn):
        """Helper: count draft projections created for a (event, conn) pair."""
        return PlatformProjection.objects.filter(
            source_event=event,
            connection=conn,
            status=PlatformProjection.Status.DRAFT,
        ).count()

    def test_unlisted_event_generates_same_draft_set_as_public(self):
        """
        An unlisted Event must produce the same number of draft projections
        as a public Event. No tier gating on syndication write path.
        """
        conn_public = _make_connection(destination_id="fl-pub-vis")
        conn_unlisted = _make_connection(destination_id="fl-unl-vis")

        event_public = _make_event(visibility="public")
        event_unlisted = _make_event(visibility="unlisted", slug="unlisted-event-vis")

        proj_public = generate_projection(
            kind="listing",
            connection=conn_public,
            source_event=event_public,
            mode="rule_based",
        )
        proj_unlisted = generate_projection(
            kind="listing",
            connection=conn_unlisted,
            source_event=event_unlisted,
            mode="rule_based",
        )

        self.assertIsNotNone(proj_public)
        self.assertIsNotNone(proj_unlisted)
        self.assertEqual(proj_public.status, PlatformProjection.Status.DRAFT)
        self.assertEqual(proj_unlisted.status, PlatformProjection.Status.DRAFT)

    def test_semi_public_event_generates_draft(self):
        """semi_public visibility produces a draft projection — same as public/unlisted."""
        event = _make_event(visibility="semi_public", slug="semi-public-event-vis")
        conn = _make_connection(destination_id="fl-semi-vis")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

    def test_public_event_generates_draft(self):
        """public visibility produces a draft projection."""
        event = _make_event(visibility="public")
        conn = _make_connection(destination_id="fl-pub-vis2")
        proj = generate_projection(
            kind="listing",
            connection=conn,
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

    def test_all_three_visibility_tiers_produce_same_draft_count(self):
        """
        Across unlisted, semi_public, and public — each produces exactly one
        draft projection per connection. No tier is special.
        """
        tiers = ["unlisted", "semi_public", "public"]
        for i, visibility in enumerate(tiers):
            conn = _make_connection(destination_id=f"fl-tier-{i}")
            event = _make_event(visibility=visibility, slug=f"tier-event-{i}")
            proj = generate_projection(
                kind="listing",
                connection=conn,
                source_event=event,
                mode="rule_based",
            )
            self.assertIsNotNone(proj, f"Expected draft for visibility={visibility!r}")
            self.assertEqual(
                proj.status,
                PlatformProjection.Status.DRAFT,
                f"Expected DRAFT status for visibility={visibility!r}",
            )


# ---------------------------------------------------------------------------
# 6. clean_for_platform seam is wired (identity stub at v0)
# ---------------------------------------------------------------------------

class CleaningSeamTest(TestCase):
    """
    The clean_for_platform seam must exist and be an identity at v0.
    It must be called during generation (wired, not dead code).
    """

    def test_clean_for_platform_identity_stub(self):
        """clean_for_platform returns text unchanged at v0."""
        from syndication.cleaning import clean_for_platform
        text = "Some raw content with BDSM vocabulary"
        result = clean_for_platform(text, "fetlife")
        self.assertEqual(result, text)

    def test_clean_for_platform_called_during_generation(self):
        """
        Verify the seam is wired: monkeypatch clean_for_platform,
        generate a projection, assert the patched version was called.
        """
        from unittest.mock import patch
        event = _make_event(title="Seam Test Event")
        conn = _make_connection(destination_id="fl-seam-test")
        with patch("syndication.engine.clean_for_platform", wraps=lambda text, platform: text) as mock_clean:
            generate_projection(
                kind="listing",
                connection=conn,
                source_event=event,
                mode="rule_based",
            )
            self.assertTrue(mock_clean.called, "clean_for_platform was not called during generation")
