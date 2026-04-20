"""Integration tests for event list view: markers payload, tag filter, drawer."""
import json
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event, Tag
from organizers.models import Organizer
from venues.models import Venue

User = get_user_model()


class EventListMarkersTest(TestCase):

    def setUp(self):
        # Create and log in a staff user to pass the login wall
        self.staff_user = User.objects.create_user(
            username="teststaff",
            email="teststaff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)

        self.organizer = Organizer.objects.create(
            name="Test Org",
            slug="test-org",
            status="approved",
        )
        self.venue_public = Venue.objects.create(
            name="Public Venue",
            slug="public-venue",
            latitude=Decimal("52.52"),
            longitude=Decimal("13.40"),
            privacy_mode="public",
        )
        self.venue_private = Venue.objects.create(
            name="Private Venue",
            slug="private-venue",
            latitude=Decimal("52.53"),
            longitude=Decimal("13.41"),
            privacy_mode="private",
        )
        self.tag_bdsm = Tag.objects.create(slug="bdsm", label="BDSM", kind="theme")
        now = timezone.now()

        self.events = []
        for i in range(2):
            event = Event.objects.create(
                title=f"Public Event {i}",
                slug=f"public-event-{i}",
                organizer=self.organizer,
                venue=self.venue_public,
                start=now + timezone.timedelta(days=i + 1),
                status="published",
            )
            event.tags.add(self.tag_bdsm)
            self.events.append(event)

        private_event = Event.objects.create(
            title="Private Event",
            slug="private-event",
            organizer=self.organizer,
            venue=self.venue_private,
            start=now + timezone.timedelta(days=3),
            status="published",
        )
        self.events.append(private_event)

    def test_markers_geojson_present_in_page_response(self):
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"markers-data", response.content)

    def test_tag_filter_returns_partial_with_server_timing(self):
        response = self.client.get(
            "/events/", {"tags": "bdsm"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Server-Timing", response)
        # Partial must not contain a full HTML document
        self.assertNotIn(b"<html", response.content.lower())

    def test_url_roundtrip_tags_param(self):
        response = self.client.get("/events/", {"tags": "bdsm"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"bdsm", response.content)

    def test_private_venue_coords_absent_from_markers(self):
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        match = re.search(
            r'id="markers-data" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "markers-data script tag not found in response")
        # The json_script filter JSON-encodes the value; since markers_geojson is
        # already a JSON string, the script tag contains a JSON-encoded string —
        # load once to get the string, then load again to get the dict.
        raw = json.loads(match.group(1))
        geojson = json.loads(raw) if isinstance(raw, str) else raw
        private_features = [
            f
            for f in geojson["features"]
            if f["properties"].get("privacy") == "private"
        ]
        self.assertGreater(
            len(private_features), 0, "Expected at least one private-venue feature"
        )
        for f in private_features:
            self.assertIsNone(
                f["geometry"],
                f'Private venue geometry must be null, got {f["geometry"]}',
            )

    def test_drawer_returns_partial(self):
        event = self.events[0]
        response = self.client.get(f"/events/{event.pk}/drawer/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<html", response.content.lower())
        self.assertIn(event.title.encode(), response.content)

    def test_drawer_404_for_unknown_event(self):
        response = self.client.get("/events/999999/drawer/")
        self.assertEqual(response.status_code, 404)
