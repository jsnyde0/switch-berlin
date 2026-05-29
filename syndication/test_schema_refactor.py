"""
TDD tests for the syndication schema refactor (kb-a4u.18, updated kb-wz8m.2).

Tests assert:
- PlatformConnection model exists with the required fields
- PlatformProjection.connection FK resolves to a PlatformConnection (not a string)
- platform_id field is removed from PlatformProjection
- override_data, provenance, generated_by, last_generated_at are removed from
  PlatformProjection (kb-wz8m.2 cutover — these now live on ContentVersion)
- ContentVersion carries provenance, generated_by, last_generated_at

Schema/migration layer only — no behavioral logic.
ADR-016 D2 (provenance + attribution on ContentVersion) and D4 (PlatformConnection FK).
ADR-008 D1: no back-compat shims — obsolete fields removed, no deprecation paths.
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
        from syndication.models import ContentVersion
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
        self.canonical_cv, _ = ContentVersion.objects.get_or_create(
            event=self.event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )

    def test_projection_connection_fk_resolves_to_platform_connection(self):
        """PlatformProjection.connection resolves to a PlatformConnection instance, not a string."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            content_version=self.canonical_cv,
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
            content_version=self.canonical_cv,
        )
        self.assertFalse(hasattr(proj, "platform_id"))


class PlatformProjectionRemovedFieldsTest(TestCase):
    """
    kb-wz8m.2 cutover: override_data, provenance, generated_by, last_generated_at
    are removed from PlatformProjection. These fields now live on ContentVersion.
    ADR-008 D1: no back-compat shims — removed outright, no deprecation paths.
    """

    def setUp(self):
        from syndication.models import ContentVersion
        self.profile = Profile.objects.create(
            name="Removed Fields Organizer",
            slug="removed-fields-organizer",
        )
        self.conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="channel-removed",
            enabled=True,
        )
        self.event = Event.objects.create(
            title="Removed Fields Test Event",
            slug="removed-fields-test-event",
            start=timezone.now(),
        )
        self.canonical_cv, _ = ContentVersion.objects.get_or_create(
            event=self.event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )

    def test_projection_has_no_override_data_field(self):
        """override_data is removed from PlatformProjection (kb-wz8m.2)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            content_version=self.canonical_cv,
        )
        self.assertFalse(
            hasattr(proj, "override_data"),
            "PlatformProjection must NOT have override_data after kb-wz8m.2 cutover",
        )

    def test_projection_has_no_provenance_field(self):
        """provenance is removed from PlatformProjection (lives on ContentVersion now)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            content_version=self.canonical_cv,
        )
        self.assertFalse(
            hasattr(proj, "provenance"),
            "PlatformProjection must NOT have provenance after kb-wz8m.2 cutover",
        )

    def test_projection_has_no_generated_by_field(self):
        """generated_by is removed from PlatformProjection (lives on ContentVersion now)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            content_version=self.canonical_cv,
        )
        self.assertFalse(
            hasattr(proj, "generated_by"),
            "PlatformProjection must NOT have generated_by after kb-wz8m.2 cutover",
        )

    def test_projection_has_no_last_generated_at_field(self):
        """last_generated_at is removed from PlatformProjection (lives on ContentVersion now)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn,
            content_version=self.canonical_cv,
        )
        self.assertFalse(
            hasattr(proj, "last_generated_at"),
            "PlatformProjection must NOT have last_generated_at after kb-wz8m.2 cutover",
        )


class ContentVersionCarriesProvenanceFieldsTest(TestCase):
    """
    ContentVersion carries the provenance + attribution fields that were
    removed from PlatformProjection (ADR-016 D2 revised 2026-05-29).
    """

    def setUp(self):
        self.profile = Profile.objects.create(
            name="CV Provenance Organizer",
            slug="cv-provenance-organizer",
        )
        self.event = Event.objects.create(
            title="CV Provenance Test Event",
            slug="cv-provenance-test-event",
            start=timezone.now(),
        )

    def test_content_version_provenance_defaults_to_rule_template(self):
        """ContentVersion.provenance defaults to rule_template."""
        from syndication.models import ContentVersion
        cv = ContentVersion.objects.create(event=self.event, name="v1")
        self.assertEqual(cv.provenance, "rule_template")

    def test_content_version_provenance_choices_are_constrained(self):
        """ContentVersion provenance enum exposes rule_template, agent_supplied, manual."""
        from syndication.models import ContentVersion
        allowed = {c[0] for c in ContentVersion.Provenance.choices}
        self.assertEqual(allowed, {"rule_template", "agent_supplied", "manual"})

    def test_content_version_generated_by_is_nullable(self):
        """ContentVersion.generated_by is nullable."""
        from syndication.models import ContentVersion
        cv = ContentVersion.objects.create(event=self.event, name="v1")
        self.assertIsNone(cv.generated_by)

    def test_content_version_generated_by_can_be_set(self):
        """ContentVersion.generated_by can store an agent identity string."""
        from syndication.models import ContentVersion
        cv = ContentVersion.objects.create(
            event=self.event, name="v1", generated_by="claude-agent-v1"
        )
        self.assertEqual(cv.generated_by, "claude-agent-v1")

    def test_content_version_last_generated_at_is_nullable(self):
        """ContentVersion.last_generated_at is nullable."""
        from syndication.models import ContentVersion
        cv = ContentVersion.objects.create(event=self.event, name="v1")
        self.assertIsNone(cv.last_generated_at)

    def test_content_version_last_generated_at_can_be_set(self):
        """ContentVersion.last_generated_at can be set to a datetime."""
        from syndication.models import ContentVersion
        now = timezone.now()
        cv = ContentVersion.objects.create(event=self.event, name="v1", last_generated_at=now)
        self.assertIsNotNone(cv.last_generated_at)
