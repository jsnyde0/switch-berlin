"""
Post master model tests (kb-shzi.4).

Contract under test:
1. CAPABILITY-AWARE GATE (ADR-008 D3 + ADR-010 D1):
   Switch does not support the 'promotion' kind yet (capability-level constraint).
   _eager_create_promotion_projections MUST NOT mint a switch promotion projection
   for posts — even if a switch connection has 'promotion' in its kinds.
   Other platforms (telegram, fetlife) with 'promotion' in kinds STILL get
   their promotion projection (the gate is switch-specific, not global).

2. RELABEL master anchor (ADR-010 D1 cheap-foresight):
   The post composer renders the master anchor labeled 'Master copy' (NOT 'Source').
   Helper text ("edits here feed every channel" or similar) is present.
   The abstract canonical anchor tab key ('source') still functions (kb-shzi.2
   selected_pk='source' default must not be broken).

3. REGRESSION guard:
   Editing the master copy (canonical CV) still feeds channels (existing sync
   mechanism not broken).
   kb-shzi.2 server-driven selected_pk survives for posts (tab-persistence).

Assertions are on response.content (NOT response.context — hollow-test anti-pattern).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection, Post

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


def _make_connection(organizer, platform, destination_id, kinds, enabled=True):
    return PlatformConnection.objects.create(
        organizer=organizer,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# 1. Capability gate: Switch does NOT get a promotion projection for posts
# ---------------------------------------------------------------------------


class SwitchPromotionProjectionGateTest(TestCase):
    """
    ADR-010 D1 + ADR-008 D3: Switch does not support 'promotion' for posts yet.
    _eager_create_promotion_projections must NOT mint a switch promotion projection
    even if the switch connection has 'promotion' in its kinds.

    The gate is capability-aware (platform=switch is listing-only at the minting
    layer), not a hard ban on 'promotion' for switch globally — that would fight
    the cheap-foresight flip. Other platforms with 'promotion' STILL get theirs.
    """

    def setUp(self):
        self.user = _make_user(username="sg_user", email="sg@test.com", password="pw")
        self.profile = _make_profile("SG Org", "sg-org", user=self.user)
        self.event = _make_event(self.profile, "SG Event", "sg-event")
        self.post = _make_post(self.event, "SG Post")

    def test_switch_promotion_projection_not_minted_even_with_promotion_in_kinds(self):
        """
        RED: _eager_create_promotion_projections must NOT mint a switch promotion
        projection even if switch connection has kinds=['listing', 'promotion'].
        """
        switch_conn = _make_connection(self.profile, "switch", "sg-switch-page", kinds=["listing", "promotion"])

        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        switch_promo_projs = PlatformProjection.objects.filter(
            connection=switch_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            source_post=self.post,
        )
        self.assertEqual(
            switch_promo_projs.count(),
            0,
            "Switch must NOT get a promotion projection for posts "
            "(capability-aware gate: Switch does not support post promotion yet).",
        )

    def test_telegram_promotion_projection_still_minted(self):
        """
        The capability gate is switch-specific. Telegram with 'promotion' in kinds
        MUST still get a promotion projection — the gate does NOT globally disable
        promotion projection minting.
        """
        telegram_conn = _make_connection(self.profile, "telegram", "sg-telegram-channel", kinds=["promotion"])

        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        telegram_promo_projs = PlatformProjection.objects.filter(
            connection=telegram_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            source_post=self.post,
        )
        self.assertEqual(
            telegram_promo_projs.count(),
            1,
            "Telegram (non-switch) with 'promotion' in kinds MUST still get "
            "a promotion projection — the gate is switch-specific.",
        )

    def test_fetlife_promotion_projection_still_minted(self):
        """
        FetLife with 'promotion' in kinds MUST still get a promotion projection.
        The switch capability gate must not affect other platforms.
        """
        fetlife_conn = _make_connection(self.profile, "fetlife", "sg-fetlife-user", kinds=["listing", "promotion"])

        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        fetlife_promo_projs = PlatformProjection.objects.filter(
            connection=fetlife_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            source_post=self.post,
        )
        self.assertEqual(
            fetlife_promo_projs.count(),
            1,
            "FetLife with 'promotion' in kinds MUST still get a promotion projection.",
        )

    def test_mixed_connections_only_non_switch_get_promotion_projections(self):
        """
        When switch + telegram + fetlife all have 'promotion' in their kinds,
        only telegram and fetlife get promotion projections — switch does not.
        """
        switch_conn = _make_connection(self.profile, "switch", "mix-switch-page", kinds=["listing", "promotion"])
        telegram_conn = _make_connection(self.profile, "telegram", "mix-telegram-channel", kinds=["promotion"])
        fetlife_conn = _make_connection(self.profile, "fetlife", "mix-fetlife-user", kinds=["listing", "promotion"])

        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        all_promo_projs = PlatformProjection.objects.filter(
            source_post=self.post,
            kind=PlatformProjection.Kind.PROMOTION,
        )
        self.assertEqual(
            all_promo_projs.count(),
            2,
            "Only 2 promotion projections (telegram + fetlife) — switch must be excluded.",
        )
        conn_ids = set(all_promo_projs.values_list("connection_id", flat=True))
        self.assertIn(telegram_conn.pk, conn_ids)
        self.assertIn(fetlife_conn.pk, conn_ids)
        self.assertNotIn(switch_conn.pk, conn_ids)


# ---------------------------------------------------------------------------
# 2. No spurious Switch tab in post composer when switch has 'promotion' in kinds
# ---------------------------------------------------------------------------


class NoSwitchPromoTabInPostComposerTest(TestCase):
    """
    ADR-010 D1: No spurious 'Switch' promo tab appears in the post composer
    when a switch connection has 'promotion' in its kinds.

    Assertions are on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="nst_user", email="nst@test.com", password="pw")
        self.profile = _make_profile("NST Org", "nst-org", user=self.user)
        self.event = _make_event(self.profile, "NST Event", "nst-event")
        self.post = _make_post(self.event, "NST Post Headline")

        # Switch connection with 'promotion' in kinds — the spurious tab case
        self.switch_conn = _make_connection(self.profile, "switch", "nst-switch-page", kinds=["listing", "promotion"])
        # Telegram with 'promotion' — MUST still appear
        self.telegram_conn = _make_connection(self.profile, "telegram", "nst-telegram-channel", kinds=["promotion"])

        # Manually trigger promotion projections (connections added after post)
        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        self.client.force_login(self.user)

    def test_switch_promo_tab_absent_from_post_composer(self):
        """
        The post composer must NOT show a switch promotion tab
        even when the switch connection has 'promotion' in its kinds.
        We identify the switch connection by its destination_id.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "nst-switch-page",
            content,
            "Switch must NOT appear as a tab in the post composer — "
            "no switch promotion projection should be minted for posts.",
        )

    def test_telegram_promo_tab_still_present_in_post_composer(self):
        """
        Telegram with 'promotion' MUST still appear in the post composer.
        The switch gate must not disable other platforms' promotion tabs.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "nst-telegram-channel",
            content,
            "Telegram with 'promotion' MUST appear in the post composer tab row.",
        )


