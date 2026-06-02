"""
Render-content regression tests for djlint reformat sweep (kb-33do.3).

These tests assert against the RENDERED HTML string, not response.context,
because the regression class (whitespace mangling, separator stripping) is
invisible to context assertions — only the rendered output can catch it.

Finding 1: connections_list.html kinds separator must render as 'listing · promotion'
  (space-middot-space in the TEXT content of the kinds span), not 'listing·promotion'
  or 'listing\n  ·\n\n  promotion' (djlint stripped surrounding spaces from the separator).

Finding 2: events/list.html sort-tab hrefs must not contain embedded newlines or
  multi-space whitespace — djlint wrapped the href attribute value across multiple lines,
  injecting literal '\n' + indentation into the attribute string, producing malformed URLs.
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


class ConnectionsListKindsSeparatorTest(TestCase):
    """
    Regression: connections_list.html kinds separator must render as ' · ' (space-middot-space).

    Pre-reformat: {% for k in conn.kinds %}{{ k }}{% if not forloop.last %} · {% endif %}{% endfor %}
    After djlint reformat the loop body was reflowed across multiple lines and the spaces were
    stripped from the separator block, so the raw rendered output is:
      \n  listing\n  ·\n\n  promotion\n
    This does NOT contain ' · ' (space-middot-space) as an adjacent sequence.

    The fix must produce 'listing · promotion' (space-middot-space) adjacent in the output,
    e.g. via {{ conn.kinds|join:" · " }}.
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
        # Create a connection with two kinds so the separator is rendered
        PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-rr-test",
            kinds=["listing", "promotion"],
            enabled=True,
        )

    def test_kinds_separator_renders_as_spaced_middot_adjacent_in_output(self):
        """
        The raw rendered HTML for a multi-kind connection must contain
        'listing · promotion' (kind1, space, middot, space, kind2) as adjacent text —
        or at minimum must contain ' · ' in the kb-mono/kinds span's text content
        without intervening newlines/indentation breaking the space-middot-space sequence.

        Specifically: the rendered text content (after collapsing Django template
        whitespace) of the span containing the kinds must produce 'listing · promotion'
        not 'listing·promotion' or 'listing \n · \n promotion'.

        We check the raw HTML: 'listing · promotion' must appear as a substring
        somewhere in the content. The only place this appears is the kinds span.
        (Other uses of ' · ' on the page are in different contexts and would not
        immediately precede 'listing' or 'promotion'.)
        """
        client = Client()
        client.force_login(self.user)
        response = client.get("/syndication/connections/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The exact sequence 'listing · promotion' must appear adjacently in the raw HTML.
        # If the loop is split across lines, the raw HTML has 'listing\n  ·\n\n  promotion'
        # which does NOT contain 'listing · promotion' as a substring.
        self.assertIn(
            "listing · promotion",
            content,
            "Kinds must render as 'listing · promotion' (space-middot-space adjacent); "
            "djlint stripped surrounding spaces — check the kinds loop or use |join:' · '",
        )


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
        # '?\n                ' instead of '?'.
        # Check: no href="? " (href="?" followed by whitespace inside the quotes) appears.
        malformed = re.search(r'href="\?[\n\r\t ]+[^"]*"', content)
        self.assertIsNone(
            malformed,
            f"Sort-tab href must not start with '?' followed by whitespace; "
            f"got: {repr(malformed.group(0)) if malformed else 'N/A'} — "
            "djlint injected newlines into href attribute value",
        )
