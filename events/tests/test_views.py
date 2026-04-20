"""View tests for events app — map spike views."""
from django.test import SimpleTestCase, RequestFactory
from django.urls import reverse


class EventDrawerURLTest(SimpleTestCase):
    """Test that event_drawer URL resolves correctly."""

    def test_event_drawer_url_resolves(self):
        url = reverse("event-drawer", kwargs={"event_id": 1})
        self.assertEqual(url, "/events/1/drawer/")

    def test_event_list_url_still_resolves(self):
        url = reverse("event-list")
        self.assertEqual(url, "/events/")
