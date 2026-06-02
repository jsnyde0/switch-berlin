"""Tests for trending sort on /events/ (bead kb-8qn.6).

TDD: written BEFORE the implementation.

Covers:
- ?sort=trending returns events ordered by score descending
  (score = interested_count/days_until_start + attendance_count*2)
- TRENDING_SORT_ENABLED=False: ?sort=trending ignored, chronological order
- TRENDING_SORT_ENABLED=True (default): ?sort=trending honored
- Default sort (no param / sort=date) returns chronological
- Context contains 'sort' and 'trending_enabled' keys
"""

import unittest
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_organizer(slug="trending-sort-org"):
    return Profile.objects.create(
        name=f"Organizer {slug}",
        slug=slug,
        status="approved",
    )


def _make_event(organizer, slug, start_days_from_now, interested=0, attendance=0):
    """Create a published visible future event with explicit counts."""
    now = timezone.now()
    event = Event.objects.create(
        title=f"Event {slug}",
        slug=slug,
        organizer=organizer,
        status="published",
        start=now + timedelta(days=start_days_from_now),
    )
    # Set denormalised counts directly (bypass signals/managers)
    Event.objects.filter(pk=event.pk).update(
        interested_count=interested,
        attendance_count=attendance,
    )
    event.refresh_from_db()
    return event


# ---------------------------------------------------------------------------
# Fixture: 5 events with varied counts + dates
# ---------------------------------------------------------------------------


@unittest.skipIf(
    connection.vendor == "sqlite",
    "TrendingSortOrderingTest uses EXTRACT(EPOCH FROM ...) PostgreSQL syntax in the "
    "trending sort query. Not supported in SQLite. Run under default Postgres settings.",
)
class TrendingSortOrderingTest(TestCase):
    """?sort=trending returns events in descending trending-score order."""

    def setUp(self):
        self.org = _make_organizer("ts-order-org")
        # Event scores (approx, days_until_start floored to 1):
        #   A: interested=10, days=2, attendance=0  → 10/2 + 0  = 5.0
        #   B: interested=0,  days=1, attendance=5  → 0/1 + 10  = 10.0
        #   C: interested=20, days=10, attendance=1 → 20/10 + 2 = 4.0
        #   D: interested=0,  days=5, attendance=0  → 0/5 + 0   = 0.0
        #   E: interested=5,  days=1, attendance=3  → 5/1 + 6   = 11.0
        # Expected order: E > B > A > C > D
        self.event_a = _make_event(self.org, "ts-a", 2, interested=10, attendance=0)
        self.event_b = _make_event(self.org, "ts-b", 1, interested=0, attendance=5)
        self.event_c = _make_event(self.org, "ts-c", 10, interested=20, attendance=1)
        self.event_d = _make_event(self.org, "ts-d", 5, interested=0, attendance=0)
        self.event_e = _make_event(self.org, "ts-e", 1, interested=5, attendance=3)

    def test_trending_sort_first_result_is_highest_score(self):
        """?sort=trending: first event in page_obj is the highest-score event (E)."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/?sort=trending")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        # E should be first
        self.assertEqual(page_pks[0], self.event_e.pk)

    def test_trending_sort_ordering_matches_score_formula(self):
        """?sort=trending: full order is E > B > A > C > D."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/?sort=trending")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected_order = [
            self.event_e.pk,
            self.event_b.pk,
            self.event_a.pk,
            self.event_c.pk,
            self.event_d.pk,
        ]
        self.assertEqual(page_pks, expected_order)

    def test_sort_context_key_present(self):
        """Context contains 'sort' key equal to request param."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/?sort=trending")
        self.assertIn("sort", response.context)
        self.assertEqual(response.context["sort"], "trending")

    def test_trending_enabled_context_key_present(self):
        """Context contains 'trending_enabled' key."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/?sort=trending")
        self.assertIn("trending_enabled", response.context)
        self.assertTrue(response.context["trending_enabled"])


# ---------------------------------------------------------------------------
# Flag disabled: ?sort=trending ignored
# ---------------------------------------------------------------------------


