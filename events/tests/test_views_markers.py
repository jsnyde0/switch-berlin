"""Integration tests for event list view: markers payload, tag filter, drawer."""
import json
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event, Tag
from organizers.models import Profile
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

        self.organizer = Profile.objects.create(
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

    def test_private_venue_exact_coords_absent_from_markers(self):
        """Private venues must use a fake-center geometry, not the real lat/lng."""
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        match = re.search(
            r'id="markers-data" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "markers-data script tag not found in response")
        geojson = json.loads(match.group(1))
        private_features = [
            f
            for f in geojson["features"]
            if f["properties"].get("privacy") == "private"
        ]
        self.assertGreater(
            len(private_features), 0, "Expected at least one private-venue feature"
        )
        real_lat = float(self.venue_private.latitude)
        real_lng = float(self.venue_private.longitude)
        for f in private_features:
            # Feature must have a geometry (fake center), not null
            self.assertIsNotNone(
                f["geometry"],
                "Private venue geometry must be a fake-center Point, not null",
            )
            coords = f["geometry"]["coordinates"]
            # Fake center must differ from real coordinates.
            # The hash-based offset guarantees at least 3rd-decimal difference
            # (minimum ~0.001° ≈ 100m). Use places=3 (>= 0.0005° threshold).
            self.assertNotAlmostEqual(
                coords[0], real_lng, places=3,
                msg="Private venue longitude must be obfuscated",
            )
            self.assertNotAlmostEqual(
                coords[1], real_lat, places=3,
                msg="Private venue latitude must be obfuscated",
            )
            # Properties must carry blur_radius_m for the obfuscation circle
            self.assertEqual(f["properties"].get("blur_radius_m"), 1000)

    def test_drawer_returns_partial(self):
        event = self.events[0]
        response = self.client.get(
            f"/events/{event.organizer.slug}/{event.slug}/drawer/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<html", response.content.lower())
        self.assertIn(event.title.encode(), response.content)

    def test_drawer_404_for_unknown_event(self):
        response = self.client.get("/events/unknown-org/unknown-event/drawer/")
        self.assertEqual(response.status_code, 404)

    def test_drawer_404_for_unpublished_event(self):
        """Drawer must not expose draft or cancelled events (security fix)."""
        now = timezone.now()
        draft_event = Event.objects.create(
            title="Draft Event",
            slug="draft-event",
            organizer=self.organizer,
            venue=self.venue_public,
            start=now + timezone.timedelta(days=1),
            status="draft",
        )
        response = self.client.get(
            f"/events/{draft_event.organizer.slug}/{draft_event.slug}/drawer/"
        )
        self.assertEqual(response.status_code, 404)

    def test_bounds_filter_includes_event_in_bounds(self):
        """Events whose venue is within bounds must appear in markers."""
        # venue_public is at lat=52.52, lng=13.40 — include it
        response = self.client.get(
            "/events/",
            {"bounds": "52.50,13.38,52.55,13.45"},
        )
        self.assertEqual(response.status_code, 200)
        import json
        import re
        content = response.content.decode()
        match = re.search(
            r'id="markers-data" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "markers-data script tag not found")
        geojson = json.loads(match.group(1))
        public_event_slugs = [
            f["properties"]["event_slug"]
            for f in geojson["features"]
            if f["properties"].get("privacy") == "public"
        ]
        self.assertIn(self.events[0].slug, public_event_slugs)

    def test_bounds_filter_excludes_event_outside_bounds(self):
        """Events whose venue is outside bounds must not appear in markers."""
        # venue_public is at lat=52.52, lng=13.40 — exclude via tight bounds far away
        response = self.client.get(
            "/events/",
            {"bounds": "51.00,12.00,51.50,12.50"},
        )
        self.assertEqual(response.status_code, 200)
        import json
        import re
        content = response.content.decode()
        match = re.search(
            r'id="markers-data" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "markers-data script tag not found")
        geojson = json.loads(match.group(1))
        self.assertEqual(
            len(geojson["features"]), 0,
            "Expected no markers when bounds exclude all venues",
        )

    def test_bounds_filter_malformed_ignored(self):
        """Malformed bounds param must be silently ignored (all events returned)."""
        response = self.client.get("/events/", {"bounds": "not,a,valid,bounds"})
        self.assertEqual(response.status_code, 200)
        import json
        import re
        content = response.content.decode()
        match = re.search(
            r'id="markers-data" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "markers-data script tag not found")
        geojson = json.loads(match.group(1))
        # All 3 events should be present (malformed bounds means no filtering)
        self.assertEqual(len(geojson["features"]), 3)
