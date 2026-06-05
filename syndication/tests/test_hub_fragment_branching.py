"""
Hub fragment branching tests (kb-9f1h.2 / kb-9f1h.7 / kb-ide0.3).

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
(d) kb-9f1h.7 — context-aware cross-links: the "Event hub ↗" link in
    _post_hub_body.html and post_syndication.html must NOT carry
    hx-target="#studio-main" on standalone pages (no #studio-main in DOM),
    but MUST carry it in the studio context (HX-Request / ?studio=1).
    A standalone click must navigate (href); in-studio it swaps.

Assertions are on response.content.decode() (NOT response.context — hollow per memory).

To set HX-Request in a Django test client: self.client.get(url, HTTP_HX_REQUEST="true").
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, Post

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

    def test_event_hub_hx_request_fragment_has_composer_bar(self):
        """
        kb-96tn.1 / kb-96tn.9: The fragment returned must contain real content.
        The h1 with the event title was removed; the bar (with pills, breadcrumb,
        publish) now lives INSIDE the event_syndication sub-fragment (Option A).
        The hub body shell contains the #event-syndication section which lazy-loads
        the full bar via HTMX. We verify the section anchor is present.
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'id="event-syndication"',
            content,
            "event_hub HX fragment must contain id='event-syndication' "
            "(the lazy-load section that renders the composer bar + pills, kb-96tn.9).",
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

    def test_post_hub_hx_request_fragment_has_composer_bar(self):
        """
        kb-96tn.1 / kb-96tn.9: Fragment must contain real content.
        The h1 with the post headline was removed; the bar (with pills, breadcrumb,
        publish) now lives INSIDE the post_syndication sub-fragment (Option A).
        The hub body shell contains the #post-syndication section which lazy-loads
        the full bar via HTMX. We verify the section anchor is present.
        """
        url = f"/syndication/posts/{self.post.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'id="post-syndication"',
            content,
            "post_hub HX fragment must contain id='post-syndication' "
            "(the lazy-load section that renders the composer bar + pills, kb-96tn.9).",
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
    kb-96tn.1: The "Event Workspace ↗" cross-link was removed from the
    post_syndication fragment. The back-link to the event hub is now the
    breadcrumb in the composer bar (_post_hub_body.html).

    These tests confirm the fragment no longer contains the old link,
    and the hub body provides the correct HTMX-aware breadcrumb.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cl_user", email="cl@test.com", password="pw")
        self.profile = _make_profile("CL Org", "cl-org", user=self.user)
        self.event = _make_event(self.profile, "CL Event", "cl-event")
        self.post = _make_post(self.event, "CL Post Headline")
        self.client.force_login(self.user)

    def test_post_syndication_fragment_has_no_event_workspace_link(self):
        """
        kb-96tn.1: The post_syndication fragment must NOT contain the old
        "Event Workspace ↗" back-link (removed in favour of the bar breadcrumb).
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "Event Workspace",
            content,
            "post_syndication fragment must NOT contain 'Event Workspace' — "
            "the back-link was moved to the composer bar breadcrumb (kb-96tn.1).",
        )

    def test_post_hub_hx_fragment_breadcrumb_has_hx_push_url_real_path(self):
        """
        kb-96tn.1 / kb-96tn.9: The breadcrumb in the post_syndication fragment
        (bar) in the STUDIO CONTEXT (?studio=1) must have hx-push-url pointing
        to the real event hub path (/syndication/events/<pk>/).
        With kb-96tn.9, the breadcrumb lives in post_syndication, not the hub shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_event_hub_path = f"/syndication/events/{self.event.pk}/"
        self.assertIn(
            f'hx-push-url="{expected_event_hub_path}"',
            content,
            f"post_syndication breadcrumb (studio=1) must have hx-push-url='{expected_event_hub_path}' (kb-96tn.1).",
        )

    def test_post_hub_hx_fragment_breadcrumb_uses_hx_get(self):
        """
        kb-96tn.1 / kb-96tn.9: The breadcrumb in the post_syndication fragment
        (bar) in the STUDIO CONTEXT (?studio=1) must use hx-get to trigger the
        HTMX swap within the studio shell.
        With kb-96tn.9, the breadcrumb lives in post_syndication, not the hub shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_event_hub_path = f"/syndication/events/{self.event.pk}/"
        self.assertIn(
            f'hx-get="{expected_event_hub_path}"',
            content,
            "post_syndication breadcrumb (studio=1) must use hx-get for swap (kb-96tn.1).",
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


# ---------------------------------------------------------------------------
# (d) kb-9f1h.7 — context-aware cross-links (standalone vs in-studio)
# ---------------------------------------------------------------------------


class PostHubStandaloneCrossLinkTest(TestCase):
    """
    kb-9f1h.7: The "Event hub ↗" back-link in _post_hub_body.html must NOT
    carry hx-target="#studio-main" when rendered on the standalone full page
    (normal GET at /syndication/posts/<pk>/ — no studio shell present).

    In the standalone context #studio-main does not exist; HTMX intercepts
    the click and fires htmx:targetError → silent no-op. This is an ADR-008
    D3 violation (silent fallback). The fix: gate the HTMX swap attrs on
    studio_swap context flag; standalone renders a plain navigable <a href>.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="phsa_user", email="phsa@test.com", password="pw")
        self.profile = _make_profile("PHSA Org", "phsa-org", user=self.user)
        self.event = _make_event(self.profile, "PHSA Event", "phsa-event")
        self.post = _make_post(self.event, "PHSA Post Headline")
        self.client.force_login(self.user)

    def test_standalone_post_hub_renders_studio_shell_with_studio_main(self):
        """
        kb-shzi.2: The standalone post_hub page (normal GET — no HX-Request header)
        now renders the studio two-pane shell, so id="studio-main" EXISTS on the page.

        This supersedes the old test that asserted hx-target="#studio-main" was absent
        (because the standalone page had no studio shell). After kb-shzi.2, the standalone
        page IS the studio shell, so:
        1. id="studio-main" is present (the shell is rendered)
        2. hx-target="#studio-main" on internal links is NOW safe/correct (the target exists)

        The old premise ("no studio shell on this page") no longer holds.
        """
        url = f"/syndication/posts/{self.post.pk}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The standalone page now has the studio shell with #studio-main
        self.assertIn(
            'id="studio-main"',
            content,
            "kb-shzi.2: Standalone post_hub must now render id='studio-main' — "
            "the standalone page IS the studio shell after this fix.",
        )

    def test_standalone_post_hub_cross_link_has_plain_href(self):
        """
        The standalone post_syndication fragment (without ?studio=1) breadcrumb
        must include a plain href pointing to the event hub URL for correct navigation.
        With kb-96tn.9, the breadcrumb lives in post_syndication, not the hub shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_event_hub_path = f"/syndication/events/{self.event.pk}/"
        self.assertIn(
            f'href="{expected_event_hub_path}"',
            content,
            "post_syndication breadcrumb (no studio) must have plain href for navigation (kb-96tn.9).",
        )

    def test_studio_fragment_post_hub_cross_link_has_hx_target_studio_main(self):
        """
        The post_syndication fragment with ?studio=1 (in-studio context)
        MUST render hx-target="#studio-main" on the "Event hub" breadcrumb link —
        the in-studio swap behavior must be preserved.
        With kb-96tn.9, the breadcrumb lives in post_syndication, not the hub shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "post_syndication (studio=1) MUST have hx-target='#studio-main' on the breadcrumb link "
            "so the studio swap works (kb-96tn.9).",
        )


