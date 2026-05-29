"""
TDD tests for ContentVersion model (bead kb-wz8m.1).

Additive-only step: introduces ContentVersion and a nullable content_version FK
on PlatformProjection. No behavior change — override_data still exists and no
code reads content_version yet.

Acceptance: ContentVersion model exists with correct fields; nullable
content_version FK exists on PlatformProjection; migrations are clean (checked
separately via makemigrations --check --dry-run).

canonical_refs: ADR-016 D2 (content-version evolution, revised 2026-05-29),
ADR-008 D1 (no back-compat shims), ADR-003 (cheap foresight on data shape).
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from syndication.models import (
    ContentVersion,
    PlatformConnection,
    PlatformProjection,
)


def _make_event(**kwargs):
    """Create a minimal Event for test setup."""
    from django.utils import timezone as tz

    defaults = {
        "title": "Test Event",
        "slug": "test-event",
        "start": tz.now(),
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_profile(**kwargs):
    """Create a minimal Profile for test setup."""
    import uuid

    defaults = {
        "name": f"Test Organizer {uuid.uuid4().hex[:6]}",
        "slug": f"test-org-{uuid.uuid4().hex[:6]}",
    }
    defaults.update(kwargs)
    return Profile.objects.create(**defaults)


def _make_connection(profile, **kwargs):
    """Create a minimal PlatformConnection for test setup."""
    defaults = {
        "organizer": profile,
        "platform": "switch",
        "destination_id": "own-page",
        "kinds": ["listing"],
    }
    defaults.update(kwargs)
    return PlatformConnection.objects.create(**defaults)


class ContentVersionModelExistsTest(TestCase):
    """ContentVersion model must exist with the correct field set (ADR-016 D2)."""

    def test_content_version_model_importable(self):
        """ContentVersion must be importable from syndication.models."""
        # noqa: F401 — importability check only
        from syndication.models import ContentVersion  # noqa: F401

    def test_content_version_can_be_created_for_event(self):
        """ContentVersion is per-Event: it must accept an event FK."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertEqual(cv.event, event)
        self.assertEqual(cv.name, "v1")

    def test_content_version_has_name_field(self):
        """ContentVersion must carry a name field (named editorial copy variant)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="canonical")
        self.assertEqual(cv.name, "canonical")

    def test_content_version_has_headline_field(self):
        """ContentVersion carries headline (nullable/blank)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", headline="Join us!")
        self.assertEqual(cv.headline, "Join us!")

    def test_content_version_headline_optional(self):
        """
        ContentVersion.headline must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical' (null-means-derive semantics).
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.headline)

    def test_content_version_has_body_field(self):
        """ContentVersion carries body text field."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", body="Come party.")
        self.assertEqual(cv.body, "Come party.")

    def test_content_version_body_optional(self):
        """
        ContentVersion.body must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical' (null-means-derive semantics).
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.body)

    def test_content_version_has_imagery_field(self):
        """ContentVersion carries imagery (JSON, nullable)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", imagery=["img1.jpg"])
        self.assertEqual(cv.imagery, ["img1.jpg"])

    def test_content_version_imagery_optional(self):
        """ContentVersion.imagery must be optional (null default)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.imagery)

    def test_content_version_has_cta_field(self):
        """ContentVersion carries cta (call to action)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", cta="https://example.com")
        self.assertEqual(cv.cta, "https://example.com")

    def test_content_version_cta_optional(self):
        """
        ContentVersion.cta must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical'.
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.cta)

    def test_content_version_has_voice_field(self):
        """ContentVersion carries voice/tone field."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", voice="playful")
        self.assertEqual(cv.voice, "playful")

    def test_content_version_voice_optional(self):
        """
        ContentVersion.voice must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical'.
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.voice)


class ContentVersionProvenanceFieldsTest(TestCase):
    """ContentVersion carries content-authorship signals (ADR-016 D2)."""

    def test_content_version_has_provenance_field(self):
        """ContentVersion must carry provenance ∈ {rule_template, agent_supplied, manual}."""  # noqa: E501
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.assertEqual(cv.provenance, "rule_template")

    def test_content_version_provenance_defaults_to_rule_template(self):
        """ContentVersion.provenance default is rule_template."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertEqual(cv.provenance, ContentVersion.Provenance.RULE_TEMPLATE)

    def test_content_version_provenance_agent_supplied(self):
        """ContentVersion.provenance accepts agent_supplied."""
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            provenance=ContentVersion.Provenance.AGENT_SUPPLIED,
        )
        self.assertEqual(cv.provenance, "agent_supplied")

    def test_content_version_provenance_manual(self):
        """ContentVersion.provenance accepts manual."""
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        self.assertEqual(cv.provenance, "manual")

    def test_content_version_has_generated_by_field(self):
        """ContentVersion carries generated_by (nullable agent identity)."""
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            generated_by="claude-code-agent",
        )
        self.assertEqual(cv.generated_by, "claude-code-agent")

    def test_content_version_generated_by_nullable(self):
        """ContentVersion.generated_by must be nullable (null default)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.generated_by)

    def test_content_version_has_last_generated_at_field(self):
        """ContentVersion carries last_generated_at (nullable datetime)."""
        now = timezone.now()
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            last_generated_at=now,
        )
        self.assertEqual(cv.last_generated_at, now)

    def test_content_version_last_generated_at_nullable(self):
        """ContentVersion.last_generated_at must be nullable (null default)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.last_generated_at)


