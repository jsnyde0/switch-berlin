"""
TDD tests for the syndication schema (kb-a4u.1).

Tests assert:
- Post.event FK resolves to events.Event
- PlatformProjection kind and status enums are constrained to allowed values
- All reservation columns are present on the models
- Event extensions (dress_code, content_warnings, age_restriction, recurrence) exist

No behavioral logic is tested here — schema/migration layer only.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from syndication.models import PlatformConnection, PlatformProjection, Post


class PostModelTest(TestCase):
    """Post model: FK to Event, all fields present, no behaviour beyond Django ORM."""

    def setUp(self):
        self.event = Event.objects.create(
            title="Test Event",
            slug="test-event",
            start=timezone.now(),
        )

    def test_post_event_fk_resolves(self):
        """Post.event FK should resolve back to an Event instance."""
        post = Post.objects.create(
            event=self.event,
            headline="Save the date",
            body="Come join us.",
        )
        fetched = Post.objects.get(pk=post.pk)
        self.assertEqual(fetched.event, self.event)
        self.assertEqual(fetched.event.title, "Test Event")

    def test_post_has_headline_field(self):
        post = Post.objects.create(event=self.event, headline="Hook here", body="Body.")
        self.assertEqual(post.headline, "Hook here")

    def test_post_has_body_field(self):
        post = Post.objects.create(event=self.event, headline="H", body="The body text.")
        self.assertEqual(post.body, "The body text.")

    def test_post_imagery_field_is_optional(self):
        """imagery field exists and is nullable/blank-able."""
        post = Post.objects.create(event=self.event, headline="H", body="B")
        # imagery is a JSONField (list of image URLs / refs); null/blank is fine
        self.assertIsNone(post.imagery)

    def test_post_cta_field_is_optional(self):
        """CTA (call to action) field exists and is optional."""
        post = Post.objects.create(event=self.event, headline="H", body="B")
        self.assertEqual(post.cta, "")

    def test_post_voice_field_is_optional(self):
        """voice/tone field exists and is optional."""
        post = Post.objects.create(event=self.event, headline="H", body="B")
        self.assertEqual(post.voice, "")

    # --- campaign-sequence reservation columns (ADR-003 + ADR-016 Consequences) ---

    def test_post_has_sequence_order_reservation(self):
        """sequence_order: reservation for multi-Post campaign ordering (ADR-016 Consequences)."""
        post = Post.objects.create(event=self.event, headline="H", body="B")
        self.assertIsNone(post.sequence_order)

    def test_post_has_lifecycle_moment_reservation(self):
        """lifecycle_moment: save-the-date/early-bird/last-call reservation."""
        post = Post.objects.create(event=self.event, headline="H", body="B")
        self.assertEqual(post.lifecycle_moment, "")

    def test_post_has_scheduled_for_reservation(self):
        """scheduled_for: when this post should be published (campaign scheduling reservation)."""
        post = Post.objects.create(event=self.event, headline="H", body="B")
        self.assertIsNone(post.scheduled_for)

    def test_post_str(self):
        post = Post.objects.create(event=self.event, headline="Early bird", body="B")
        self.assertIn("Early bird", str(post))


class PlatformProjectionKindStatusTest(TestCase):
    """PlatformProjection: enum constraints for kind and status."""

    def setUp(self):
        self.profile = Profile.objects.create(
            name="Proj Status Test Organizer",
            slug="proj-status-test-organizer",
        )
        self.event = Event.objects.create(
            title="Projection Test Event",
            slug="proj-test-event",
            start=timezone.now(),
        )
        self.post = Post.objects.create(
            event=self.event,
            headline="Promo post",
            body="Come along.",
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user-tests",
        )
        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="channel-123",
        )
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
        )
        self.conn_tt = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="tickettailor",
            destination_id="tt-account",
        )

    def test_listing_projection_from_event(self):
        """kind=listing with source_event FK resolves correctly."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn_fetlife,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertEqual(fetched.kind, "listing")
        self.assertEqual(fetched.status, "draft")
        self.assertEqual(fetched.source_event, self.event)
        self.assertIsNone(fetched.source_post)

    def test_promotion_projection_from_post(self):
        """kind=promotion with source_post FK resolves correctly."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            connection=self.conn_telegram,
        )
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertEqual(fetched.kind, "promotion")
        self.assertEqual(fetched.source_post, self.post)
        self.assertIsNone(fetched.source_event)

    def test_kind_choices_are_constrained(self):
        """Kind enum exposes only listing and promotion choices."""
        allowed_kinds = {c[0] for c in PlatformProjection.Kind.choices}
        self.assertEqual(allowed_kinds, {"listing", "promotion"})

    def test_status_choices_are_constrained(self):
        """Status enum exposes draft, ready, published, failed."""
        allowed_statuses = {c[0] for c in PlatformProjection.Status.choices}
        self.assertEqual(allowed_statuses, {"draft", "ready", "published", "failed"})

    def test_projection_has_override_data(self):
        """override_data is a JSONField for per-field overrides (ADR-016 D2)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn_switch,
        )
        self.assertEqual(proj.override_data, {})

    def test_projection_has_external_id(self):
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.PUBLISHED,
            source_event=self.event,
            connection=self.conn_fetlife,
            external_id="fl-12345",
        )
        self.assertEqual(proj.external_id, "fl-12345")

    def test_projection_has_external_url(self):
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.PUBLISHED,
            source_event=self.event,
            connection=self.conn_fetlife,
            external_url="https://fetlife.com/events/12345",
        )
        self.assertEqual(proj.external_url, "https://fetlife.com/events/12345")

    def test_projection_has_syndicated_at(self):
        """syndicated_at is nullable; populated after successful publish."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn_tt,
        )
        self.assertIsNone(proj.syndicated_at)

    def test_projection_str(self):
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn_fetlife,
        )
        self.assertIn("fetlife", str(proj))

    def test_projection_has_created_at(self):
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn_fetlife,
        )
        self.assertIsNotNone(proj.created_at)

    def test_projection_has_updated_at(self):
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            connection=self.conn_fetlife,
        )
        self.assertIsNotNone(proj.updated_at)


class EventExtensionFieldsTest(TestCase):
    """Event model extensions: dress_code, content_warnings, age_restriction, recurrence."""

    def test_event_has_dress_code_field(self):
        """dress_code: free-text dress code for the event."""
        event = Event.objects.create(
            title="Dress Code Event",
            slug="dress-code-event",
            start=timezone.now(),
            dress_code="Fetish attire required",
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertEqual(fetched.dress_code, "Fetish attire required")

    def test_event_dress_code_is_optional(self):
        event = Event.objects.create(
            title="No Dress Code",
            slug="no-dress-code",
            start=timezone.now(),
        )
        self.assertEqual(event.dress_code, "")

    def test_event_has_content_warnings_field(self):
        """content_warnings: JSONField list of content warning strings."""
        event = Event.objects.create(
            title="CW Event",
            slug="cw-event",
            start=timezone.now(),
            content_warnings=["nudity", "bdsm"],
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertEqual(fetched.content_warnings, ["nudity", "bdsm"])

    def test_event_content_warnings_defaults_to_empty_list(self):
        event = Event.objects.create(
            title="No CW",
            slug="no-cw",
            start=timezone.now(),
        )
        self.assertEqual(event.content_warnings, [])

    def test_event_has_age_restriction_field(self):
        """age_restriction: minimum age integer, nullable."""
        event = Event.objects.create(
            title="18+ Event",
            slug="18plus-event",
            start=timezone.now(),
            age_restriction=18,
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertEqual(fetched.age_restriction, 18)

    def test_event_age_restriction_is_optional(self):
        event = Event.objects.create(
            title="Open Event",
            slug="open-event",
            start=timezone.now(),
        )
        self.assertIsNone(event.age_restriction)

    # --- recurrence reservation (ADR-016 Consequences, ADR-003 cheap foresight) ---

    def test_event_has_recurrence_rule_reservation(self):
        """recurrence_rule: iCal RRULE string, null = one-time event."""
        event = Event.objects.create(
            title="Weekly Event",
            slug="weekly-event",
            start=timezone.now(),
        )
        self.assertIsNone(event.recurrence_rule)

    def test_event_has_recurrence_parent_reservation(self):
        """recurrence_parent: FK to the original recurring event, null for originals."""
        event = Event.objects.create(
            title="Parent Event",
            slug="parent-event",
            start=timezone.now(),
        )
        self.assertIsNone(event.recurrence_parent)

    # --- ticket type taxonomy reservation (ADR-016 Consequences, ADR-003) ---

    def test_event_has_ticket_types_reservation(self):
        """ticket_types: JSONField reservation for the full ticket type taxonomy."""
        event = Event.objects.create(
            title="Ticket Event",
            slug="ticket-event",
            start=timezone.now(),
        )
        self.assertEqual(event.ticket_types, [])

    # --- buyer / attendee screening questions reservation (ADR-016 Consequences) ---

    def test_event_has_buyer_questions_reservation(self):
        """buyer_questions: JSONField reservation for buyer screening questions."""
        event = Event.objects.create(
            title="Q Event",
            slug="q-event",
            start=timezone.now(),
        )
        self.assertEqual(event.buyer_questions, [])

    def test_event_has_attendee_questions_reservation(self):
        """attendee_questions: JSONField reservation for attendee screening questions."""
        event = Event.objects.create(
            title="AQ Event",
            slug="aq-event",
            start=timezone.now(),
        )
        self.assertEqual(event.attendee_questions, [])
