"""
TDD tests for the Telegram channel promotion adapter (kb-a4u.14).

Acceptance items covered:
(a) Happy path → published, external_id == str(message_id), syndicated_at set.
(b) status != ready → raises, status unchanged (no transition).
(c) kind != promotion → raises.
(d) missing source_post → status == failed + raises.
(e) transport error → exactly 3 attempts (assert call count == 3), final status == failed, raises.
(f) HTTP 400 → exactly 1 attempt, status == failed, raises.
    200 with {"ok": false} → exactly 1 attempt, status == failed, raises.
(g) visibility-agnostic: event.visibility = "unlisted" → still publishes.
(h) token resolution: connection.credentials = {"bot_token": "override"} → override
    token in request URL; empty credentials → settings.TELEGRAM_BOT_TOKEN used.

ADR-008 D2: no speculative adapter abstraction.
ADR-008 D3: fail loud on data-integrity failures.
ADR-008 D4: transport errors retry ≤2 times (3 total attempts); data-integrity errors no retry.
ADR-016 carried-forward (REVISED): NO visibility gate.
"""

from unittest.mock import MagicMock, call, patch

import httpx
from django.test import TestCase, override_settings
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile
from syndication.engine import generate_projection, transition_status
from syndication.models import PlatformConnection, PlatformProjection, Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(slug="tg-test-org"):
    return Profile.objects.create(name="Telegram Test Organizer", slug=slug)


def _make_event(slug="tg-test-event", visibility="public", **kwargs):
    defaults = {
        "title": "Telegram Test Party",
        "slug": slug,
        "start": timezone.now(),
        "status": "published",
        "visibility": visibility,
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, headline="Save the Date!", body="Come join us for a night of fun."):
    return Post.objects.create(event=event, headline=headline, body=body)


def _make_telegram_connection(profile, destination_id="-1001234567890", credentials=None):
    """Create a Telegram PlatformConnection."""
    if credentials is None:
        credentials = {}
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=["promotion"],
        credentials=credentials,
    )


def _seed_canonical_cv(event):
    """
    Get-or-create the canonical ContentVersion for an event.
    Required by the F1 non-null content_version FK (kb-wz8m.2 A1 invariant).
    """
    from syndication.models import ContentVersion
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


def _make_ready_promotion_projection(connection, post):
    """
    Generate a promotion projection and advance it to ready status.
    Uses generate_projection + transition_status (never direct .status write).
    """
    proj = generate_projection(
        kind="promotion",
        connection=connection,
        source_post=post,
        mode="rule_based",
    )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    return proj


def _make_bot_api_success_response(message_id=42):
    """Return a MagicMock that looks like a successful Telegram Bot API response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "result": {"message_id": message_id},
    }
    return mock_response


# ---------------------------------------------------------------------------
# (a) Happy path
# ---------------------------------------------------------------------------


class TelegramPublishHappyPathTest(TestCase):
    """
    publish_telegram_promotion: happy path.
    On success, projection reaches status=published, external_id = str(message_id),
    syndicated_at is stamped.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-happy-org")
        self.event = _make_event(slug="tg-happy-event")
        EventOrganizer.objects.create(
            event=self.event, profile=self.profile, is_primary=True
        )
        self.post = _make_post(self.event)
        self.conn = _make_telegram_connection(self.profile)
        self.proj = _make_ready_promotion_projection(self.conn, self.post)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_happy_path_reaches_published(self, mock_post):
        mock_post.return_value = _make_bot_api_success_response(message_id=42)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.PUBLISHED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_happy_path_sets_external_id_to_message_id(self, mock_post):
        mock_post.return_value = _make_bot_api_success_response(message_id=99)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.external_id, "99")

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_happy_path_stamps_syndicated_at(self, mock_post):
        mock_post.return_value = _make_bot_api_success_response(message_id=42)
        before = timezone.now()

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(self.proj)
        self.proj.refresh_from_db()
        self.assertIsNotNone(self.proj.syndicated_at)
        self.assertGreaterEqual(self.proj.syndicated_at, before)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_happy_path_makes_exactly_one_api_call(self, mock_post):
        mock_post.return_value = _make_bot_api_success_response(message_id=42)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(self.proj)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_happy_path_payload_contains_chat_id_and_text(self, mock_post):
        """
        Fix E: assert that the json= kwarg sent to httpx.post contains
        chat_id == connection.destination_id and text == render_projection(projection).
        Guards against regressions that drop text or use the wrong channel.
        """
        mock_post.return_value = _make_bot_api_success_response(message_id=42)

        from syndication.adapters import publish_telegram_promotion
        from syndication.engine import render_projection

        expected_text = render_projection(self.proj)
        publish_telegram_promotion(self.proj)

        call_kwargs = mock_post.call_args[1]  # keyword args
        sent_payload = call_kwargs["json"]
        self.assertEqual(sent_payload["chat_id"], self.conn.destination_id)
        self.assertEqual(sent_payload["text"], expected_text)
        self.assertTrue(len(sent_payload["text"]) > 0)


