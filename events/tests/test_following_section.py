"""Tests for following-as-filter on /events/ (bead kb-wdh0.3).

D5: "From organizers you follow" section removed. Following is now a
?filter=following query param (sidebar toggle). The view no longer
computes `following_events`; the section heading is gone. This file
tests the surviving invariants:

- The old section heading is absent from all responses.
- `following_events` is not in the context (deleted per ADR-008 D1).
- ?filter=following in pagination/sort links is preserved via
  filter_query_string / pagination_query_string.
- ?filter=following returns only events from followed organizers.
- Anonymous ?filter=following returns empty.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Follow, Profile

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(username, status="vouched"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
    )
    user.status = status
    user.save()
    return user


def _make_organizer(slug, status="approved", hidden=False):
    return Profile.objects.create(
        name=f"Organizer {slug}",
        slug=slug,
        status=status,
        hidden=hidden,
    )


def _make_event(organizer, slug, start_delta_days, status="published", hidden=False):
    now = timezone.now()
    start = now + timedelta(days=start_delta_days)
    return Event.objects.create(
        title=f"Event {slug}",
        slug=slug,
        organizer=organizer,
        status=status,
        start=start,
        hidden=hidden,
    )


# ---------------------------------------------------------------------------
# Section removed: heading must not appear anywhere
# ---------------------------------------------------------------------------


class FollowingSectionAbsentTest(TestCase):
    """'From organizers you follow' section is deleted; heading never appears."""

    def test_anon_no_following_section(self):
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "From organizers you follow")

    def test_anon_following_events_not_in_context(self):
        """following_events was deleted from context (ADR-008 D1)."""
        response = self.client.get("/events/")
        self.assertNotIn("following_events", response.context)

    def test_authed_no_following_section(self):
        user = _make_user("fsauth")
        org = _make_organizer("fsauth-org")
        Follow.objects.create(user=user, profile=org)
        _make_event(org, "fsauth-ev", start_delta_days=3)
        self.client.force_login(user)
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "From organizers you follow")

    def test_authed_following_events_not_in_context(self):
        """following_events is deleted from context even when user has follows."""
        user = _make_user("fsauth2")
        org = _make_organizer("fsauth2-org")
        Follow.objects.create(user=user, profile=org)
        _make_event(org, "fsauth2-ev", start_delta_days=3)
        self.client.force_login(user)
        response = self.client.get("/events/")
        self.assertNotIn("following_events", response.context)


# ---------------------------------------------------------------------------
# ?filter=following preserved in pagination query string
# ---------------------------------------------------------------------------


class FollowingFilterPreservedTest(TestCase):
    """filter=following is preserved in filter_query_string / pagination_query_string."""

    def setUp(self):
        self.user = _make_user("fqparam")
        self.client.force_login(self.user)

    def test_filter_following_in_filter_query_string(self):
        """filter_query_string contains filter=following when ?filter=following is active."""
        response = self.client.get("/events/?filter=following")
        self.assertEqual(response.status_code, 200)
        qs = response.context.get("filter_query_string", "")
        self.assertIn("filter=following", qs)

    def test_filter_following_in_pagination_query_string(self):
        """pagination_query_string contains filter=following so pagination keeps it."""
        response = self.client.get("/events/?filter=following")
        self.assertEqual(response.status_code, 200)
        qs = response.context.get("pagination_query_string", "")
        self.assertIn("filter=following", qs)

    def test_no_filter_not_in_query_strings(self):
        """Without ?filter=following, filter param is absent from query strings."""
        response = self.client.get("/events/")
        filter_qs = response.context.get("filter_query_string", "")
        pagination_qs = response.context.get("pagination_query_string", "")
        self.assertNotIn("filter=following", filter_qs)
        self.assertNotIn("filter=following", pagination_qs)


# ---------------------------------------------------------------------------
# ?filter=following filters the main list
# ---------------------------------------------------------------------------


class FollowingFilterParamTest(TestCase):
    """?filter=following on /events/ returns only events from followed organizers."""

    def setUp(self):
        self.user = _make_user("followparam")
        self.client.force_login(self.user)
        self.org = _make_organizer("follow-param-org")
        Follow.objects.create(user=self.user, profile=self.org)
        self.other_org = _make_organizer("follow-param-other-org")

    def test_filter_following_includes_followed_org_events(self):
        """?filter=following includes events from followed org in main page_obj."""
        event = _make_event(self.org, "fp-ev1", start_delta_days=3)
        response = self.client.get("/events/?filter=following")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        self.assertIn(event.pk, page_pks)

    def test_filter_following_excludes_non_followed_org_events(self):
        """?filter=following excludes events from orgs the user does not follow."""
        other_event = _make_event(self.other_org, "fp-other-ev1", start_delta_days=3)
        response = self.client.get("/events/?filter=following")
        page_pks = [e.pk for e in response.context["page_obj"]]
        self.assertNotIn(other_event.pk, page_pks)

    def test_filter_following_anon_returns_empty(self):
        """Anonymous ?filter=following returns 200 with empty list."""
        _make_event(self.org, "fp-anon-ev1", start_delta_days=3)
        self.client.logout()
        response = self.client.get("/events/?filter=following")
        self.assertEqual(response.status_code, 200)
        page_pks = [e.pk for e in response.context["page_obj"]]
        self.assertEqual(page_pks, [])
