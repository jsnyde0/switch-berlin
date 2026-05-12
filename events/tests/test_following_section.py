"""Tests for the 'From organizers you follow' section on /events/ (bead kb-8qn.5).

TDD: these tests are written BEFORE the implementation.

Covers:
- Anonymous users: section not rendered
- Authenticated with no follows: empty state shown
- Authenticated with follows: section shows events from followed organizers
- Filtering: only published, not hidden, start > now
- Exclusion: suspended organizer or hidden organizer excluded
- Cap: at most 5 events shown
- Order: start ascending (nearest-future first)
- filter=following query param: returns only events from followed organizers
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import OrganizerFollow, Profile

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(username, is_approved=True):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
    )
    user.is_approved = is_approved
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
# Anonymous: no section
# ---------------------------------------------------------------------------


class FollowingSectionAnonymousTest(TestCase):
    """Anonymous users see no 'From organizers you follow' section."""

    def test_anon_no_following_section(self):
        """Anonymous user sees no 'From organizers you follow' text."""
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "From organizers you follow")

    def test_anon_following_events_not_in_context(self):
        """Anonymous request: following_events context is empty list."""
        response = self.client.get("/events/")
        # Should be an empty list (falsy), not a queryset of events
        self.assertFalse(response.context.get("following_events"))


# ---------------------------------------------------------------------------
# Authenticated: empty follows
# ---------------------------------------------------------------------------


class FollowingSectionEmptyTest(TestCase):
    """Authenticated user with no follows sees empty state."""

    def setUp(self):
        self.user = _make_user("followempty")
        self.client.force_login(self.user)

    def test_empty_follow_shows_not_following_state(self):
        """No follows → 'You're not following anyone yet.' shown."""
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not following anyone yet")

    def test_empty_follow_no_events_in_following_context(self):
        """No follows → following_events is empty."""
        response = self.client.get("/events/")
        following = list(response.context.get("following_events", []))
        self.assertEqual(following, [])


# ---------------------------------------------------------------------------
# Authenticated: populated follows
# ---------------------------------------------------------------------------


class FollowingSectionPopulatedTest(TestCase):
    """Authenticated user with follows sees correct events."""

    def setUp(self):
        self.user = _make_user("followpop")
        self.client.force_login(self.user)
        self.org = _make_organizer("follow-pop-org")
        OrganizerFollow.objects.create(user=self.user, organizer=self.org)

    def test_future_published_event_from_followed_org_shown(self):
        """Future published event from followed organizer in following_events."""
        event = _make_event(self.org, "follow-pop-ev1", start_delta_days=3)
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertIn(event.pk, following_pks)

    def test_section_heading_shown_when_events_exist(self):
        """Heading shown when following_events is non-empty."""
        _make_event(self.org, "follow-pop-heading", start_delta_days=3)
        response = self.client.get("/events/")
        self.assertContains(response, "From organizers you follow")

    def test_past_event_from_followed_org_excluded(self):
        """Past events (start < now) not shown in following_events."""
        event = _make_event(self.org, "follow-pop-past", start_delta_days=-2)
        response = self.client.get("/events/")
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertNotIn(event.pk, following_pks)

    def test_hidden_event_from_followed_org_excluded(self):
        """Hidden events excluded from following_events."""
        event = _make_event(
            self.org, "follow-pop-hidden", start_delta_days=3, hidden=True
        )
        response = self.client.get("/events/")
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertNotIn(event.pk, following_pks)

    def test_draft_event_from_followed_org_excluded(self):
        """Non-published events excluded from following_events."""
        event = _make_event(
            self.org, "follow-pop-draft", start_delta_days=3, status="draft"
        )
        response = self.client.get("/events/")
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertNotIn(event.pk, following_pks)


# ---------------------------------------------------------------------------
# Organizer status filtering
# ---------------------------------------------------------------------------


