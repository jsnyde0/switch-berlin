"""
TDD tests for EventFacilitator M2M migration (kb-qhl).

Acceptance criteria covered:
  1. EventFacilitator model importable and has correct fields
  2. Event.facilitators M2M shape via EventFacilitator through-table
  3. EventFacilitator.event FK is CASCADE, profile FK is PROTECT
  4. unique_together = (('event', 'profile'),) enforced
  5. Same Profile can be both EventOrganizer AND EventFacilitator for the same Event
  6. blank role='' is allowed (no validation error)
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone


class EventFacilitatorModelFieldsTest(TestCase):
    """Clause 1: EventFacilitator model has expected fields."""

    def test_eventfacilitator_model_importable(self):
        from events.models import EventFacilitator  # noqa: F401

    def test_field_event_is_fk(self):
        from django.db.models import ForeignKey

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("event")
        self.assertIsInstance(f, ForeignKey)

    def test_field_profile_is_fk(self):
        from django.db.models import ForeignKey

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("profile")
        self.assertIsInstance(f, ForeignKey)

    def test_field_role_is_charfield_max100_blank(self):
        from django.db.models import CharField

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("role")
        self.assertIsInstance(f, CharField)
        self.assertEqual(f.max_length, 100)
        self.assertTrue(f.blank)

    def test_field_order_is_int_default_zero(self):
        from django.db.models import IntegerField

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("order")
        self.assertIsInstance(f, IntegerField)
        self.assertEqual(f.default, 0)

    def test_field_created_at_is_datetime_auto(self):
        from django.db.models import DateTimeField

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("created_at")
        self.assertIsInstance(f, DateTimeField)
        self.assertTrue(f.auto_now_add)


class EventFacilitatorM2MShapeTest(TestCase):
    """Clause 2: Event.facilitators is a M2M field through EventFacilitator."""

    def test_event_facilitators_field_is_m2m(self):
        from django.db.models import ManyToManyField

        from events.models import Event

        f = Event._meta.get_field("facilitators")
        self.assertIsInstance(f, ManyToManyField)

    def test_event_facilitators_through_is_eventfacilitator(self):
        from events.models import Event, EventFacilitator

        f = Event._meta.get_field("facilitators")
        self.assertEqual(f.remote_field.through, EventFacilitator)

    def test_event_facilitators_related_name_is_events_facilitated(self):
        from events.models import Event

        f = Event._meta.get_field("facilitators")
        self.assertEqual(f.remote_field.related_name, "events_facilitated")

    def test_profile_events_facilitated_reverse_accessor_exists(self):
        from organizers.models import Profile

        self.assertTrue(hasattr(Profile, "events_facilitated"))

    def test_event_facilitators_is_blank(self):
        """Event.facilitators should allow blank (no facilitators required)."""
        from events.models import Event

        f = Event._meta.get_field("facilitators")
        self.assertTrue(f.blank)


class EventFacilitatorOnDeleteTest(TestCase):
    """Clause 3: event FK is CASCADE, profile FK is PROTECT."""

    def test_event_fk_on_delete_cascade(self):
        from django.db.models import CASCADE

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("event")
        self.assertEqual(f.remote_field.on_delete, CASCADE)

    def test_profile_fk_on_delete_protect(self):
        from django.db.models import PROTECT

        from events.models import EventFacilitator

        f = EventFacilitator._meta.get_field("profile")
        self.assertEqual(f.remote_field.on_delete, PROTECT)

    def test_deleting_event_cascades_to_facilitator_rows(self):
        from events.models import Event, EventFacilitator
        from organizers.models import Profile

        profile = Profile.objects.create(
            name="Cascade Test Profile",
            slug="cascade-test-profile",
            status="approved",
        )
        event = Event.objects.create(
            title="Cascade Test Event",
            slug="cascade-test-event",
            start=timezone.now(),
        )
        ef = EventFacilitator.objects.create(event=event, profile=profile, role="Lead")
        ef_pk = ef.pk

        event.delete()

        self.assertFalse(EventFacilitator.objects.filter(pk=ef_pk).exists())


class EventFacilitatorUniquenessTest(TestCase):
    """Clause 4: unique_together = (('event', 'profile'),)."""

    def setUp(self):
        from events.models import Event
        from organizers.models import Profile

        self.profile = Profile.objects.create(
            name="Unique Test Profile",
            slug="unique-test-profile",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Unique Test Event",
            slug="unique-test-event",
            start=timezone.now(),
        )

    def test_duplicate_event_profile_raises_integrity_error(self):
        from events.models import EventFacilitator

        EventFacilitator.objects.create(event=self.event, profile=self.profile, role="Lead", order=0)
        with self.assertRaises(IntegrityError):
            EventFacilitator.objects.create(event=self.event, profile=self.profile, role="Co-facilitator", order=1)

    def test_different_profiles_same_event_allowed(self):
        from events.models import EventFacilitator
        from organizers.models import Profile

        profile2 = Profile.objects.create(
            name="Second Facilitator",
            slug="second-facilitator",
            status="approved",
        )
        EventFacilitator.objects.create(event=self.event, profile=self.profile, role="Lead")
        EventFacilitator.objects.create(event=self.event, profile=profile2, role="DJ")
        self.assertEqual(EventFacilitator.objects.filter(event=self.event).count(), 2)

    def test_same_profile_different_events_allowed(self):
        from events.models import Event, EventFacilitator

        event2 = Event.objects.create(
            title="Another Event",
            slug="another-event-facilitator",
            start=timezone.now(),
        )
        EventFacilitator.objects.create(event=self.event, profile=self.profile, role="Lead")
        EventFacilitator.objects.create(event=event2, profile=self.profile, role="Co-facilitator")
        self.assertEqual(EventFacilitator.objects.filter(profile=self.profile).count(), 2)


class ProfileCanBeBothOrganizerAndFacilitatorTest(TestCase):
    """Clause 5: Same Profile can be both EventOrganizer AND EventFacilitator."""

    def test_same_profile_organizer_and_facilitator_of_same_event(self):
        from events.models import Event, EventFacilitator, EventOrganizer
        from organizers.models import Profile

        profile = Profile.objects.create(
            name="Lavinia",
            slug="lavinia",
            status="approved",
        )
        event = Event.objects.create(
            title="Silent Hunger Workshop",
            slug="silent-hunger-workshop",
            start=timezone.now(),
        )

        # Same profile: organizer
        EventOrganizer.objects.create(event=event, profile=profile, is_primary=True, order=0)
        # Same profile: also facilitator
        EventFacilitator.objects.create(event=event, profile=profile, role="Lead", order=0)

        # Both rows exist
        self.assertTrue(EventOrganizer.objects.filter(event=event, profile=profile).exists())
        self.assertTrue(EventFacilitator.objects.filter(event=event, profile=profile).exists())

        # Reverse accessors both work
        self.assertIn(event, profile.events_organized.all())
        self.assertIn(event, profile.events_facilitated.all())


class EventFacilitatorBlankRoleTest(TestCase):
    """Clause 6: blank role='' is allowed."""

    def test_blank_role_creates_successfully(self):
        from events.models import Event, EventFacilitator
        from organizers.models import Profile

        profile = Profile.objects.create(
            name="Blank Role Profile",
            slug="blank-role-profile",
            status="approved",
        )
        event = Event.objects.create(
            title="Blank Role Event",
            slug="blank-role-event",
            start=timezone.now(),
        )

        ef = EventFacilitator.objects.create(event=event, profile=profile, role="")
        self.assertEqual(ef.role, "")

    def test_blank_role_no_validation_error(self):
        from events.models import Event, EventFacilitator
        from organizers.models import Profile

        profile = Profile.objects.create(
            name="No Role Profile",
            slug="no-role-profile",
            status="approved",
        )
        event = Event.objects.create(
            title="No Role Event",
            slug="no-role-event",
            start=timezone.now(),
        )

        ef = EventFacilitator(event=event, profile=profile, role="")
        # Should raise no ValidationError
        try:
            ef.full_clean()
        except ValidationError as e:
            self.fail(f"full_clean() raised ValidationError for blank role: {e}")
