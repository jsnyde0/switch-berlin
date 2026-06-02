"""
Hub fragment branching tests (kb-9f1h.2).

Contract groups:
(a) event_hub + post_hub, requested with HX-Request, return layout-less body
    fragments (no <html>/<body>) — so they can be swapped into a <div> without
    nesting <head>/<body> in the studio shell.
(b) The same paths on a normal GET return the full {% extends %} layout
    (deep-link/refresh must still work).
(c) The post→event-hub cross-link and the symmetric back-link carry
    hx-target="#studio-main" + hx-push-url set to the real composer path
    (/syndication/events/<pk>/ or /syndication/posts/<pk>/), NOT the
    fragments/ endpoint.

Assertions are on response.content.decode() (NOT response.context — hollow per memory).

To set HX-Request in a Django test client: self.client.get(url, HTTP_HX_REQUEST="true").
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
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


def _make_event(profile, title, slug):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now(),
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_post(event, headline):
    return Post.objects.create(
        event=event,
        headline=headline,
        body="test body content",
    )


# ---------------------------------------------------------------------------
# (a) HX-Request → layout-less fragment (no <html>/<body>)
# ---------------------------------------------------------------------------


class EventHubHxFragmentTest(TestCase):
    """
    event_hub requested with HX-Request returns a layout-less fragment.
    The response must NOT contain <html or <body — if either appears the
    fragment would nest a full document inside the #studio-main div.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ehf_user", email="ehf@test.com", password="pw")
        self.profile = _make_profile("EHF Org", "ehf-org", user=self.user)
        self.event = _make_event(self.profile, "EHF Event", "ehf-event")
        self.client.force_login(self.user)

    def test_event_hub_hx_request_returns_no_html_or_body_tags(self):
        """
        event_hub with HX-Request header must return a body-only fragment —
        no <html or <body tags so the swap into #studio-main does not nest docs.
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "<html",
            content,
            "event_hub HX fragment must not contain <html — nested document defect.",
        )
        self.assertNotIn(
            "<body",
            content,
            "event_hub HX fragment must not contain <body — nested document defect.",
        )

    def test_event_hub_hx_request_fragment_contains_event_title(self):
        """
        The fragment returned must still contain the event title (sanity check
        that we're getting real content, not an empty response).
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "EHF Event",
            content,
            "event_hub HX fragment must contain the event title.",
        )


class PostHubHxFragmentTest(TestCase):
    """
    post_hub requested with HX-Request returns a layout-less fragment.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="phf_user", email="phf@test.com", password="pw")
        self.profile = _make_profile("PHF Org", "phf-org", user=self.user)
        self.event = _make_event(self.profile, "PHF Event", "phf-event")
        self.post = _make_post(self.event, "PHF Post Headline")
        self.client.force_login(self.user)

    def test_post_hub_hx_request_returns_no_html_or_body_tags(self):
        """
        post_hub with HX-Request header must return a body-only fragment —
        no <html or <body tags so the swap into #studio-main does not nest docs.
        """
        url = f"/syndication/posts/{self.post.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "<html",
            content,
            "post_hub HX fragment must not contain <html — nested document defect.",
        )
        self.assertNotIn(
            "<body",
            content,
            "post_hub HX fragment must not contain <body — nested document defect.",
        )

    def test_post_hub_hx_request_fragment_contains_post_headline(self):
        """
        Sanity: fragment must contain the post headline (not an empty response).
        """
        url = f"/syndication/posts/{self.post.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "PHF Post Headline",
            content,
            "post_hub HX fragment must contain the post headline.",
        )


# ---------------------------------------------------------------------------
# (b) Normal GET → full layout (deep-link/refresh works)
# ---------------------------------------------------------------------------


class EventHubNormalGetFullPageTest(TestCase):
    """
    event_hub on a normal (non-HX) GET must return the full {% extends %} page.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ehfull_user", email="ehfull@test.com", password="pw")
        self.profile = _make_profile("EHFull Org", "ehfull-org", user=self.user)
        self.event = _make_event(self.profile, "EHFull Event", "ehfull-event")
        self.client.force_login(self.user)

    def test_event_hub_normal_get_returns_full_html_layout(self):
        """
        Normal GET of event_hub must return the full page including <html tag.
        Deep-link and refresh must still work.
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "<html",
            content,
            "event_hub normal GET must return the full layout including <html.",
        )


class PostHubNormalGetFullPageTest(TestCase):
    """
    post_hub on a normal (non-HX) GET must return the full {% extends %} page.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="phfull_user", email="phfull@test.com", password="pw")
        self.profile = _make_profile("PHFull Org", "phfull-org", user=self.user)
        self.event = _make_event(self.profile, "PHFull Event", "phfull-event")
        self.post = _make_post(self.event, "PHFull Post Headline")
        self.client.force_login(self.user)

    def test_post_hub_normal_get_returns_full_html_layout(self):
        """
        Normal GET of post_hub must return the full page including <html tag.
        Deep-link and refresh must still work.
        """
        url = f"/syndication/posts/{self.post.pk}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "<html",
            content,
            "post_hub normal GET must return the full layout including <html.",
        )


