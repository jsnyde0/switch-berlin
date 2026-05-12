"""
TDD tests for EventOrganizer M2M migration (kb-n0y).

Acceptance criteria covered:
  (a) EventOrganizer model fields (AC-1)
  (b) Event.organizers M2M shape + reverse accessor (AC-2)
  (c) Event.organizer FK gone (AC-3)
  (d) event.organizer property returns primary Profile (AC-4)
  (e) event.organizer returns None when no organizers (AC-4)
  (f) event.primary_organizer alias (AC-4)
  (g) profile.events.all() returns events (AC-5)
  (h) Partial unique constraint on is_primary (AC-6)
  (i) TDD evidence: multiple organizers, compat property, data shape (AC-12)
"""

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone


class EventOrganizerModelFieldsTest(TestCase):
    """AC-1: EventOrganizer model has expected fields."""

    def test_eventorganizer_model_importable(self):
        from events.models import EventOrganizer  # noqa: F401

    def test_field_event_is_fk(self):
        from django.db.models import ForeignKey

        from events.models import EventOrganizer

        f = EventOrganizer._meta.get_field("event")
        self.assertIsInstance(f, ForeignKey)

    def test_field_profile_is_fk(self):
        from django.db.models import ForeignKey

        from events.models import EventOrganizer

        f = EventOrganizer._meta.get_field("profile")
        self.assertIsInstance(f, ForeignKey)

    def test_field_is_primary_is_bool(self):
        from django.db.models import BooleanField

        from events.models import EventOrganizer

        f = EventOrganizer._meta.get_field("is_primary")
        self.assertIsInstance(f, BooleanField)

    def test_field_order_is_int_default_zero(self):
        from django.db.models import IntegerField

        from events.models import EventOrganizer

        f = EventOrganizer._meta.get_field("order")
        self.assertIsInstance(f, IntegerField)
        self.assertEqual(f.default, 0)

    def test_field_created_at_is_datetime_auto(self):
        from django.db.models import DateTimeField

        from events.models import EventOrganizer

        f = EventOrganizer._meta.get_field("created_at")
        self.assertIsInstance(f, DateTimeField)
        self.assertTrue(f.auto_now_add)


class EventOrganizerM2MShapeTest(TestCase):
    """AC-2: Event.organizers is a M2M field through EventOrganizer."""

    def test_event_organizers_field_is_m2m(self):
        from django.db.models import ManyToManyField

        from events.models import Event

        f = Event._meta.get_field("organizers")
        self.assertIsInstance(f, ManyToManyField)

    def test_event_organizers_through_is_eventorganizer(self):
        from events.models import Event, EventOrganizer

        f = Event._meta.get_field("organizers")
        self.assertEqual(f.remote_field.through, EventOrganizer)

    def test_profile_events_organized_reverse_accessor(self):
        from organizers.models import Profile

        # The reverse M2M accessor should exist
        self.assertTrue(hasattr(Profile, "events_organized"))


class EventOrganizerFKGoneTest(TestCase):
    """AC-3: Event.organizer FK field no longer exists on the model."""

    def test_organizer_fk_field_gone(self):
        from django.core.exceptions import FieldDoesNotExist

        from events.models import Event

        with self.assertRaises(FieldDoesNotExist):
            Event._meta.get_field("organizer")


class EventOrganizerCompatPropertyTest(TestCase):
    """AC-4: event.organizer property returns primary Profile or None."""

    def setUp(self):
        from events.models import Event, EventOrganizer
        from organizers.models import Profile

        self.profile = Profile.objects.create(
            name="Test Organizer",
            slug="test-organizer",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Test Event",
            slug="test-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile,
            is_primary=True,
            order=0,
        )

    def test_event_organizer_property_returns_primary_profile(self):
        self.assertEqual(self.event.organizer, self.profile)

    def test_event_primary_organizer_alias_returns_same(self):
        self.assertEqual(self.event.primary_organizer, self.profile)

    def test_event_organizer_property_returns_none_when_no_organizers(self):
        from events.models import Event

        event_no_org = Event.objects.create(
            title="No Org Event",
            slug="no-org-event",
            start=timezone.now(),
        )
        self.assertIsNone(event_no_org.organizer)

    def test_event_organizer_is_not_queryset(self):
        """The property must return a Profile instance, NOT a queryset."""
        from organizers.models import Profile

        result = self.event.organizer
        self.assertIsInstance(result, Profile)

    def test_event_with_non_primary_organizer_returns_none(self):
        from events.models import Event, EventOrganizer
        from organizers.models import Profile

        event2 = Event.objects.create(
            title="Event Co-only",
            slug="event-co-only",
            start=timezone.now(),
        )
        profile2 = Profile.objects.create(
            name="Co Organizer",
            slug="co-organizer",
            status="approved",
        )
        EventOrganizer.objects.create(
            event=event2,
            profile=profile2,
            is_primary=False,
            order=0,
        )
        # No is_primary=True row, so property returns None
        self.assertIsNone(event2.organizer)


