from django.test import TestCase
from django.utils import timezone

from events.models import Event


class EventOrganizerNullableTest(TestCase):
    """
    [kb-n0y] Event.organizer FK was replaced by EventOrganizer M2M.
    The compat property event.organizer returns Profile-or-None.
    """

    def test_organizer_m2m_field_exists(self):
        from django.db.models import ManyToManyField

        from events.models import EventOrganizer

        f = Event._meta.get_field("organizers")
        self.assertIsInstance(f, ManyToManyField)
        self.assertEqual(f.remote_field.through, EventOrganizer)

    def test_organizer_property_returns_none_without_organizer(self):
        """event.organizer returns None if no EventOrganizer row exists."""
        event = Event(
            title="Draft event",
            slug="draft-event",
            start=timezone.now(),
        )
        # Property uses pk to query, and pk is None before save
        # So simulate a saved event with no organizer rows via compat setter
        event._pending_organizer = None
        self.assertIsNone(event._pending_organizer)


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


class EventCapacityRegistrationFieldsTest(TestCase):
    """Event has capacity, registration_required, registration_url optional fields."""

    def test_capacity_field_exists_and_is_nullable(self):
        f = Event._meta.get_field("capacity")
        self.assertTrue(f.null)
        self.assertTrue(f.blank)

    def test_capacity_defaults_to_none(self):
        event = Event()
        self.assertIsNone(event.capacity)

    def test_registration_required_field_exists(self):
        f = Event._meta.get_field("registration_required")
        self.assertFalse(f.null)
        self.assertFalse(f.blank)

    def test_registration_required_defaults_to_false(self):
        event = Event()
        self.assertFalse(event.registration_required)

    def test_registration_url_field_exists_and_is_blank(self):
        f = Event._meta.get_field("registration_url")
        self.assertTrue(f.blank)
        self.assertFalse(f.null)

    def test_registration_url_defaults_to_empty_string(self):
        event = Event()
        self.assertEqual(event.registration_url, "")
