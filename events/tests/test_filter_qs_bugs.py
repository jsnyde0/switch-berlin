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
        # Find the clear-area link — it appears as '✕ Clear area' inside an <a> tag.
        # Use a tight pattern scoped to the same <a> element to avoid matching
        # sort-tab hrefs that appear earlier in the document and also include bounds.
        match = re.search(
            r'<a\s[^>]*href="\?([^"]*)"[^>]*>[^<]*Clear area',
            content,
        )
        self.assertIsNotNone(match, "Clear-area link not found in rendered HTML")
        href_qs = match.group(1)
        self.assertNotIn(
            "bounds",
            href_qs,
            f"Clear-area href must not contain bounds; got: ?{href_qs}",
        )
        self.assertIn(
            "price=free",
            href_qs,
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


class BoundsPreservedOnFilterFormTest(TestCase):
    """Bug 2a — filter-form submit with ?bounds= active must keep bounds in filtered qs.

    The #filter-form must carry a hidden `bounds` input so submitting any sidebar
    control (tag, price, date, Following) does not silently drop the active area.
    Verified via the view's queryset: only events inside the bounds survive.
    """

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="bounds_form_staff",
            email="bounds_form_staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)
        self.organizer = Profile.objects.create(
            name="BoundsForm Org",
            slug="bounds-form-org",
            status="approved",
        )
        # Venue INSIDE the Berlin bounds
        self.venue_inside = Venue.objects.create(
            name="Inside Venue",
            slug="inside-venue",
            latitude=Decimal("52.52"),
            longitude=Decimal("13.40"),
            privacy_mode="public",
        )
        # Venue OUTSIDE the Berlin bounds
        self.venue_outside = Venue.objects.create(
            name="Outside Venue",
            slug="outside-venue",
            latitude=Decimal("48.00"),  # Munich-ish
            longitude=Decimal("11.00"),
            privacy_mode="public",
        )
        self.tag = Tag.objects.create(slug="bf-tag", label="BF Tag", kind="theme")
        now = timezone.now()
        self.event_inside = Event.objects.create(
            title="Inside Event",
            slug="inside-event",
            organizer=self.organizer,
            venue=self.venue_inside,
            start=now + timezone.timedelta(days=1),
            status="published",
            is_free=True,
        )
        self.event_inside.tags.add(self.tag)
        self.event_outside = Event.objects.create(
            title="Outside Event",
            slug="outside-event",
            organizer=self.organizer,
            venue=self.venue_outside,
            start=now + timezone.timedelta(days=2),
            status="published",
            is_free=True,
        )
        self.event_outside.tags.add(self.tag)

    def test_bounds_plus_tags_filters_to_inside_events_only(self):
        """GET /events/?bounds=...&tags=... returns only events inside the bounds."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "tags": "bf-tag"},
        )
        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        event_slugs = [e.slug for e in page_obj]
        self.assertIn(
            "inside-event",
            event_slugs,
            "Event inside bounds must appear when both bounds and tag filter are active",
        )
        self.assertNotIn(
            "outside-event",
            event_slugs,
            "Event outside bounds must be excluded when bounds filter is active",
        )

    def test_bounds_input_present_in_filter_form_html(self):
        """Rendered list.html must contain a hidden bounds input inside #filter-form."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": "free"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The hidden input must appear somewhere in the filter-form region.
        # A simple substring check is sufficient; it must carry the correct value.
        self.assertIn(
            'name="bounds"',
            content,
            "Hidden bounds input must be present in rendered list.html when bounds is active",
        )
        self.assertIn(
            BOUNDS_BERLIN,
            content,
            "Bounds value must appear in rendered HTML so the form can round-trip it",
        )


class SortTabBoundsPreservationTest(TestCase):
    """Bug 2b — sort-tab hrefs must include ?bounds= when an area is active.

    INVARIANT: the clear-area link (filter_query_string) must NOT contain bounds.
    Only sort-tab hrefs change; the clear-area href is untouched.
    """

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="sort_tab_staff",
            email="sort_tab_staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)
        self.organizer = Profile.objects.create(
            name="SortTab Org",
            slug="sort-tab-org",
            status="approved",
        )
        self.venue = Venue.objects.create(
            name="ST Venue",
            slug="st-venue",
            latitude=Decimal("52.52"),
            longitude=Decimal("13.40"),
            privacy_mode="public",
        )
        now = timezone.now()
        Event.objects.create(
            title="ST Event",
            slug="st-event",
            organizer=self.organizer,
            venue=self.venue,
            start=now + timezone.timedelta(days=1),
            status="published",
            is_free=True,
        )

    def test_sort_tab_hrefs_contain_bounds_when_active(self):
        """Rendered sort-tab hrefs must include bounds= when ?bounds= is in the request."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": "free"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Find all tab hrefs — they are rendered as href="?..." links in the sort group.
        # All tab hrefs that include sort or are the default-sort tab must carry bounds.
        sort_tab_hrefs = re.findall(r'href="\?([^"]*)"[^>]*role="tab"', content)
        # Tabs use <c-kb.tab> which renders an <a role="tab">; look for those.
        # Fall back to looking for any ?-prefixed href near the sort group.
        # The template renders tabs as <a ... href="?..."> so we scan for those.
        if not sort_tab_hrefs:
            # Alternative: scan for href patterns that match sort-tab hrefs
            sort_tab_hrefs = re.findall(
                r'<a[^>]+href="\?([^"]*)"[^>]*>[\s\S]{0,40}(?:Latest|Trending|Lowest|Most reviewed)',
                content,
            )
        self.assertTrue(
            len(sort_tab_hrefs) > 0,
            "Expected sort-tab anchor hrefs in rendered HTML",
        )
        for href_qs in sort_tab_hrefs:
            self.assertIn(
                "bounds=",
                href_qs,
                f"Sort-tab href must include bounds= when area is active; got: ?{href_qs}",
            )

    def test_clear_area_href_does_not_contain_bounds(self):
        """Clear-area link href must NOT contain bounds= (invariant preserved)."""
        response = self.client.get(
            "/events/",
            {"bounds": BOUNDS_BERLIN, "price": "free"},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Find the clear-area anchor: look for 'Clear area' text inside an <a> tag.
        # The text appears as '✕ Clear area' so search for 'Clear area' in the
        # anchor-text region and grab the preceding href on the same tag.
        # Pattern: <a ...href="?..."...>... Clear area ...</a>
        # Use a tight pattern: the href and the tag close together (same <a> tag).
        match = re.search(
            r'<a\s[^>]*href="\?([^"]*)"[^>]*>[^<]*Clear area',
            content,
        )
        self.assertIsNotNone(match, "Clear-area link not found in rendered HTML")
        href_qs = match.group(1)
        self.assertNotIn(
            "bounds",
            href_qs,
            f"Clear-area href must NOT include bounds=; got: ?{href_qs}",
        )
