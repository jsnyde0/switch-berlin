from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase

from a_core.models import FeatureFlag
from ingestion.bot import _bot_enabled, _is_rate_limited, _rate_buckets, handle_message
from ingestion.models import ApprovedSender, RawMessage


def make_update(
    text="Test event", user_id=123456789, message_id=42, has_forward_chat=False
):
    """Build a minimal mock Telegram Update.
    Note: user_id is passed as int (matching real Telegram API), but the bot
    casts str(update.effective_user.id) before any DB lookup -- tests that pass
    user_id=123456789 must have ApprovedSender.telegram_user_id='123456789'."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.message_id = message_id
    update.message.forward_from_chat = MagicMock(id=999) if has_forward_chat else None
    update.message.to_dict.return_value = {"text": text or "", "message_id": message_id}
    update.message.reply_text = AsyncMock()
    return update


class BotHandlerTest(TestCase):
    def setUp(self):
        super().setUp()
        _rate_buckets.clear()
        cache.clear()

    def test_bot_enabled_when_ingestion_paused_false(self):
        """INGESTION_PAUSED=False -> _bot_enabled() returns True."""
        FeatureFlag.objects.update_or_create(
            key="INGESTION_PAUSED",
            defaults={"enabled": False},
        )
        cache.clear()
        self.assertTrue(_bot_enabled())

    def test_bot_disabled_when_ingestion_paused_true(self):
        """INGESTION_PAUSED=True -> _bot_enabled() returns False."""
        FeatureFlag.objects.update_or_create(
            key="INGESTION_PAUSED",
            defaults={"enabled": True},
        )
        cache.clear()
        self.assertFalse(_bot_enabled())

    def test_bot_enabled_by_default_when_flag_missing(self):
        """No INGESTION_PAUSED flag in DB -> _bot_enabled() returns True.

        default=False -> not False = True."""
        FeatureFlag.objects.filter(key="INGESTION_PAUSED").delete()
        cache.clear()
        self.assertTrue(_bot_enabled())

    def test_handle_message_short_circuits_when_paused(self):
        """INGESTION_PAUSED=True -> handle_message replies 'temporarily offline'."""
        FeatureFlag.objects.update_or_create(
            key="INGESTION_PAUSED",
            defaults={"enabled": True},
        )
        cache.clear()
        update = make_update()
        context = MagicMock()
        async_to_sync(handle_message)(update, context)
        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args[0][0]
        self.assertIn("temporarily offline", args)

    def test_handle_message_processes_normally_when_not_paused(self):
        """INGESTION_PAUSED=False -> handle_message processes message normally."""
        FeatureFlag.objects.update_or_create(
            key="INGESTION_PAUSED",
            defaults={"enabled": False},
        )
        cache.clear()
        update = make_update(user_id=555, message_id=77)
        context = MagicMock()
        ApprovedSender.objects.create(telegram_user_id="555")
        with patch("ingestion.bot.async_task") as mock_task:
            async_to_sync(handle_message)(update, context)
        mock_task.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("Received", reply_text)

    def test_non_text_message_creates_skipped_rawmessage(self):
        update = make_update(text=None)  # photo/sticker
        context = MagicMock()
        # ApprovedSender must use string representation of user_id
        ApprovedSender.objects.create(telegram_user_id="123456789")
        with patch("ingestion.bot.async_task") as mock_task:
            async_to_sync(handle_message)(update, context)
        mock_task.assert_not_called()
        raw = RawMessage.objects.filter(sender_id="123456789").first()
        self.assertIsNotNone(raw)
        self.assertEqual(raw.extraction_status, "skipped")
        self.assertEqual(raw.extraction_error, "non_text_message")
        reply_text = update.message.reply_text.call_args_list[-1][0][0]
        self.assertIn("Only text", reply_text)

    def test_unapproved_sender_non_text_rejected_without_rawmessage(self):
        """Unapproved sender sending a non-text message should be rejected at
        allowlist step -- NOT create a RawMessage row."""
        update = make_update(text=None, user_id=888888)  # photo/sticker, not approved
        context = MagicMock()
        # No ApprovedSender created for 888888
        async_to_sync(handle_message)(update, context)
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("approved organizers", reply_text)
        # Must NOT create a RawMessage row for unapproved sender
        self.assertEqual(RawMessage.objects.filter(sender_id="888888").count(), 0)

    def test_non_allowlisted_sender_rejected(self):
        update = make_update(user_id=999999)
        context = MagicMock()
        # No ApprovedSender created for 999999
        async_to_sync(handle_message)(update, context)
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("approved organizers", reply_text)

    def test_rate_limit_enforced(self):
        _rate_buckets.clear()
        # First 100 calls should not be limited
        for i in range(100):
            limited = _is_rate_limited("sender_x")
            self.assertFalse(limited, f"Should not be limited on call {i + 1}")
        # 101st call should be limited
        self.assertTrue(_is_rate_limited("sender_x"))

    def test_valid_message_queued(self):
        update = make_update(user_id=222, message_id=88)
        context = MagicMock()
        ApprovedSender.objects.create(telegram_user_id="222")
        with patch("ingestion.bot.async_task") as mock_task:
            async_to_sync(handle_message)(update, context)
        mock_task.assert_called_once()
        call_args = mock_task.call_args[0]
        self.assertEqual(call_args[0], "ingestion.tasks.process_raw_message")
        raw = RawMessage.objects.get(sender_id="222")
        self.assertEqual(call_args[1], raw.id)
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("Received", reply_text)


class BotDuplicateTest(TransactionTestCase):
    """Separate TransactionTestCase for the duplicate-message test.

    IntegrityError (even when caught) poisons the surrounding atomic block,
    which is the TestCase transaction wrapper. Using TransactionTestCase avoids
    this by not wrapping the test in a transaction."""

    def setUp(self):
        _rate_buckets.clear()

    def test_duplicate_message_rejected(self):
        update = make_update(user_id=111, message_id=77)
        context = MagicMock()
        ApprovedSender.objects.create(telegram_user_id="111")
        # Pre-create a RawMessage with same dedup key
        # (source_type, channel_id='', message_id='77').
        # Constraint fires when message_id > ''; bot casts str(77) == '77'.
        RawMessage.objects.create(
            source_type="telegram_bot_forward",
            sender_id="111",
            channel_id="",
            message_id="77",
            raw_payload={},
            text="existing",
        )
        with patch("ingestion.bot.async_task"):
            async_to_sync(handle_message)(update, context)
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("Already received", reply_text)
        # Only one RawMessage should exist
        self.assertEqual(RawMessage.objects.filter(sender_id="111").count(), 1)
