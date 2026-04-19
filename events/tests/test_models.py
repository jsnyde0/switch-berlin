from django.test import TestCase
from django.utils import timezone

from events.models import Event


class EventOrganizerNullableTest(TestCase):
    """Event.organizer can be null."""

    def test_organizer_field_is_nullable(self):
        f = Event._meta.get_field("organizer")
        self.assertTrue(f.null)
        self.assertTrue(f.blank)

    def test_create_event_without_organizer(self):
        event = Event(
            title="Draft event",
            slug="draft-event",
            start=timezone.now(),
            organizer=None,
        )
        # Just check field access; no DB save (no start field collision)
        self.assertIsNone(event.organizer)


class EventSuggestedTagsTest(TestCase):
    """Event.suggested_tags is a JSONField that defaults to []."""

    def test_suggested_tags_defaults_to_empty_list(self):
        event = Event()
        self.assertEqual(event.suggested_tags, [])

    def test_suggested_tags_stores_list(self):
        f = Event._meta.get_field("suggested_tags")
        self.assertEqual(f.default, list)
