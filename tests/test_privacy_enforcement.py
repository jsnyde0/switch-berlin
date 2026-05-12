"""Tests for Attendance model + privacy enforcement (kb-2eu.3).

RED-GREEN-REFACTOR — write failing tests first.
"""
import pytest

from venues.serializers import venue_to_geojson

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_venue(**kwargs):
    from venues.models import Venue

    defaults = dict(
        name="Test Venue",
        slug="privacy-test-venue",
        latitude="52.520000",
        longitude="13.405000",
        privacy_mode="public",
    )
    defaults.update(kwargs)
    return Venue.objects.create(**defaults)


def _make_organizer(**kwargs):
    from organizers.models import Profile

    defaults = dict(
        name="Privacy Org",
        slug="privacy-org",
        status="approved",
    )
    defaults.update(kwargs)
    return Profile.objects.create(**defaults)


def _make_event(organizer, venue=None, **kwargs):
    from datetime import timedelta

    import django.utils.timezone as tz

    from events.models import Event

    defaults = dict(
        title="Privacy Event",
        slug="privacy-event",
        organizer=organizer,
        venue=venue,
        status="published",
        start=tz.now() + timedelta(days=7),
    )
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Attendance model tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_attendance_model_exists():
    """Attendance model can be imported and has expected fields."""
    from events.models import Attendance  # noqa: F401 — tests import succeeds


@pytest.mark.django_db
def test_attendance_can_be_created():
    """An Attendance record can be created linking user, event, and status."""
    from django.contrib.auth import get_user_model

    from events.models import Attendance

    User = get_user_model()
    user = User.objects.create_user("attend_user", "a@example.com", "pw")
    organizer = _make_organizer(slug="att-org")
    event = _make_event(organizer, slug="att-event")

    att = Attendance.objects.create(user=user, event=event, status="going")
    assert att.pk is not None
    assert att.status == "going"
    assert att.user == user
    assert att.event == event


@pytest.mark.django_db
def test_attendance_unique_together():
    """A user can only have one Attendance per event (unique_together constraint)."""
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError

    from events.models import Attendance

    User = get_user_model()
    user = User.objects.create_user("attend_uniq", "uniq@example.com", "pw")
    organizer = _make_organizer(slug="uniq-org")
    event = _make_event(organizer, slug="uniq-event")

    Attendance.objects.create(user=user, event=event, status="interested")
    with pytest.raises(IntegrityError):
        Attendance.objects.create(user=user, event=event, status="going")


@pytest.mark.django_db
def test_attendance_default_status():
    """Default status is 'interested'."""
    from django.contrib.auth import get_user_model

    from events.models import Attendance

    User = get_user_model()
    user = User.objects.create_user("att_default", "def@example.com", "pw")
    organizer = _make_organizer(slug="def-org")
    event = _make_event(organizer, slug="def-event")

    att = Attendance.objects.create(user=user, event=event)
    assert att.status == "interested"


# ---------------------------------------------------------------------------
# venue_to_geojson: going_venue_ids parameter
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_private_venue_blurred_when_going_venue_ids_empty():
    """Private venue returns blurred coords when going_venue_ids is empty frozenset."""
    venue = _make_venue(slug="priv-blur-empty", privacy_mode="private")
    feature = venue_to_geojson(venue, going_venue_ids=frozenset())
    assert feature is not None
    assert feature["properties"]["blur_radius_m"] == 1000
    assert feature["properties"]["privacy"] == "private"


@pytest.mark.django_db
def test_private_venue_exact_when_in_going_venue_ids():
    """Private venue returns exact coords when venue.pk is in going_venue_ids."""
    venue = _make_venue(slug="priv-exact", privacy_mode="private")
    feature = venue_to_geojson(venue, going_venue_ids=frozenset([venue.pk]))
    assert feature is not None
    assert feature["properties"]["blur_radius_m"] is None
    assert feature["properties"]["privacy"] == "private"
    # Exact coords must be returned
    coords = feature["geometry"]["coordinates"]
    assert coords == [float(venue.longitude), float(venue.latitude)]


@pytest.mark.django_db
def test_private_venue_blurred_when_other_venue_in_going_ids():
    """Private venue stays blurred when going_venue_ids has different venue PKs."""
    venue = _make_venue(slug="priv-blur-other", privacy_mode="private")
    feature = venue_to_geojson(venue, going_venue_ids=frozenset([venue.pk + 9999]))
    assert feature is not None
    assert feature["properties"]["blur_radius_m"] == 1000


@pytest.mark.django_db
def test_private_venue_blurred_when_going_venue_ids_none():
    """Backward compat: going_venue_ids=None → blurred (default behavior)."""
    venue = _make_venue(slug="priv-blur-none", privacy_mode="private")
    feature = venue_to_geojson(venue, going_venue_ids=None)
    assert feature is not None
    assert feature["properties"]["blur_radius_m"] == 1000


@pytest.mark.django_db
def test_public_venue_unaffected_by_going_venue_ids():
    """Public venues always return exact coords regardless of going_venue_ids."""
    venue = _make_venue(slug="pub-going", privacy_mode="public")
    feature = venue_to_geojson(venue, going_venue_ids=frozenset())
    assert feature is not None
    assert feature["properties"]["privacy"] == "public"
    assert feature["properties"]["blur_radius_m"] is None


@pytest.mark.django_db
def test_neighborhood_blur_unaffected_by_going_venue_ids():
    """Neighborhood blur venues unaffected by going_venue_ids."""
    venue = _make_venue(
        slug="nb-going",
        privacy_mode="neighborhood_blur",
        blur_radius_m=250,
    )
    feature = venue_to_geojson(venue, going_venue_ids=frozenset([venue.pk]))
    assert feature is not None
    assert feature["properties"]["privacy"] == "neighborhood_blur"


# ---------------------------------------------------------------------------
# in_set template filter
# ---------------------------------------------------------------------------

def test_in_set_filter_returns_true_when_value_in_set():
    from events.templatetags.event_tags import in_set

    assert in_set(5, {5, 6, 7}) is True


def test_in_set_filter_returns_false_when_value_not_in_set():
    from events.templatetags.event_tags import in_set

    assert in_set(99, {5, 6, 7}) is False


def test_in_set_filter_returns_false_when_set_is_none():
    from events.templatetags.event_tags import in_set

    assert in_set(5, None) is False


def test_in_set_filter_returns_false_when_set_is_empty_string():
    """Cotton passes unset props as empty string — must not raise TypeError."""
    from events.templatetags.event_tags import in_set

    assert in_set(5, "") is False


def test_in_set_filter_returns_false_when_set_is_empty_list():
    from events.templatetags.event_tags import in_set

    assert in_set(5, []) is False


def test_in_set_filter_returns_false_when_set_is_empty_frozenset():
    from events.templatetags.event_tags import in_set

    assert in_set(5, frozenset()) is False


def test_in_set_filter_works_with_list():
    from events.templatetags.event_tags import in_set

    assert in_set(3, [1, 2, 3]) is True