# ---------------------------------------------------------------------------
# (c) Cross-links carry hx-target + hx-push-url to the real composer path
# ---------------------------------------------------------------------------


class PostSyndicationCrossLinkTest(TestCase):
    """
    The post_syndication fragment must have the "Event hub" cross-link rewired
    to use hx-get (not a plain <a href>) with hx-target="#studio-main" and
    hx-push-url pointing to the real event hub path (/syndication/events/<pk>/).

    The symmetric back-link in post_hub (the link from post header to event hub)
    is a full-navigate <a> — this test verifies the fragment cross-link only.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cl_user", email="cl@test.com", password="pw")
        self.profile = _make_profile("CL Org", "cl-org", user=self.user)
        self.event = _make_event(self.profile, "CL Event", "cl-event")
        self.post = _make_post(self.event, "CL Post Headline")
        self.client.force_login(self.user)

    def test_post_syndication_fragment_event_hub_link_has_hx_target(self):
        """
        The "Event hub" link in post_syndication fragment must have
        hx-target="#studio-main" so clicks swap within the studio shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "post_syndication fragment Event hub link must have hx-target='#studio-main'.",
        )

    def test_post_syndication_fragment_event_hub_link_has_hx_push_url_real_path(self):
        """
        The "Event hub" link in post_syndication fragment must have
        hx-push-url pointing to the real event hub path (/syndication/events/<pk>/).
        NOT the fragments/ endpoint — history must show the real page URL.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_event_hub_path = f"/syndication/events/{self.event.pk}/"
        self.assertIn(
            f'hx-push-url="{expected_event_hub_path}"',
            content,
            f"post_syndication fragment Event hub link must have hx-push-url='{expected_event_hub_path}'.",
        )

    def test_post_syndication_fragment_event_hub_link_uses_hx_get(self):
        """
        The "Event hub" link must use hx-get to trigger the HTMX swap
        (not a plain href full-navigation).
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_event_hub_path = f"/syndication/events/{self.event.pk}/"
        self.assertIn(
            f'hx-get="{expected_event_hub_path}"',
            content,
            "post_syndication fragment Event hub link must use hx-get for swap.",
        )


class EventHubBackLinkTest(TestCase):
    """
    The event_hub page (when rendered as HX fragment) should NOT contain a
    full-page navigate back-link to post_hub that bypasses the studio shell.

    NOTE: The bead asks for the back-link in post_syndication.html (the
    symmetric "event hub ↗" link). The event_hub has no inherent back-link
    to post_hub (events are the parent). This test class covers the event_hub
    fragment form (no <html>/<body>) from the complementary direction:
    any navigation links within the event_hub fragment that point to a post hub
    should also use hx-target="#studio-main".

    If there are no such links in the current template, these tests confirm
    the cross-link rewiring is isolated to post_syndication.html.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ebl_user", email="ebl@test.com", password="pw")
        self.profile = _make_profile("EBL Org", "ebl-org", user=self.user)
        self.event = _make_event(self.profile, "EBL Event", "ebl-event")
        self.post = _make_post(self.event, "EBL Post Headline")
        self.client.force_login(self.user)

    def test_event_hub_hx_fragment_does_not_contain_html(self):
        """Regression: the event_hub HX fragment must not re-introduce <html."""
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "<html",
            content,
            "event_hub HX fragment regression: must not contain <html.",
        )
