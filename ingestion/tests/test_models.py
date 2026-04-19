from django.db import IntegrityError
from django.test import TestCase

from ingestion.models import ApprovedSender, ExtractionAttempt, RawMessage


class RawMessageNeedsReviewChoiceTest(TestCase):
    """RawMessage.extraction_status accepts 'needs_review' choice."""

    def test_needs_review_choice_valid(self):
        msg = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            raw_payload={"test": True},
            extraction_status="needs_review",
        )
        msg.refresh_from_db()
        self.assertEqual(msg.extraction_status, "needs_review")

    def test_default_status_still_pending(self):
        msg = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            raw_payload={"test": True},
        )
        self.assertEqual(msg.extraction_status, "pending")


class RawMessageContentHashTest(TestCase):
    """RawMessage has content_hash field with blank default (empty string)."""

    def test_content_hash_defaults_to_empty_string(self):
        msg = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            raw_payload={"test": True},
        )
        self.assertEqual(msg.content_hash, "")

    def test_content_hash_can_be_set(self):
        msg = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            raw_payload={"test": True},
            content_hash="abc123" * 10,  # 60 chars < 64
        )
        msg.refresh_from_db()
        self.assertEqual(msg.content_hash, "abc123" * 10)


class RawMessageDedupConstraintTest(TestCase):
    """Unique constraint on (source_type, channel_id, message_id) when non-empty."""

    def test_duplicate_with_message_id_raises(self):
        RawMessage.objects.create(
            source_type="telegram_bot_forward",
            channel_id="chan1",
            message_id="msg1",
            raw_payload={"n": 1},
        )
        with self.assertRaises(IntegrityError):
            RawMessage.objects.create(
                source_type="telegram_bot_forward",
                channel_id="chan1",
                message_id="msg1",
                raw_payload={"n": 2},
            )

    def test_empty_message_id_allows_duplicates(self):
        """Empty message_id is excluded from constraint; duplicates are allowed."""
        RawMessage.objects.create(
            source_type="telegram_bot_forward",
            channel_id="chan1",
            message_id="",
            raw_payload={"n": 1},
        )
        # Should not raise
        RawMessage.objects.create(
            source_type="telegram_bot_forward",
            channel_id="chan1",
            message_id="",
            raw_payload={"n": 2},
        )
        self.assertEqual(
            RawMessage.objects.filter(channel_id="chan1").count(), 2
        )


class ExtractionAttemptModelTest(TestCase):
    """ExtractionAttempt model exists and has correct fields."""

    def setUp(self):
        self.raw = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            raw_payload={"text": "Hello"},
        )

    def test_create_extraction_attempt(self):
        attempt = ExtractionAttempt.objects.create(
            raw_message=self.raw,
            model_name="claude-opus-4-7",
            prompt_version="v1",
            raw_response={"choices": []},
            success=True,
        )
        self.assertEqual(attempt.raw_message, self.raw)
        self.assertEqual(attempt.model_name, "claude-opus-4-7")
        self.assertEqual(attempt.prompt_version, "v1")
        self.assertTrue(attempt.success)

    def test_defaults(self):
        attempt = ExtractionAttempt.objects.create(
            raw_message=self.raw,
            model_name="gpt-4",
            prompt_version="v2",
            raw_response={},
        )
        self.assertEqual(attempt.extracted_draft, {})
        self.assertIsNone(attempt.confidence_score)
        self.assertFalse(attempt.success)
        self.assertEqual(attempt.error, "")
        self.assertIsNone(attempt.event)

    def test_str(self):
        attempt = ExtractionAttempt.objects.create(
            raw_message=self.raw,
            model_name="gpt-4",
            prompt_version="v1",
            raw_response={},
        )
        self.assertIn("ExtractionAttempt", str(attempt))

    def test_reverse_relation_on_raw_message(self):
        ExtractionAttempt.objects.create(
            raw_message=self.raw,
            model_name="gpt-4",
            prompt_version="v1",
            raw_response={},
        )
        self.assertEqual(self.raw.attempts.count(), 1)

    def test_ordering_is_by_attempted_at_desc(self):
        meta = ExtractionAttempt._meta
        self.assertEqual(meta.ordering, ["-attempted_at"])


class ApprovedSenderModelTest(TestCase):
    """ApprovedSender model exists and has correct fields."""

    def test_create_approved_sender(self):
        sender = ApprovedSender.objects.create(
            telegram_user_id="123456789",
            telegram_handle="testuser",
        )
        self.assertEqual(sender.telegram_user_id, "123456789")
        self.assertEqual(sender.telegram_handle, "testuser")

    def test_telegram_user_id_is_unique(self):
        ApprovedSender.objects.create(telegram_user_id="111")
        with self.assertRaises(IntegrityError):
            ApprovedSender.objects.create(telegram_user_id="111")

    def test_defaults(self):
        sender = ApprovedSender.objects.create(telegram_user_id="999")
        self.assertEqual(sender.telegram_handle, "")
        self.assertIsNone(sender.organizer)
        self.assertEqual(sender.notes, "")

    def test_str(self):
        sender = ApprovedSender.objects.create(
            telegram_user_id="123",
            telegram_handle="myhandle",
        )
        self.assertIn("123", str(sender))
        self.assertIn("myhandle", str(sender))
