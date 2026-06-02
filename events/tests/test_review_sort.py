"""Tests for lowest_rated and most_reviewed sort variants on the events list page.

TDD: written BEFORE the implementation (bead kb-dwb).

Covers:
- ?sort=lowest_rated returns events ordered by avg_rating ascending (nulls last)
- ?sort=most_reviewed returns events ordered by rating_count descending
- Events with no reviews (avg_rating=None) come last in lowest_rated sort
- Context 'sort' key reflects the chosen sort
"""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from a_core.models import FeatureFlag
from events.models import Event
from organizers.models import Profile


def _enable_event_reviews():
    """Flip EVENT_REVIEWS_DISPLAYED=True so rating-based sorts are exposed."""
    cache.clear()
    FeatureFlag.objects.update_or_create(key="EVENT_REVIEWS_DISPLAYED", defaults={"enabled": True})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_organizer(slug="review-sort-org"):
    return Profile.objects.create(
        name=f"Organizer {slug}",
        slug=slug,
        status="approved",
    )


def _make_event(organizer, slug, days_from_now=1, rating_count=0, avg_rating=None):
    """Create a published, visible, future event with explicit rating fields."""
    now = timezone.now()
    event = Event.objects.create(
        title=f"Event {slug}",
        slug=slug,
        organizer=organizer,
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
# Events list: ?sort=lowest_rated
# ---------------------------------------------------------------------------


class LowestRatedSortTest(TestCase):
    """?sort=lowest_rated returns events ordered by avg_rating ascending, nulls last."""

    def setUp(self):
        _enable_event_reviews()
        self.org = _make_organizer("lr-org")
        # avg_rating values:  3.0,  5.0,  1.0,  None (no reviews)
        self.event_mid = _make_event(self.org, "lr-mid", avg_rating=3.0, rating_count=2)
        self.event_high = _make_event(self.org, "lr-high", avg_rating=5.0, rating_count=1)
        self.event_low = _make_event(self.org, "lr-low", avg_rating=1.0, rating_count=3)
        self.event_none = _make_event(self.org, "lr-none", avg_rating=None, rating_count=0)

    def test_lowest_rated_ordering(self):
        """?sort=lowest_rated: order is low(1.0) < mid(3.0) < high(5.0), none last."""
        response = self.client.get("/events/?sort=lowest_rated")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected = [
            self.event_low.pk,
            self.event_mid.pk,
            self.event_high.pk,
            self.event_none.pk,
        ]
        self.assertEqual(page_pks, expected)

    def test_lowest_rated_nulls_last(self):
        """Events with avg_rating=None appear after all rated events."""
        response = self.client.get("/events/?sort=lowest_rated")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        none_idx = page_pks.index(self.event_none.pk)
        rated_indices = [page_pks.index(pk) for pk in [self.event_low.pk, self.event_mid.pk, self.event_high.pk]]
        self.assertTrue(all(none_idx > i for i in rated_indices))

    def test_lowest_rated_context_sort_key(self):
        """Context['sort'] equals 'lowest_rated' when that param is used."""
        response = self.client.get("/events/?sort=lowest_rated")
        self.assertEqual(response.context["sort"], "lowest_rated")


# ---------------------------------------------------------------------------
# Events list: ?sort=most_reviewed
# ---------------------------------------------------------------------------


class MostReviewedSortTest(TestCase):
    """?sort=most_reviewed returns events ordered by rating_count descending."""

    def setUp(self):
        _enable_event_reviews()
        self.org = _make_organizer("mr-org")
        self.event_few = _make_event(self.org, "mr-few", rating_count=2, avg_rating=4.0)
        self.event_many = _make_event(self.org, "mr-many", rating_count=20, avg_rating=3.0)
        self.event_none = _make_event(self.org, "mr-none", rating_count=0, avg_rating=None)
        self.event_mid = _make_event(self.org, "mr-mid", rating_count=10, avg_rating=4.5)

    def test_most_reviewed_ordering(self):
        """?sort=most_reviewed: order is many(20) > mid(10) > few(2) > none(0)."""
        response = self.client.get("/events/?sort=most_reviewed")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected = [
            self.event_many.pk,
            self.event_mid.pk,
            self.event_few.pk,
            self.event_none.pk,
        ]
        self.assertEqual(page_pks, expected)

    def test_most_reviewed_context_sort_key(self):
        """Context['sort'] equals 'most_reviewed' when that param is used."""
        response = self.client.get("/events/?sort=most_reviewed")
        self.assertEqual(response.context["sort"], "most_reviewed")


# ---------------------------------------------------------------------------
# Events list: invalid ?sort param normalisation
# ---------------------------------------------------------------------------


class InvalidSortFallbackTest(TestCase):
    """An unrecognised ?sort value must be silently coerced to 'date'."""

    def setUp(self):
        self.org = _make_organizer("fallback-org")
        self.event_first = _make_event(self.org, "fb-first", days_from_now=1)
        self.event_second = _make_event(self.org, "fb-second", days_from_now=5)

    def test_invalid_sort_returns_200(self):
        """?sort=order_by_password returns HTTP 200."""
        response = self.client.get("/events/?sort=order_by_password")
        self.assertEqual(response.status_code, 200)

    def test_invalid_sort_context_normalised_to_date(self):
        """Context['sort'] is normalised to 'date' for an invalid sort param."""
        response = self.client.get("/events/?sort=order_by_password")
        self.assertEqual(response.context["sort"], "date")

    def test_invalid_sort_order_is_chronological(self):
        """Invalid ?sort falls back to chronological (start ascending) order."""
        response = self.client.get("/events/?sort=order_by_password")
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected = [self.event_first.pk, self.event_second.pk]
        self.assertEqual(page_pks, expected)


# ---------------------------------------------------------------------------
# Events list: rating-based sorts are gated by EVENT_REVIEWS_DISPLAYED
# ---------------------------------------------------------------------------


class RatingSortFlagGateTest(TestCase):
    """With EVENT_REVIEWS_DISPLAYED=False, ?sort=lowest_rated/most_reviewed
    must fall back to 'date' (ADR-002 Non-goals, ADR-005 Bundle A)."""

    def setUp(self):
        # Flag is default False — do NOT enable it. Clear cache so a prior
        # test's enabled-flag state doesn't leak via the 60s TTL.
        cache.clear()
        self.org = _make_organizer("gate-org")
        self.event_a = _make_event(self.org, "gate-a", days_from_now=1)
        self.event_b = _make_event(self.org, "gate-b", days_from_now=5)

    def test_lowest_rated_falls_back_when_flag_off(self):
        response = self.client.get("/events/?sort=lowest_rated")
        self.assertEqual(response.context["sort"], "date")

    def test_most_reviewed_falls_back_when_flag_off(self):
        response = self.client.get("/events/?sort=most_reviewed")
        self.assertEqual(response.context["sort"], "date")

    def test_chips_hidden_when_flag_off(self):
        response = self.client.get("/events/")
        self.assertNotContains(response, "?sort=lowest_rated")
        self.assertNotContains(response, "?sort=most_reviewed")