# ---------------------------------------------------------------------------
# 3. Post anchor relabeled 'Master copy' with helper text
# ---------------------------------------------------------------------------


class PostMasterAnchorLabelTest(TestCase):
    """
    ADR-010 D1 cheap-foresight: The post composer's canonical anchor tab must
    be labeled 'Master copy' (not 'Source') with helper text indicating that
    edits here feed every channel.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="pal_user", email="pal@test.com", password="pw")
        self.profile = _make_profile("PAL Org", "pal-org", user=self.user)
        self.event = _make_event(self.profile, "PAL Event", "pal-event")
        self.post = _make_post(self.event, "PAL Post Headline")
        self.client.force_login(self.user)

    def test_post_composer_renders_master_copy_label(self):
        """
        The post composer anchor tab must use 'Master copy' as its label,
        not 'Source' or 'canonical'.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Master copy",
            content,
            "Post composer anchor tab must be labeled 'Master copy'.",
        )

    def test_post_composer_renders_helper_text_about_channel_feeding(self):
        """
        The anchor tab must include helper text indicating edits feed every channel.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Helper text must indicate that edits here feed every channel.
        # Accept any reasonable phrasing containing 'channel' or 'feed'.
        # The actual text per bead spec: "edits here feed every channel"
        helper_phrases = ["edits here feed every channel", "feed every channel", "feeds every channel"]
        found_helper = any(phrase in content for phrase in helper_phrases)
        self.assertTrue(
            found_helper,
            "Post composer anchor must include helper text about feeding every channel. "
            f"Expected one of: {helper_phrases!r}. "
            "Content excerpt: " + content[content.find("Master copy") - 50 : content.find("Master copy") + 200]
            if "Master copy" in content
            else "Content does not contain 'Master copy' at all.",
        )

    def test_post_composer_selected_pk_source_default_still_works(self):
        """
        kb-shzi.2 regression: the 'source' tab key for x-data selectedPk must
        still be present (the server-driven selected_pk default). The template
        must contain selectedPk: 'source' as the fallback in the x-data attribute
        so Alpine defaults to the master anchor tab.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # x-data block seeds selectedPk to 'source' when no other pk is selected
        self.assertIn(
            "'source'",
            content,
            "x-data must still contain 'source' as the selectedPk default "
            "so the master anchor tab is selected when no other pk is active.",
        )

    def test_post_composer_master_anchor_panel_shown_when_source_selected(self):
        """
        The master anchor panel must use x-show="selectedPk === 'source'" —
        still controlled by the 'source' key (kb-shzi.2 compatibility).
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "selectedPk === 'source'",
            content,
            "Master anchor panel x-show must use selectedPk === 'source' "
            "so the 'source' Alpine key still controls visibility (kb-shzi.2 compat).",
        )

    def test_post_composer_selected_pk_server_driven_survives_for_non_source_tab(self):
        """
        kb-shzi.2: When selected_pk is posted, the re-rendered fragment opens
        that tab. We verify that a non-source tab selection (via POST with
        selected_pk) is reflected in the x-data selectedPk seed in the response.
        """
        # Create a telegram connection + projection so a non-source tab exists
        telegram_conn = _make_connection(self.profile, "telegram", "pal-telegram-for-selected-pk", kinds=["promotion"])
        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        proj = PlatformProjection.objects.get(connection=telegram_conn, source_post=self.post)

        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        # POST with selected_pk simulates what customize/reset/duplicate do
        response = self.client.post(url, data={"selected_pk": str(proj.pk)})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # x-data should seed selectedPk to the posted pk (not 'source')
        self.assertIn(
            str(proj.pk),
            content,
            "When selected_pk is posted, the fragment should seed selectedPk to that pk.",
        )


# ---------------------------------------------------------------------------
# 4. FINDING 13: has_promotion_connections excludes non-capable platforms
#    A Switch connection with 'promotion' in kinds must NOT make the event board
#    show the "Add promo message" CTA — Switch can't deliver promo posts.
# ---------------------------------------------------------------------------


class EventBoardNoPromoCTAForSwitchOnlyTest(TestCase):
    """
    FINDING 13 (user-facing): When the ONLY promotion-capable connections belong
    to Switch (which does not support post promotion), the event board must NOT
    display the "Add promo message" / "No promo posts yet" CTA, because creating
    a post would yield no Switch channel tab — an invite-with-no-result.

    Fix: has_promotion_connections must also check _supports_post_promotion(conn.platform).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="f13_user", email="f13@test.com", password="pw")
        self.profile = _make_profile("F13 Org", "f13-org", user=self.user)
        self.event = _make_event(self.profile, "F13 Event", "f13-event")
        # Switch-only connection with 'promotion' in kinds — the broken case
        self.switch_conn = _make_connection(self.profile, "switch", "f13-switch-page", kinds=["listing", "promotion"])
        self.client.force_login(self.user)

    def test_event_board_does_not_show_add_promo_cta_for_switch_only_connection(self):
        """
        When only a Switch connection has 'promotion' in kinds, the event board
        must NOT show the 'Add promo message' CTA — Switch cannot deliver promo posts,
        so showing the CTA leads to an invite-with-no-result (FINDING 13).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The CTA text appears when no_promo_posts is True in the template.
        # With a Switch-only promo connection, has_promotion_connections must be False
        # so no_promo_posts is False and the CTA is suppressed.
        self.assertNotIn(
            "Add promo message",
            content,
            "Event board must NOT show 'Add promo message' CTA when the only "
            "promotion connection is Switch (Switch cannot deliver promo posts).",
        )

    def test_event_board_shows_add_promo_cta_with_telegram_connection(self):
        """
        Regression: when a real promotion-capable connection (Telegram) exists,
        the 'Add promo message' CTA IS shown.
        """
        _make_connection(self.profile, "telegram", "f13-telegram-channel", kinds=["promotion"])

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Add promo message",
            content,
            "Event board MUST show 'Add promo message' CTA when a real "
            "promotion-capable connection (e.g. Telegram) exists.",
        )


# ---------------------------------------------------------------------------
# 5. FINDING 4: Post composer excludes Switch promo tabs from legacy DB state
#    Even if a Switch promotion projection exists in DB (pre-existing legacy data),
#    the post composer must NOT render it as a tab (render-level filter).
# ---------------------------------------------------------------------------


class LegacySwitchPromoTabFilteredAtRenderTest(TestCase):
    """
    FINDING 4 (robustness): The post composer's projection filter must exclude
    projections whose connection.platform does not support post promotion —
    even if those projections already exist in the database (legacy/force-created).

    This makes the 'no spurious Switch tab' guarantee hold regardless of DB state,
    not just for new posts (which are guarded by the mint-time gate).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="f4_user", email="f4@test.com", password="pw")
        self.profile = _make_profile("F4 Org", "f4-org", user=self.user)
        self.event = _make_event(self.profile, "F4 Event", "f4-event")
        self.post = _make_post(self.event, "F4 Post Headline")

        # Switch connection with 'promotion' in kinds
        self.switch_conn = _make_connection(self.profile, "switch", "f4-switch-page", kinds=["listing", "promotion"])
        # Force-create a Switch promotion projection directly in DB
        # (simulating legacy data that pre-dates the mint-time gate)
        from syndication.models import ContentVersion

        switch_cv = ContentVersion.objects.create(
            post=self.post,
            name="legacy-switch-canonical",
        )
        self.switch_proj = PlatformProjection.objects.create(
            connection=self.switch_conn,
            source_post=self.post,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            content_version=switch_cv,
        )

        # Also add a Telegram connection + projection so we have something to show
        self.telegram_conn = _make_connection(self.profile, "telegram", "f4-telegram-channel", kinds=["promotion"])
        from syndication.services import _eager_create_promotion_projections

        _eager_create_promotion_projections(self.post)

        self.client.force_login(self.user)

    def test_switch_promo_tab_absent_even_with_legacy_db_projection(self):
        """
        Even if a Switch promotion projection exists in DB (force-created / legacy),
        the post composer must NOT render it as a tab.

        This is FINDING 4: the render-level filter must apply _supports_post_promotion,
        not just the kinds filter, so the guarantee holds regardless of DB state.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            "f4-switch-page",
            content,
            "Post composer must NOT render a Switch promo tab even when a Switch "
            "promotion projection exists in DB (render-level capability filter — FINDING 4).",
        )

    def test_telegram_promo_tab_still_present_with_legacy_switch_projection(self):
        """
        Regression: Telegram must still appear in the post composer tabs
        even when a legacy Switch projection is in DB and filtered out.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "f4-telegram-channel",
            content,
            "Telegram must still appear in post composer tabs — "
            "filtering out legacy Switch projection must not affect other platforms.",
        )
