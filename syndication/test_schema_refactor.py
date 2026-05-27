"""
TDD tests for the syndication schema refactor (kb-a4u.18).

Tests assert:
- PlatformConnection model exists with the required fields
- PlatformProjection.connection FK resolves to a PlatformConnection (not a string)
- platform_id field is removed from PlatformProjection
- PlatformProjection carries provenance enum (rule_template/agent_supplied/manual)
- PlatformProjection carries generated_by (nullable) and last_generated_at (nullable)
- override_data is retained unchanged

Schema/migration layer only — no behavioral logic.
ADR-016 D2 (provenance + attribution fields) and D4 (PlatformConnection FK).
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from syndication.models import PlatformConnection, PlatformProjection


class PlatformConnectionModelTest(TestCase):
    """PlatformConnection model: organizer FK, platform, destination id, credentials, enabled, kinds."""

    def setUp(self):
        self.profile = Profile.objects.create(
            name="Test Organizer",
            slug="test-organizer",
        )

    def test_platform_connection_creation(self):
        """PlatformConnection can be created with required fields."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fetlife-user-123",
            enabled=True,
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.organizer, self.profile)
        self.assertEqual(fetched.platform, "fetlife")
        self.assertEqual(fetched.destination_id, "fetlife-user-123")
        self.assertTrue(fetched.enabled)

    def test_platform_connection_organizer_fk_resolves_to_profile(self):
        """organizer FK resolves to an organizers.Profile instance."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="channel-456",
        )
        self.assertIsInstance(conn.organizer, Profile)
        self.assertEqual(conn.organizer.slug, "test-organizer")

    def test_platform_connection_enabled_defaults_to_true(self):
        """enabled flag defaults to True."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="switch-own-page",
        )
        self.assertTrue(conn.enabled)

    def test_platform_connection_has_credentials_field(self):
        """credentials JSONField stores per-destination credentials."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="tickettailor",
            destination_id="tt-account-789",
            credentials={"api_key": "secret"},
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.credentials, {"api_key": "secret"})

    def test_platform_connection_credentials_defaults_to_empty_dict(self):
        """credentials field defaults to empty dict."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user",
        )
        self.assertEqual(conn.credentials, {})

    def test_platform_connection_has_kinds_field(self):
        """kinds JSONField stores supported projection kinds (listing/promotion/both)."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user",
            kinds=["listing", "promotion"],
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.kinds, ["listing", "promotion"])

    def test_platform_connection_multiple_per_organizer_allowed(self):
        """An organizer may hold multiple connections per platform."""
        PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="channel-a",
        )
        PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="channel-b",
        )
        connections = PlatformConnection.objects.filter(
            organizer=self.profile, platform="telegram"
        )
        self.assertEqual(connections.count(), 2)


class PlatformProjectionConnectionFKTest(TestCase):
    """PlatformProjection.connection FK to PlatformConnection — not a platform_id string."""

    def setUp(self):
        self.profile = Profile.objects.create(
            name="FK Test Organizer",
            slug="fk-test-organizer",
        )
        self.conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user-001",
            enabled=True,
        )
        self.event = Event.objects.create(
            title="FK Test Event",
            slug="fk-test-event",
            start=timezone.now(),
        )

    def test_projection_connection_fk_resolves_to_platform_connection(self):
        """PlatformProjection.connection resolves to a PlatformConnection instance, not a string."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertIsInstance(fetched.connection, PlatformConnection)
        self.assertEqual(fetched.connection, self.conn)
        self.assertEqual(fetched.connection.platform, "fetlife")

    def test_projection_has_no_platform_id_field(self):
        """platform_id string field has been removed — PlatformProjection has no platform_id attribute."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )
        self.assertFalse(hasattr(proj, "platform_id"))


class PlatformProjectionProvenanceFieldsTest(TestCase):
    """PlatformProjection provenance enum and attribution reservation fields."""

    def setUp(self):
        self.profile = Profile.objects.create(
            name="Provenance Organizer",
            slug="provenance-organizer",
        )
        self.conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="channel-prov",
            enabled=True,
        )
        self.event = Event.objects.create(
            title="Provenance Test Event",
            slug="provenance-test-event",
            start=timezone.now(),
        )

    def test_projection_provenance_defaults_to_rule_template(self):
        """provenance defaults to 'rule_template' for a freshly created projection."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertEqual(fetched.provenance, "rule_template")

    def test_projection_provenance_choices_are_constrained(self):
        """provenance enum exposes only rule_template, agent_supplied, and manual."""
        allowed = {c[0] for c in PlatformProjection.Provenance.choices}
        self.assertEqual(allowed, {"rule_template", "agent_supplied", "manual"})

    def test_projection_provenance_can_be_set_to_agent_supplied(self):
        """provenance can be set to agent_supplied."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            provenance=PlatformProjection.Provenance.AGENT_SUPPLIED,
        )
        self.assertEqual(proj.provenance, "agent_supplied")

    def test_projection_provenance_can_be_set_to_manual(self):
        """provenance can be set to manual (flipped on human edit)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            provenance=PlatformProjection.Provenance.MANUAL,
        )
        self.assertEqual(proj.provenance, "manual")

    def test_projection_generated_by_is_nullable(self):
        """generated_by is nullable; null for human-driven flows."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertIsNone(fetched.generated_by)

    def test_projection_generated_by_can_be_set(self):
        """generated_by can store an agent identity string."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            generated_by="claude-agent-v1",
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertEqual(fetched.generated_by, "claude-agent-v1")

    def test_projection_last_generated_at_is_nullable(self):
        """last_generated_at is nullable; null for human-driven flows."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertIsNone(fetched.last_generated_at)

    def test_projection_last_generated_at_can_be_set(self):
        """last_generated_at can be set to a datetime."""
        now = timezone.now()
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            last_generated_at=now,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertIsNotNone(fetched.last_generated_at)


class PlatformProjectionRetainsOverrideDataTest(TestCase):
    """override_data JSONField is retained unchanged after the schema refactor."""

    def setUp(self):
        self.profile = Profile.objects.create(
            name="Override Organizer",
            slug="override-organizer",
        )
        self.conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="switch-own-page",
        )
        self.event = Event.objects.create(
            title="Override Test Event",
            slug="override-test-event",
            start=timezone.now(),
        )

    def test_projection_override_data_defaults_to_empty_dict(self):
        """override_data defaults to {} and is retained after the FK refront."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
        )
        self.assertEqual(proj.override_data, {})

    def test_projection_override_data_stores_overrides(self):
        """override_data stores per-field override dict."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            override_data={"title": "Custom Title for Platform"},
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertEqual(fetched.override_data, {"title": "Custom Title for Platform"})
