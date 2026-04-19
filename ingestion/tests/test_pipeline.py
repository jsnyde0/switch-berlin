from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from events.models import Event, Tag
from ingestion.models import ExtractionAttempt, RawMessage
from ingestion.schemas import EventDraft
from organizers.models import Organizer
from venues.models import Venue


class EnrichUrlsTest(TestCase):
    def test_enrich_urls_success(self):
        from ingestion.enrichment import enrich_urls

        mock_resp = MagicMock()
        mock_resp.text = "<html><body><h1>Event</h1></body></html>"
        mock_resp.status_code = 200
        with patch("ingestion.enrichment.httpx.get", return_value=mock_resp):
            result = enrich_urls("See https://example.com for details")
        self.assertIn("Event", result["url_content"])

    def test_enrich_urls_partial_failure(self):
        import httpx as _httpx

        from ingestion.enrichment import enrich_urls

        call_count = [0]

        def selective_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise _httpx.TimeoutException("timeout", request=None)
            mock_resp = MagicMock()
            mock_resp.text = f"<html><body>Content from {url}</body></html>"
            mock_resp.status_code = 200
            return mock_resp

        # All three calls are inside the patch -- no real HTTP requests made
        with patch("ingestion.enrichment.httpx.get", side_effect=selective_get):
            result = enrich_urls(
                "Visit https://site1.com and https://site2.com and https://site3.com"
            )
        self.assertIn("site1", result["url_content"])
        self.assertIn("site3", result["url_content"])
        # Timed-out site2 should not appear
        self.assertNotIn("site2", result["url_content"])

    def test_enrich_urls_all_fail(self):
        from ingestion.enrichment import enrich_urls

        with patch("ingestion.enrichment.httpx.get", side_effect=Exception("fail")):
            result = enrich_urls("https://a.com https://b.com")
        self.assertEqual(result, {"url_content": ""})

    def test_enrich_urls_cap_20kb(self):
        from ingestion.enrichment import enrich_urls

        mock_resp = MagicMock()
        mock_resp.text = "<html>" + ("x" * 25_000) + "</html>"
        mock_resp.status_code = 200
        with patch("ingestion.enrichment.httpx.get", return_value=mock_resp):
            result = enrich_urls("https://big.com")
        self.assertLessEqual(
            len(result["url_content"]), 20_100
        )  # small tolerance for markers
        self.assertIn("[truncated at 20KB]", result["url_content"])


