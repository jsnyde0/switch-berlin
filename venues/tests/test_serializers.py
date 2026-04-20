"""Privacy enforcement tests for venues/serializers.py — venue_to_geojson."""
from decimal import Decimal

from django.test import TestCase

from venues.models import Venue
from venues.serializers import venue_to_geojson


class VenueToGeoJSONPrivacyTest(TestCase):

    def test_public_venue_exact_coords(self):
        venue = Venue(
            slug="v1",
            latitude=Decimal("52.520000"),
            longitude=Decimal("13.400000"),
            privacy_mode="public",
        )
        feature = venue_to_geojson(venue)
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [13.4, 52.52])
        self.assertEqual(feature["properties"]["privacy"], "public")

    def test_neighborhood_blur_rounds_to_3dp(self):
        venue = Venue(
            slug="v2",
            latitude=Decimal("52.520123"),
            longitude=Decimal("13.400456"),
            privacy_mode="neighborhood_blur",
            blur_radius_m=250,
        )
        feature = venue_to_geojson(venue)
        self.assertEqual(feature["geometry"]["coordinates"][1], round(52.520123, 3))
        self.assertEqual(feature["geometry"]["coordinates"][0], round(13.400456, 3))
        self.assertEqual(feature["properties"]["blur_radius_m"], 250)

    def test_private_venue_geometry_is_null(self):
        venue = Venue(
            slug="v3",
            latitude=Decimal("52.520000"),
            longitude=Decimal("13.400000"),
            privacy_mode="private",
        )
        feature = venue_to_geojson(venue)
        self.assertIsNone(
            feature["geometry"],
            "Exact coords must not be in GeoJSON for private venues",
        )
        self.assertIn("fake_center", feature["properties"])
        self.assertEqual(feature["properties"]["blur_radius_m"], 1000)

    def test_private_venue_fake_center_is_deterministic(self):
        venue = Venue(
            slug="v4",
            latitude=Decimal("52.520000"),
            longitude=Decimal("13.400000"),
            privacy_mode="private",
        )
        f1 = venue_to_geojson(venue)
        f2 = venue_to_geojson(venue)
        self.assertEqual(
            f1["properties"]["fake_center"], f2["properties"]["fake_center"]
        )

    def test_venue_with_null_coords_returns_none(self):
        venue = Venue(slug="v5", latitude=None, longitude=None, privacy_mode="public")
        self.assertIsNone(venue_to_geojson(venue))