class FollowingSectionOrganizerFilterTest(TestCase):
    """Suspended or hidden organizers excluded from following section."""

    def setUp(self):
        self.user = _make_user("followorgfilter")
        self.client.force_login(self.user)

    def test_suspended_organizer_events_excluded(self):
        """Events from suspended organizer not shown in following_events."""
        org = _make_organizer("follow-suspended-org", status="suspended")
        OrganizerFollow.objects.create(user=self.user, organizer=org)
        event = _make_event(org, "follow-suspended-ev", start_delta_days=5)
        response = self.client.get("/events/")
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertNotIn(event.pk, following_pks)

    def test_hidden_organizer_events_excluded(self):
        """Events from hidden organizer not shown in following_events."""
        org = _make_organizer("follow-hidden-org", hidden=True)
        OrganizerFollow.objects.create(user=self.user, organizer=org)
        event = _make_event(org, "follow-hidden-ev", start_delta_days=5)
        response = self.client.get("/events/")
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertNotIn(event.pk, following_pks)

    def test_approved_visible_organizer_events_shown(self):
        """Events from approved, visible organizer are shown."""
        org = _make_organizer("follow-good-org")
        OrganizerFollow.objects.create(user=self.user, organizer=org)
        event = _make_event(org, "follow-good-ev", start_delta_days=5)
        response = self.client.get("/events/")
        following_pks = [e.pk for e in response.context["following_events"]]
        self.assertIn(event.pk, following_pks)


# ---------------------------------------------------------------------------
# Cap at 5 events
# ---------------------------------------------------------------------------


class FollowingSectionCapTest(TestCase):
    """following_events capped at 5 events."""

    def setUp(self):
        self.user = _make_user("followcap")
        self.client.force_login(self.user)
        self.org = _make_organizer("follow-cap-org")
        OrganizerFollow.objects.create(user=self.user, organizer=self.org)

    def test_cap_at_five_events(self):
        """Even with 8 future events from followed org, only 5 returned."""
        for i in range(8):
            _make_event(
                self.org, f"follow-cap-ev{i}", start_delta_days=i + 1
            )
        response = self.client.get("/events/")
        following = list(response.context["following_events"])
        self.assertLessEqual(len(following), 5)


# ---------------------------------------------------------------------------
# Order: ascending by start
# ---------------------------------------------------------------------------


class FollowingSectionOrderTest(TestCase):
    """following_events ordered by start ascending (nearest first)."""

    def setUp(self):
        self.user = _make_user("followorder")
        self.client.force_login(self.user)
        self.org = _make_organizer("follow-order-org")
        OrganizerFollow.objects.create(user=self.user, organizer=self.org)

    def test_events_ordered_start_ascending(self):
        """Nearest-future event first."""
        _make_event(self.org, "follow-ord-ev3", start_delta_days=10)
        _make_event(self.org, "follow-ord-ev1", start_delta_days=2)
        _make_event(self.org, "follow-ord-ev2", start_delta_days=5)
        response = self.client.get("/events/")
        following = list(response.context["following_events"])
        starts = [e.start for e in following]
        self.assertEqual(starts, sorted(starts))


# ---------------------------------------------------------------------------
# ?filter=following query param
# ---------------------------------------------------------------------------


class FollowingFilterParamTest(TestCase):
    """?filter=following on /events/ returns only events from followed organizers."""

    def setUp(self):
        self.user = _make_user("followparam")
        self.client.force_login(self.user)
        self.org = _make_organizer("follow-param-org")
        OrganizerFollow.objects.create(user=self.user, organizer=self.org)
        self.other_org = _make_organizer("follow-param-other-org")

    def test_filter_following_includes_followed_org_events(self):
        """?filter=following includes events from followed org in main page_obj."""
        event = _make_event(self.org, "fp-ev1", start_delta_days=3)
        response = self.client.get("/events/?filter=following")
        self.assertEqual(response.status_code, 200)
        # Event from followed org should appear in page_obj
        page_pks = [e.pk for e in response.context["page_obj"]]
        self.assertIn(event.pk, page_pks)

    def test_filter_following_excludes_non_followed_org_events(self):
        """?filter=following excludes events from orgs the user does not follow."""
        other_event = _make_event(
            self.other_org, "fp-other-ev1", start_delta_days=3
        )
        response = self.client.get("/events/?filter=following")
        page_pks = [e.pk for e in response.context["page_obj"]]
        self.assertNotIn(other_event.pk, page_pks)

    def test_filter_following_anon_returns_empty(self):
        """Anonymous ?filter=following returns empty or ignores filter (no crash)."""
        _make_event(self.org, "fp-anon-ev1", start_delta_days=3)
        response = self.client.get("/events/?filter=following")
        # Should not crash; returns 200
        self.assertEqual(response.status_code, 200)
