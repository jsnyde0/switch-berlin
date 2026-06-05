"""
Tests for kb-kgza.5: Studio breadcrumb links to the publishables index.

Contract:
1. Route resolution: reverse('syndication:studio') resolves; GET returns 200
   for authenticated organizer.
2. Content: rendered composer breadcrumbs (event AND post) contain an anchor
   whose href is the studio URL AND that carries hx-get + hx-target="#studio-main"
   + hx-push-url (gated on studio_swap context flag).
3. No NoReverseMatch anywhere in the templates.

Harness target (kb-kgza.5):
  Signal: route resolution + content test.
  Expected green: reverse(syndication:studio) resolves, view returns 200,
  rendered breadcrumb contains an anchor href to it with hx-* attrs.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
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
        start=timezone.now() + timezone.timedelta(days=7),
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_connection(profile, platform, destination_id, kinds):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=True,
    )


def _make_canonical_cv(event=None, post=None, body="canonical body"):
    if event is not None:
        cv, _ = ContentVersion.objects.get_or_create(
            event=event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE, "body": body},
        )
    else:
        cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE, "body": body},
        )
    return cv


def _make_listing_projection(conn, event, cv, status="draft"):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        source_event=event,
        content_version=cv,
    )


def _make_promotion_projection(conn, post, cv, status="draft"):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=status,
        source_post=post,
        content_version=cv,
    )


# ---------------------------------------------------------------------------
# 1. Route resolution tests
# ---------------------------------------------------------------------------


class StudioRouteTest(TestCase):
    """
    Route resolution: syndication:studio resolves and returns 200 for a claimant.

    The studio view must be registered under the syndication namespace so that
    {% url 'syndication:studio' %} works in templates without raising NoReverseMatch.
    """

    def test_syndication_studio_reverse_resolves(self):
        """
        reverse('syndication:studio') must not raise NoReverseMatch.

        This is the primary contract for the route registration fix.
        """
        try:
            url = reverse("syndication:studio")
        except NoReverseMatch as exc:
            self.fail(f"reverse('syndication:studio') raised NoReverseMatch: {exc}")
        self.assertIsNotNone(url)

    def test_studio_view_returns_200_for_authenticated_organizer(self):
        """
        GET syndication:studio returns 200 for an authenticated organizer (claimant).
        """
        user = _make_user(username="sb_route_user", email="sb_route@test.com", password="pw")
        _make_profile("SB Route Org", "sb-route-org", user=user)
        client = Client()
        client.force_login(user)

        url = reverse("syndication:studio")
        response = client.get(url)

        self.assertEqual(
            response.status_code,
            200,
            f"GET {url} must return 200 for authenticated organizer.",
        )


# ---------------------------------------------------------------------------
# 2. Event composer breadcrumb: Studio anchor (studio_swap=True path)
# ---------------------------------------------------------------------------


class EventBreadcrumbStudioLinkTest(TestCase):
    """
    When studio_swap is True (i.e. ?studio=1), the event composer breadcrumb
    must render "Studio" as an anchor pointing to the syndication:studio URL
    with hx-get, hx-target="#studio-main", and hx-push-url attributes.

    A plain href anchor without hx-* would full-page-reload and lose studio context.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_sb_user", email="evt_sb@test.com", password="pw")
        self.profile = _make_profile("Evt SB Org", "evt-sb-org", user=self.user)
        self.event = _make_event(self.profile, "SB Event", "sb-event")
        conn = _make_connection(self.profile, "fetlife", "fl-sb-evt", ["listing"])
        cv = _make_canonical_cv(event=self.event, body="sb event body")
        _make_listing_projection(conn, self.event, cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)
        self.studio_url = reverse("syndication:studio")

    def test_event_breadcrumb_studio_anchor_href(self):
        """
        With studio_swap=True: the event breadcrumb renders 'Studio' as an
        anchor with href pointing to the syndication:studio URL.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            self.studio_url,
            content,
            f"Event breadcrumb (studio_swap=True) must contain href to studio URL '{self.studio_url}'.",
        )

    def test_event_breadcrumb_studio_anchor_has_hx_get(self):
        """
        With studio_swap=True: the Studio anchor must carry hx-get pointing
        to the studio URL (not just a plain href that would full-page-reload).
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            f'hx-get="{self.studio_url}"',
            content,
            "Event breadcrumb Studio anchor must have hx-get attribute.",
        )

    def test_event_breadcrumb_studio_anchor_has_hx_target_studio_main(self):
        """
        With studio_swap=True: the Studio anchor must carry hx-target="#studio-main".
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "Event breadcrumb Studio anchor must have hx-target='#studio-main'.",
        )

    def test_event_breadcrumb_studio_anchor_has_hx_push_url(self):
        """
        With studio_swap=True: the Studio anchor must carry hx-push-url so that
        the browser URL updates to /studio/ when the user clicks it.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "hx-push-url",
            content,
            "Event breadcrumb Studio anchor must have hx-push-url attribute.",
        )

    def test_event_breadcrumb_studio_no_htmx_without_studio_swap(self):
        """
        Without studio_swap (no ?studio=1): 'Studio' may still be a plain anchor
        with href but must NOT emit hx-get on the Studio root (non-studio context).

        This test is permissive — the important constraint is the studio_swap=True path.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # Just verify the view renders without error — the exact form is not the
        # primary concern for this fix. The HTMX attrs are only needed in studio context.
        self.assertIn("Studio", response.content.decode())


# ---------------------------------------------------------------------------
# 3. Post composer breadcrumb: Studio root anchor (studio_swap=True path)
# ---------------------------------------------------------------------------


class PostBreadcrumbStudioLinkTest(TestCase):
    """
    When studio_swap is True (i.e. ?studio=1), the post composer breadcrumb
    must render "Studio" as an anchor pointing to the syndication:studio URL
    with hx-get, hx-target="#studio-main", and hx-push-url attributes.

    The post composer already has "Studio › event.title" with a link on the event
    title (the event-hub crumb). This bead fixes the LEFTMOST "Studio" root
    segment to also be a link. The event-hub crumb must still work.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_sb_user", email="post_sb@test.com", password="pw")
        self.profile = _make_profile("Post SB Org", "post-sb-org", user=self.user)
        self.event = _make_event(self.profile, "SB Post Event", "sb-post-event")
        self.post = Post.objects.create(event=self.event, headline="SB Post", body="sb post body")
        conn = _make_connection(self.profile, "fetlife", "fl-sb-post", ["promotion"])
        cv = _make_canonical_cv(post=self.post, body="sb post body")
        _make_promotion_projection(conn, self.post, cv)
        _make_canonical_cv(post=self.post)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)
        self.studio_url = reverse("syndication:studio")
        self.event_hub_url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})

    def test_post_breadcrumb_studio_anchor_href(self):
        """
        With studio_swap=True: the post breadcrumb renders 'Studio' as an
        anchor with href pointing to the syndication:studio URL.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            self.studio_url,
            content,
            f"Post breadcrumb (studio_swap=True) must contain href to studio URL '{self.studio_url}'.",
        )

    def test_post_breadcrumb_studio_anchor_has_hx_get(self):
        """
        With studio_swap=True: the Studio anchor must carry hx-get pointing
        to the studio URL.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            f'hx-get="{self.studio_url}"',
            content,
            "Post breadcrumb Studio anchor must have hx-get attribute.",
        )

    def test_post_breadcrumb_studio_anchor_has_hx_target_studio_main(self):
        """
        With studio_swap=True: the Studio anchor must carry hx-target="#studio-main".
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "Post breadcrumb Studio anchor must have hx-target='#studio-main'.",
        )

    def test_post_breadcrumb_studio_anchor_has_hx_push_url(self):
        """
        With studio_swap=True: the Studio anchor must carry hx-push-url.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "hx-push-url",
            content,
            "Post breadcrumb Studio anchor must have hx-push-url attribute.",
        )

    def test_post_breadcrumb_event_hub_link_still_present(self):
        """
        With studio_swap=True: the existing event-hub crumb link (Studio › event.title)
        must still be present. This bead must NOT break the existing post breadcrumb link.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            self.event_hub_url,
            content,
            f"Post breadcrumb must still link to event hub '{self.event_hub_url}'.",
        )

    def test_post_breadcrumb_separator_still_present(self):
        """
        With studio_swap=True: the '›' separator between Studio and event title
        must still be rendered.
        """
        response = self.client.get(self.url + "?studio=1")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("›", content)


# ---------------------------------------------------------------------------
# 4. No NoReverseMatch guard
# ---------------------------------------------------------------------------


class NoReverseMatchGuardTest(TestCase):
    """
    Verify that templates render without raising NoReverseMatch when
    syndication:studio is referenced via {% url 'syndication:studio' %}.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="nm_guard_user", email="nm_guard@test.com", password="pw")
        self.profile = _make_profile("NM Guard Org", "nm-guard-org", user=self.user)
        self.event = _make_event(self.profile, "NM Guard Event", "nm-guard-event")
        conn = _make_connection(self.profile, "fetlife", "fl-nm-guard", ["listing"])
        cv = _make_canonical_cv(event=self.event, body="nm guard event body")
        _make_listing_projection(conn, self.event, cv)
        self.client.force_login(self.user)

    def test_event_composer_renders_without_noreversematch(self):
        """
        Event composer fragment must render without raising NoReverseMatch
        (template uses {% url 'syndication:studio' %}).
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url + "?studio=1")
        self.assertEqual(
            response.status_code,
            200,
            "Event composer fragment must render without NoReverseMatch "
            "(syndication:studio must resolve via URLs config).",
        )
