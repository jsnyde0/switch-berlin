"""
TDD write tests for the destination picker mutation layer (kb-sbhs.3).

Tests assert against real DB state and server responses (NOT only view context).
Server-side guard, kinds additivity, projection-eligibility, overlay writer, auth.

Run: DJANGO_SETTINGS_MODULE=a_core.test_settings uv run pytest syndication/test_picker_write.py -v
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import (
    AgentCredential,
    PlatformConnection,
    PlatformProjection,
    TelegramDialogType,
    TelegramPostability,
)

User = get_user_model()

FORUM_CHAT_ID = "-1009999002"
FORUM_TOPIC_ID = 2001


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
    kwargs.setdefault("kinds", [])
    return PlatformConnection.objects.create(organizer=profile, **kwargs)


def _make_event(profile, **kwargs):
    kwargs.setdefault("title", "Test Event")
    kwargs.setdefault("slug", "test-event")
    kwargs.setdefault("start", timezone.now())
    event = Event.objects.create(**kwargs)
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


class PickerWriteBaseTest(TestCase):
    """
    Shared setUp: a user+profile with an AgentCredential (agent connected)
    and a variety of connections.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="picker_write_user",
            email="pickerwrite@test.com",
            password="testpass",
        )
        self.profile = _make_profile(
            name="Picker Write Profile",
            slug="picker-write-profile",
            user=self.user,
        )

        # Agent connected — so agent-tier rows are NOT locked by default
        self.agent_cred = AgentCredential.objects.create(
            user=self.user,
            key_hash="b" * 64,
            enabled=True,
        )

        # A plain bot-tier channel (postability=bot, not locked)
        self.channel = _make_connection(
            self.profile,
            destination_id="-1001111001",
            type=TelegramDialogType.CHANNEL,
            title="My Channel",
            postability=TelegramPostability.BOT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
        )

        # An agent-tier group (postability=agent, not locked because agent connected)
        self.group = _make_connection(
            self.profile,
            destination_id="-1001111002",
            type=TelegramDialogType.GROUP,
            title="My Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
        )

        # A forum cluster (type=GROUP, same destination_id as topic, NOT selectable)
        self.forum_parent = _make_connection(
            self.profile,
            destination_id=FORUM_CHAT_ID,
            type=TelegramDialogType.GROUP,
            title="My Forum",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
            topic_id=None,
        )

        # A forum topic leaf (selectable)
        self.forum_topic = _make_connection(
            self.profile,
            destination_id=FORUM_CHAT_ID,
            type=TelegramDialogType.FORUM_TOPIC,
            title="My Forum",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
            topic_id=FORUM_TOPIC_ID,
            friendly_name="Topic One",
        )

        # A vanished/flagged_missing connection
        self.vanished = _make_connection(
            self.profile,
            destination_id="-1001111099",
            type=TelegramDialogType.CHANNEL,
            title="Vanished Channel",
            postability=TelegramPostability.BOT,
            flagged_missing=True,
            kinds=[],
            enabled=False,
        )

        # A second user without an agent credential — for locked-agent-tier guard tests
        self.user_no_agent = _make_vouched_user(
            username="picker_no_agent",
            email="noagent@test.com",
            password="testpass",
        )
        self.profile_no_agent = _make_profile(
            name="No Agent Profile",
            slug="no-agent-profile",
            user=self.user_no_agent,
        )
        self.locked_group = _make_connection(
            self.profile_no_agent,
            destination_id="-1001111003",
            type=TelegramDialogType.GROUP,
            title="Locked Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
        )

        self.client = Client()
        self.client.login(username="picker_write_user", password="testpass")
        self.select_url = lambda pk: reverse("syndication:destination-select", kwargs={"pk": pk})
        self.overlay_url = lambda pk: reverse("syndication:destination-overlay", kwargs={"pk": pk})


# ---------------------------------------------------------------------------
# 1. SELECT / DESELECT — kinds additivity
# ---------------------------------------------------------------------------


