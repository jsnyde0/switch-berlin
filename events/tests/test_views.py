"""View tests for events app."""

from django.test import SimpleTestCase
from django.urls import reverse


class EventListURLTest(SimpleTestCase):
    """Test that event-list URL resolves correctly."""

    def test_event_list_url_resolves(self):
        url = reverse("event-list")
        self.assertEqual(url, "/events/")

    def test_event_drawer_url_does_not_exist(self):
        """event-drawer route must be gone (deleted per ADR-008 D1)."""
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse(
                "event-drawer",
                kwargs={"org_slug": "test-organizer", "event_slug": "test-event"},
            )