class ContentVersionUniquenessTest(TestCase):
    """
    ContentVersion (event, name) pair must be unique within an event.

    Same name on DIFFERENT events is allowed (uniqueness is scoped per-event).
    Duplicate (event, name) must raise IntegrityError (ADR-016 D2 revised
    2026-05-29; kb-wz8m.2 seeds exactly one 'canonical' version per event and
    must not create duplicates).
    """

    def test_duplicate_name_on_same_event_raises_integrity_error(self):
        """Two ContentVersions with the same name on the same event must fail."""
        from django.db import IntegrityError

        event = _make_event(slug="unique-test-event")
        ContentVersion.objects.create(event=event, name="canonical")
        with self.assertRaises(IntegrityError):
            ContentVersion.objects.create(event=event, name="canonical")

    def test_same_name_on_different_events_is_allowed(self):
        """The uniqueness constraint is scoped per-event; cross-event reuse is fine."""
        event_a = _make_event(slug="event-a-uniq")
        event_b = _make_event(slug="event-b-uniq")
        cv_a = ContentVersion.objects.create(event=event_a, name="canonical")
        cv_b = ContentVersion.objects.create(event=event_b, name="canonical")
        self.assertEqual(cv_a.name, cv_b.name)
        self.assertNotEqual(cv_a.event_id, cv_b.event_id)


class ContentVersionStrTest(TestCase):
    """ContentVersion.__str__ should be human-readable."""

    def test_content_version_str_includes_name(self):
        """__str__ of ContentVersion includes the name field."""
        event = _make_event(title="My Event")
        cv = ContentVersion.objects.create(event=event, name="campaign-v1")
        self.assertIn("campaign-v1", str(cv))


class PlatformProjectionContentVersionFKTest(TestCase):
    """PlatformProjection must have a nullable content_version FK (ADR-016 D2)."""

    def test_platform_projection_has_content_version_field(self):
        """PlatformProjection.content_version attribute must exist."""
        pp = PlatformProjection()
        self.assertTrue(
            hasattr(pp, "content_version"),
            "PlatformProjection must have a content_version attribute",
        )

    def test_platform_projection_content_version_nullable(self):
        """content_version FK must be nullable — the additive step leaves it unset."""
        event = _make_event()
        profile = _make_profile()
        conn = _make_connection(profile)
        pp = PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
        )
        self.assertIsNone(pp.content_version)

    def test_platform_projection_content_version_can_be_set(self):
        """content_version FK can be set to a ContentVersion instance."""
        event = _make_event()
        profile = _make_profile()
        conn = _make_connection(profile)
        cv = ContentVersion.objects.create(event=event, name="v1")
        pp = PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        self.assertEqual(pp.content_version, cv)

    def test_platform_projection_override_data_removed(self):
        """
        kb-wz8m.2 cutover: override_data must NOT be present on PlatformProjection.
        Content fields now live on ContentVersion (ADR-016 D2, ADR-008 D1).
        """
        event = _make_event()
        profile = _make_profile()
        conn = _make_connection(profile)
        pp = PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
        )
        self.assertFalse(
            hasattr(pp, "override_data"),
            "PlatformProjection must NOT have override_data after kb-wz8m.2 cutover",
        )

    def test_multiple_projections_can_share_one_content_version(self):
        """
        Multiple projections may point at one ContentVersion
        (single-row sharing — ADR-016 D2 content-version evolution).
        """
        event = _make_event()
        profile = _make_profile()
        conn1 = _make_connection(profile, destination_id="own-page", kinds=["listing"])
        conn2 = _make_connection(
            profile, platform="fetlife", destination_id="user123", kinds=["listing"]
        )
        cv = ContentVersion.objects.create(event=event, name="shared")
        pp1 = PlatformProjection.objects.create(
            connection=conn1,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        pp2 = PlatformProjection.objects.create(
            connection=conn2,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        self.assertEqual(pp1.content_version, cv)
        self.assertEqual(pp2.content_version, cv)
        self.assertEqual(pp1.content_version_id, pp2.content_version_id)
