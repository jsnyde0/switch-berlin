"""
Tests for WYSIWYG Telegram composer surface (kb-6yyp).

Contract groups:
(A) One editable styled surface — no textarea + read-only preview split.
    Draft Telegram channels (CHANNEL and GROUP/SUPERGROUP/FORUM_TOPIC) must have
    exactly ONE editable surface — a styled textarea inside the platform-skinned
    body. No separate read-only preview element (<div data-testid="channel-preview">)
    alongside the textarea for the same channel.

(B) Per-destination-type render (D2: channel-post vs group-message+card).
    - CHANNEL type: channel-post framing (NO chat bubble, channel name shown).
    - GROUP/SUPERGROUP/FORUM_TOPIC: group-message (chat bubble) + link-preview card.

(C) Card image URL == card_image_url(event, request).
    For GROUP/SUPERGROUP/FORUM_TOPIC draft Telegram projections, the card image
    URL shown in the WYSIWYG surface equals the resolver output.

(D) Non-Telegram channels unaffected.
    FetLife and Switch channel editor rendering is unchanged by the Telegram
    per-type branching: their existing skins render correctly; no Telegram
    data-testids leak into non-Telegram channels.

(E) Body handling is segment-agnostic.
    No segments schema is reserved at v0 (ADR-016 D7 cheap-foresight + ADR-008 D2 —
    flat body is correct; flat→segments is a cheap squashable pre-launch migration).
    The template/view does not presume exactly one block in a way a later segments
    structure would tear out. An absent/None body context does not break rendering.

Assertions on response.content (NOT response.context — hollow per harness.md).
ADR-016 D7 (FIRM): the styled preview IS the editing surface; editor and preview
are ONE surface.
"""

import tempfile

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from events.models import Event, EventOrganizer
from events.og import card_image_url
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, TelegramDialogType

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


def _make_event(profile, title, slug, description="Test event for WYSIWYG composer."):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
        description=description,
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_telegram_connection(profile, destination_id, dialog_type=None, title=None):
    """Create a Telegram PlatformConnection with an optional TelegramDialogType."""
    conn = PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=["listing"],
        enabled=True,
        type=dialog_type,
        title=title,
    )
    return conn


def _make_draft_projection(event, connection):
    """Create a listing projection in 'draft' status (the editable-bubble path)."""
    cv = ContentVersion.objects.create(
        event=event,
        name="canonical",
        body="Test Telegram body content",
    )
    proj = PlatformProjection.objects.create(
        connection=connection,
        source_event=event,
        content_version=cv,
        kind=PlatformProjection.Kind.LISTING,
        status="draft",
    )
    return proj


def _make_ready_projection(event, connection):
    """Create a listing projection in 'ready' status (the read-only _channel_preview path).

    'ready' projections must have frozen_content set (ADR-016 D5 / ADR-008 D3).
    """
    cv = ContentVersion.objects.create(
        event=event,
        name="canonical",
        body="Test Telegram ready body content",
    )
    proj = PlatformProjection.objects.create(
        connection=connection,
        source_event=event,
        content_version=cv,
        kind=PlatformProjection.Kind.LISTING,
        status="ready",
        frozen_content={"body": "Test Telegram ready body content"},
    )
    return proj


# ---------------------------------------------------------------------------
# (A) One editable styled surface — no textarea + read-only preview split
# ---------------------------------------------------------------------------


