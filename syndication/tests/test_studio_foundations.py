"""
Studio backend foundations tests (kb-9f1h.1).

Three contract groups:
(a) get_publishables_for_profile — merged Event+Post sorted updated_at desc,
    no visibility filter (owner always sees their own assets, ADR-012).
(b) user_primary_profile context processor — returns Profile for claimant,
    None (not raise) for non-claimant.
(c) /studio/ view — 200 for claimant, 403/redirect for zero-claims user.

canonical_refs:
- ADR-008 D2 (no UNION/pagination at V0), D3 (zero-claims fail-loud)
- ADR-012 (visibility does NOT gate owner-management)
- ADR-014 D1 (ProfileClaim presence = claimant)
"""

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(profile, title, slug, updated_at=None):
    """Create an Event and link it to a profile via EventOrganizer."""
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now(),
    )
    EventOrganizer.objects.create(
        event=event,
        profile=profile,
        is_primary=True,
    )
    if updated_at is not None:
        Event.objects.filter(pk=event.pk).update(updated_at=updated_at)
        event.refresh_from_db()
    return event


def _make_post(event, headline, updated_at=None):
    """Create a Post for an Event."""
    post = Post.objects.create(
        event=event,
        headline=headline,
        body="test body",
    )
    if updated_at is not None:
        Post.objects.filter(pk=post.pk).update(updated_at=updated_at)
        post.refresh_from_db()
    return post


# ---------------------------------------------------------------------------
# (a) get_publishables_for_profile
# ---------------------------------------------------------------------------


class GetPublishablesForProfileTest(TestCase):
    """
    Unit tests for get_publishables_for_profile(profile).

    Asserts:
    - Returns a merged list of Events and Posts belonging to the profile.
    - Sorted by updated_at descending.
    - NON-public/unlisted publishables are included (no visibility filter).
    """

    def setUp(self):
        self.user = _make_user(username="pub_user", email="pub@test.com", password="pw")
        self.profile = _make_profile("Pub Organizer", "pub-organizer", user=self.user)

    def test_returns_merged_events_and_posts_sorted_by_updated_at_desc(self):
        """
        Merged list is sorted updated_at desc; Events and Posts both appear.
        """
        from syndication.services import get_publishables_for_profile

        older_time = timezone.now().replace(microsecond=0) - timezone.timedelta(hours=2)
        newer_time = timezone.now().replace(microsecond=0) - timezone.timedelta(hours=1)

        event = _make_event(self.profile, "Test Event A", "test-event-a", updated_at=older_time)
        _post = _make_post(event, "Test Post A", updated_at=newer_time)

        result = get_publishables_for_profile(self.profile)

        # Both appear
        titles = [getattr(p, "title", None) or getattr(p, "headline", None) for p in result]
        self.assertIn("Test Event A", titles)
        self.assertIn("Test Post A", titles)

        # Sorted newest first: the post (newer_time) should come before the event (older_time)
        result_updated = [p.updated_at for p in result]
        self.assertEqual(
            result_updated,
            sorted(result_updated, reverse=True),
            "Publishables must be sorted by updated_at descending.",
        )
        # Post (newer) is first
        first_headline = getattr(result[0], "title", None) or getattr(result[0], "headline", None)
        self.assertEqual(first_headline, "Test Post A")

    def test_non_public_publishable_appears_in_list(self):
        """
        A NON-public (unlisted) Event still appears — no visibility filter.
        Pins the ADR-012 no-filter guarantee: visibility is a public-render
        concept and must NOT gate owner-management.
        """
        from syndication.services import get_publishables_for_profile

        # Create an unlisted event (non-public visibility)
        unlisted_event = Event.objects.create(
            title="Unlisted Event",
            slug="unlisted-event",
            start=timezone.now(),
            visibility="unlisted",
        )
        EventOrganizer.objects.create(
            event=unlisted_event,
            profile=self.profile,
            is_primary=True,
        )

        result = get_publishables_for_profile(self.profile)

        titles = [getattr(p, "title", None) or getattr(p, "headline", None) for p in result]
        self.assertIn(
            "Unlisted Event",
            titles,
            "An unlisted Event must appear in the owner's publishables list — "
            "no visibility filter may gate owner-management (ADR-012).",
        )

    def test_returns_empty_list_for_profile_with_no_publishables(self):
        """Profile with no Events or Posts returns an empty list."""
        from syndication.services import get_publishables_for_profile

        empty_profile = _make_profile("Empty Org", "empty-org")
        result = get_publishables_for_profile(empty_profile)
        self.assertEqual(list(result), [])

    def test_only_own_publishables_returned(self):
        """
        Publishables from another profile do NOT appear in this profile's list.
        """
        from syndication.services import get_publishables_for_profile

        other_user = _make_user(username="other_user", email="other@test.com", password="pw")
        other_profile = _make_profile("Other Org", "other-org", user=other_user)
        _make_event(other_profile, "Other Profile Event", "other-profile-event")

        result = get_publishables_for_profile(self.profile)
        titles = [getattr(p, "title", None) or getattr(p, "headline", None) for p in result]
        self.assertNotIn("Other Profile Event", titles)