class ProfileEventsCompatTest(TestCase):
    """AC-5: profile.events.all() returns events where profile is organizer."""

    def setUp(self):
        from events.models import Event, EventOrganizer
        from organizers.models import Profile

        self.profile = Profile.objects.create(
            name="Profile Events Test",
            slug="profile-events-test",
            status="approved",
        )
        self.event1 = Event.objects.create(
            title="Event 1",
            slug="event-1",
            start=timezone.now(),
        )
        self.event2 = Event.objects.create(
            title="Event 2",
            slug="event-2",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event1,
            profile=self.profile,
            is_primary=True,
            order=0,
        )
        EventOrganizer.objects.create(
            event=self.event2,
            profile=self.profile,
            is_primary=False,
            order=1,
        )

    def test_profile_events_all_returns_queryset(self):
        result = self.profile.events.all()
        # Should be queryset-like (iterable), and contain both events
        event_pks = {e.pk for e in result}
        self.assertIn(self.event1.pk, event_pks)
        self.assertIn(self.event2.pk, event_pks)

    def test_profile_events_count_correct(self):
        self.assertEqual(self.profile.events.all().count(), 2)


class EventOrganizerPartialUniqueTest(TestCase):
    """AC-6: partial unique constraint on is_primary=True per event."""

    def setUp(self):
        from events.models import Event
        from organizers.models import Profile

        self.profile1 = Profile.objects.create(
            name="Organizer A",
            slug="organizer-a",
            status="approved",
        )
        self.profile2 = Profile.objects.create(
            name="Organizer B",
            slug="organizer-b",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Constraint Test Event",
            slug="constraint-test-event",
            start=timezone.now(),
        )

    def test_two_is_primary_true_raises_integrity_error(self):
        from events.models import EventOrganizer

        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile1,
            is_primary=True,
            order=0,
        )
        with self.assertRaises(IntegrityError):
            EventOrganizer.objects.create(
                event=self.event,
                profile=self.profile2,
                is_primary=True,
                order=1,
            )

    def test_multiple_is_primary_false_succeeds(self):
        from events.models import EventOrganizer

        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile1,
            is_primary=False,
            order=0,
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile2,
            is_primary=False,
            order=1,
        )
        self.assertEqual(
            EventOrganizer.objects.filter(event=self.event).count(), 2
        )


class EventOrganizerMultipleOrganizersTest(TestCase):
    """AC-12 TDD evidence: Event can have multiple organizers via through-rows."""

    def test_event_with_primary_and_co_organizer(self):
        from events.models import Event, EventOrganizer
        from organizers.models import Profile

        primary = Profile.objects.create(
            name="Primary Org",
            slug="primary-org",
            status="approved",
        )
        co = Profile.objects.create(
            name="Co Org",
            slug="co-org",
            status="approved",
        )
        event = Event.objects.create(
            title="Multi Org Event",
            slug="multi-org-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=event, profile=primary, is_primary=True, order=0
        )
        EventOrganizer.objects.create(
            event=event, profile=co, is_primary=False, order=1
        )

        # event.organizers queryset has both
        organizer_pks = set(event.organizers.values_list("pk", flat=True))
        self.assertIn(primary.pk, organizer_pks)
        self.assertIn(co.pk, organizer_pks)

        # compat property returns primary only
        self.assertEqual(event.organizer, primary)

    def test_events_organized_reverse_accessor(self):
        from events.models import Event, EventOrganizer
        from organizers.models import Profile

        profile = Profile.objects.create(
            name="Reverse Test Org",
            slug="reverse-test-org",
            status="approved",
        )
        event = Event.objects.create(
            title="Reverse Test Event",
            slug="reverse-test-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=event, profile=profile, is_primary=True, order=0
        )

        # events_organized is the M2M reverse
        self.assertIn(event, profile.events_organized.all())
