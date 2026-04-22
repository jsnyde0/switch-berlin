"""Tests for the /me page (bead kb-8qn.5).

TDD: these tests are written BEFORE the implementation.

Covers:
- GET /me/ unauthenticated → redirect to login
- GET /me/ authenticated → 200 with context vars
- Followed organizers section: empty, populated
- Upcoming attendances: going/interested, future, published, visible
- Past attendances: went status, past events
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Attendance, Event
from organizers.models import Organizer, OrganizerFollow

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(username="testme", is_approved=True):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
    )
    user.is_approved = is_approved
    user.save()
    return user


def _make_organizer(slug="me-org", status="approved", hidden=False):
    return Organizer.objects.create(
        name=f"Me Organizer {slug}",
        slug=slug,
        status=status,
        hidden=hidden,
    )


def _make_event(organizer, slug, start_delta_days, status="published", hidden=False):
    """Create an event relative to now. Positive = future, negative = past."""
    now = timezone.now()
    start = now + timedelta(days=start_delta_days)
    end = start + timedelta(hours=3)
    return Event.objects.create(
        title=f"Event {slug}",
        slug=slug,
        organizer=organizer,
        status=status,
        start=start,
        end=end,
        hidden=hidden,
    )


# ---------------------------------------------------------------------------
# Authentication gate
# ---------------------------------------------------------------------------


class MeViewAuthTest(TestCase):
    """Unauthenticated access to /me/ must redirect to login."""

    def test_anon_redirects_to_login(self):
        response = self.client.get("/me/")
        self.assertRedirects(
            response,
            "/accounts/login/?next=/me/",
            fetch_redirect_response=False,
        )

    def test_authenticated_user_gets_200(self):
        user = _make_user("meuser200")
        self.client.force_login(user)
        response = self.client.get("/me/")
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Context variables
# ---------------------------------------------------------------------------


class MeViewContextTest(TestCase):
    """Authenticated /me/ must pass followed, upcoming, past to template."""

    def setUp(self):
        self.user = _make_user("mecontextuser")
        self.client.force_login(self.user)

    def test_context_has_followed(self):
        response = self.client.get("/me/")
        self.assertIn("followed", response.context)

    def test_context_has_upcoming(self):
        response = self.client.get("/me/")
        self.assertIn("upcoming", response.context)

    def test_context_has_past(self):
        response = self.client.get("/me/")
        self.assertIn("past", response.context)


# ---------------------------------------------------------------------------
# Followed organizers section
# ---------------------------------------------------------------------------


class MeViewFollowedOrganizersTest(TestCase):
    """Followed organizers section on /me/."""

    def setUp(self):
        self.user = _make_user("mefollowuser")
        self.client.force_login(self.user)

    def test_empty_followed_shows_empty_state(self):
        """No follows → empty state text shown."""
        response = self.client.get("/me/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not following anyone")

    def test_followed_organizer_appears(self):
        """After following an organizer, its name appears on /me/."""
        org = _make_organizer(slug="me-followed-org")
        OrganizerFollow.objects.create(user=self.user, organizer=org)
        response = self.client.get("/me/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, org.name)

    def test_followed_section_has_unfollow_form(self):
        """Each followed organizer row has a form pointing to organizer-follow URL."""
        org = _make_organizer(slug="me-unfollow-org")
        OrganizerFollow.objects.create(user=self.user, organizer=org)
        response = self.client.get("/me/")
        self.assertEqual(response.status_code, 200)
        # The unfollow form should POST to /o/<slug>/follow/
        self.assertContains(response, f"/o/{org.slug}/follow/")

    def test_only_own_follows_shown(self):
        """Follows from another user are not shown."""
        other_user = _make_user("othermeuser")
        org = _make_organizer(slug="me-other-org")
        OrganizerFollow.objects.create(user=other_user, organizer=org)
        response = self.client.get("/me/")
        # org is only followed by other_user, not self.user
        self.assertNotContains(response, org.name)


# ---------------------------------------------------------------------------
# Upcoming attendances
# ---------------------------------------------------------------------------


class MeViewUpcomingAttendancesTest(TestCase):
    """Upcoming attendances section on /me/: going + interested, future events."""

    def setUp(self):
        self.user = _make_user("meupcominguser")
        self.client.force_login(self.user)
        self.org = _make_organizer(slug="me-upcoming-org")

    def test_going_future_event_appears_in_upcoming(self):
        event = _make_event(self.org, "me-going-future", start_delta_days=5)
        Attendance.objects.create(user=self.user, event=event, status="going")
        response = self.client.get("/me/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, event.title)

    def test_interested_future_event_appears_in_upcoming(self):
        event = _make_event(self.org, "me-interested-future", start_delta_days=10)
        Attendance.objects.create(user=self.user, event=event, status="interested")
        response = self.client.get("/me/")
        self.assertContains(response, event.title)

    def test_went_future_event_not_in_upcoming(self):
        """'went' status events don't appear in upcoming section."""
        event = _make_event(self.org, "me-went-future", start_delta_days=3)
        Attendance.objects.create(user=self.user, event=event, status="went")
        response = self.client.get("/me/")
        # Should not appear in 'upcoming'; might appear in past, but past filter
        # also requires event to be in the past so it won't appear there either.
        # Check upcoming context directly.
        upcoming_events = [a.event for a in response.context["upcoming"]]
        self.assertNotIn(event, upcoming_events)

    def test_going_past_event_not_in_upcoming(self):
        """Past events with going status are not in upcoming."""
        event = _make_event(self.org, "me-going-past", start_delta_days=-5)
        Attendance.objects.create(user=self.user, event=event, status="going")
        response = self.client.get("/me/")
        upcoming_events = [a.event for a in response.context["upcoming"]]
        self.assertNotIn(event, upcoming_events)

    def test_hidden_event_not_in_upcoming(self):
        """Hidden events are not shown in upcoming."""
        event = _make_event(
            self.org, "me-going-hidden", start_delta_days=7, hidden=True
        )
        Attendance.objects.create(user=self.user, event=event, status="going")
        response = self.client.get("/me/")
        upcoming_events = [a.event for a in response.context["upcoming"]]
        self.assertNotIn(event, upcoming_events)

    def test_unpublished_event_not_in_upcoming(self):
        """Draft/cancelled events don't appear in upcoming."""
        event = _make_event(
            self.org, "me-going-draft", start_delta_days=7, status="draft"
        )
        Attendance.objects.create(user=self.user, event=event, status="going")
        response = self.client.get("/me/")
        upcoming_events = [a.event for a in response.context["upcoming"]]
        self.assertNotIn(event, upcoming_events)


