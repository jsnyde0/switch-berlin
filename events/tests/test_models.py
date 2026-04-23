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


class EventNewSchemaFieldsTest(TestCase):
    """Event has price_description, language, registration_email optional fields."""

    def test_price_description_field_exists_and_is_blank(self):
        f = Event._meta.get_field("price_description")
        self.assertTrue(f.blank)
        self.assertFalse(f.null)  # TextField — blank string not NULL

    def test_price_description_defaults_to_empty_string(self):
        event = Event()
        self.assertEqual(event.price_description, "")

    def test_language_field_exists_and_is_blank(self):
        f = Event._meta.get_field("language")
        self.assertTrue(f.blank)
        self.assertFalse(f.null)

    def test_language_field_has_expected_choices(self):
        f = Event._meta.get_field("language")
        choice_values = [c[0] for c in f.choices]
        self.assertIn("de", choice_values)
        self.assertIn("en", choice_values)
        self.assertIn("bilingual", choice_values)

    def test_registration_email_field_exists_and_is_blank(self):
        f = Event._meta.get_field("registration_email")
        self.assertTrue(f.blank)
        self.assertFalse(f.null)

    def test_registration_email_defaults_to_empty_string(self):
        event = Event()
        self.assertEqual(event.registration_email, "")