# ---------------------------------------------------------------------------
# (b) user_primary_profile context processor
# ---------------------------------------------------------------------------


class UserPrimaryProfileProcessorTest(TestCase):
    """
    Tests for user_primary_profile context processor.

    Asserts:
    - Returns the Profile for a claimant user.
    - Returns None (does NOT raise) for a non-claimant user.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_profile_for_claimant(self):
        """Context processor returns the claimant's primary Profile."""
        from a_core.context_processors import user_primary_profile

        user = _make_user(username="cp_claimant", email="cp_claimant@test.com", password="pw")
        profile = _make_profile("CP Organizer", "cp-organizer", user=user)

        request = self.factory.get("/")
        request.user = user

        ctx = user_primary_profile(request)

        self.assertIn("user_primary_profile", ctx)
        self.assertEqual(ctx["user_primary_profile"], profile)

    def test_returns_none_for_non_claimant(self):
        """
        Context processor returns None for a user with no ProfileClaim.
        MUST NOT raise (raising would break template rendering on every page).
        """
        from a_core.context_processors import user_primary_profile

        non_claimant = _make_user(username="cp_noclaim", email="cp_noclaim@test.com", password="pw")

        request = self.factory.get("/")
        request.user = non_claimant

        # Must not raise — that's the critical contract
        ctx = user_primary_profile(request)

        self.assertIn("user_primary_profile", ctx)
        self.assertIsNone(
            ctx["user_primary_profile"],
            "Context processor must return None for a non-claimant user, never raise.",
        )

    def test_returns_none_for_anonymous_user(self):
        """
        Context processor returns None for an anonymous user.
        Anonymous users are never claimants.
        """
        from django.contrib.auth.models import AnonymousUser

        from a_core.context_processors import user_primary_profile

        request = self.factory.get("/")
        request.user = AnonymousUser()

        ctx = user_primary_profile(request)

        self.assertIn("user_primary_profile", ctx)
        self.assertIsNone(ctx["user_primary_profile"])


# ---------------------------------------------------------------------------
# (c) /studio/ view — authz invariant
# ---------------------------------------------------------------------------


class StudioViewAuthzTest(TestCase):
    """
    AUTHZ invariant tests for the /studio/ view.

    Asserts:
    - A claimant gets 200.
    - A zero-claims user gets 403 or a redirect (fail loud, ADR-008 D3).

    Note: does NOT assert response.context['publishables'] — that is a hollow-
    test trap and .3/.4's concern. This test pins only the status-code authz
    invariant.
    """

    def setUp(self):
        self.client = Client()

    def test_claimant_gets_200(self):
        """A claimant user hitting /studio/ gets HTTP 200."""
        user = _make_user(username="studio_claimant", email="sc@test.com", password="pw")
        _make_profile("Studio Org", "studio-org", user=user)
        self.client.force_login(user)

        response = self.client.get("/studio/")

        self.assertEqual(
            response.status_code,
            200,
            "A claimant user must get 200 from /studio/.",
        )

    def test_zero_claims_user_gets_styled_403(self):
        """
        A zero-claims user hitting /studio/ gets a 403 rendered via the styled
        403 template (navbar/footer + go-back affordance), never a synthesized
        empty 200 (ADR-008 D3 — fail loud) and never a bare unstyled string.

        Asserts on response.content (not just status / context) so a regression
        back to HttpResponseForbidden("...") is caught — see bd memory
        django-view-test-context-vs-content-hollow.
        """
        user = _make_user(username="studio_noclaim", email="snc@test.com", password="pw")
        # No ProfileClaim created
        self.client.force_login(user)

        response = self.client.get("/studio/")

        self.assertEqual(
            response.status_code,
            403,
            "A zero-claims user must get 403 from /studio/ — never a synthesized empty 200 (ADR-008 D3).",
        )
        self.assertTemplateUsed(
            response,
            "syndication/403.html",
            "The studio zero-claims 403 must render the styled 403 template, not a bare HttpResponseForbidden string.",
        )
        content = response.content.decode()
        # Styled-template markers (the bare-string response has none of these)
        self.assertIn("403", content)
        self.assertIn("Go back", content)
        self.assertIn("profile claim", content)

    def test_unauthenticated_user_gets_redirect(self):
        """An unauthenticated user is redirected (to login)."""
        response = self.client.get("/studio/")

        self.assertIn(
            response.status_code,
            [302, 301],
            "An unauthenticated user must be redirected from /studio/.",
        )
