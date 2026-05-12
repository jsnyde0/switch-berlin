"""Tests for lowest_rated and most_reviewed event sort variants on the organizer
detail page (bead kb-dwb).

TDD: written BEFORE the implementation.

Covers:
- ?event_sort=lowest_rated: upcoming events ordered by avg_rating asc, nulls last
- ?event_sort=most_reviewed: upcoming events ordered by rating_count desc
- Default event sort (no param) remains chronological (start asc)
- Context 'event_sort' key reflects the chosen sort
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from a_core.models import FeatureFlag
from events.models import Event
from organizers.models import Profile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Profile.objects.create(
        name="Event Sort Org",
        slug="event-sort-org",
        status="approved",
    )


@pytest.fixture
def enable_event_reviews(db):
    """Enable EVENT_REVIEWS_DISPLAYED flag so rating-based sorts are active."""
    cache.clear()
    FeatureFlag.objects.update_or_create(
        key="EVENT_REVIEWS_DISPLAYED", defaults={"enabled": True}
    )


def _make_event(org, slug, days_from_now=1, rating_count=0, avg_rating=None):
    """Create a published, visible, future event with explicit rating fields."""
    now = timezone.now()
    event = Event.objects.create(
        title=f"Event {slug}",
        slug=slug,
        organizer=org,
        status="published",
        start=now + timedelta(days=days_from_now),
    )
    Event.objects.filter(pk=event.pk).update(
        rating_count=rating_count,
        avg_rating=avg_rating,
    )
    event.refresh_from_db()
    return event


# ---------------------------------------------------------------------------
# Tests: ?event_sort=lowest_rated
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_event_sort_lowest_rated_ordering(org, enable_event_reviews):
    """?event_sort=lowest_rated: upcoming events by avg_rating asc, nulls last."""
    event_low = _make_event(org, "es-low", avg_rating=1.0, rating_count=3)
    event_mid = _make_event(org, "es-mid", avg_rating=3.0, rating_count=2)
    event_high = _make_event(org, "es-high", avg_rating=5.0, rating_count=1)
    event_none = _make_event(org, "es-none", avg_rating=None, rating_count=0)

    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=lowest_rated")

    assert resp.status_code == 200
    upcoming_pks = [e.pk for e in resp.context["upcoming_events"]]
    expected = [event_low.pk, event_mid.pk, event_high.pk, event_none.pk]
    assert upcoming_pks == expected


@pytest.mark.django_db
def test_organizer_event_sort_lowest_rated_nulls_last(org, enable_event_reviews):
    """Events with avg_rating=None appear after rated events (lowest_rated sort)."""
    event_rated = _make_event(org, "es-rated", avg_rating=2.0, rating_count=1)
    event_unrated = _make_event(org, "es-unrated", avg_rating=None, rating_count=0)

    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=lowest_rated")

    assert resp.status_code == 200
    upcoming_pks = [e.pk for e in resp.context["upcoming_events"]]
    assert upcoming_pks.index(event_rated.pk) < upcoming_pks.index(event_unrated.pk)


@pytest.mark.django_db
def test_organizer_event_sort_context_key_lowest_rated(org, enable_event_reviews):
    """Context['event_sort'] equals 'lowest_rated' when that param is used."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=lowest_rated")

    assert resp.status_code == 200
    assert resp.context["event_sort"] == "lowest_rated"


# ---------------------------------------------------------------------------
# Tests: ?event_sort=most_reviewed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_event_sort_most_reviewed_ordering(org, enable_event_reviews):
    """?event_sort=most_reviewed: upcoming events ordered by rating_count desc."""
    event_few = _make_event(org, "es2-few", rating_count=2, avg_rating=4.0)
    event_many = _make_event(org, "es2-many", rating_count=20, avg_rating=3.0)
    event_none = _make_event(org, "es2-none", rating_count=0, avg_rating=None)
    event_mid = _make_event(org, "es2-mid", rating_count=10, avg_rating=4.5)

    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=most_reviewed")

    assert resp.status_code == 200
    upcoming_pks = [e.pk for e in resp.context["upcoming_events"]]
    expected = [event_many.pk, event_mid.pk, event_few.pk, event_none.pk]
    assert upcoming_pks == expected


@pytest.mark.django_db
def test_organizer_event_sort_context_key_most_reviewed(org, enable_event_reviews):
    """Context['event_sort'] equals 'most_reviewed' when that param is used."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=most_reviewed")

    assert resp.status_code == 200
    assert resp.context["event_sort"] == "most_reviewed"


# ---------------------------------------------------------------------------
# Tests: default sort
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_event_sort_default_is_chronological(org):
    """No ?event_sort param → upcoming events ordered by start ascending."""
    event_first = _make_event(org, "es-def-first", days_from_now=1)
    event_second = _make_event(org, "es-def-second", days_from_now=5)
    event_third = _make_event(org, "es-def-third", days_from_now=10)

    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url)

    assert resp.status_code == 200
    upcoming_pks = [e.pk for e in resp.context["upcoming_events"]]
    expected = [event_first.pk, event_second.pk, event_third.pk]
    assert upcoming_pks == expected


@pytest.mark.django_db
def test_organizer_event_sort_context_key_default(org):
    """No ?event_sort param → context['event_sort'] defaults to 'date'."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url)

    assert resp.status_code == 200
    assert resp.context["event_sort"] == "date"


# ---------------------------------------------------------------------------
# Tests: invalid ?event_sort param normalisation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_invalid_event_sort_returns_200(org):
    """?event_sort=order_by_password returns HTTP 200."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=order_by_password")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_organizer_invalid_event_sort_context_normalised_to_date(org):
    """Context['event_sort'] is normalised to 'date' for an invalid event_sort param."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=order_by_password")
    assert resp.status_code == 200
    assert resp.context["event_sort"] == "date"


@pytest.mark.django_db
def test_organizer_invalid_event_sort_order_is_chronological(org):
    """Invalid ?event_sort falls back to chronological (start ascending) order."""
    event_first = _make_event(org, "inv-first", days_from_now=1)
    event_second = _make_event(org, "inv-second", days_from_now=5)

    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url + "?event_sort=order_by_password")

    assert resp.status_code == 200
    upcoming_pks = [e.pk for e in resp.context["upcoming_events"]]
    expected = [event_first.pk, event_second.pk]
    assert upcoming_pks == expected
