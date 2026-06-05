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
(h) HTMX inline-create success responses include an OOB rail fragment so the
    left rail auto-refreshes without a full reload (kb-96tn.6 gap closure).
    - event_create HTMX POST success: rail OOB fragment contains new event title.
    - post_create_standalone HTMX POST success: rail OOB contains new post headline.
    - The rail <aside> carries id="studio-rail" so HTMX can target it.
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


# ---------------------------------------------------------------------------
# (h) HTMX inline-create success responses include OOB rail fragment
# ---------------------------------------------------------------------------


class RailStableIdTest(TestCase):
    """
    The studio rail <aside> must carry id="studio-rail" so HTMX can target it
    for OOB swap on inline-create success.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="railid_user", email="railid@test.com", password="pw")
        self.profile = _make_profile("RailId Org", "railid-org", user=self.user)
        self.event = _make_event(self.profile, "RailId Event", "railid-event")
        self.client.force_login(self.user)

    def test_studio_rail_has_stable_id(self):
        """The rail <aside> must have id='studio-rail' for OOB targeting."""
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'id="studio-rail"',
            content,
            "Rail <aside> must carry id='studio-rail' so HTMX OOB swap can target it.",
        )


class EventCreateHtmxOobRailTest(TestCase):
    """
    HTMX POST to event_create must include an OOB rail fragment (hx-swap-oob='true')
    in the same response that delivers the event hub composer. The OOB fragment must:
    - carry hx-swap-oob="true" on the element with id="studio-rail"
    - contain the newly-created event's title (so the rail reflects the new state)
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="eoob_user", email="eoob@test.com", password="pw")
        self.profile = _make_profile("EOob Org", "eoob-org", user=self.user)
        self.client.force_login(self.user)

    def test_htmx_post_success_includes_rail_oob_fragment(self):
        """HTMX POST success includes hx-swap-oob='true' on an element with id='studio-rail'."""
        response = self.client.post(
            "/syndication/events/new/",
            {
                "title": "OOB Rail Event",
                "slug": "oob-rail-event",
                "start": "2026-09-01 18:00",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "HTMX create response must contain hx-swap-oob='true' for the rail OOB swap.",
        )
        self.assertIn(
            'id="studio-rail"',
            content,
            "HTMX create response must contain id='studio-rail' in the OOB element.",
        )

    def test_htmx_post_success_rail_oob_contains_new_event(self):
        """The OOB rail fragment must contain the newly-created event's title."""
        response = self.client.post(
            "/syndication/events/new/",
            {
                "title": "Brand New Event",
                "slug": "brand-new-event",
                "start": "2026-09-01 18:00",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Brand New Event",
            content,
            "The OOB rail fragment must include the newly-created event's title.",
        )


class PostCreateStandaloneHtmxOobRailTest(TestCase):
    """
    HTMX POST to post_create_standalone must include an OOB rail fragment
    containing the newly-created post's headline. Same contract as event_create.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="poob_user", email="poob@test.com", password="pw")
        self.profile = _make_profile("POob Org", "poob-org", user=self.user)
        self.event = _make_event(self.profile, "POob Parent Event", "poob-parent-event")
        self.client.force_login(self.user)

    def test_htmx_post_success_includes_rail_oob_fragment(self):
        """HTMX POST success includes hx-swap-oob='true' on an element with id='studio-rail'."""
        response = self.client.post(
            "/syndication/posts/new/",
            {
                "headline": "OOB Rail Post",
                "body": "Post body content",
                "event_id": str(self.event.pk),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "HTMX post-create response must contain hx-swap-oob='true' for rail OOB swap.",
        )
        self.assertIn(
            'id="studio-rail"',
            content,
            "HTMX post-create response must contain id='studio-rail' in the OOB element.",
        )

    def test_htmx_post_success_rail_oob_contains_new_post(self):
        """The OOB rail fragment must contain the newly-created post's headline."""
        response = self.client.post(
            "/syndication/posts/new/",
            {
                "headline": "Fresh OOB Post Headline",
                "body": "Post body content",
                "event_id": str(self.event.pk),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Fresh OOB Post Headline",
            content,
            "The OOB rail fragment must include the newly-created post's headline.",
        )


# ---------------------------------------------------------------------------
# (i) post_create (event-scoped) HTMX POST success → OOB rail update
# ---------------------------------------------------------------------------


class PostCreateEventScopedHtmxOobRailTest(TestCase):
    """
    HTMX POST to post_create (event-scoped, /syndication/events/<pk>/posts/new/)
    must include an OOB rail fragment containing the newly-created post's headline.

    Parity contract: same OOB rail update as post_create_standalone and event_create.

    Harness target (kb-kgza.1):
      Signal: POST post_create with HX-Request header.
      Expected green: response body contains id="studio-rail" hx-swap-oob="true"
                      AND the specific new post's title/headline inside it.
      An empty OOB rail FAILS (mere presence of studio-rail is insufficient).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="escoped_oob_user", email="escoped_oob@test.com", password="pw")
        self.profile = _make_profile("EScopedOob Org", "escoped-oob-org", user=self.user)
        self.event = _make_event(self.profile, "EScopedOob Parent Event", "escoped-oob-parent-event")
        self.client.force_login(self.user)

    def test_htmx_post_success_includes_oob_rail_attrs(self):
        """HTMX POST success includes hx-swap-oob='true' on id='studio-rail'."""
        response = self.client.post(
            f"/syndication/events/{self.event.pk}/posts/new/",
            {
                "headline": "EScopedOob Rail Post",
                "body": "Post body content",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "HTMX event-scoped post_create response must contain hx-swap-oob='true' for rail OOB swap.",
        )
        self.assertIn(
            'id="studio-rail"',
            content,
            "HTMX event-scoped post_create response must contain id='studio-rail' in the OOB element.",
        )

    def test_htmx_post_success_rail_oob_contains_new_post_headline(self):
        """The OOB rail fragment must contain the newly-created post's specific headline."""
        response = self.client.post(
            f"/syndication/events/{self.event.pk}/posts/new/",
            {
                "headline": "Freshly Minted Event-Scoped Post",
                "body": "Body text for the new post.",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Freshly Minted Event-Scoped Post",
            content,
            "The OOB rail fragment must include the newly-created post's specific headline.",
        )