class PickerSelectDeselectTest(PickerWriteBaseTest):
    """
    Selecting a postable destination sets kinds=["promotion"] + enabled=True.
    Deselecting removes "promotion" from kinds.
    Existing kinds (e.g. "listing") are preserved.

    NOTE: Use plain dict data (no explicit content_type) so Django test client
    encodes it correctly via multipart. Passing a dict with an explicit
    content_type='application/x-www-form-urlencoded' serializes as Python repr,
    leaving request.POST empty.
    """

    def test_select_channel_sets_promotion_kind_and_enabled(self):
        """POST selected=true on a channel → kinds contains 'promotion', enabled=True."""
        response = self.client.post(
            self.select_url(self.channel.pk),
            data={"selected": "true"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        self.assertIn("promotion", self.channel.kinds)
        self.assertTrue(self.channel.enabled)

    def test_select_group_sets_promotion_kind_and_enabled(self):
        """POST selected=true on a group → kinds contains 'promotion', enabled=True."""
        response = self.client.post(
            self.select_url(self.group.pk),
            data={"selected": "true"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.group.refresh_from_db()
        self.assertIn("promotion", self.group.kinds)
        self.assertTrue(self.group.enabled)

    def test_select_topic_leaf_sets_promotion_kind_and_enabled(self):
        """POST selected=true on a forum topic leaf → kinds contains 'promotion', enabled=True."""
        response = self.client.post(
            self.select_url(self.forum_topic.pk),
            data={"selected": "true"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.forum_topic.refresh_from_db()
        self.assertIn("promotion", self.forum_topic.kinds)
        self.assertTrue(self.forum_topic.enabled)

    def test_select_preserves_existing_listing_kind(self):
        """
        Additive: if kinds was ['listing'], selecting sets kinds to
        contain both 'listing' and 'promotion' (order-insensitive).
        """
        self.channel.kinds = ["listing"]
        self.channel.save(update_fields=["kinds"])

        response = self.client.post(
            self.select_url(self.channel.pk),
            data={"selected": "true"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        self.assertIn("promotion", self.channel.kinds)
        self.assertIn("listing", self.channel.kinds)

    def test_deselect_removes_only_promotion_kind(self):
        """
        Deselect: removes 'promotion' from kinds; other kinds remain.
        """
        self.channel.kinds = ["listing", "promotion"]
        self.channel.save(update_fields=["kinds"])

        response = self.client.post(
            self.select_url(self.channel.pk),
            data={"selected": "false"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        self.assertNotIn("promotion", self.channel.kinds)
        self.assertIn("listing", self.channel.kinds)

    def test_deselect_removes_promotion_leaves_empty_kinds(self):
        """Deselect when only 'promotion' was set → kinds=[]."""
        self.channel.kinds = ["promotion"]
        self.channel.enabled = True
        self.channel.save(update_fields=["kinds", "enabled"])

        response = self.client.post(
            self.select_url(self.channel.pk),
            data={"selected": "false"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        self.assertNotIn("promotion", self.channel.kinds)
        # Fix 5: deselect removes promotion intent, NOT the connection itself.
        # enabled stays True — deselect is kinds-only, not connection disable.
        self.assertTrue(
            self.channel.enabled,
            "Deselect removes 'promotion' from kinds but leaves enabled=True (deselect is NOT connection disable).",
        )


# ---------------------------------------------------------------------------
# 2. Projection-eligibility END-TO-END
# ---------------------------------------------------------------------------


class PickerProjectionEligibilityTest(PickerWriteBaseTest):
    """
    After selecting a destination, creating a Post → PlatformProjection row
    exists for the newly-enabled connection (services.py gate:
    "promotion" in conn.kinds AND conn.enabled).
    Deselect → new Post → no new projection.
    """

    def test_select_then_create_post_yields_projection(self):
        """
        1. Select a channel (sets kinds+enabled).
        2. Create a Post for an event owned by this profile.
        3. Assert PlatformProjection row EXISTS for channel.
        """
        from syndication.services import create_post

        # Select the channel
        self.client.post(
            self.select_url(self.channel.pk),
            data={"selected": "true"},
        )
        self.channel.refresh_from_db()
        self.assertIn("promotion", self.channel.kinds)
        self.assertTrue(self.channel.enabled)

        # Create an event + post
        event = _make_event(self.profile, title="Promo Event", slug="promo-event")
        post = create_post(self.user, event, title="Promo Post")

        projection_count = PlatformProjection.objects.filter(
            connection=self.channel,
            source_post=post,
            kind=PlatformProjection.Kind.PROMOTION,
        ).count()
        self.assertEqual(
            projection_count,
            1,
            f"Expected 1 projection for channel pk={self.channel.pk}, got {projection_count}",
        )

    def test_deselect_then_create_post_yields_no_projection(self):
        """
        1. Connection starts with kinds=["promotion"], enabled=True.
        2. Deselect it.
        3. Create a Post → NO PlatformProjection for that connection.
        """
        from syndication.services import create_post

        # Pre-select
        self.channel.kinds = ["promotion"]
        self.channel.enabled = True
        self.channel.save(update_fields=["kinds", "enabled"])

        # Deselect
        self.client.post(
            self.select_url(self.channel.pk),
            data={"selected": "false"},
        )
        self.channel.refresh_from_db()
        self.assertNotIn("promotion", self.channel.kinds)

        # Create an event + post
        event = _make_event(self.profile, title="No Promo Event", slug="no-promo-event")
        post = create_post(self.user, event, title="No Promo Post")

        projection_count = PlatformProjection.objects.filter(
            connection=self.channel,
            source_post=post,
            kind=PlatformProjection.Kind.PROMOTION,
        ).count()
        self.assertEqual(
            projection_count,
            0,
            f"Expected 0 projections after deselect, got {projection_count}",
        )


# ---------------------------------------------------------------------------
# 3. Server-side guard (ADR-008 D3 FIRM)
# ---------------------------------------------------------------------------


class PickerServerSideGuardTest(PickerWriteBaseTest):
    """
    A forged POST selecting a locked/forum-parent row MUST be rejected 4xx
    with NO kinds mutation.
    """

    def test_select_vanished_connection_returns_4xx(self):
        """
        Selecting a flagged_missing=True connection → 4xx, kinds unchanged.
        """
        response = self.client.post(
            self.select_url(self.vanished.pk),
            data={"selected": "true"},
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.vanished.refresh_from_db()
        self.assertNotIn("promotion", self.vanished.kinds)

    def test_select_locked_agent_tier_no_agent_returns_4xx(self):
        """
        A locked agent-tier connection (user has no agent connected) →
        crafted POST must be rejected 4xx, kinds unchanged.
        The user_no_agent owns this connection, so we log in as them.
        """
        no_agent_client = Client()
        no_agent_client.login(username="picker_no_agent", password="testpass")

        response = no_agent_client.post(
            self.select_url(self.locked_group.pk),
            data={"selected": "true"},
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.locked_group.refresh_from_db()
        self.assertNotIn("promotion", self.locked_group.kinds)

    def test_select_forum_cluster_parent_returns_4xx(self):
        """
        A forum cluster parent (type=group/supergroup WITH forum_topic children,
        has no topic_id itself) → crafted POST must be rejected 4xx, kinds unchanged.
        """
        initial_kinds = list(self.forum_parent.kinds)
        response = self.client.post(
            self.select_url(self.forum_parent.pk),
            data={"selected": "true"},
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.forum_parent.refresh_from_db()
        # Fix 4: full equality proves ZERO mutation, not just absence of "promotion"
        self.assertEqual(self.forum_parent.kinds, initial_kinds)

    def test_select_vanished_connection_zero_mutation(self):
        """Fix 4: vanished guard — assert full kinds equality (not just absence)."""
        initial_kinds = list(self.vanished.kinds)
        response = self.client.post(
            self.select_url(self.vanished.pk),
            data={"selected": "true"},
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.vanished.refresh_from_db()
        self.assertEqual(self.vanished.kinds, initial_kinds)

    def test_select_locked_agent_tier_zero_mutation(self):
        """Fix 4: locked-agent-tier guard — assert full kinds equality (not just absence)."""
        initial_kinds = list(self.locked_group.kinds)
        no_agent_client = Client()
        no_agent_client.login(username="picker_no_agent", password="testpass")
        response = no_agent_client.post(
            self.select_url(self.locked_group.pk),
            data={"selected": "true"},
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.locked_group.refresh_from_db()
        self.assertEqual(self.locked_group.kinds, initial_kinds)

    # Fix 1: Cross-tenant guard test — MUST FAIL with current code (no organizer scope)
    def test_cross_tenant_forum_parent_does_not_block_other_org_plain_group(self):
        """
        Fix 1 — cross-tenant security: Org B has a FORUM_TOPIC at destination_id X.
        Org A has a plain GROUP at the SAME destination_id X.
        Org A's group must remain SELECTABLE — org B's forum must NOT bleed across.
        Also: org A's OWN forum parent (self.forum_parent) IS correctly blocked.
        """
        # Create org B with a FORUM_TOPIC at a shared destination_id
        shared_dest = "-1009999777"
        user_b = _make_vouched_user(
            username="cross_tenant_org_b",
            email="orgb@test.com",
            password="testpass",
        )
        profile_b = _make_profile(name="Org B", slug="org-b", user=user_b)
        AgentCredential.objects.create(user=user_b, key_hash="c" * 64, enabled=True)
        # Org B: forum topic at shared_dest
        _make_connection(
            profile_b,
            destination_id=shared_dest,
            type=TelegramDialogType.FORUM_TOPIC,
            title="Org B Forum Topic",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
            topic_id=9001,
        )

        # Org A: plain GROUP at the same shared_dest (no topic_id)
        org_a_group = _make_connection(
            self.profile,
            destination_id=shared_dest,
            type=TelegramDialogType.GROUP,
            title="Org A Plain Group",
            postability=TelegramPostability.AGENT,
            flagged_missing=False,
            kinds=[],
            enabled=False,
        )

        # Org A selects their plain group → should SUCCEED (2xx), not be blocked by org B's forum
        response = self.client.post(
            self.select_url(org_a_group.pk),
            data={"selected": "true"},
        )
        self.assertIn(
            response.status_code,
            [200, 204],
            f"Org A's plain group was wrongly blocked (status={response.status_code}). "
            "Cross-tenant forum_topic from org B should not affect org A's selectability.",
        )
        org_a_group.refresh_from_db()
        self.assertIn("promotion", org_a_group.kinds)

        # Sanity: org A's own forum parent (self.forum_parent has FORUM_TOPIC in same organizer)
        # is still blocked
        response2 = self.client.post(
            self.select_url(self.forum_parent.pk),
            data={"selected": "true"},
        )
        self.assertGreaterEqual(response2.status_code, 400)
        self.assertLess(response2.status_code, 500)


# ---------------------------------------------------------------------------
# 4. Overlay writer — friendly_name + theme_tags
# ---------------------------------------------------------------------------


class PickerOverlayWriterTest(PickerWriteBaseTest):
    """
    POST friendly_name + theme_tags to the overlay endpoint → persists,
    and the destination_picker response renders the new tag chip.
    """

    def test_overlay_write_persists_friendly_name(self):
        """POST friendly_name → saved to DB."""
        response = self.client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": "My Custom Name", "theme_tags": ""},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.friendly_name, "My Custom Name")

    def test_overlay_write_persists_theme_tags(self):
        """POST theme_tags → saved to DB as a list."""
        response = self.client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": "", "theme_tags": "techno, underground"},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        self.assertIn("techno", self.channel.theme_tags)
        self.assertIn("underground", self.channel.theme_tags)

    def test_overlay_write_reflects_in_picker_tag_filter(self):
        """After saving a tag, the picker page renders a filter chip for it."""
        self.channel.theme_tags = []
        self.channel.save(update_fields=["theme_tags"])

        self.client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": "", "theme_tags": "newtag"},
        )
        response = self.client.get(reverse("syndication:destination-picker"))
        html = response.content.decode("utf-8")
        self.assertIn("newtag", html)

    def test_overlay_write_clears_friendly_name(self):
        """Posting empty friendly_name clears/nulls the override."""
        self.channel.friendly_name = "Old Name"
        self.channel.save(update_fields=["friendly_name"])

        response = self.client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": "", "theme_tags": ""},
        )
        self.assertIn(response.status_code, [200, 204])
        self.channel.refresh_from_db()
        # Empty string or None both mean "no override"
        self.assertFalse(self.channel.friendly_name)

    # Fix 2: friendly_name > 300 chars → 400, NOT a 500
    def test_overlay_friendly_name_too_long_returns_400(self):
        """Fix 2: POST friendly_name > 300 chars → 400, DB unchanged (fail-loud ADR-008 D3)."""
        original_friendly_name = self.channel.friendly_name
        long_name = "x" * 301

        response = self.client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": long_name, "theme_tags": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.channel.refresh_from_db()
        # DB must be unchanged — no silent truncation
        self.assertEqual(self.channel.friendly_name, original_friendly_name)

    def test_overlay_theme_tags_non_list_type_field_oversized_returns_400(self):
        """Fix 2: POST a single tag that is absurdly long → 400, DB unchanged."""
        original_tags = list(self.channel.theme_tags)
        absurd_tag = "y" * 201  # over a sane per-tag limit

        response = self.client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": "", "theme_tags": absurd_tag},
        )
        self.assertEqual(response.status_code, 400)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.theme_tags, original_tags)

    # Fix 3: XSS — tag with single-quote must NOT be interpolated into Alpine JS expressions
    def test_picker_html_does_not_interpolate_tag_into_alpine_expression(self):
        """
        Fix 3: a tag containing a single-quote is dangerous in an Alpine expression attribute
        like @click="selectTag('{{ tag }}')". Django autoescape converts ' to &#x27;, but
        browsers HTML-decode &#x27; back to ' BEFORE Alpine evaluates the expression, so
        the raw injection still fires. The fix must NOT interpolate user data into Alpine
        expression strings at all — use data-attribute approach or escapejs.
        After the fix, the selectTag / activeTag expressions must NOT contain the tag value
        inline (they must reference a data attribute instead), OR the tag must be
        passed through escapejs in a JS-string context that is not HTML-decoded.
        """
        malicious_tag = "x'; alert(1); //"
        self.channel.theme_tags = [malicious_tag]
        self.channel.save(update_fields=["theme_tags"])

        response = self.client.get(reverse("syndication:destination-picker"))
        html = response.content.decode("utf-8")

        # The Alpine @click expression must NOT contain the tag value inline.
        # With the data-attribute fix, @click="selectTag($el.dataset.tag)" — no tag value.
        # With escapejs: the &#x27; HTML-encode issue is avoided at the source.
        # Either way: the rendered HTML must NOT contain the dangerous pattern
        # @click="selectTag('...' where ... resolves to the injection payload.
        # We detect the worst case: &#x27; appears INSIDE an @click selectTag() call.
        self.assertNotIn(
            "selectTag('x&#x27;",
            html,
            "Tag value must NOT be interpolated directly into @click selectTag() expression; "
            "browser HTML-decodes &#x27; back to ' before Alpine evaluates, causing injection.",
        )
        # Also must not contain :class with tag directly
        self.assertNotIn(
            "activeTag === 'x&#x27;",
            html,
            "Tag value must NOT be interpolated directly into :class activeTag expression.",
        )
        # The tag itself should still appear somewhere in the page (so filter still works)
        self.assertIn("alert", html, "Tag text should still appear in the page (safely)")


# ---------------------------------------------------------------------------
# 5. Auth isolation — another user cannot select/edit your connection
# ---------------------------------------------------------------------------


class PickerAuthIsolationTest(PickerWriteBaseTest):
    """
    Another profile's user cannot select or edit your connection (404/403).
    """

    def setUp(self):
        super().setUp()
        self.other_user = _make_vouched_user(
            username="picker_other_write",
            email="otherwrite@test.com",
            password="testpass",
        )
        self.other_client = Client()
        self.other_client.login(username="picker_other_write", password="testpass")

    def test_other_user_cannot_select_channel(self):
        """A user without a claim on the owning profile gets 404."""
        response = self.other_client.post(
            self.select_url(self.channel.pk),
            data={"selected": "true"},
        )
        self.assertIn(response.status_code, [403, 404])
        self.channel.refresh_from_db()
        self.assertNotIn("promotion", self.channel.kinds)

    def test_other_user_cannot_edit_overlay(self):
        """A user without a claim on the owning profile gets 404."""
        response = self.other_client.post(
            self.overlay_url(self.channel.pk),
            data={"friendly_name": "Stolen Name", "theme_tags": ""},
        )
        self.assertIn(response.status_code, [403, 404])
        self.channel.refresh_from_db()
        self.assertNotEqual(self.channel.friendly_name, "Stolen Name")

    def test_unauthenticated_cannot_select(self):
        """Unauthenticated POST to select endpoint redirects (login_required)."""
        anon = Client()
        response = anon.post(
            self.select_url(self.channel.pk),
            data={"selected": "true"},
        )
        self.assertEqual(response.status_code, 302)
        self.channel.refresh_from_db()
        self.assertNotIn("promotion", self.channel.kinds)