# ---------------------------------------------------------------------------
# (b) Precondition: status != ready
# ---------------------------------------------------------------------------


class TelegramPublishStatusPreconditionTest(TestCase):
    """
    publish_telegram_promotion requires status=ready.
    If status != ready, raises ValueError without any status transition.
    (draft→failed is illegal; the guard must fire before any transition.)
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-status-guard-org")
        self.event = _make_event(slug="tg-status-guard-event")
        self.post = _make_post(self.event)
        self.conn = _make_telegram_connection(self.profile)

    def test_draft_status_raises_without_transition(self):
        """A draft projection raises ValueError; status stays draft."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            connection=self.conn,
            source_post=self.post,
            content_version=_seed_canonical_cv(self.event),
            frozen_content={"body": "test body", "headline": "test"},
        )

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError) as ctx:
            publish_telegram_promotion(proj)

        # Must name the precondition
        error_msg = str(ctx.exception)
        self.assertIn("ready", error_msg.lower())

        # Status must NOT have changed (draft→failed is illegal — the guard fires first)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)

    def test_published_status_raises(self):
        """An already-published projection raises ValueError."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.PUBLISHED,
            connection=self.conn,
            source_post=self.post,
            content_version=_seed_canonical_cv(self.event),
            frozen_content={"body": "test body", "headline": "test"},
            external_id="123",
        )

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.PUBLISHED)


# ---------------------------------------------------------------------------
# (c) Precondition: kind != promotion
# ---------------------------------------------------------------------------


class TelegramPublishKindGuardTest(TestCase):
    """
    publish_telegram_promotion only handles kind=promotion.
    A listing projection must raise ValueError.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-kind-guard-org")
        self.event = _make_event(slug="tg-kind-guard-event")
        self.conn = _make_telegram_connection(self.profile)

    def test_listing_kind_raises(self):
        """A listing-kind projection raises ValueError (Telegram is promotion-only)."""
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_event=self.event,
            content_version=_seed_canonical_cv(self.event),
            frozen_content={"body": "listing body", "title": "test"},
        )

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError) as ctx:
            publish_telegram_promotion(proj)

        error_msg = str(ctx.exception)
        self.assertIn("promotion", error_msg.lower())


# ---------------------------------------------------------------------------
# (d) Data integrity: missing source_post → failed + raises
# ---------------------------------------------------------------------------


class TelegramPublishMissingSourcePostTest(TestCase):
    """
    ADR-008 D3: if source_post is missing, transition→failed and raise ValueError.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-no-post-org")
        self.conn = _make_telegram_connection(self.profile)

    def test_missing_source_post_transitions_to_failed_and_raises(self):
        """source_post=None → status=failed + ValueError."""
        # Need a ContentVersion even though source_post is None — use a standalone event.
        from events.models import Event
        from django.utils import timezone as tz
        orphan_event = Event.objects.create(
            title="Orphan Event",
            slug="orphan-event-tg-missing-post",
            start=tz.now(),
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.READY,
            connection=self.conn,
            source_post=None,
            content_version=_seed_canonical_cv(orphan_event),
            frozen_content={"body": "promo body", "headline": "test"},
        )

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)


# ---------------------------------------------------------------------------
# (e) Transport error retry: exactly 3 attempts, final status=failed, raises
# ---------------------------------------------------------------------------


class TelegramPublishTransportRetryTest(TestCase):
    """
    ADR-008 D4: transport errors (httpx.TransportError) get up to 2 retries
    (3 total attempts). After final failure → status=failed + raise.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-retry-org")
        self.event = _make_event(slug="tg-retry-event")
        self.post = _make_post(self.event)
        self.conn = _make_telegram_connection(self.profile)
        self.proj = _make_ready_promotion_projection(self.conn, self.post)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("syndication.adapters.time.sleep")  # patch at adapter's symbol for meaningful assertion
    @patch("httpx.post")
    def test_transport_error_retries_3_times_total_then_fails(self, mock_post, mock_sleep):
        """
        ConnectError (a TransportError) causes exactly 3 attempts, then
        status=failed and the exception propagates as ValueError.
        Sleep fires after attempt 0 and attempt 1 (not after final attempt 2) → 2 calls.
        """
        mock_post.side_effect = httpx.ConnectError("connection refused")

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(self.proj)

        # Exactly 3 attempts: 1 original + 2 retries
        self.assertEqual(mock_post.call_count, 3)
        # Sleep fires after attempt 0 and attempt 1, NOT after final attempt 2
        self.assertEqual(mock_sleep.call_count, 2)

        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.FAILED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("syndication.adapters.time.sleep")  # patch at adapter's symbol for meaningful assertion
    @patch("httpx.post")
    def test_read_timeout_retries_3_times_total(self, mock_post, mock_sleep):
        """ReadTimeout is also a TransportError — same 3-attempt policy. Raises ValueError."""
        mock_post.side_effect = httpx.ReadTimeout("timed out")

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(self.proj)

        self.assertEqual(mock_post.call_count, 3)
        # Sleep fires after attempt 0 and attempt 1, NOT after final attempt 2
        self.assertEqual(mock_sleep.call_count, 2)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.FAILED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("syndication.adapters.time.sleep")  # patch at adapter's symbol for meaningful assertion
    @patch("httpx.post")
    def test_transport_error_then_success_retries_and_publishes(self, mock_post, mock_sleep):
        """
        Two ConnectErrors followed by a success response:
        - function succeeds, projection reaches published
        - external_id == "999"
        - mock_post.call_count == 3
        - mock_sleep.call_count == 2 (sleep after attempt 0 and attempt 1)
        """
        success_response = _make_bot_api_success_response(message_id=999)
        mock_post.side_effect = [
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            success_response,
        ]

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(self.proj)

        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.PUBLISHED)
        self.assertEqual(self.proj.external_id, "999")


