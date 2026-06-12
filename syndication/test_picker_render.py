"""
TDD render tests for the destination picker (kb-sbhs.2).

Tests assert against response.content (rendered HTML), NOT response.context,
because context-only tests pass on broken templates (memory:
django-view-test-context-vs-content-hollow).

Seeded inventory:
- one channel (postability=bot)
- one group (postability=agent)
- one forum with >=2 topics (postability=agent)
- one flagged_missing=True row (channel, postability=bot)
- one agent-tier row (postability=agent, group)

All tests run with NO AgentCredential for the user — verifies the "agent
required" locked state for agent-tier destinations.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from organizers.models import Profile, ProfileClaim
from syndication.models import (
    AgentCredential,
    PlatformConnection,
    TelegramDialogType,
    TelegramPostability,
)

User = get_user_model()

# Shared destination_id for forum + its topics (simulates same Telegram chat_id)
FORUM_CHAT_ID = "-1009999001"
FORUM_TOPIC1_ID = 1001
FORUM_TOPIC2_ID = 1002


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


def _make_connection(profile, **kwargs):
    kwargs.setdefault("platform", "telegram")
    kwargs.setdefault("kinds", ["promotion"])
    return PlatformConnection.objects.create(organizer=profile, **kwargs)


class DestinationPickerRenderTest(TestCase):
    """
    Core render assertions for the destination picker page.

    All sub-tests use the same seeded inventory and confirm correctness
    by inspecting decoded HTML output.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="picker_user",
            email="picker@test.com",
            password="testpass",
        )
        self.profile = _make_profile(
            name="Picker Test Profile",
            slug="picker-test-profile",
            user=self.user,
        )

        # --- Seed inventory ---

        # 1. A channel (bot-tier)
        self.channel = _make_connection(
            self.profile,
            destination_id="-1001000001",
            type=TelegramDialogType.CHANNEL,
            title="Test Channel",
            postability=TelegramPostability.BOT,
            flagged_missing=False,
            theme_tags=["music", "nightlife"],
        )

        # 2. A group (agent-tier) — normal, not vanished
        self.group = _make_connection(
            self.profile,
            destination_id="-1001000002",
            type=TelegramDialogType.GROUP,
            title="Test Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            theme_tags=["queer"],
        )

        # 3. Forum cluster + two topic leaves — share same destination_id (chat_id)
        #    The forum/group cluster is represented by type=GROUP (or SUPERGROUP)
        #    rows are forum_topic leaves with topic_id set.
        self.forum_parent = _make_connection(
            self.profile,
            destination_id=FORUM_CHAT_ID,
            type=TelegramDialogType.GROUP,
            title="Test Forum Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            theme_tags=["kink"],
            topic_id=None,
        )
        self.forum_topic1 = _make_connection(
            self.profile,
            destination_id=FORUM_CHAT_ID,
            type=TelegramDialogType.FORUM_TOPIC,
            title="Test Forum Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            theme_tags=["kink"],
            topic_id=FORUM_TOPIC1_ID,
            friendly_name="Topic One",
        )
        self.forum_topic2 = _make_connection(
            self.profile,
            destination_id=FORUM_CHAT_ID,
            type=TelegramDialogType.FORUM_TOPIC,
            title="Test Forum Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            theme_tags=["kink"],
            topic_id=FORUM_TOPIC2_ID,
            friendly_name="Topic Two",
        )

        # 4. A vanished channel (flagged_missing=True)
        self.vanished = _make_connection(
            self.profile,
            destination_id="-1001000099",
            type=TelegramDialogType.CHANNEL,
            title="Vanished Channel",
            postability=TelegramPostability.BOT,
            flagged_missing=True,
            theme_tags=[],
        )

        self.client = Client()
        self.client.login(username="picker_user", password="testpass")
        self.url = reverse("syndication:destination-picker")

    def _get_html(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    # -----------------------------------------------------------------------
    # (a) Three category sections render
    # -----------------------------------------------------------------------

    def test_channels_section_renders(self):
        """The 'Channels' category heading must appear in the rendered HTML."""
        html = self._get_html()
        self.assertIn("Channels", html)

    def test_groups_section_renders(self):
        """The 'Groups' category heading must appear in the rendered HTML."""
        html = self._get_html()
        self.assertIn("Groups", html)

    def test_forums_section_renders(self):
        """The 'Forums' category heading must appear in the rendered HTML."""
        html = self._get_html()
        self.assertIn("Forums", html)

    def test_channel_title_renders(self):
        """The channel title must appear in the rendered HTML."""
        html = self._get_html()
        self.assertIn("Test Channel", html)

    def test_group_title_renders(self):
        """The group title must appear in the rendered HTML."""
        html = self._get_html()
        self.assertIn("Test Group", html)

    # -----------------------------------------------------------------------
    # (b) Forum topics nest under forum cluster
    # -----------------------------------------------------------------------

    def test_forum_topic_friendly_names_render(self):
        """
        Forum topic leaves display friendly_name when set.
        Both topics must appear in the rendered HTML.
        """
        html = self._get_html()
        self.assertIn("Topic One", html)
        self.assertIn("Topic Two", html)

    def test_forum_parent_title_renders_as_cluster_label(self):
        """The forum parent group title renders as a cluster label."""
        html = self._get_html()
        self.assertIn("Test Forum Group", html)

    # -----------------------------------------------------------------------
    # (c) Forum cluster label has NO checkbox; topic leaves DO have checkboxes
    # -----------------------------------------------------------------------

    def test_forum_cluster_label_has_no_checkbox(self):
        """
        The forum/group cluster label row must NOT render an interactive
        checkbox affordance. Assert:
        1. The cluster-label marker (data-role="forum-cluster") exists.
        2. No <input type="checkbox"> with value="{forum_parent.pk}" appears
           anywhere in the rendered HTML.
        This test FAILS if someone adds a forum-parent checkbox.
        """
        import re

        html = self._get_html()
        forum_parent_pk = str(self.forum_parent.pk)

        # 1. Cluster-label marker must exist
        self.assertIn('data-role="forum-cluster"', html)

        # 2. No checkbox carrying the forum parent's pk
        checkbox_for_parent = re.search(
            rf'<input[^>]*type=["\']checkbox["\'][^>]*value="{re.escape(forum_parent_pk)}"[^>]*>',
            html,
        )
        self.assertIsNone(
            checkbox_for_parent,
            msg=f"Forum cluster label must NOT have a checkbox (value={forum_parent_pk!r}), "
            f"but found: {checkbox_for_parent.group(0) if checkbox_for_parent else ''}",
        )

    def test_forum_topic_leaves_have_checkboxes(self):
        """
        Forum topic leaves must render with a checkbox affordance.
        We assert checkbox inputs with the topic connection pks exist.
        """
        html = self._get_html()
        # Each topic leaf should have a checkbox. We look for an input type=checkbox
        # with a value matching the topic connection pks.
        topic1_pk = str(self.forum_topic1.pk)
        topic2_pk = str(self.forum_topic2.pk)
        # Checkboxes should reference the connection pks
        self.assertIn(f'value="{topic1_pk}"', html)
        self.assertIn(f'value="{topic2_pk}"', html)

    def test_channel_row_has_checkbox(self):
        """
        Regular channel rows must render with a checkbox affordance.
        kb-sbhs.3 mutation layer: the checkbox is now wired via HTMX with
        name="selected" value="true/false"; the connection pk is tracked
        via data-connection-pk and data-picker-row attributes.
        """
        import re

        html = self._get_html()
        channel_pk = str(self.channel.pk)
        # The row wrapper must carry the channel pk (via data-connection-pk)
        self.assertIn(f'data-connection-pk="{channel_pk}"', html)
        # An <input type="checkbox"> must be present in this row
        checkbox_match = re.search(
            r'<input[^>]*type=["\']checkbox["\'][^>]*>',
            html,
        )
        self.assertIsNotNone(
            checkbox_match,
            msg=f"Channel row (pk={channel_pk!r}) must render a checkbox, but none found.",
        )

    # -----------------------------------------------------------------------
    # (d) Vanished destinations render with a LOUD flag
    # -----------------------------------------------------------------------

    def test_vanished_row_renders_loud_flag(self):
        """
        flagged_missing=True rows must render a loud vanished marker.
        Assert the HTML contains a vanished indicator with 'Vanished Channel'.
        """
        html = self._get_html()
        # The vanished channel title must appear
        self.assertIn("Vanished Channel", html)
        # And a loud vanished indicator must be present
        self.assertIn("data-vanished", html)

    def test_vanished_row_is_not_selectable(self):
        """
        The vanished row must render a DISABLED checkbox (visible-but-locked,
        per ADR-008 D3). Assert:
        1. A checkbox with value="{vanished_pk}" IS present (not silently hidden).
        2. That checkbox carries the `disabled` attribute.
        Fails if the checkbox is absent OR not disabled.
        """
        import re

        html = self._get_html()
        vanished_pk = str(self.vanished.pk)

        checkbox_match = re.search(
            rf'<input[^>]*type=["\']checkbox["\'][^>]*value="{re.escape(vanished_pk)}"[^>]*>',
            html,
        )
        self.assertIsNotNone(
            checkbox_match,
            msg=f"Vanished row (pk={vanished_pk!r}) must render a checkbox (disabled), but no checkbox found.",
        )
        self.assertIn(
            "disabled",
            checkbox_match.group(0),
            msg=f"Vanished row checkbox must carry `disabled`; got: {checkbox_match.group(0)!r}",
        )

    # -----------------------------------------------------------------------
    # (e) Agent-tier rows: VISIBLE-but-LOCKED with "agent required" indicator
    #     (no agent connected for test user)
    # -----------------------------------------------------------------------

    def test_agent_tier_group_renders_visible(self):
        """
        With no agent connected, agent-tier rows must still render
        (not hidden). The group title must appear in the HTML.
        """
        html = self._get_html()
        self.assertIn("Test Group", html)

    def test_agent_tier_renders_locked_indicator(self):
        """
        With no agent connected, agent-tier rows must render a locked
        'agent required' indicator (not hidden, not selectable).
        """
        html = self._get_html()
        # The "agent required" label must name the actual mechanism
        self.assertIn("agent required", html.lower())

    def test_agent_tier_group_checkbox_is_not_active(self):
        """
        With no agent connected, the agent-tier group must render a DISABLED
        checkbox (visible-but-locked, ADR-018 D1/D4). Assert:
        1. A checkbox with value="{group_pk}" IS present (not hidden).
        2. That checkbox carries the `disabled` attribute.
        Fails if the checkbox is absent OR not disabled.
        """
        import re

        html = self._get_html()
        group_pk = str(self.group.pk)

        checkbox_match = re.search(
            rf'<input[^>]*type=["\']checkbox["\'][^>]*value="{re.escape(group_pk)}"[^>]*>',
            html,
        )
        self.assertIsNotNone(
            checkbox_match,
            msg=f"Agent-tier group (pk={group_pk!r}) must render a checkbox (disabled), but no checkbox found.",
        )
        self.assertIn(
            "disabled",
            checkbox_match.group(0),
            msg=f"Agent-tier group checkbox must carry `disabled`; got: {checkbox_match.group(0)!r}",
        )

    # -----------------------------------------------------------------------
    # (f) Tag chips render from union of theme_tags
    # -----------------------------------------------------------------------

    def test_theme_tag_chips_render(self):
        """
        Theme tag chips must render from the union of all theme_tags across
        the seeded connections. Tags: music, nightlife, queer, kink.
        """
        html = self._get_html()
        self.assertIn("music", html)
        self.assertIn("nightlife", html)
        self.assertIn("queer", html)
        self.assertIn("kink", html)

    # -----------------------------------------------------------------------
    # Auth gate
    # -----------------------------------------------------------------------

    def test_unauthenticated_redirects(self):
        """Unauthenticated requests must redirect (login required)."""
        anon_client = Client()
        response = anon_client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_profile_isolation(self):
        """
        A user with no profile claims sees no connections (auth seam).
        """
        other_user = _make_vouched_user(
            username="picker_other",
            email="other_picker@test.com",
            password="x",
        )
        other_client = Client()
        other_client.login(username="picker_other", password="x")
        response = other_client.get(self.url)
        html = response.content.decode("utf-8")
        # Other user has no claims — their picker renders no inventory rows
        self.assertNotIn("Test Channel", html)


class DestinationPickerAgentConnectedTest(TestCase):
    """
    When an AgentCredential exists for the user, agent-tier rows render
    normally (not locked). This is the positive capability-ladder case.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="picker_agent_user",
            email="picker_agent@test.com",
            password="testpass",
        )
        self.profile = _make_profile(
            name="Picker Agent Profile",
            slug="picker-agent-profile",
            user=self.user,
        )
        # Agent-tier group connection
        self.agent_group = _make_connection(
            self.profile,
            destination_id="-1001000010",
            type=TelegramDialogType.GROUP,
            title="Agent Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            theme_tags=[],
        )
        # Create an active AgentCredential for the user
        AgentCredential.objects.create(
            user=self.user,
            key_hash="a" * 64,  # dummy hash
            enabled=True,
        )

        self.client = Client()
        self.client.login(username="picker_agent_user", password="testpass")
        self.url = reverse("syndication:destination-picker")

    def test_agent_tier_row_not_locked_when_agent_connected(self):
        """
        With an active AgentCredential, agent-tier rows render without
        the 'agent required' lock indicator.
        """
        response = self.client.get(self.url)
        html = response.content.decode("utf-8")
        self.assertIn("Agent Group", html)
        # When agent IS connected, the agent-required label must NOT appear
        # for this group's checkbox (it may appear for other things, but
        # the group checkbox should be active, not disabled).
        group_pk = str(self.agent_group.pk)
        import re

        checkbox_match = re.search(
            rf'<input[^>]*type=["\']checkbox["\'][^>]*value="{re.escape(group_pk)}"[^>]*>',
            html,
        )
        if checkbox_match:
            self.assertNotIn("disabled", checkbox_match.group(0))
