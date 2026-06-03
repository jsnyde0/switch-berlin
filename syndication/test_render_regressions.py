"""
Render-content regression tests for djlint reformat sweep (kb-33do.3).

These tests assert against the RENDERED HTML string, not response.context,
because the regression class (whitespace mangling, separator stripping) is
invisible to context assertions — only the rendered output can catch it.

Finding 1: connections_list.html kinds separator must render as
  'listing · promotion' (space-middot-space in the kinds span's text content),
  not 'listing·promotion' or a newline-broken form (djlint stripped the
  surrounding spaces from the separator).

Finding 2: events/list.html sort-tab hrefs must not contain embedded newlines
  or multi-space whitespace — djlint wrapped the href attribute value across
  lines, injecting literal newlines + indentation and producing malformed URLs.
"""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection

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


class ConnectionsListKindsChipTest(TestCase):
    """
    Regression: connections_list.html renders kinds as kb-tag chips, not a
    separator-joined span.

    The redesign (kb-bxdm) replaced the ' · ' separator pattern with individual
    kb-tag elements, one per kind. Each chip must render its label text in the
    HTML output. Listing shows with kb-tag-accent, Promotion with purple tint.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="rr_conn_user",
            email="rr_conn@test.com",
            password="x",
        )
        self.profile = _make_profile(
            name="RR Conn Profile",
            slug="rr-conn-profile",
            user=self.user,
        )
        # Create a connection with two kinds so both chips are rendered
        PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-rr-test",
            kinds=["listing", "promotion"],
            enabled=True,
        )

    def test_kinds_render_as_individual_chips(self):
        """
        The redesigned list renders each kind as a separate kb-tag chip.
        Both 'Listing' and 'Promotion' must appear as chip label text in the
        rendered HTML output for a multi-kind connection.
        """
        client = Client()
        client.force_login(self.user)
        response = client.get("/syndication/connections/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Both chips must be present with their display labels.
        self.assertIn("Listing", content, "Listing chip label must appear in connections list")
        self.assertIn("Promotion", content, "Promotion chip label must appear in connections list")
        # kb-tag class must appear (chip structure present).
        self.assertIn("kb-tag", content, "kb-tag class must appear in connections list for kind chips")


class EventListSortTabHrefTest(TestCase):
    """
    Regression: events/list.html sort-tab hrefs must not contain embedded newlines.

    Pre-reformat: <c-kb.tab href="?{% if filter_query_string %}...{% endif %}..." ...>
    After djlint reformat the href attribute value was wrapped across multiple lines,
    injecting literal '\\n' + indentation into the attribute string.

    The rendered HTML must show sort-tab href attributes with no embedded newlines
    or multi-space whitespace sequences (which would make the URL malformed).
    """

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="rr_events_staff",
            email="rr_events_staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.staff_user)
        organizer = Profile.objects.create(
            name="RR Events Org",
            slug="rr-events-org",
            status="approved",
        )
        now = timezone.now()
        Event.objects.create(
            title="RR Events Test",
            slug="rr-events-test",
            organizer=organizer,
            start=now + timezone.timedelta(days=1),
            status="published",
        )

    def test_sort_tab_hrefs_contain_no_embedded_newlines(self):
        """
        Rendered sort-tab <a href="..."> attributes must not contain newlines.

        The cotton <c-kb.tab href="..."> renders to <a href="...">; the href value
        must be a clean query string with no embedded whitespace from template
        line-wrapping. We check the rendered HTML for href= attributes that contain
        a literal newline character inside the quoted value.
        """
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Find all href="..." attribute values in the rendered HTML
        # and assert none contain a newline character.
        href_values = re.findall(r'href="([^"]*)"', content)
        for href in href_values:
            self.assertNotIn(
                "\n",
                href,
                f"href attribute must not contain embedded newline; got: {repr(href)}",
            )

    def test_sort_tab_latest_href_is_valid_query_string(self):
        """
        The 'Latest' sort-tab href='?' must be a clean query string (just '?')
        when no filters are active — not '?\n                ' with injected whitespace.
        """
        response = self.client.get("/events/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The Latest sort tab renders as <a href="?"> when no filters are active.
        # If djlint injected newlines into the href attribute, the value would be
        # '?' followed by whitespace instead of a bare '?'.
        # Check: no href="?" immediately followed by whitespace inside the quotes.
        malformed = re.search(r'href="\?[\n\r\t ]+[^"]*"', content)
        self.assertIsNone(
            malformed,
            f"Sort-tab href must not start with '?' followed by whitespace; "
            f"got: {repr(malformed.group(0)) if malformed else 'N/A'} — "
            "djlint injected newlines into href attribute value",
        )