class TrendingSortFlagDisabledTest(TestCase):
    """TRENDING_SORT_ENABLED=False: ?sort=trending ignored, chronological order."""

    def setUp(self):
        self.org = _make_organizer("ts-flag-off-org")
        # Create events with staggered start dates so chronological order is clear
        self.event_first = _make_event(self.org, "ts-off-first", 1, interested=0, attendance=5)
        self.event_second = _make_event(self.org, "ts-off-second", 3, interested=10, attendance=0)
        self.event_third = _make_event(self.org, "ts-off-third", 7, interested=20, attendance=1)

    def test_flag_disabled_returns_chronological_order(self):
        """With flag=False, ?sort=trending is ignored; order is start ascending."""
        with patch("events.views.get_flag", return_value=False):
            response = self.client.get("/events/?sort=trending")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected_order = [
            self.event_first.pk,
            self.event_second.pk,
            self.event_third.pk,
        ]
        self.assertEqual(page_pks, expected_order)

    def test_flag_disabled_trending_enabled_context_false(self):
        """Context trending_enabled=False when flag is off."""
        with patch("events.views.get_flag", return_value=False):
            response = self.client.get("/events/")
        self.assertFalse(response.context["trending_enabled"])

    def test_flag_disabled_chips_absent(self):
        """When trending_enabled=False, sort=trending chip not rendered in HTML."""
        with patch("events.views.get_flag", return_value=False):
            response = self.client.get("/events/?sort=trending")
        self.assertNotContains(response, "sort=trending")


# ---------------------------------------------------------------------------
# Flag enabled: ?sort=trending honored
# ---------------------------------------------------------------------------


@unittest.skipIf(
    connection.vendor == "sqlite",
    "TrendingSortFlagEnabledTest uses EXTRACT(EPOCH FROM ...) PostgreSQL syntax in the "
    "trending sort query. Not supported in SQLite. Run under default Postgres settings.",
)
class TrendingSortFlagEnabledTest(TestCase):
    """TRENDING_SORT_ENABLED=True: ?sort=trending is honored."""

    def setUp(self):
        self.org = _make_organizer("ts-flag-on-org")
        # Two events: B has much higher score than A
        self.event_a = _make_event(self.org, "ts-on-a", 10, interested=0, attendance=0)
        self.event_b = _make_event(self.org, "ts-on-b", 1, interested=50, attendance=20)

    def test_flag_enabled_trending_sort_honored(self):
        """With flag=True, ?sort=trending sorts B before A."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/?sort=trending")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        self.assertEqual(page_pks[0], self.event_b.pk)

    def test_flag_enabled_trending_enabled_context_true(self):
        """Context trending_enabled=True when flag is on."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/")
        self.assertTrue(response.context["trending_enabled"])


# ---------------------------------------------------------------------------
# Default sort (no param / sort=date)
# ---------------------------------------------------------------------------


class DefaultSortTest(TestCase):
    """Default sort (no param or non-trending param) returns chronological ascending."""

    def setUp(self):
        self.org = _make_organizer("ts-default-org")
        self.event_first = _make_event(self.org, "ts-def-first", 1, interested=100, attendance=100)
        self.event_second = _make_event(self.org, "ts-def-second", 3, interested=0, attendance=0)
        self.event_third = _make_event(self.org, "ts-def-third", 7, interested=50, attendance=10)

    def test_no_sort_param_returns_chronological(self):
        """No ?sort param → start ascending."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected = [self.event_first.pk, self.event_second.pk, self.event_third.pk]
        self.assertEqual(page_pks, expected)

    def test_sort_date_param_returns_chronological(self):
        """?sort=date → start ascending."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/?sort=date")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        expected = [self.event_first.pk, self.event_second.pk, self.event_third.pk]
        self.assertEqual(page_pks, expected)

    def test_default_sort_context_key(self):
        """No ?sort param → context['sort'] defaults to 'date'."""
        with patch("events.views.get_flag", return_value=True):
            response = self.client.get("/events/")
        self.assertEqual(response.context["sort"], "date")
