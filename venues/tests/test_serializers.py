"""Unit tests for venues/serializers.py — venue_to_geojson privacy enforcement."""
import hashlib
from decimal import Decimal

from django.test import SimpleTestCase

from venues.models import Venue
from venues.serializers import venue_to_geojson


class VenueToGeoJSONPublicTest(SimpleTestCase):
    def _make_venue(self, **kwargs):
        defaults = dict(
            slug="test-venue",
            latitude=Decimal("52.520000"),
            longitude=Decimal("13.400000"),
            privacy_mode="public",
            blur_radius_m=250,
        )
        defaults.update(kwargs)
        return Venue(**defaults)

    def test_returns_none_when_latitude_missing(self):
        v = self._make_venue(latitude=None)
        assert venue_to_geojson(v) is None

    def test_returns_none_when_longitude_missing(self):
        v = self._make_venue(longitude=None)
        assert venue_to_geojson(v) is None

    def test_public_returns_exact_coordinates(self):
        v = self._make_venue(
            latitude=Decimal("52.520123"),
            longitude=Decimal("13.400456"),
            privacy_mode="public",
        )
        feature = venue_to_geojson(v)
        assert feature is not None
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        assert feature["geometry"]["coordinates"] == [13.400456, 52.520123]
        assert feature["properties"]["privacy"] == "public"
        assert feature["properties"]["blur_radius_m"] is None

    def test_neighborhood_blur_rounds_to_3dp(self):
        v = self._make_venue(
            latitude=Decimal("52.520123"),
            longitude=Decimal("13.400456"),
            privacy_mode="neighborhood_blur",
            blur_radius_m=250,
        )
        feature = venue_to_geojson(v)
        assert feature is not None
        assert feature["geometry"]["coordinates"] == [round(13.400456, 3), round(52.520123, 3)]
        assert feature["properties"]["privacy"] == "neighborhood_blur"
        assert feature["properties"]["blur_radius_m"] == 250

    def test_neighborhood_blur_uses_venue_blur_radius(self):
        v = self._make_venue(
            privacy_mode="neighborhood_blur",
            blur_radius_m=500,
        )
        feature = venue_to_geojson(v)
        assert feature["properties"]["blur_radius_m"] == 500

    def test_private_has_no_geometry(self):
        v = self._make_venue(
            slug="private-venue",
            latitude=Decimal("52.5"),
            longitude=Decimal("13.4"),
            privacy_mode="private",
            blur_radius_m=1000,
        )
        feature = venue_to_geojson(v)
        assert feature is not None
        assert feature["geometry"] is None
        assert feature["properties"]["privacy"] == "private"
        assert feature["properties"]["blur_radius_m"] == 1000
        assert "fake_center" in feature["properties"]

    def test_private_fake_center_is_deterministic(self):
        v = self._make_venue(
            slug="my-slug",
            latitude=Decimal("52.5"),
            longitude=Decimal("13.4"),
            privacy_mode="private",
        )
        f1 = venue_to_geojson(v)
        f2 = venue_to_geojson(v)
        assert f1["properties"]["fake_center"] == f2["properties"]["fake_center"]

    def test_private_fake_center_differs_from_real_coords(self):
        v = self._make_venue(
            slug="my-slug",
            latitude=Decimal("52.500000"),
            longitude=Decimal("13.400000"),
            privacy_mode="private",
        )
        feature = venue_to_geojson(v)
        fake_lng, fake_lat = feature["properties"]["fake_center"]
        # Should not equal exact coords
        assert fake_lat != 52.5 or fake_lng != 13.4

    def test_private_fake_center_within_reasonable_range(self):
        """Fake center must stay within ~1.5km of real location."""
        v = self._make_venue(
            slug="range-test",
            latitude=Decimal("52.500000"),
            longitude=Decimal("13.400000"),
            privacy_mode="private",
        )
        feature = venue_to_geojson(v)
        fake_lng, fake_lat = feature["properties"]["fake_center"]
        # Max offset is 0.018 lat and 0.025 lng
        assert abs(fake_lat - 52.5) <= 0.018
        assert abs(fake_lng - 13.4) <= 0.025
