"""
TDD tests for the syndication engine (kb-a4u.4).

Five harness checks per acceptance contract:
1. State-machine: legal transitions succeed, illegal ones raise.
2. Override-independence: projection body stable after canonical mutation post-generation.
3. mode=rule_based produces deterministic template body from canonical fields.
4. mode=agent_assisted accepts and stores an agent-supplied body.
5. unlisted Event → generation produces NO external projection.
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event
from syndication.engine import generate_projection
from syndication.models import PlatformProjection, Post


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


# ---------------------------------------------------------------------------
# 1. State-machine: legal transitions succeed, illegal transitions raise
# ---------------------------------------------------------------------------

class StateMachineTest(TestCase):
    """PlatformProjection status state-machine: draft→ready→published→failed."""

    def setUp(self):
        self.event = _make_event()
        self.proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            platform_id="fetlife",
        )

    def test_draft_to_ready_is_legal(self):
        from syndication.engine import transition_status
        transition_status(self.proj, "ready")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "ready")

    def test_ready_to_published_is_legal(self):
        from syndication.engine import transition_status
        self.proj.status = "ready"
        self.proj.save()
        transition_status(self.proj, "published")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "published")

    def test_ready_to_failed_is_legal(self):
        from syndication.engine import transition_status
        self.proj.status = "ready"
        self.proj.save()
        transition_status(self.proj, "failed")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "failed")

    def test_published_to_failed_is_legal(self):
        from syndication.engine import transition_status
        self.proj.status = "published"
        self.proj.save()
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
        self.proj.status = "published"
        self.proj.save()
        with self.assertRaises(ValueError):
            transition_status(self.proj, "draft")

    def test_published_to_ready_is_illegal(self):
        """No backward transition."""
        from syndication.engine import transition_status
        self.proj.status = "published"
        self.proj.save()
        with self.assertRaises(ValueError):
            transition_status(self.proj, "ready")

    def test_failed_to_draft_is_legal(self):
        """Failed projections can be reset to draft for retry."""
        from syndication.engine import transition_status
        self.proj.status = "failed"
        self.proj.save()
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
    ADR-016 D2: projections are editable copies, not live views.

    Rule: rule_based generation SNAPSHOTS body at generation time.
    An explicit override must be immune to later canonical mutation.
    """

    def test_rule_based_body_stable_after_canonical_mutation(self):
        """
        Generate a listing projection via rule_based, then mutate event.title.
        The projection's rendered body MUST reflect the ORIGINAL title,
        not the mutated one — because rule_based snapshots body at generation time.
        """
        event = _make_event(title="Original Title", description="Original desc")
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )

        # Mutate canonical after generation
        event.title = "Mutated Title"
        event.save()

        # Projection body was snapshotted at generation time; must not reflect mutation
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
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
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
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Kinky Bubbles Party", body)

    def test_rule_based_is_deterministic(self):
        """Same inputs produce same output — no randomness."""
        event = _make_event(title="Repeat Test", description="Same every time")
        proj1 = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )
        proj2 = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )
        from syndication.engine import render_projection
        self.assertEqual(render_projection(proj1), render_projection(proj2))

    def test_rule_based_requires_no_agent_body(self):
        """rule_based MUST NOT require an agent-supplied body parameter."""
        event = _make_event()
        # Should not raise even with no body kwarg
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj)

    def test_rule_based_is_default_mode(self):
        """When mode is not specified, defaults to rule_based."""
        event = _make_event(title="Default Mode Event")
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
        )
        self.assertIsNotNone(proj)
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Default Mode Event", body)

    def test_rule_based_promotion_includes_post_headline(self):
        """Promotion-kind rule_based includes Post headline."""
        event = _make_event(title="Bubble Night")
        post = _make_post(event, headline="Save the Date: Bubble Night!")
        proj = generate_projection(
            kind="promotion",
            platform_id="telegram-channel:123",
            source_post=post,
            mode="rule_based",
        )
        from syndication.engine import render_projection
        body = render_projection(proj)
        self.assertIn("Save the Date: Bubble Night!", body)


# ---------------------------------------------------------------------------
# 4. mode=agent_assisted: accepts and stores agent-supplied body
# ---------------------------------------------------------------------------

class AgentAssistedGenerationTest(TestCase):
    """mode=agent_assisted accepts and stores a pre-authored body."""

    def test_agent_assisted_stores_supplied_body(self):
        event = _make_event()
        agent_body = "The agent wrote this announcement copy."
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="agent_assisted",
            body=agent_body,
        )
        from syndication.engine import render_projection
        self.assertEqual(render_projection(proj), agent_body)

    def test_agent_assisted_without_body_raises(self):
        """agent_assisted mode requires a body; omitting it raises ValueError."""
        event = _make_event()
        with self.assertRaises(ValueError):
            generate_projection(
                kind="listing",
                platform_id="fetlife",
                source_event=event,
                mode="agent_assisted",
                # no body
            )

    def test_agent_assisted_body_stored_in_override_data(self):
        """Body is stored as an override, making it immune to canonical changes."""
        event = _make_event()
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="agent_assisted",
            body="Agent content",
        )
        self.assertIn("body", proj.override_data)
        self.assertEqual(proj.override_data["body"], "Agent content")


# ---------------------------------------------------------------------------
# 5. unlisted Event → generation produces NO external projection
# ---------------------------------------------------------------------------

class UnlistedVisibilityGateTest(TestCase):
    """
    ADR-012 + ADR-016 Consequences:
    unlisted Events generate no external projections (write-side gate).
    """

    def test_unlisted_event_raises_on_generate(self):
        """
        generate_projection for an unlisted event MUST raise, not silently
        return None or create a projection record.
        """
        event = _make_event(visibility="unlisted")
        with self.assertRaises(ValueError):
            generate_projection(
                kind="listing",
                platform_id="fetlife",
                source_event=event,
                mode="rule_based",
            )

    def test_unlisted_event_leaves_no_projection_record(self):
        """Even after a failed generate call, no PlatformProjection should exist."""
        event = _make_event(visibility="unlisted")
        initial_count = PlatformProjection.objects.filter(source_event=event).count()
        try:
            generate_projection(
                kind="listing",
                platform_id="fetlife",
                source_event=event,
                mode="rule_based",
            )
        except ValueError:
            pass
        final_count = PlatformProjection.objects.filter(source_event=event).count()
        self.assertEqual(initial_count, final_count)

    def test_public_event_can_generate(self):
        """public visibility allows projection generation."""
        event = _make_event(visibility="public")
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj)

    def test_semi_public_event_can_generate(self):
        """semi_public visibility allows projection generation (only unlisted is blocked)."""
        event = _make_event(visibility="semi_public")
        proj = generate_projection(
            kind="listing",
            platform_id="fetlife",
            source_event=event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj)

    def test_promotion_unlisted_source_event_raises(self):
        """
        Promotion projections whose source Post's event is unlisted also blocked.
        The write-gate consults the related Event even for promotion-kind.
        """
        event = _make_event(visibility="unlisted")
        post = _make_post(event)
        with self.assertRaises(ValueError):
            generate_projection(
                kind="promotion",
                platform_id="telegram-channel:123",
                source_post=post,
                mode="rule_based",
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
        with patch("syndication.engine.clean_for_platform", wraps=lambda text, pid: text) as mock_clean:
            generate_projection(
                kind="listing",
                platform_id="fetlife",
                source_event=event,
                mode="rule_based",
            )
            self.assertTrue(mock_clean.called, "clean_for_platform was not called during generation")