class TelegramOneSurfaceTest(TestCase):
    """
    (A) Draft Telegram channels must have exactly ONE surface — the styled
    editable textarea. No separate <div data-testid="channel-preview"> alongside
    it for the same channel (ADR-016 D7 FIRM).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tg_one_user", email="tg_one@test.com", password="pw")
        self.profile = _make_profile("TG One Org", "tg-one-org", user=self.user)
        self.event = _make_event(self.profile, "One Surface Event", "one-surface-event")
        self.client.force_login(self.user)

    def test_draft_telegram_channel_has_editable_textarea(self):
        """
        (A1) A draft Telegram CHANNEL must have a textarea with name='body' —
        the WYSIWYG editing surface.
        """
        conn = _make_telegram_connection(
            self.profile, "my-channel", dialog_type=TelegramDialogType.CHANNEL
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'name="body"',
            content,
            "Draft Telegram CHANNEL must have a textarea with name='body' — "
            "the WYSIWYG editing surface (ADR-016 D7).",
        )

    def test_draft_telegram_group_has_editable_textarea(self):
        """
        (A2) A draft Telegram GROUP must have a textarea with name='body' —
        the WYSIWYG editing surface.
        """
        conn = _make_telegram_connection(
            self.profile, "my-group", dialog_type=TelegramDialogType.GROUP
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'name="body"',
            content,
            "Draft Telegram GROUP must have a textarea with name='body' — "
            "the WYSIWYG editing surface (ADR-016 D7).",
        )

    def test_draft_telegram_channel_has_no_separate_readonly_preview(self):
        """
        (A3) A draft Telegram CHANNEL must NOT have a separate read-only preview
        element (<div data-testid="channel-preview">) alongside the textarea.
        ONE surface only (ADR-016 D7 FIRM).
        """
        conn = _make_telegram_connection(
            self.profile, "my-channel", dialog_type=TelegramDialogType.CHANNEL
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'data-testid="channel-preview"',
            content,
            "Draft Telegram CHANNEL must NOT have a separate read-only channel-preview div — "
            "the styled textarea IS the preview (ONE surface, ADR-016 D7 FIRM).",
        )

    def test_draft_telegram_group_has_no_separate_readonly_preview(self):
        """
        (A4) A draft Telegram GROUP must NOT have a separate read-only preview
        element alongside the textarea. ONE surface only (ADR-016 D7 FIRM).
        """
        conn = _make_telegram_connection(
            self.profile, "my-group", dialog_type=TelegramDialogType.GROUP
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'data-testid="channel-preview"',
            content,
            "Draft Telegram GROUP must NOT have a separate read-only channel-preview div — "
            "the styled textarea IS the preview (ONE surface, ADR-016 D7 FIRM).",
        )


# ---------------------------------------------------------------------------
# (B) Per-destination-type render (D2: channel-post vs group-message+card)
# ---------------------------------------------------------------------------


class TelegramPerTypeRenderTest(TestCase):
    """
    (B) D2: Channel-post framing for CHANNEL; group-message + card for GROUP/SUPERGROUP/FORUM_TOPIC.

    Channel-post marker: data-testid="tg-channel-post" (channel name shown, no chat bubble).
    Group-message marker: data-testid="tg-group-message" (chat bubble style).
    Card marker: data-testid="tg-wysiwyg-card" (link-preview card in the editable surface).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tg_type_user", email="tg_type@test.com", password="pw")
        self.profile = _make_profile("TG Type Org", "tg-type-org", user=self.user)
        self.event = _make_event(self.profile, "Per-Type Render Event", "per-type-render-event")
        self.client.force_login(self.user)

    def test_channel_type_renders_channel_post_framing(self):
        """
        (B1) A Telegram CHANNEL must render with channel-post framing
        (data-testid="tg-channel-post"), NOT a chat bubble.
        """
        conn = _make_telegram_connection(
            self.profile, "my-channel", dialog_type=TelegramDialogType.CHANNEL, title="My Channel"
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'data-testid="tg-channel-post"',
            content,
            "Telegram CHANNEL must render with channel-post framing "
            "(data-testid='tg-channel-post') — bead kb-6yyp D2.",
        )

    def test_channel_type_does_not_render_group_message(self):
        """
        (B2) A Telegram CHANNEL must NOT render the group-message (chat-bubble) style.
        """
        conn = _make_telegram_connection(
            self.profile, "my-channel", dialog_type=TelegramDialogType.CHANNEL
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'data-testid="tg-group-message"',
            content,
            "Telegram CHANNEL must NOT render group-message style — "
            "channel-post framing only (kb-6yyp D2).",
        )

    def test_group_type_renders_group_message_framing(self):
        """
        (B3) A Telegram GROUP must render with group-message (chat bubble) framing
        (data-testid="tg-group-message").
        """
        conn = _make_telegram_connection(
            self.profile, "my-group", dialog_type=TelegramDialogType.GROUP
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'data-testid="tg-group-message"',
            content,
            "Telegram GROUP must render with group-message framing "
            "(data-testid='tg-group-message') — bead kb-6yyp D2.",
        )

    def test_supergroup_type_renders_group_message_framing(self):
        """
        (B4) A Telegram SUPERGROUP must render with group-message (chat bubble) framing.
        """
        conn = _make_telegram_connection(
            self.profile, "my-supergroup", dialog_type=TelegramDialogType.SUPERGROUP
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'data-testid="tg-group-message"',
            content,
            "Telegram SUPERGROUP must render with group-message framing — kb-6yyp D2.",
        )

    def test_forum_topic_type_renders_group_message_framing(self):
        """
        (B5) A Telegram FORUM_TOPIC must render with group-message (chat bubble) framing.
        """
        conn = _make_telegram_connection(
            self.profile, "my-forum", dialog_type=TelegramDialogType.FORUM_TOPIC
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'data-testid="tg-group-message"',
            content,
            "Telegram FORUM_TOPIC must render with group-message framing — kb-6yyp D2.",
        )

    def test_channel_type_does_not_render_wysiwyg_card(self):
        """
        (B6) A Telegram CHANNEL must NOT render the link-preview card.
        Channel posts don't have link-preview cards in the styled surface.
        """
        conn = _make_telegram_connection(
            self.profile, "my-channel", dialog_type=TelegramDialogType.CHANNEL
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'data-testid="tg-wysiwyg-card"',
            content,
            "Telegram CHANNEL must NOT render the link-preview card — "
            "channel-post framing only (kb-6yyp D2).",
        )

    def test_group_type_renders_wysiwyg_card(self):
        """
        (B7) A Telegram GROUP must render the WYSIWYG link-preview card
        (data-testid="tg-wysiwyg-card") as part of the editable surface.
        """
        conn = _make_telegram_connection(
            self.profile, "my-group", dialog_type=TelegramDialogType.GROUP
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'data-testid="tg-wysiwyg-card"',
            content,
            "Telegram GROUP draft must render the WYSIWYG link-preview card "
            "(data-testid='tg-wysiwyg-card') — kb-6yyp D2/D3.",
        )

    def test_null_type_falls_back_to_group_message_framing(self):
        """
        (B8) A Telegram connection with NULL type (legacy / not yet synced)
        must fall back to group-message (chat bubble) framing — not break silently.
        ADR-008 D3: NULL/absent-type path must not break (fail-loud or render gracefully).
        The original chat-bubble style is the safe fallback.
        """
        conn = _make_telegram_connection(
            self.profile, "legacy-channel", dialog_type=None
        )
        _make_draft_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        # Must render without 500 — no silent failure
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # With NULL type, falls back to group-message (existing chat-bubble style)
        self.assertIn(
            'data-testid="tg-group-message"',
            content,
            "Telegram NULL type must fall back to group-message style — "
            "NULL path must not break (ADR-008 D3 fail-loud, no silent zero-fill).",
        )