# ---------------------------------------------------------------------------
# (f) HTTP error / API error: exactly 1 attempt, status=failed, raises
# ---------------------------------------------------------------------------


class TelegramPublishApiErrorTest(TestCase):
    """
    ADR-008 D4: data-integrity errors (HTTP 4xx/5xx OR ok=false in response)
    get NO retry — exactly 1 attempt, status=failed, raises ValueError.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-apierr-org")
        self.event = _make_event(slug="tg-apierr-event")
        self.post = _make_post(self.event)
        self.conn = _make_telegram_connection(self.profile)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_http_400_no_retry_status_failed(self, mock_post):
        """HTTP 400 → exactly 1 attempt, status=failed, raises."""
        proj = _make_ready_promotion_projection(self.conn, self.post)

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "ok": False,
            "description": "Bad Request: chat not found",
        }
        mock_post.return_value = mock_response

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        self.assertEqual(mock_post.call_count, 1)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_http_500_no_retry_status_failed(self, mock_post):
        """HTTP 500 → exactly 1 attempt, status=failed, raises."""
        proj = _make_ready_promotion_projection(self.conn, self.post)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        self.assertEqual(mock_post.call_count, 1)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_ok_false_in_200_response_no_retry_status_failed(self, mock_post):
        """HTTP 200 but {"ok": false} → exactly 1 attempt, status=failed, raises."""
        proj = _make_ready_promotion_projection(self.conn, self.post)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": False,
            "description": "Forbidden: bot was kicked from the channel chat",
        }
        mock_post.return_value = mock_response

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        self.assertEqual(mock_post.call_count, 1)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)


# ---------------------------------------------------------------------------
# (f2) Malformed HTTP 200 responses: Fix A coverage
# ---------------------------------------------------------------------------


class TelegramPublishMalformed200Test(TestCase):
    """
    Fix A: HTTP 200 bodies that are malformed (non-JSON or missing result/message_id)
    must transition→failed and raise ValueError. No retry (data-integrity error).
    ADR-008 D3: fail loud, never strand in ready.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-malformed-org")
        self.event = _make_event(slug="tg-malformed-event")
        self.post = _make_post(self.event)
        self.conn = _make_telegram_connection(self.profile)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_200_with_ok_true_but_missing_result_key_transitions_failed(self, mock_post):
        """
        HTTP 200 with {"ok": true} but no "result" key → ValueError raised,
        status == failed, call_count == 1 (no retry — data-integrity error).
        """
        proj = _make_ready_promotion_projection(self.conn, self.post)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}  # missing "result" key
        mock_post.return_value = mock_response

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        self.assertEqual(mock_post.call_count, 1)
        # Verify persisted status (not just in-memory)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_200_with_non_json_body_transitions_failed(self, mock_post):
        """
        HTTP 200 whose .json() raises json.JSONDecodeError → ValueError raised,
        status == failed, call_count == 1 (no retry — data-integrity error).
        """
        import json

        proj = _make_ready_promotion_projection(self.conn, self.post)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_post.return_value = mock_response

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        self.assertEqual(mock_post.call_count, 1)
        # Verify persisted status (not just in-memory)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)


