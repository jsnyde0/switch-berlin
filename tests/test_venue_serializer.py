"""Tests for venues.serializers.venue_to_geojson — privacy enforcement."""

import pytest

from venues.serializers import venue_to_geojson


def _make_venue(**kwargs):
    from venues.models import Venue

    defaults = dict(
        name="Test Venue",
        slug="test-venue-serial",
        latitude="52.520000",
        longitude="13.405000",
        privacy_mode="public",
    )
    defaults.update(kwargs)
    return Venue.objects.create(**defaults)


@pytest.mark.django_db
def test_public_venue_returns_exact_coords():
    venue = _make_venue(
        privacy_mode="public", latitude="52.520008", longitude="13.404954"
    )
    feature = venue_to_geojson(venue)
    assert feature is not None
    coords = feature["geometry"]["coordinates"]
    assert coords == [13.404954, 52.520008]
    assert feature["properties"]["privacy"] == "public"


@pytest.mark.django_db
def test_neighborhood_blur_coords_truncated_to_3_decimals():
    venue = _make_venue(
        privacy_mode="neighborhood_blur",
        latitude="52.520008",
        longitude="13.404954",
        blur_radius_m=250,
    )
    feature = venue_to_geojson(venue)
    assert feature is not None
    lng, lat = feature["geometry"]["coordinates"]
    # Must be exactly 3 decimal places — no more
    assert lat == round(lat, 3)
    assert lng == round(lng, 3)
    assert len(str(lat).split(".")[-1]) <= 3
    assert len(str(lng).split(".")[-1]) <= 3
    assert feature["properties"]["privacy"] == "neighborhood_blur"
    assert feature["properties"]["blur_radius_m"] == 250


@pytest.mark.django_db
def test_private_venue_coords_at_most_3_decimal_places():
    """Private venue fake center must be at most 3 decimal places — regression guard
    against the round(..., 4) bug that briefly leaked too-precise coords."""
    venue = _make_venue(
        slug="private-venue-serial",
        privacy_mode="private",
        latitude="52.520008",
        longitude="13.404954",
    )
    feature = venue_to_geojson(venue)
    assert feature is not None
    lng, lat = feature["geometry"]["coordinates"]
    # Exactly 3dp — ensures the fake center is ambiguous enough
    assert lat == round(lat, 3), f"private lat has >3dp: {lat}"
    assert lng == round(lng, 3), f"private lng has >3dp: {lng}"
    assert feature["properties"]["privacy"] == "private"
    assert feature["properties"]["blur_radius_m"] == 1000


@pytest.mark.django_db
def test_private_venue_fake_center_differs_from_real():
    """The fake center must not equal the real coordinates."""
    venue = _make_venue(
        slug="private-offset-serial",
        privacy_mode="private",
        latitude="52.520000",
        longitude="13.405000",
    )
    feature = venue_to_geojson(venue)
    lng, lat = feature["geometry"]["coordinates"]
    assert (lat, lng) != (52.52, 13.405), "fake center must be offset from real coords"


@pytest.mark.django_db
def test_private_venue_fake_center_is_deterministic():
    """Same venue slug always produces the same fake center (slug-hash derived)."""
    venue = _make_venue(slug="deterministic-serial", privacy_mode="private")
    f1 = venue_to_geojson(venue)
    f2 = venue_to_geojson(venue)
    assert f1["geometry"]["coordinates"] == f2["geometry"]["coordinates"]


@pytest.mark.django_db
def test_venue_missing_coords_returns_none():
    venue = _make_venue(latitude=None, longitude=None)
    assert venue_to_geojson(venue) is None