# ---------------------------------------------------------------------------
# Past attendances
# ---------------------------------------------------------------------------


class MeViewPastAttendancesTest(TestCase):
    """Past attendances section on /me/: went status, past events."""

    def setUp(self):
        self.user = _make_user("mepastuser")
        self.client.force_login(self.user)
        self.org = _make_organizer(slug="me-past-org")

    def test_went_past_event_appears_in_past(self):
        event = _make_event(self.org, "me-went-past", start_delta_days=-10)
        Attendance.objects.create(user=self.user, event=event, status="went")
        response = self.client.get("/me/")
        self.assertEqual(response.status_code, 200)
        past_events = [a.event for a in response.context["past"]]
        self.assertIn(event, past_events)

    def test_going_past_event_not_in_past_section(self):
        """'going' status doesn't appear in past section."""
        event = _make_event(self.org, "me-going-in-past", start_delta_days=-5)
        Attendance.objects.create(user=self.user, event=event, status="going")
        response = self.client.get("/me/")
        past_events = [a.event for a in response.context["past"]]
        self.assertNotIn(event, past_events)

    def test_went_future_event_not_in_past_section(self):
        """'went' on a future event (shouldn't happen normally) not in past."""
        event = _make_event(self.org, "me-went-future-p", start_delta_days=5)
        Attendance.objects.create(user=self.user, event=event, status="went")
        response = self.client.get("/me/")
        past_events = [a.event for a in response.context["past"]]
        self.assertNotIn(event, past_events)