class PostSyndicationStudioContextTest(TestCase):
    """
    kb-9f1h.7: The "Event hub ↗" link in post_syndication.html must be
    context-aware:
    - Without ?studio=1 (standalone context): no hx-target="#studio-main"
      → plain navigable <a href>
    - With ?studio=1 (in-studio context): hx-target="#studio-main" present
      → HTMX swap within the studio shell
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="pssc_user", email="pssc@test.com", password="pw")
        self.profile = _make_profile("PSSC Org", "pssc-org", user=self.user)
        self.event = _make_event(self.profile, "PSSC Event", "pssc-event")
        self.post = _make_post(self.event, "PSSC Post Headline")
        self.client.force_login(self.user)

    def test_post_syndication_without_studio_param_has_no_hx_target_studio_main(self):
        """
        post_syndication fragment without ?studio=1 must NOT render
        hx-target="#studio-main" — the "Event Workspace" link is removed from
        the fragment (kb-96tn.1); the bar breadcrumb carries the HTMX attrs.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'hx-target="#studio-main"',
            content,
            "post_syndication without ?studio=1 must NOT emit hx-target='#studio-main'.",
        )

    def test_post_hub_standalone_breadcrumb_has_plain_href(self):
        """
        kb-96tn.1 / kb-96tn.9: The post_syndication fragment breadcrumb without
        ?studio=1 must have a plain href to the event hub for correct navigation.
        (studio_swap=False → plain <a href>, no hx-get/hx-target.)
        With kb-96tn.9, the breadcrumb lives in post_syndication, not the hub shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_event_hub_path = f"/syndication/events/{self.event.pk}/"
        self.assertIn(
            f'href="{expected_event_hub_path}"',
            content,
            "post_syndication breadcrumb (no studio) must have plain href for navigation (kb-96tn.1 / kb-96tn.9).",
        )

    def test_post_hub_hx_fragment_breadcrumb_has_hx_target_studio_main(self):
        """
        kb-96tn.1 / kb-96tn.9: The post_syndication fragment with ?studio=1
        (in-studio context, studio_swap=True) MUST render hx-target="#studio-main"
        so the studio swap works correctly.
        With kb-96tn.9, the breadcrumb lives in post_syndication, not the hub shell.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "post_syndication (studio=1) breadcrumb MUST have hx-target='#studio-main' "
            "for the in-studio swap (kb-96tn.1 / kb-96tn.9).",
        )


