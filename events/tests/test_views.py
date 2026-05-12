"""View tests for events app — map spike views."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone


class EventDrawerURLTest(SimpleTestCase):
    """Test that event_drawer URL resolves correctly."""

    def test_event_drawer_url_resolves(self):
        url = reverse(
            "event-drawer",
            kwargs={"org_slug": "test-organizer", "event_slug": "test-event"},
        )
        self.assertEqual(url, "/events/test-organizer/test-event/drawer/")

    def test_event_list_url_still_resolves(self):
        url = reverse("event-list")
        self.assertEqual(url, "/events/")


User = get_user_model()


class EventDrawerContextTest(TestCase):
    """event_drawer view sets user_has_went_attendance correctly in context."""

    def setUp(self):
        from events.models import Event
        from organizers.models import Profile

        self.organizer = Profile.objects.create(
            name="Drawer Test Org", slug="drawer-test-org", status="approved"
        )
        self.event = Event.objects.create(
            title="Drawer Test Event",
            slug="drawer-test-event",
            organizer=self.organizer,
            status="published",
            start=timezone.now() - timedelta(days=3),
        )
        self.user = User.objects.create_user(
            username="drawer_user", email="drawer@example.com", password="testpass123"
        )
        self.user.is_approved = True
        self.user.save()

    def _drawer_url(self):
        return reverse(
            "event-drawer",
            kwargs={"org_slug": self.organizer.slug, "event_slug": self.event.slug},
        )

    def test_anonymous_user_has_went_attendance_false(self):
        """Anonymous request: user_has_went_attendance should be False in context."""
        c = Client()
        resp = c.get(self._drawer_url())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["user_has_went_attendance"])

    def test_user_without_went_attendance_false(self):
        """Authenticated user with no 'went' attendance: user_has_went_attendance is False."""
        c = Client()
        c.login(username="drawer_user", password="testpass123")
        resp = c.get(self._drawer_url())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["user_has_went_attendance"])

    def test_user_with_went_attendance_true(self):
        """Authenticated user with 'went' attendance: user_has_went_attendance is True."""
        from events.models import Attendance

        Attendance.objects.create(user=self.user, event=self.event, status="went")
        c = Client()
        c.login(username="drawer_user", password="testpass123")
        resp = c.get(self._drawer_url())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["user_has_went_attendance"])