class ExtractEventDraftTest(TestCase):
    def test_extract_event_draft_success(self):
        from ingestion.extraction import extract_event_draft

        mock_draft = EventDraft(
            title="Test Event",
            organizer_name="Test Org",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        mock_result = MagicMock()
        mock_result.data = mock_draft
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            draft, version = extract_event_draft("Some event text", {})
        self.assertIsInstance(draft, EventDraft)
        self.assertEqual(version, "v1")
        self.assertEqual(draft.title, "Test Event")


class EntityMatchingTest(TestCase):
    def test_organizer_exact_match(self):
        from ingestion.extraction import match_entities

        organizer = Organizer.objects.create(name="Test Org", slug="test-org")
        draft = EventDraft(
            title="T",
            organizer_name="Test Org",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        result = match_entities(draft)
        self.assertEqual(result["organizer"], organizer)

    def test_organizer_exact_match_case_insensitive(self):
        from ingestion.extraction import match_entities

        organizer = Organizer.objects.create(name="Test Org", slug="test-org")
        draft = EventDraft(
            title="T",
            organizer_name="test org",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        result = match_entities(draft)
        self.assertEqual(result["organizer"], organizer)

    def test_organizer_no_match_returns_none(self):
        from ingestion.extraction import match_entities

        # Empty DB -- no organizers
        draft = EventDraft(
            title="T",
            organizer_name="Unknown Org",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        result = match_entities(draft)
        self.assertIsNone(result["organizer"])

    def test_organizer_fuzzy_match(self):
        from ingestion.extraction import match_entities

        organizer = Organizer.objects.create(
            name="Queer Collective", slug="queer-collective"
        )
        draft = EventDraft(
            title="T",
            organizer_name="Queer Colective",  # typo -- close enough
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        # This test relies on pg_trgm being active (migration 0004_enable_pg_trgm).
        # If it fails with "function similarity does not exist", the pg_trgm migration
        # was not applied -- run: python manage.py migrate ingestion
        result = match_entities(draft)
        # Exact match fails ('Queer Colective' != 'Queer Collective'), fuzzy fires.
        # pg_trgm threshold 0.6: 'Queer Colective' vs 'Queer Collective' should match.
        self.assertEqual(result["organizer"], organizer)

    def test_venue_exact_match(self):
        from ingestion.extraction import match_entities

        venue = Venue.objects.create(name="KitKatClub", slug="kitkatclub")
        draft = EventDraft(
            title="T",
            organizer_name="X",
            venue_name="KitKatClub",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        result = match_entities(draft)
        self.assertEqual(result["venue"], venue)

    def test_venue_no_match_returns_none(self):
        from ingestion.extraction import match_entities

        draft = EventDraft(
            title="T",
            organizer_name="X",
            venue_name="Unknown Venue",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
        )
        result = match_entities(draft)
        self.assertIsNone(result["venue"])

    def test_tag_matching_splits_matched_and_unmatched(self):
        from ingestion.extraction import match_entities

        tag = Tag.objects.create(slug="queer", label="Queer", kind="identity")
        draft = EventDraft(
            title="T",
            organizer_name="X",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=0.9,
            tags=["queer", "underground-tag", "fetish"],
        )
        result = match_entities(draft)
        self.assertIn(tag, result["matched_tags"])
        self.assertIn("underground-tag", result["unmatched_tags"])
        self.assertIn("fetish", result["unmatched_tags"])


class ProcessRawMessageTest(TestCase):
    def _make_raw(self, **kwargs):
        defaults = dict(
            source_type="telegram_bot_forward",
            raw_payload={},
            sender_id="111",
        )
        defaults.update(kwargs)
        return RawMessage.objects.create(**defaults)

    def _mock_draft(self, confidence=0.9, **kwargs):
        defaults = dict(
            title="Test Event",
            organizer_name="Nobody",
            start=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            confidence=confidence,
        )
        defaults.update(kwargs)
        return EventDraft(**defaults)

    def test_low_confidence_skips_event_creation(self):
        from ingestion.tasks import process_raw_message

        raw = self._make_raw()
        mock_result = MagicMock()
        mock_result.data = self._mock_draft(confidence=0.25)
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

    def test_high_confidence_creates_draft_event(self):
        from ingestion.tasks import process_raw_message

        raw = self._make_raw(text="Event info https://example.com")
        mock_resp = MagicMock()
        mock_resp.text = "<html>Event detail</html>"
        mock_resp.status_code = 200
        mock_result = MagicMock()
        mock_result.data = self._mock_draft(confidence=0.9)
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value = mock_result
            with patch("ingestion.enrichment.httpx.get", return_value=mock_resp):
                process_raw_message(raw.id)
        raw.refresh_from_db()
        self.assertEqual(raw.extraction_status, "extracted")
        event = Event.objects.get(raw_message=raw)
        self.assertEqual(event.status, "draft")
        self.assertIsNone(event.organizer)  # no organizer in DB
        self.assertTrue(
            ExtractionAttempt.objects.filter(raw_message=raw, success=True).exists()
        )

    def test_extraction_failure_sets_failed_status(self):
        from ingestion.tasks import process_raw_message

        raw = self._make_raw()
        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.side_effect = Exception("LLM error")
            with patch("ingestion.enrichment.httpx.get", side_effect=Exception("skip")):
                process_raw_message(raw.id)
        raw.refresh_from_db()
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("LLM error", raw.extraction_error)


class ScheduledTaskTest(TestCase):
    def test_archive_past_events(self):
        from ingestion.tasks import archive_past_events

        now = timezone.now()
        org = Organizer.objects.create(name="Org", slug="org-sched")
        e1 = Event.objects.create(
            title="Old",
            slug="old-sched-1",
            organizer=org,
            start=now - timedelta(hours=30),
            end=now - timedelta(hours=25),
            status="published",
        )
        e2 = Event.objects.create(
            title="Recent",
            slug="recent-sched-2",
            organizer=org,
            start=now - timedelta(hours=2),
            end=now - timedelta(hours=1),
            status="published",
        )
        e3 = Event.objects.create(
            title="Draft",
            slug="draft-sched-3",
            organizer=org,
            start=now - timedelta(hours=30),
            end=now - timedelta(hours=25),
            status="draft",
        )
        e4 = Event.objects.create(
            title="NoEnd",
            slug="noend-sched-4",
            organizer=org,
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

    def test_soft_purge_rawmessages(self):
        from ingestion.tasks import soft_purge_rawmessages

        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            text="Secret event info",
            raw_payload={"some": "data"},
            enriched_payload={"url_content": "scraped"},
            sender_id="111",
        )
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
        self.assertTrue(ExtractionAttempt.objects.filter(pk=attempt.pk).exists())

    def test_soft_purge_leaves_recent_rawmessages(self):
        from ingestion.tasks import soft_purge_rawmessages

        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward",
            text="Recent event",
            raw_payload={"k": "v"},
            sender_id="222",
        )
        soft_purge_rawmessages()
        raw.refresh_from_db()
        self.assertEqual(raw.text, "Recent event")
