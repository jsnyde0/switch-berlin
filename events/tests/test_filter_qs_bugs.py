"""Tests for filter query string bugs — bounds in pagination, clear-area safety.

Bug 2: pagination_query_string must include bounds when ?bounds= is active so
       page-2 links preserve the area filter.
Bug 1: filter_query_string must NOT include bounds (clear-area preserves other
       filters, drops only bounds).
Bug 3: _event_list.html must not reference $store.map.selectedKey (removed in store.js).
"""

import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event, Tag
from organizers.models import Profile
from venues.models import Venue

User = get_user_model()

BOUNDS_BERLIN = "52.50,13.38,52.55,13.45"
PRICE_FREE = "free"


class PaginationQueryStringBoundsTest(TestCase):
    """pagination_query_string must include ?bounds= so page links preserve area."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="pqs_staff",
            email="pqs_staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)
        self.organizer = Profile.objects.create(
            name="PQS Org",
            slug="pqs-org",
            status="approved",
        )
        self.venue = Venue.objects.create(
            name="PQS Venue",
            slug="pqs-venue",
            latitude=Decimal("52.52"),
            longitude=Decimal("13.40"),
            privacy_mode="public",
        )
        now = timezone.now()
        for i in range(3):
            Event.objects.create(
                title=f"PQS Event {i}",
                slug=f"pqs-event-{i}",
                organizer=self.organizer,
                venue=self.venue,
                start=now + timezone.timedelta(days=i + 1),
                status="published",
                is_free=True,
            )

    def test_pagination_query_string_includes_bounds_when_active(self):
        """With ?bounds= active, pagination_query_string context var contains bounds."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": PRICE_FREE},
        )
        self.assertEqual(response.status_code, 200)
        pqs = response.context["pagination_query_string"]
        self.assertIn("bounds=", pqs, "pagination_query_string must include bounds param")
        self.assertIn("price=free", pqs, "pagination_query_string must include price param")

    def test_filter_query_string_excludes_bounds(self):
        """filter_query_string (clear-area target) must NOT contain bounds."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": PRICE_FREE},
        )
        self.assertEqual(response.status_code, 200)
        fqs = response.context["filter_query_string"]
        self.assertNotIn("bounds", fqs, "filter_query_string must NOT include bounds (clear-area)")
        self.assertIn("price=free", fqs, "filter_query_string must preserve price filter")

    def test_pagination_links_contain_bounds(self):
        """Rendered page-link hrefs must contain both bounds and price params."""
        # We need >20 events to trigger pagination; create more
        now = timezone.now()
        for i in range(3, 25):
            Event.objects.create(
                title=f"PQS Extra {i}",
                slug=f"pqs-extra-{i}",
                organizer=self.organizer,
                venue=self.venue,
                start=now + timezone.timedelta(days=i + 1),
                status="published",
                is_free=True,
            )

        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": PRICE_FREE},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Pagination links appear as href="?...&page=N"
        # Both bounds and price must appear in any pagination link href
        pagination_hrefs = re.findall(r'href="\?([^"]*page=\d[^"]*)"', content)
        self.assertTrue(
            len(pagination_hrefs) > 0,
            "Expected pagination links when >20 events match bounds+price",
        )
        for href in pagination_hrefs:
            self.assertIn(
                "bounds=",
                href,
                f"Pagination link href must contain bounds; got: ?{href}",
            )
            self.assertIn(
                "price=free",
                href,
                f"Pagination link href must contain price; got: ?{href}",
            )


class ClearAreaQueryStringTest(TestCase):
    """Clear-area control in rendered HTML must preserve non-bounds filters."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="clear_area_staff",
            email="clear_area_staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)
        self.organizer = Profile.objects.create(
            name="CA Org",
            slug="ca-org",
            status="approved",
        )
        self.venue = Venue.objects.create(
            name="CA Venue",
            slug="ca-venue",
            latitude=Decimal("52.52"),
            longitude=Decimal("13.40"),
            privacy_mode="public",
        )
        now = timezone.now()
        Event.objects.create(
            title="CA Event",
            slug="ca-event",
            organizer=self.organizer,
            venue=self.venue,
            start=now + timezone.timedelta(days=1),
            status="published",
            is_free=True,
        )
        self.tag = Tag.objects.create(slug="ca-tag", label="CA Tag", kind="theme")

    def test_clear_area_href_preserves_price_drops_bounds(self):
        """Clear-area link href must contain price= but not bounds=."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": PRICE_FREE},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Find the clear-area link — it appears as 'Clear area' anchor text
        # The href must include price but not bounds
        match = re.search(
            r'href="\?([^"]*)"[^>]*>[\s\S]*?Clear area',
            content,
        )
        self.assertIsNotNone(match, "Clear-area link not found in rendered HTML")
        href_qs = match.group(1)
        self.assertNotIn(
            "bounds", href_qs,
            f"Clear-area href must not contain bounds; got: ?{href_qs}",
        )
        self.assertIn(
            "price=free", href_qs,
            f"Clear-area href must preserve price; got: ?{href_qs}",
        )


class SelectedKeyRemovedFromTemplateTest(TestCase):
    """_event_list.html must not reference $store.map.selectedKey (dead reference)."""

    def test_selected_key_not_in_event_list_template(self):
        """The rendered partial must contain no reference to selectedKey."""
        import os
        # __file__ is events/tests/test_filter_qs_bugs.py
        # repo root is two levels up: events/ -> repo root
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        template_path = os.path.join(repo_root, "templates", "events", "_event_list.html")
        with open(template_path) as f:
            content = f.read()
        self.assertNotIn(
            "selectedKey",
            content,
            "_event_list.html must not reference selectedKey (removed from store.js)",
        )
        self.assertNotIn(
            "kb-card-selected",
            content,
            "_event_list.html must not reference kb-card-selected",
        )