# ---------------------------------------------------------------------------
# (g) Visibility-agnostic: unlisted event still publishes
# ---------------------------------------------------------------------------


class TelegramPublishVisibilityAgnosticTest(TestCase):
    """
    ADR-016 carried-forward (REVISED): NO visibility gate.
    An event with visibility="unlisted" must publish identically to a public event.
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-vis-org")
        self.conn = _make_telegram_connection(self.profile)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_unlisted_event_still_publishes(self, mock_post):
        """Event with visibility=unlisted → projection reaches published."""
        mock_post.return_value = _make_bot_api_success_response(message_id=55)

        event = _make_event(slug="tg-vis-unlisted", visibility="unlisted")
        post = _make_post(event)
        proj = _make_ready_promotion_projection(self.conn, post)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.PUBLISHED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_semi_public_event_still_publishes(self, mock_post):
        """Event with visibility=semi_public → projection reaches published."""
        mock_post.return_value = _make_bot_api_success_response(message_id=66)

        event = _make_event(slug="tg-vis-semi", visibility="semi_public")
        post = _make_post(event)
        proj = _make_ready_promotion_projection(self.conn, post)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.PUBLISHED)


# ---------------------------------------------------------------------------
# (h) Token resolution
# ---------------------------------------------------------------------------


class TelegramPublishTokenResolutionTest(TestCase):
    """
    Token resolution:
    - Per-channel override: connection.credentials["bot_token"] → use that token.
    - No override: settings.TELEGRAM_BOT_TOKEN is used.
    The token appears in the Bot API URL: POST .../bot{token}/sendMessage
    """

    def setUp(self):
        self.profile = _make_profile(slug="tg-token-org")
        self.event = _make_event(slug="tg-token-event")
        self.post = _make_post(self.event)

    @override_settings(TELEGRAM_BOT_TOKEN="settings-token")
    @patch("httpx.post")
    def test_per_channel_bot_token_override_used_in_url(self, mock_post):
        """connection.credentials = {"bot_token": "override-token"} → override used."""
        mock_post.return_value = _make_bot_api_success_response(message_id=10)

        conn = _make_telegram_connection(
            self.profile,
            destination_id="-1001111111111",
            credentials={"bot_token": "override-token"},
        )
        proj = _make_ready_promotion_projection(conn, self.post)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(proj)

        # The URL passed to httpx.post must contain the override token
        called_url = mock_post.call_args[0][0]  # first positional arg
        self.assertIn("override-token", called_url)
        self.assertNotIn("settings-token", called_url)

    @override_settings(TELEGRAM_BOT_TOKEN="settings-token-fallback")
    @patch("httpx.post")
    def test_settings_token_used_when_no_credential_override(self, mock_post):
        """connection.credentials = {} → settings.TELEGRAM_BOT_TOKEN is used."""
        mock_post.return_value = _make_bot_api_success_response(message_id=11)

        conn = _make_telegram_connection(
            self.profile,
            destination_id="-1002222222222",
            credentials={},
        )
        proj = _make_ready_promotion_projection(conn, self.post)

        from syndication.adapters import publish_telegram_promotion

        publish_telegram_promotion(proj)

        called_url = mock_post.call_args[0][0]
        self.assertIn("settings-token-fallback", called_url)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    @patch("httpx.post")
    def test_no_token_anywhere_transitions_failed_and_raises(self, mock_post):
        """No per-channel token + no settings token → status=failed + raises."""
        conn = _make_telegram_connection(
            self.profile,
            destination_id="-1003333333333",
            credentials={},
        )
        proj = _make_ready_promotion_projection(conn, self.post)

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)
        # httpx.post must NOT have been called (fail loud before network call)
        mock_post.assert_not_called()

    @override_settings(TELEGRAM_BOT_TOKEN="settings-token")
    @patch("httpx.post")
    def test_no_destination_id_transitions_failed_and_raises(self, mock_post):
        """No destination_id (empty string) → status=failed + raises."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="",  # deliberately empty
            kinds=["promotion"],
            credentials={},
        )
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.READY,
            connection=conn,
            source_post=self.post,
            content_version=_seed_canonical_cv(self.event),
            frozen_content={"body": "test body", "headline": "test"},
        )

        from syndication.adapters import publish_telegram_promotion

        with self.assertRaises(ValueError):
            publish_telegram_promotion(proj)

        proj.refresh_from_db()
        self.assertEqual(proj.status, PlatformProjection.Status.FAILED)
        mock_post.assert_not_called()
