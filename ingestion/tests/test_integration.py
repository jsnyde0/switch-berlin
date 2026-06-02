import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from events.models import Event, Tag
from ingestion.bot import handle_message
from ingestion.models import ApprovedSender, ExtractionAttempt, RawMessage
from ingestion.schemas import EventDraft
from ingestion.tasks import process_raw_message
from organizers.models import Profile

User = get_user_model()


def make_update(
    text="Test event",
    user_id=123456789,
    message_id=42,
    has_forward_chat=False,
    channel_id=999,
):
    """Build a minimal mock Telegram Update.
    user_id is int (matching real Telegram API); bot casts to str internally."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.message_id = message_id
    update.message.forward_from_chat = (
        MagicMock(id=channel_id) if has_forward_chat else None
    )
    update.message.to_dict.return_value = {"text": text or "", "message_id": message_id}
    update.message.reply_text = AsyncMock()
    return update


class FullIngestionLoopTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin_integ", email="admin@test.com", password="pw"
        )
        self.client.force_login(self.superuser)
        self.organizer = Profile.objects.create(name="Test Org", slug="test-org-integ")
        self.approved = ApprovedSender.objects.create(telegram_user_id="123456789")

    def _event_post_data(self, event, status="published"):
        return {
            "title": event.title,
            "slug": event.slug,
            "status": status,
            "start_0": event.start.strftime("%Y-%m-%d"),
            "start_1": event.start.strftime("%H:%M:%S"),
            "currency": event.currency,
            # EventImageInline uses prefix 'images' (from related_name="images")
            "images-TOTAL_FORMS": "0",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "1000",
            # EventOrganizerInline management form (kb-n0y: EventOrganizer M2M)
            "event_organizer_set-TOTAL_FORMS": "0",
            "event_organizer_set-INITIAL_FORMS": "0",
            "event_organizer_set-MIN_NUM_FORMS": "0",
            "event_organizer_set-MAX_NUM_FORMS": "1000",
            # EventFacilitatorInline management form (kb-qhl: EventFacilitator M2M)
            "event_facilitator_set-TOTAL_FORMS": "0",
            "event_facilitator_set-INITIAL_FORMS": "0",
            "event_facilitator_set-MIN_NUM_FORMS": "0",
            "event_facilitator_set-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        }

    def test_full_ingestion_loop(self):
        """Happy path: bot forward -> RawMessage -> process task
        -> draft Event -> admin publish."""
        update = make_update(user_id=123456789, message_id=42, text="Test event text")
        context = MagicMock()

        # Step 1: Bot receives message and enqueues task
        with patch("ingestion.bot.async_task") as mock_task:
            async_to_sync(handle_message)(update, context)

        raw = RawMessage.objects.get(sender_id="123456789")
        self.assertEqual(raw.extraction_status, "pending")
        mock_task.assert_called_once_with("ingestion.tasks.process_raw_message", raw.id)

        # Step 2: Process task creates draft Event (mock httpx + pydantic-ai)
        mock_draft = EventDraft(
            title="Test Event",
            organizer_name="Test Org",
            start=datetime(2026, 6, 1, 20, 0),
            confidence=0.9,
        )
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Event details</body></html>"
        mock_resp.status_code = 200
        mock_result = MagicMock()
        mock_result.data = mock_draft
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            with patch("ingestion.enrichment.httpx.get", return_value=mock_resp):
                process_raw_message(raw.id)

        event = Event.objects.get(raw_message=raw)
        self.assertEqual(event.status, "draft")
        self.assertEqual(event.organizer, self.organizer)  # exact match on 'Test Org'
        self.assertTrue(
            ExtractionAttempt.objects.filter(event=event, success=True).exists()
        )

        # Step 3: Admin publishes via change form POST
        post_data = self._event_post_data(event, status="published")
        post_data["organizer"] = self.organizer.pk
        response = self.client.post(
            f"/admin/events/event/{event.id}/change/",
            data=post_data,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.status, "published")

    def test_non_text_message_creates_skipped_rawmessage(self):
        """Image/sticker forward creates skipped RawMessage, no task enqueued."""
        update = make_update(user_id=123456789, message_id=55, text=None)
        context = MagicMock()
        with patch("ingestion.bot.async_task") as mock_task:
            async_to_sync(handle_message)(update, context)

        mock_task.assert_not_called()
        raw = RawMessage.objects.filter(sender_id="123456789").first()
        self.assertIsNotNone(raw)
        self.assertEqual(raw.extraction_status, "skipped")
        self.assertEqual(raw.extraction_error, "non_text_message")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Only text", reply)

    @unittest.skipIf(
        connection.vendor == "sqlite",
        "Calls process_raw_message which invokes match_entities (TrigramSimilarity / "
        "pg_trgm). Not available in SQLite. Run under default Postgres settings.",
    )
    def test_low_confidence_does_not_create_event(self):
        """Extraction with confidence < 0.4 sets needs_review, no Event created."""
        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward", raw_payload={}, sender_id="111"
        )
        mock_draft = EventDraft(
            title="Vague Event",
            organizer_name="Unknown Org",
            start=datetime(2026, 6, 1, 20, 0),
            confidence=0.25,
        )
        mock_result = MagicMock()
        mock_result.data = mock_draft
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            with patch("ingestion.enrichment.httpx.get", side_effect=Exception("skip")):
                process_raw_message(raw.id)

        raw.refresh_from_db()
        self.assertEqual(raw.extraction_status, "needs_review")
        self.assertEqual(Event.objects.filter(raw_message=raw).count(), 0)
        self.assertTrue(
            ExtractionAttempt.objects.filter(
                raw_message=raw, success=False, error="low_confidence"
            ).exists()
        )

    def test_partial_url_enrichment_proceeds_to_extraction(self):
        """One URL times out, enrichment continues with remaining URLs."""
        import httpx as _httpx

        from ingestion.enrichment import enrich_urls

        call_count = [0]

        def selective_get(url, **kwargs):
            call_count[0] += 1
            if "site2" in url:
                raise _httpx.TimeoutException("timeout", request=None)
            mock_resp = MagicMock()
            mock_resp.text = f"<html><body>Content from {url}</body></html>"
            mock_resp.status_code = 200
            mock_resp.is_redirect = False
            return mock_resp

        text = "Check https://site1.com and https://site2.com and https://site3.com"
        with (
            patch("ingestion.enrichment.httpx.get", side_effect=selective_get),
            patch("ingestion.enrichment._is_safe_url", return_value=True),
        ):
            result = enrich_urls(text)

        self.assertIn("site1", result["url_content"])
        self.assertIn("site3", result["url_content"])
        # site2 timed out -- should not appear
        self.assertNotIn("site2", result["url_content"])

    def test_organizer_exact_match_links_event(self):
        """Exact organizer name match links Event.organizer."""
        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward", raw_payload={}, sender_id="111"
        )
        mock_draft = EventDraft(
            title="Test",
            organizer_name="Test Org",
            start=datetime(2026, 6, 1, 20, 0),
            confidence=0.9,
        )
        mock_result = MagicMock()
        mock_result.data = mock_draft
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            with patch("ingestion.enrichment.httpx.get", side_effect=Exception("skip")):
                process_raw_message(raw.id)

        event = Event.objects.get(raw_message=raw)
        self.assertEqual(event.organizer, self.organizer)

    @unittest.skipIf(
        connection.vendor == "sqlite",
        "Calls process_raw_message which invokes match_entities (TrigramSimilarity / "
        "pg_trgm). Not available in SQLite. Run under default Postgres settings.",
    )
    def test_organizer_no_match_leaves_event_organizer_null(self):
        """No organizer match -> Event.organizer is NULL (admin resolves later)."""
        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward", raw_payload={}, sender_id="111"
        )
        mock_draft = EventDraft(
            title="Test",
            organizer_name="Completely Unknown Org",
            start=datetime(2026, 6, 1, 20, 0),
            confidence=0.9,
        )
        mock_result = MagicMock()
        mock_result.data = mock_draft
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            with patch("ingestion.enrichment.httpx.get", side_effect=Exception("skip")):
                process_raw_message(raw.id)

        event = Event.objects.get(raw_message=raw)
        self.assertIsNone(event.organizer)

    @unittest.skipIf(
        connection.vendor == "sqlite",
        "Calls process_raw_message which invokes match_entities (TrigramSimilarity / "
        "pg_trgm). Not available in SQLite. Run under default Postgres settings.",
    )
    def test_tag_matching_splits_into_matched_and_suggested(self):
        """Known tags go to M2M, unknown tags go to suggested_tags JSONField."""
        Tag.objects.create(slug="queer", label="Queer", kind="identity")
        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward", raw_payload={}, sender_id="111"
        )
        mock_draft = EventDraft(
            title="Test",
            organizer_name="Nobody",
            start=datetime(2026, 6, 1, 20, 0),
            confidence=0.9,
            tags=["queer", "underground", "fetish"],
        )
        mock_result = MagicMock()
        mock_result.data = mock_draft
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            with patch("ingestion.enrichment.httpx.get", side_effect=Exception("skip")):
                process_raw_message(raw.id)

        event = Event.objects.get(raw_message=raw)
        self.assertTrue(event.tags.filter(slug="queer").exists())
        self.assertIn("underground", event.suggested_tags)
        self.assertIn("fetish", event.suggested_tags)

    def test_archive_past_events_task(self):
        """archive_past_events archives published events older
        than 24h, leaves drafts."""
        from ingestion.tasks import archive_past_events

        now = timezone.now()
        # Should archive: published, end=25h ago
        e1 = Event.objects.create(
            title="Old",
            slug="old-integ-1",
            organizer=self.organizer,
            start=now - timedelta(hours=30),
            end=now - timedelta(hours=25),
            status="published",
        )
        # Should stay published: end=1h ago (within 24h window)
        e2 = Event.objects.create(
            title="Recent",
            slug="recent-integ-2",
            organizer=self.organizer,
            start=now - timedelta(hours=2),
            end=now - timedelta(hours=1),
            status="published",
        )
        # Should stay draft: old but draft status
        e3 = Event.objects.create(
            title="Draft",
            slug="draft-integ-3",
            organizer=self.organizer,
            start=now - timedelta(hours=30),
            end=now - timedelta(hours=25),
            status="draft",
        )
        # Should archive: published, no end, start=25h ago (start fallback)
        e4 = Event.objects.create(
            title="NoEnd",
            slug="noend-integ-4",
            organizer=self.organizer,
            start=now - timedelta(hours=25),
            status="published",
        )
        archive_past_events()
        e1.refresh_from_db()
        e2.refresh_from_db()
        e3.refresh_from_db()
        e4.refresh_from_db()
        self.assertEqual(e1.status, "archived")
        self.assertEqual(e2.status, "published")
        self.assertEqual(e3.status, "draft")
        self.assertEqual(e4.status, "archived")

    def test_soft_purge_preserves_row_clears_pii(self):
        """soft_purge clears text/payloads but preserves row
        and audit trail."""
        from ingestion.tasks import soft_purge_rawmessages

        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            text="Secret event info",
            raw_payload={"some": "data"},
            enriched_payload={"url_content": "scraped data"},
            sender_id="111",
        )
        # Backdate received_at to 91 days ago (auto_now_add prevents direct creation)
        RawMessage.objects.filter(pk=raw.pk).update(
            received_at=timezone.now() - timedelta(days=91)
        )
        attempt = ExtractionAttempt.objects.create(
            raw_message=raw,
            model_name="claude-opus-4-7",
            prompt_version="v1",
            raw_response={},
            success=True,
        )
        soft_purge_rawmessages()
        raw.refresh_from_db()
        self.assertTrue(RawMessage.objects.filter(pk=raw.pk).exists())
        self.assertEqual(raw.text, "")
        self.assertEqual(raw.raw_payload, {})
        self.assertEqual(raw.enriched_payload, {})
        # ExtractionAttempt (audit trail) must be preserved
        self.assertTrue(ExtractionAttempt.objects.filter(pk=attempt.pk).exists())


class DeduplicationTest(TransactionTestCase):
    """TransactionTestCase is required here because handle_message internally catches an
    IntegrityError from the DB unique constraint. That error would corrupt a TestCase
    atomic block, so we use TransactionTestCase which resets the DB between tests."""

    def setUp(self):
        ApprovedSender.objects.create(telegram_user_id="123456789")

    def test_deduplication_prevents_duplicate_rawmessage(self):
        """Same Telegram message forwarded twice creates only one RawMessage.
        The dedup constraint fires because message_id='42' is non-empty."""
        update = make_update(user_id=123456789, message_id=42, text="First forward")
        context = MagicMock()
        with patch("ingestion.bot.async_task"):
            async_to_sync(handle_message)(update, context)
        self.assertEqual(RawMessage.objects.filter(sender_id="123456789").count(), 1)

        # Second forward of the same message
        update2 = make_update(user_id=123456789, message_id=42, text="First forward")
        with patch("ingestion.bot.async_task"):
            async_to_sync(handle_message)(update2, context)

        # Still only one RawMessage
        self.assertEqual(RawMessage.objects.filter(sender_id="123456789").count(), 1)
        last_reply = update2.message.reply_text.call_args[0][0]
        self.assertIn("Already received", last_reply)