# ---------------------------------------------------------------------------
# (C) Card image URL == card_image_url(event, request)
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TelegramWysiwygCardImageEqualityTest(TestCase):
    """
    (C) For GROUP/SUPERGROUP/FORUM_TOPIC draft Telegram projections, the
    WYSIWYG link-preview card image URL must equal card_image_url(event, request).
    This is the load-bearing equality: preview == live (ADR-016 D7, D3).
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client()
        self.user = _make_user(username="tg_card_eq_user", email="tg_card_eq@test.com", password="pw")
        self.profile = _make_profile("TG Card Eq Org", "tg-card-eq-org", user=self.user)
        self.client.force_login(self.user)

    def _resolver_url_for(self, event):
        """Return card_image_url(event, request) matching testserver."""
        request = self.factory.get(f"/syndication/events/{event.pk}/fragments/event_syndication/")
        request.META["SERVER_NAME"] = "testserver"
        request.META["SERVER_PORT"] = "80"
        return card_image_url(event, request)

    def test_group_wysiwyg_card_image_equals_resolver(self):
        """
        (C1) For a Telegram GROUP draft projection, the card image URL in the
        rendered WYSIWYG surface equals card_image_url(event, request).
        """
        event = _make_event(
            self.profile,
            "Card Image Eq Event",
            "card-image-eq-event",
            description="Card image equality test.",
        )
        conn = _make_telegram_connection(
            self.profile, "my-group-card", dialog_type=TelegramDialogType.GROUP
        )
        _make_draft_projection(event, conn)

        expected_url = self._resolver_url_for(event)

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            expected_url,
            content,
            f"WYSIWYG GROUP card image must equal card_image_url result '{expected_url}' — "
            "structural equality guarantee (ADR-016 D3, kb-6yyp C).",
        )

    def test_forum_topic_wysiwyg_card_image_equals_resolver(self):
        """
        (C2) For a Telegram FORUM_TOPIC draft projection, the card image URL in the
        rendered WYSIWYG surface equals card_image_url(event, request).
        """
        event = _make_event(
            self.profile,
            "Forum Card Image Event",
            "forum-card-image-event",
            description="Forum topic card image equality test.",
        )
        conn = _make_telegram_connection(
            self.profile, "my-forum-card", dialog_type=TelegramDialogType.FORUM_TOPIC
        )
        _make_draft_projection(event, conn)

        expected_url = self._resolver_url_for(event)

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            expected_url,
            content,
            f"WYSIWYG FORUM_TOPIC card image must equal card_image_url result '{expected_url}' — "
            "structural equality guarantee (ADR-016 D3, kb-6yyp C).",
        )

    def test_wysiwyg_card_image_default_og_asset_for_no_cover(self):
        """
        (C3) WYSIWYG GROUP card image URL contains 'og-default.png' when no cover
        image is set (the default og:image asset).
        """
        event = _make_event(
            self.profile,
            "No Cover Group Event",
            "no-cover-group-event",
        )
        conn = _make_telegram_connection(
            self.profile, "no-cover-group", dialog_type=TelegramDialogType.GROUP
        )
        _make_draft_projection(event, conn)

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "og-default.png",
            content,
            "WYSIWYG GROUP card must show og-default.png when event has no cover — "
            "same as the live og:image.",
        )


# ---------------------------------------------------------------------------
# (A2) _channel_preview.html per-type branching for non-draft projections
# ---------------------------------------------------------------------------
# Finding 1 (kb-6yyp review): _channel_preview.html renders for Telegram when
#   (a) render_error=True AND proj.status == 'draft'  [error-panel only, no content]
#   (b) proj.status != 'draft' AND not editable       [content preview, reached here]
# The per-type branching must be the SAME as _channel_editor.html for case (b).
# The editable WYSIWYG surface (draft path) is always the primary editing path;
# _channel_preview.html is the read-only fallback for approved/staged projections.


class TelegramPreviewPerTypeTest(TestCase):
    """
    (A2) For non-draft (ready/failed) Telegram projections, _channel_preview.html
    must branch per destination type — same framing as the WYSIWYG editor.

    Channel-post framing for CHANNEL; group-message framing for GROUP/NULL.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="tg_preview_user", email="tg_preview@test.com", password="pw"
        )
        self.profile = _make_profile("TG Preview Org", "tg-preview-org", user=self.user)
        self.event = _make_event(self.profile, "TG Preview Event", "tg-preview-event")
        self.client.force_login(self.user)

    def test_ready_channel_renders_channel_post_preview(self):
        """
        (A2.1) A ready Telegram CHANNEL must render the channel-post framing
        (data-testid="tg-channel-post-preview") in the read-only preview.
        """
        conn = _make_telegram_connection(
            self.profile,
            "ready-channel",
            dialog_type=TelegramDialogType.CHANNEL,
            title="Ready Channel",
        )
        _make_ready_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'data-testid="tg-channel-post-preview"',
            content,
            "Ready Telegram CHANNEL must render channel-post-preview framing in "
            "_channel_preview.html (kb-6yyp Finding 1).",
        )

    def test_ready_channel_does_not_render_chat_bubble_preview(self):
        """
        (A2.2) A ready Telegram CHANNEL must NOT render the group-message (chat
        bubble) framing in the read-only preview.
        """
        conn = _make_telegram_connection(
            self.profile,
            "ready-channel-2",
            dialog_type=TelegramDialogType.CHANNEL,
        )
        _make_ready_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Must not render the old group-message bubble in the read-only preview.
        # The only chat-bubble wrapping in _channel_preview is inside the group branch.
        self.assertNotIn(
            "rounded-2xl rounded-tl-sm",
            content,
            "Ready Telegram CHANNEL must NOT render the chat-bubble (group-message) "
            "framing in the read-only preview (kb-6yyp Finding 1).",
        )

    def test_ready_group_renders_group_message_preview(self):
        """
        (A2.3) A ready Telegram GROUP must render the group-message (chat bubble)
        framing in the read-only preview — same visual as the WYSIWYG editor.
        """
        conn = _make_telegram_connection(
            self.profile,
            "ready-group",
            dialog_type=TelegramDialogType.GROUP,
        )
        _make_ready_projection(self.event, conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Group-message in the preview uses the same chat-bubble HTML.
        self.assertIn(
            "rounded-2xl rounded-tl-sm",
            content,
            "Ready Telegram GROUP must render the chat-bubble (group-message) "
            "framing in the read-only preview (kb-6yyp Finding 1).",
        )


# ---------------------------------------------------------------------------
# (D) Non-Telegram channels unaffected
# ---------------------------------------------------------------------------


class NonTelegramChannelsUnaffectedTest(TestCase):
    """
    (D) Regression: FetLife and Switch channel editor rendering is unchanged by
    the Telegram per-type branching introduced in kb-6yyp.

    Specifically:
    - FetLife renders its own platform skin (warm-purple body text).
    - Switch listing renders the EventForm card (fuchsia hairline accent).
    - Neither renders Telegram data-testids (tg-channel-post, tg-group-message,
      tg-wysiwyg-card, tg-channel-post-preview).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="non_tg_user", email="non_tg@test.com", password="pw"
        )
        self.profile = _make_profile("Non-TG Org", "non-tg-org", user=self.user)
        self.event = _make_event(self.profile, "Non-TG Event", "non-tg-event")
        self.client.force_login(self.user)

    def _make_connection(self, platform, destination_id, kinds):
        return PlatformConnection.objects.create(
            organizer=self.profile,
            platform=platform,
            destination_id=destination_id,
            kinds=kinds,
            enabled=True,
        )

    def _make_projection(self, connection):
        cv = ContentVersion.objects.create(
            event=self.event,
            name="canonical",
            body="Non-TG body content",
        )
        return PlatformProjection.objects.create(
            connection=connection,
            source_event=self.event,
            content_version=cv,
            kind=PlatformProjection.Kind.LISTING,
            status="draft",
        )

    def test_fetlife_renders_platform_skin_no_telegram_testids(self):
        """
        (D1) A FetLife draft projection must render the FetLife warm-purple
        body skin and must NOT emit any Telegram data-testids.
        """
        conn = self._make_connection("fetlife", "my-fetlife", ["listing"])
        self._make_projection(conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # FetLife warm-purple text colour — present in the editor textarea styling.
        self.assertIn(
            "rgb(210 165 230",
            content,
            "FetLife must render its warm-purple body skin.",
        )
        # No Telegram testids must leak into a FetLife channel.
        for testid in (
            'data-testid="tg-channel-post"',
            'data-testid="tg-group-message"',
            'data-testid="tg-wysiwyg-card"',
            'data-testid="tg-channel-post-preview"',
        ):
            self.assertNotIn(
                testid,
                content,
                f"FetLife channel must NOT contain Telegram testid {testid!r}.",
            )

    def test_switch_listing_renders_eventform_card_no_telegram_testids(self):
        """
        (D2) A Switch listing draft projection must render the EventForm card
        (fuchsia hairline accent) and must NOT emit any Telegram data-testids.
        """
        conn = self._make_connection("switch", "own-page", ["listing"])
        self._make_projection(conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Switch EventForm card renders a fuchsia hairline accent div.
        self.assertIn(
            "rgb(248 113 196",
            content,
            "Switch listing must render its fuchsia hairline accent (EventForm card).",
        )
        # No Telegram testids must leak into a Switch channel.
        for testid in (
            'data-testid="tg-channel-post"',
            'data-testid="tg-group-message"',
            'data-testid="tg-wysiwyg-card"',
            'data-testid="tg-channel-post-preview"',
        ):
            self.assertNotIn(
                testid,
                content,
                f"Switch channel must NOT contain Telegram testid {testid!r}.",
            )


# ---------------------------------------------------------------------------
# (E) Body handling is segment-agnostic
# ---------------------------------------------------------------------------


class BodySegmentAgnosticTest(TestCase):
    """
    (E) No segments schema is reserved at v0.

    ADR-016 D7 cheap-foresight + ADR-008 D2: a flat `body` field is correct at
    v0; the future flat→ordered-segments change is a cheap, squashable pre-launch
    migration (ADR-008 D1), not the painful rewrite cheap-foresight exists to
    prevent. Reserving an unused `segments` schema now would be the speculative
    abstraction ADR-008 D2 forbids (extract from the third diverging caller —
    the first thread-native platform, Twitter/Bluesky). So: no segments field,
    no splitting logic; only ensure body handling is segment-agnostic.

    What "segment-agnostic" means in practice:
    - The template/view does NOT presume exactly one block in a way a future
      ordered-segments structure would have to tear out (e.g. no parse/transform
      that relies on the body being a single unbreakable unit).
    - An empty/None body context does not cause a crash or blank-out — the
      textarea renders gracefully with the placeholder.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="seg_user", email="seg@test.com", password="pw"
        )
        self.profile = _make_profile("Seg Org", "seg-org", user=self.user)
        self.client.force_login(self.user)

    def test_empty_body_renders_gracefully_for_telegram_group(self):
        """
        (E1) A Telegram GROUP draft projection with an empty body (None / empty
        string) must render without crashing and must still show the editable
        textarea surface. The flat body is the correct v0 representation — the
        future flat→segments change is a squashable migration (ADR-016 D7 + ADR-008 D2).
        """
        event = _make_event(self.profile, "Seg Event", "seg-event")
        conn = _make_telegram_connection(
            self.profile, "seg-group", dialog_type=TelegramDialogType.GROUP
        )
        # ContentVersion with empty body — None resolves to "" at render time.
        cv = ContentVersion.objects.create(
            event=event,
            name="canonical",
            body=None,
        )
        PlatformProjection.objects.create(
            connection=conn,
            source_event=event,
            content_version=cv,
            kind=PlatformProjection.Kind.LISTING,
            status="draft",
        )

        url = f"/syndication/events/{event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        # Must not 500 — an absent body is a valid v0 draft state.
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The editable surface must still render (textarea present).
        self.assertIn(
            'name="body"',
            content,
            "An empty body must still render the editable textarea surface — "
            "no crash, no blank-out (ADR-016 D7 + ADR-008 D3).",
        )
        # The group-message framing must render (body content or not).
        self.assertIn(
            'data-testid="tg-group-message"',
            content,
            "An empty body must still render the group-message framing — "
            "framing does not depend on body content.",
        )
