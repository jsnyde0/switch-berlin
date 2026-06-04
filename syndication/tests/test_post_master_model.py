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
