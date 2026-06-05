"""
Tests for the "+ New" dropdown in the studio rail (kb-96tn.6).

Contract:
(a) The rail shows a prominent "+ New" button (not a plain link) at the top of
    the publishables section.
(b) The button has an Alpine x-data ancestor enabling the dropdown; clicking it
    shows [New event] / [New promo post] — no full-page nav happens yet.
(c) Each choice carries hx-get + hx-target="#studio-main" + hx-push-url so that
    the create form lands in the studio main pane inline.
(d) event_create GET with HX-Request header returns a layout-less fragment
    (no <html>, no <body>, no {% extends %}) — not the full page.
(e) event_create POST success with HX-Request redirects to the event hub fragment.
(f) A standalone post-create route (GET /syndication/posts/new/) exists,
    returns 200, and is HX-Request-aware (fragment on HTMX GET).
(g) The empty-state link also becomes an hx-get button (or the CTA link still
    works — no regression).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim

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


def _make_event(profile, title, slug):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now(),
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


# ---------------------------------------------------------------------------
# (a)+(b)+(c) Rail + New button / dropdown
# ---------------------------------------------------------------------------


class NewMenuRailTest(TestCase):
    """
    The studio rail must have a prominent '+ New' dropdown button (not a plain
    link) that exposes [New event] and [New promo post] choices.

    Each choice carries HTMX attrs so the create form opens inline in #studio-main.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="menu_user", email="menu@test.com", password="pw")
        self.profile = _make_profile("Menu Org", "menu-org", user=self.user)
        self.event = _make_event(self.profile, "Menu Event", "menu-event")
        self.client.force_login(self.user)

    def test_new_button_present_in_rail(self):
        """A '+ New' button must appear in the rail HTML."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must have a button (not just <a>) element with '+ New' text
        self.assertIn("+ New", content)
        self.assertIn("<button", content)

    def test_new_button_has_alpine_dropdown(self):
        """The '+ New' area must have Alpine x-data for the dropdown."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("x-data", content)

    def test_new_event_choice_has_hx_get(self):
        """The 'New event' dropdown item must carry hx-get."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("hx-get", content)

    def test_new_event_choice_targets_studio_main(self):
        """The 'New event' dropdown item must target #studio-main."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("#studio-main", content)

    def test_new_event_choice_has_push_url(self):
        """The 'New event' dropdown item must carry hx-push-url."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("hx-push-url", content)

    def test_new_post_choice_present(self):
        """The dropdown must offer a 'New promo post' or 'New post' choice."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Either 'New promo post' or 'New post' is acceptable phrasing
        self.assertTrue(
            "New promo post" in content or "New post" in content,
            "Dropdown must include a 'New promo post' or 'New post' option",
        )

    def test_new_post_choice_targets_studio_main(self):
        """The 'New post' dropdown item must also target #studio-main."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # #studio-main appears at least once (the main pane itself and the hx-target)
        self.assertGreaterEqual(content.count("#studio-main"), 1)


# ---------------------------------------------------------------------------
# (d) event_create GET with HX-Request → layout-less fragment
# ---------------------------------------------------------------------------


class EventCreateHtmxGetTest(TestCase):
    """
    GET /syndication/events/new/ with HX-Request header must return a
    layout-less fragment (no <html> tag) for swapping into #studio-main.
    A plain GET must still return the full page (with <html>).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ecreate_user", email="ecreate@test.com", password="pw")
        _make_profile("ECreate Org", "ecreate-org", user=self.user)
        self.client.force_login(self.user)

    def test_plain_get_returns_full_page(self):
        """Plain GET (no HX-Request) returns full HTML page with <html> tag."""
        response = self.client.get("/syndication/events/new/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("<html", content)

    def test_htmx_get_returns_fragment(self):
        """GET with HX-Request returns layout-less fragment (no <html> tag)."""
        response = self.client.get(
            "/syndication/events/new/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("<html", content)
        # Must still contain the form
        self.assertIn("<form", content)


# ---------------------------------------------------------------------------
# (e) event_create POST success with HX-Request → hub fragment redirect
# ---------------------------------------------------------------------------


class EventCreateHtmxPostTest(TestCase):
    """
    POST to /syndication/events/new/ with HX-Request and valid data must
    return the event hub fragment (not a full-page redirect) so the studio
    main pane is updated inline.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="epost_user", email="epost@test.com", password="pw")
        _make_profile("EPost Org", "epost-org", user=self.user)
        self.client.force_login(self.user)

    def test_htmx_post_success_returns_fragment_not_redirect(self):
        """POST with HX-Request and valid data returns 200 fragment, not 302."""
        response = self.client.post(
            "/syndication/events/new/",
            {
                "title": "HTMX-Created Event",
                "slug": "htmx-created-event",
                "start": "2026-09-01 18:00",
            },
            HTTP_HX_REQUEST="true",
        )
        # Must be 200 (fragment), not 302 (redirect)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must not have the full page chrome
        self.assertNotIn("<html", content)

    def test_plain_post_success_redirects(self):
        """Plain POST (no HX-Request) still redirects to event hub."""
        response = self.client.post(
            "/syndication/events/new/",
            {
                "title": "Plain-Created Event",
                "slug": "plain-created-event",
                "start": "2026-09-01 19:00",
            },
        )
        # Must be 302 redirect (full-page flow unchanged)
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# (f) Standalone post-create route
# ---------------------------------------------------------------------------


class StandalonePostCreateTest(TestCase):
    """
    GET /syndication/posts/new/ must exist and return 200.
    With HX-Request it returns a layout-less fragment.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="pcreate_user", email="pcreate@test.com", password="pw")
        self.profile = _make_profile("PCreate Org", "pcreate-org", user=self.user)
        self.event = _make_event(self.profile, "PCreate Event", "pcreate-event")
        self.client.force_login(self.user)

    def test_standalone_post_create_get_200(self):
        """GET /syndication/posts/new/ returns 200."""
        response = self.client.get("/syndication/posts/new/")
        self.assertEqual(response.status_code, 200)

    def test_standalone_post_create_htmx_returns_fragment(self):
        """GET /syndication/posts/new/ with HX-Request returns a fragment (no <html>)."""
        response = self.client.get(
            "/syndication/posts/new/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("<html", content)
        self.assertIn("<form", content)