# ---------------------------------------------------------------------------
# (e) kb-ide0.3 — capability-filtered channel tabs
#
# PlatformConnection.kinds drives which composer shows which channels.
# Event composer: only listing-capable connections (kinds contains "listing").
# Post composer: only promotion-capable connections (kinds contains "promotion").
# FetLife (both) and Switch (both) appear in BOTH composers.
# Telegram (promotion-only) appears ONLY in the post composer.
#
# Assertions are on response.content (assertContains/assertNotContains),
# NOT response.context — hollow test prevention (memory anti-pattern).
# ---------------------------------------------------------------------------


def _make_connection(organizer, platform, destination_id, kinds, enabled=True):
    """Create a PlatformConnection with given kinds."""
    return PlatformConnection.objects.create(
        organizer=organizer,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=enabled,
    )


class CapabilityFilteredEventComposerTabsTest(TestCase):
    """
    kb-ide0.3: The event composer (event_syndication fragment) tab row MUST
    show ONLY listing-capable channels. A promotion-only connection (Telegram,
    kinds=['promotion']) must be ABSENT from the event composer tab row —
    even when the event HAS Posts (which generate Telegram promotion projections).

    FetLife (kinds=['listing','promotion']) and Switch (kinds=['listing','promotion'])
    must be PRESENT in the event composer tab row.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cfe_user", email="cfe@test.com", password="pw")
        self.profile = _make_profile("CFE Org", "cfe-org", user=self.user)
        self.event = _make_event(self.profile, "CFE Event", "cfe-event")

        # Telegram: promotion-only — must be ABSENT from event composer tabs
        self.telegram_conn = _make_connection(self.profile, "telegram", "cfe-telegram-channel", kinds=["promotion"])
        # FetLife: both — must be PRESENT in event composer tabs
        self.fetlife_conn = _make_connection(
            self.profile, "fetlife", "cfe-fetlife-user", kinds=["listing", "promotion"]
        )
        # Switch: both — must be PRESENT in event composer tabs
        self.switch_conn = _make_connection(self.profile, "switch", "cfe-switch-page", kinds=["listing", "promotion"])

        # Trigger eager listing projections for the event.
        from syndication.services import _eager_create_listing_projections

        _eager_create_listing_projections(self.event)

        # Create a Post for the event with promotion projections.
        # This is the critical case: Telegram gets a promotion projection via this
        # Post, but must still be ABSENT from the EVENT composer tab row.
        self.post = _make_post(self.event, "CFE Post Headline")
        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        self.client.force_login(self.user)

    def test_telegram_absent_from_event_composer_tab_row(self):
        """
        Telegram (promotion-only, kinds=['promotion']) MUST NOT appear as a tab
        in the event composer's tab row — even when the event has a Post with a
        Telegram promotion projection. The event composer shows ONLY listing-
        capable channels; promotion-only channels belong to the post composer.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # We use the destination_id as the unique identifier so we don't
        # accidentally match the platform name in unrelated places (e.g. text).
        self.assertNotIn(
            "cfe-telegram-channel",
            content,
            "Telegram (promotion-only) must be ABSENT from the event composer tab row "
            "even when the event has a Post with a Telegram promotion projection.",
        )

    def test_fetlife_present_in_event_composer_tab_row(self):
        """
        FetLife (kinds=['listing','promotion']) MUST appear in the event composer
        tab row — it supports listing.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "cfe-fetlife-user",
            content,
            "FetLife (both kinds) must be PRESENT in the event composer tab row.",
        )

    def test_switch_present_in_event_composer_tab_row(self):
        """
        Switch (kinds=['listing','promotion']) MUST appear in the event composer
        tab row — it supports listing.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "cfe-switch-page",
            content,
            "Switch (both kinds) must be PRESENT in the event composer tab row.",
        )


