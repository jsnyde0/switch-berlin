"""
TDD tests for kb-96tn.7 — clickable promo cards + promo strip below channel composer.

Two acceptance targets:
1. event_posts.html: the whole promo card article is hx-wired (hx-get to post-hub),
   and the "Open composer ↗" inner link is removed.
2. _event_hub_body.html: #event-syndication section is rendered BEFORE #event-posts
   (promo strip is secondary, below the channel composer section).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import Profile, ProfileClaim
from syndication.models import Post

User = get_user_model()


def _make_vouched_user(**kwargs):
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


class PromoCardClickableTest(TestCase):
    """
    D-IA7: the whole promo card `<article>` must be the click target (hx-get to
    post-hub URL, hx-target="#studio-main", hx-push-url). The inner "Open
    composer ↗" link must be gone.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="promo_card_user",
            email="promo_card@test.com",
            password="x",
        )
        self.profile = _make_profile(
            name="Promo Card Organiser",
            slug="promo-card-org",
            user=self.user,
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title="Promo Card Test Event",
            slug="promo-card-test-event",
            organizer=self.profile,
            start=now + timezone.timedelta(days=7),
            status="published",
        )
        self.post = Post.objects.create(
            event=self.event,
            headline="Join us for Promo Card Test",
            body="This is the promo body.",
        )

    def _get_fragment(self):
        client = Client()
        client.force_login(self.user)
        url = reverse("syndication:fragment-event-posts", kwargs={"pk": self.event.pk})
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_article_has_hx_get_to_post_hub(self):
        """
        The promo card <article> must carry hx-get pointing to the post-hub URL
        for the post (hx-get="/syndication/posts/<pk>/").
        """
        content = self._get_fragment()
        post_hub_url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        # The article element must have an hx-get attribute pointing to this URL
        self.assertIn(
            f'hx-get="{post_hub_url}"',
            content,
            f"Article must have hx-get={post_hub_url!r} but got:\n{content}",
        )

    def test_article_has_hx_target_studio_main(self):
        """
        The promo card <article> must carry hx-target="#studio-main" so the
        click swaps the studio main pane (not the full page).
        """
        content = self._get_fragment()
        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "Article must have hx-target='#studio-main'",
        )

    def test_article_has_cursor_pointer_class(self):
        """
        The promo card <article> must carry cursor-pointer so the user gets a
        visual affordance that the whole card is clickable.
        """
        content = self._get_fragment()
        self.assertIn(
            "cursor-pointer",
            content,
            "Article must have cursor-pointer class",
        )

    def test_no_open_composer_link_text(self):
        """
        The inner 'Open composer ↗' <a> link must be removed entirely from
        every promo card in the rendered HTML.
        """
        content = self._get_fragment()
        self.assertNotIn(
            "Open composer",
            content,
            "The 'Open composer' inner link must not appear in the rendered promo card",
        )


class EventHubBodySectionOrderTest(TestCase):
    """
    D-IA8: #event-syndication must appear BEFORE #event-posts in the rendered
    HTML of the event hub body. The promo strip is secondary and should sit
    below the channel composer.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="hub_order_user",
            email="hub_order@test.com",
            password="x",
        )
        self.profile = _make_profile(
            name="Hub Order Organiser",
            slug="hub-order-org",
            user=self.user,
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title="Hub Order Test Event",
            slug="hub-order-test-event",
            organizer=self.profile,
            start=now + timezone.timedelta(days=7),
            status="published",
        )

    def test_event_syndication_precedes_event_posts_in_dom(self):
        """
        In the rendered event hub page, the element with id="event-syndication"
        must appear at an earlier character position than id="event-posts".
        This mirrors the DOM order assertion in the harness target.
        """
        client = Client()
        client.force_login(self.user)
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        pos_syndication = content.find('id="event-syndication"')
        pos_posts = content.find('id="event-posts"')

        self.assertGreater(
            pos_syndication,
            -1,
            "id='event-syndication' must be present in the event hub page",
        )
        self.assertGreater(
            pos_posts,
            -1,
            "id='event-posts' must be present in the event hub page",
        )
        self.assertLess(
            pos_syndication,
            pos_posts,
            f"#event-syndication (pos={pos_syndication}) must precede "
            f"#event-posts (pos={pos_posts}) in the rendered HTML",
        )
