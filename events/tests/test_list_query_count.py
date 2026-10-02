"""/events/ runs a fixed, small number of SQL queries however many events show (sb-x5xh.7)."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from events.models import Event, EventArtist, Tag
from organizers.models import Profile
from venues.models import Venue

User = get_user_model()

# Measured 30 on a warm cache: 13 are feature-flag reads from the DB cache table
# (fixed per request), the rest are the page's own queries. The test's job is
# that the count never scales with events; the ceiling catches a fixed-cost creep.
QUERY_CEILING = 35


class EventListQueryCountTest(TestCase):
    def setUp(self):
        self.client.force_login(
            User.objects.create_user(username="qc", email="qc@example.com", password="x", is_staff=True)
        )
        self.tag = Tag.objects.create(slug="bdsm", label="BDSM", kind="theme")
        self.created = 0

    def _add_events(self, n):
        for _ in range(n):
            i = self.created
            self.created += 1
            org = Profile.objects.create(name=f"Org {i}", slug=f"org-{i}", status="approved")
            venue = Venue.objects.create(
                name=f"Venue {i}",
                slug=f"venue-{i}",
                latitude=Decimal("52.52"),
                longitude=Decimal("13.40"),
                privacy_mode="public",
            )
            event = Event.objects.create(
                title=f"Event {i}",
                slug=f"event-{i}",
                organizer=org,
                venue=venue,
                start=timezone.now() + timezone.timedelta(days=i + 1),
                status="published",
            )
            event.tags.add(self.tag)
            EventArtist.objects.create(event=event, name=f"Artist {i}a", profile=org)
            EventArtist.objects.create(event=event, name=f"Artist {i}b")

    def _count(self, **extra):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/events/", **extra)
        self.assertEqual(response.status_code, 200)
        return len(ctx), response

    def _assert_fixed_count(self, **extra):
        self._add_events(5)
        self._count(**extra)  # warm the DB cache table; its first-request misses are one-off reads
        few, response_few = self._count(**extra)
        self._add_events(15)
        many, response_many = self._count(**extra)
        self.assertEqual(few, many, f"query count grew with events: 5 -> {few}, 20 -> {many}")
        self.assertLessEqual(many, QUERY_CEILING)
        return response_few, response_many

    def test_full_page_query_count_independent_of_event_count(self):
        _, response = self._assert_fixed_count()
        self.assertEqual(len(response.context["markers_geojson"]["features"]), 20)

    def test_htmx_partial_query_count_independent_of_event_count(self):
        self._assert_fixed_count(HTTP_HX_REQUEST="true")