class CapabilityFilteredPostComposerTabsTest(TestCase):
    """
    kb-ide0.3: The post composer (post_syndication fragment) tab row MUST
    show ONLY promotion-capable channels. A promotion-only Telegram connection
    (kinds=['promotion']) must be PRESENT. FetLife and Switch (both kinds) must
    also be PRESENT.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cfp_user", email="cfp@test.com", password="pw")
        self.profile = _make_profile("CFP Org", "cfp-org", user=self.user)
        self.event = _make_event(self.profile, "CFP Event", "cfp-event")
        self.post = _make_post(self.event, "CFP Post Headline")

        # Telegram: promotion-only — must be PRESENT in the post composer tabs
        self.telegram_conn = _make_connection(self.profile, "telegram", "cfp-telegram-channel", kinds=["promotion"])
        # FetLife: both — must be PRESENT in post composer tabs
        self.fetlife_conn = _make_connection(
            self.profile, "fetlife", "cfp-fetlife-user", kinds=["listing", "promotion"]
        )
        # Switch: both — must be PRESENT in post composer tabs
        self.switch_conn = _make_connection(self.profile, "switch", "cfp-switch-page", kinds=["listing", "promotion"])

        # Trigger eager promotion projections for the post.
        # The service creates projections at create_post time, but we created
        # connections after the post — trigger manually for test isolation.
        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        self.client.force_login(self.user)

    def test_telegram_present_in_post_composer_tab_row(self):
        """
        Telegram (promotion-only, kinds=['promotion']) MUST appear as a tab
        in the post composer's tab row — promotion channels belong here.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "cfp-telegram-channel",
            content,
            "Telegram (promotion-only) must be PRESENT in the post composer tab row.",
        )

    def test_fetlife_present_in_post_composer_tab_row(self):
        """
        FetLife (kinds=['listing','promotion']) MUST appear in the post composer
        tab row — it supports promotion.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "cfp-fetlife-user",
            content,
            "FetLife (both kinds) must be PRESENT in the post composer tab row.",
        )

    def test_switch_absent_from_post_composer_tab_row(self):
        """
        ADR-010 D1 (kb-shzi.4): Switch does NOT support post promotion yet —
        the capability gate in _eager_create_promotion_projections skips switch
        even when the connection has kinds=['listing','promotion'].
        Switch must NOT appear as a tab in the post composer.

        When Switch posting ships, remove 'switch' from
        _PLATFORMS_WITHOUT_POST_PROMOTION in services.py to flip this cheap.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "cfp-switch-page",
            content,
            "Switch must NOT appear in the post composer tab row "
            "(capability gate: Switch does not support post promotion yet, ADR-010 D1).",
        )


class ListingOnlyChannelAbsentFromPostComposerTest(TestCase):
    """
    kb-ide0.3 Fix 1: The post composer (post_syndication fragment) view MUST
    filter projections to only those whose connection.kinds contains "promotion".
    A listing-only connection (kinds=['listing']) must be ABSENT from the post
    composer tab row — its projection must not appear even if one exists.

    This test was RED before Fix 1 (the view fetched all source_post projections
    without the kinds filter) and GREEN after.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="loa_user", email="loa@test.com", password="pw")
        self.profile = _make_profile("LOA Org", "loa-org", user=self.user)
        self.event = _make_event(self.profile, "LOA Event", "loa-event")
        self.post = _make_post(self.event, "LOA Post Headline")

        # listing-only connection — must be ABSENT from post composer tabs
        self.listing_only_conn = _make_connection(
            self.profile, "fetlife", "loa-fetlife-listing-only", kinds=["listing"]
        )

        # Manually create a projection for the listing-only connection tied
        # to the post — simulates a corrupt/unexpected DB state, or tests that
        # the view-layer filter is the real guard (not just the eager-creation
        # invariant). We use PlatformProjection.objects.create directly to
        # bypass service-layer guards.
        from syndication.models import ContentVersion, PlatformProjection

        cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            body="listing-only body",
        )
        self.listing_only_proj = PlatformProjection.objects.create(
            connection=self.listing_only_conn,
            source_post=self.post,
            content_version=cv,
            kind=PlatformProjection.Kind.LISTING,
        )

        self.client.force_login(self.user)

    def test_listing_only_connection_absent_from_post_composer_tab_row(self):
        """
        A listing-only connection (kinds=['listing']) whose projection is
        associated to the post MUST NOT appear in the post composer tab row.
        The view-layer 'promotion' filter is the real guard; the listing-only
        projection must be excluded regardless of eager-creation invariants.

        This test was RED before Fix 1 (no kinds filter in fragment_post_syndication)
        and GREEN after (symmetric promotion filter added).
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "loa-fetlife-listing-only",
            content,
            "Listing-only connection (kinds=['listing']) MUST be ABSENT from the "
            "post composer tab row. The view must filter to promotion-capable "
            "connections only — not rely solely on the eager-creation invariant.",
        )


# ---------------------------------------------------------------------------
# (f) kb-shzi.5 — vocabulary locks: Event Workspace label + cross-link text
# ---------------------------------------------------------------------------


class EventWorkspaceVocabLockTest(TestCase):
    """
    kb-shzi.5: The event kicker and page title must read 'Event Workspace',
    not 'Event Hub'. The cross-link in the post composer must read
    'Event Workspace', not 'Event hub'.

    Content assertions lock the vocabulary so a future template edit cannot
    silently regress the renamed labels.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="vocab_user", email="vocab@test.com", password="pw")
        self.profile = _make_profile("Vocab Org", "vocab-org", user=self.user)
        self.event = _make_event(self.profile, "Vocab Event", "vocab-event")
        self.post = _make_post(self.event, "Vocab Post Headline")
        self.client.force_login(self.user)

    def test_event_hub_body_has_composer_bar_not_eyebrow(self):
        """
        kb-96tn.1 / kb-96tn.9: The event hub body must NOT have the old 'Event Workspace'
        status eyebrow or h1.kb-display — those were replaced by the composer bar.
        With kb-96tn.9, the bar (pills + 'Studio' breadcrumb + publish) lives INSIDE the
        event_syndication fragment. The hub shell no longer carries #composer-pills
        or the "Studio" text directly; it has the #event-syndication lazy-load section.
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # kb-96tn.1: eyebrow removed — no "Event Workspace" text in the bar
        self.assertNotIn(
            "Event Workspace",
            content,
            "Event hub body must NOT have the old 'Event Workspace' status eyebrow (kb-96tn.1).",
        )
        # The hub shell must have the event-syndication section which lazy-loads the bar
        self.assertIn(
            'id="event-syndication"',
            content,
            "Event hub body must have id='event-syndication' section that lazy-loads the composer bar (kb-96tn.9).",
        )

    def test_post_syndication_fragment_has_no_event_workspace_cross_link(self):
        """
        kb-96tn.1: The post_syndication fragment must NOT contain the old
        'Event Workspace ↗' cross-link — it was removed in favour of the
        breadcrumb in the composer bar (_post_hub_body.html).
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "Event Workspace",
            content,
            "Post syndication fragment must NOT have 'Event Workspace' cross-link — "
            "it moved to the composer bar breadcrumb (kb-96tn.1).",
        )

    def test_event_posts_fragment_add_button_says_add_promo_post(self):
        """
        The event posts add-button must read 'Add promo post' (unified from 'Add post').
        kb-shzi.5: one consistent term across all post-create entry points.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_posts/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Add promo post",
            content,
            "event_posts add-button must read 'Add promo post' (kb-shzi.5 unified vocab).",
        )
        self.assertNotIn(
            "Add post",
            content,
            "event_posts add-button must NOT read bare 'Add post' (kb-shzi.5: use 'Add promo post').",
        )
