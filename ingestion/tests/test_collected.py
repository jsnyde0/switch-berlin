"""
Collected-event feed (sb-7wzb.2, Track A walk): collector rows enter the
RawMessage seam through the staff-only API verb, and the pipeline lands each
extracted event by claim state (ADR-017 D4) at the source-derived tier
(ADR-012 D2).

Postgres-only: process_raw_message runs match_entities (TrigramSimilarity).
"""

import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from ingestion.models import RawMessage
from ingestion.schemas import CollectedEvents, EventDraft
from organizers.models import Profile, ProfileClaim
from syndication.models import IdentityToken

User = get_user_model()

_PG_ONLY = unittest.skipIf(
    connection.vendor == "sqlite",
    "process_raw_message invokes match_entities (TrigramSimilarity / pg_trgm).",
)


def _row(**kwargs):
    row = {
        "source_type": "website",
        "channel_id": "iksk-berlin.de",
        "message_id": "https://iksk-berlin.de/bondage-jam#2026-10-01",
        "text": "Bondage Jam, Thursday 1 October 19-23, IKSK",
        "raw_payload": {"source": "IKSK program page", "organizer": "IKSK"},
        "collect_only": False,
    }
    row.update(kwargs)
    return row


class CollectedRowsEndpointTest(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="operator", password="pw", is_staff=True)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {IdentityToken.issue(self.operator).token}"}

    def _post(self, rows, headers=None):
        return self.client.post(
            "/api/ingest/raw-messages",
            data=rows,
            content_type="application/json",
            **(headers if headers is not None else self.headers),
        )

    def test_rows_land_as_rawmessages_and_enqueue_extraction(self):
        with patch("ingestion.collected.async_task") as mock_task:
            resp = self._post([_row(), _row(message_id="m2", collect_only=True)])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["created"], 2)
        raw = RawMessage.objects.get(message_id="m2")
        self.assertEqual(raw.source_type, "website")
        self.assertTrue(raw.collect_only)
        self.assertEqual(raw.raw_payload["organizer"], "IKSK")
        self.assertEqual(mock_task.call_count, 2)

    def test_recollected_row_is_reported_not_duplicated(self):
        with patch("ingestion.collected.async_task") as mock_task:
            self._post([_row()])
            resp = self._post([_row()])
        self.assertEqual(resp.json(), {"created": 0, "already_collected": 1})
        self.assertEqual(RawMessage.objects.count(), 1)
        self.assertEqual(mock_task.call_count, 1)

    def test_collector_fetched_page_text_lands_in_the_link_content_column(self):
        with patch("ingestion.collected.async_task"):
            resp = self._post([_row(enriched_payload={"url_content": "Open practice, everybody welcome."})])
        self.assertEqual(resp.status_code, 200, resp.content)
        raw = RawMessage.objects.get()
        self.assertEqual(raw.enriched_payload, {"url_content": "Open practice, everybody welcome."})

    def test_bot_forward_source_type_is_rejected(self):
        resp = self._post([_row(source_type="telegram_bot_forward")])
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(RawMessage.objects.count(), 0)

    def test_non_staff_agent_is_forbidden(self):
        vouched = User.objects.create_user(username="vouched", password="pw", status="vouched")
        headers = {"HTTP_AUTHORIZATION": f"Bearer {IdentityToken.issue(vouched).token}"}
        resp = self._post([_row()], headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(RawMessage.objects.count(), 0)


@_PG_ONLY
class CollectedEventLandingTest(TestCase):
    def setUp(self):
        self.start = timezone.now() + timedelta(days=3)
        self.iksk = Profile.objects.create(name="IKSK", slug="iksk", status="approved")

    def _draft(self, **draft_kwargs):
        draft = dict(title="Bondage Jam", organizer_name="IKSK", start=self.start, confidence=0.9)
        draft.update(draft_kwargs)
        return EventDraft(**draft)

    def _run(self, raw, output):
        """Run the pipeline on `raw` with the extractor model returning `output`; return the Agent mock."""
        from ingestion.tasks import process_raw_message

        result = MagicMock()
        result.output = output
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        raw.refresh_from_db()
        return MockAgent

    def test_collector_page_text_and_url_enrichment_both_reach_the_extractor(self):
        from ingestion.tasks import process_raw_message

        raw = self._raw(enriched_payload={"url_content": "COLLECTOR PAGE TEXT"})
        result = MagicMock()
        result.output = CollectedEvents(events=[self._draft()])
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={"url_content": "ENRICHED LINK TEXT"}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        prompt = str(MockAgent.return_value.run_sync.call_args)
        self.assertIn("COLLECTOR PAGE TEXT", prompt)
        self.assertIn("ENRICHED LINK TEXT", prompt)

    def _process(self, raw, **draft_kwargs):
        draft = self._draft(**draft_kwargs)
        output = draft if raw.source_type == "telegram_bot_forward" else CollectedEvents(events=[draft])
        self._run(raw, output)
        return raw

    def _raw(self, **kwargs):
        defaults = dict(
            source_type="website",
            channel_id="iksk-berlin.de",
            message_id="m1",
            text="Bondage Jam",
            raw_payload={"organizer": "IKSK"},
        )
        defaults.update(kwargs)
        return RawMessage.objects.create(**defaults)

    def test_unclaimed_organizer_website_event_publishes_public(self):
        raw = self._process(self._raw())
        event = Event.objects.get(raw_message=raw)
        self.assertEqual((event.status, event.visibility), ("published", "public"))
        self.assertIsNotNone(event.published_at)
        self.assertEqual(event.organizer, self.iksk)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_private_channel_event_publishes_semi_public(self):
        raw = self._process(self._raw(source_type="telegram_private_channel", channel_id="-100123"))
        event = Event.objects.get(raw_message=raw)
        self.assertEqual((event.status, event.visibility), ("published", "semi_public"))

    def test_claimed_organizer_lands_draft_for_claimant(self):
        claimant = User.objects.create_user(username="claimant", password="pw")
        ProfileClaim.objects.create(profile=self.iksk, user=claimant)
        raw = self._process(self._raw())
        self.assertEqual(Event.objects.get(raw_message=raw).status, "draft")

    def test_collect_only_row_never_publishes(self):
        raw = self._process(self._raw(collect_only=True, source_type="telegram_telethon", channel_id="@party"))
        self.assertEqual(Event.objects.get(raw_message=raw).status, "draft")

    def test_unknown_organizer_gets_reachable_unclaimed_profile(self):
        raw = self._process(self._raw(raw_payload={}, channel_id="-100999"), organizer_name="Fist Them Berlin")
        profile = Event.objects.get(raw_message=raw).organizer
        self.assertEqual(profile.name, "Fist Them Berlin")
        self.assertEqual(profile.status, "approved")  # organizer page (claim affordance) must resolve
        self.assertFalse(profile.is_claimed)
        self.assertEqual(profile.consent_method, "legitimate_interest")

    def test_same_event_from_second_source_is_duplicate(self):
        existing = Event.objects.create(
            title="BONDAGE JAM", slug="bondage-jam", start=self.start, status="published", organizer=self.iksk
        )
        raw = self._process(self._raw(source_type="telegram_telethon", channel_id="@IKSKBerlin"))
        self.assertEqual(raw.extraction_status, "duplicate")
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(raw.attempts.get().event, existing)

    def test_past_event_is_skipped(self):
        raw = self._process(self._raw(), start=timezone.now() - timedelta(days=2))
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "past_event"))
        self.assertFalse(Event.objects.exists())

    def test_bot_forward_rows_still_land_as_drafts(self):
        raw = self._process(self._raw(source_type="telegram_bot_forward", raw_payload={}))
        self.assertEqual(Event.objects.get(raw_message=raw).status, "draft")

    def test_post_announcing_no_event_is_wiped_at_once(self):
        raw = self._raw(
            source_type="telegram_private_group",
            channel_id="-100777",
            sender_id="4242",
            text="Anyone for a taxi?",
            raw_payload={"source": "SeQret", "images": ["aGVsbG8="]},
        )
        self._run(raw, CollectedEvents(events=[]))
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "not_event"))
        self.assertEqual((raw.text, raw.raw_payload, raw.enriched_payload, raw.sender_id), ("", {}, {}, ""))
        self.assertEqual(raw.message_id, "m1")  # the bare id stays so a re-collect does not re-extract
        self.assertFalse(Event.objects.exists())

    def test_post_announcing_several_events_lands_each(self):
        raw = self._raw(source_type="telegram_telethon", channel_id="@TillTailorShirka", raw_payload={})
        drafts = [
            self._draft(title="Tantra Evening", organizer_name="Till & Shirka"),
            self._draft(title="Shibari Basics", organizer_name="Till & Shirka", start=self.start + timedelta(days=1)),
            self._draft(title="Old Workshop", organizer_name="Till & Shirka", start=timezone.now() - timedelta(days=2)),
        ]
        self._run(raw, CollectedEvents(events=drafts))
        titles = set(Event.objects.filter(raw_message=raw).values_list("title", flat=True))
        self.assertEqual(titles, {"Tantra Evening", "Shibari Basics"})
        self.assertEqual(Profile.objects.filter(name="Till & Shirka").count(), 1)  # one organizer, not one per event
        self.assertEqual(raw.extraction_status, "extracted")  # the best per-event outcome
        self.assertEqual(sorted(a.error for a in raw.attempts.all()), ["", "", "past_event"])

    def test_images_reach_the_extractor_and_are_dropped_after(self):
        from pydantic_ai import BinaryContent

        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@IKSKBerlin",
            text="THURSDAY 1.10.26",
            raw_payload={"organizer": "IKSK", "images": ["aGVsbG8=", "d29ybGQ="]},
        )
        agent = self._run(raw, CollectedEvents(events=[self._draft()]))
        (parts,), _ = agent.return_value.run_sync.call_args
        self.assertIn("THURSDAY 1.10.26", parts[0])
        self.assertEqual(
            [(p.data, p.media_type) for p in parts[1:]], [(b"hello", "image/jpeg"), (b"world", "image/jpeg")]
        )
        self.assertTrue(all(isinstance(p, BinaryContent) for p in parts[1:]))
        self.assertEqual(raw.raw_payload, {"organizer": "IKSK"})  # image bytes do not outlive the pipeline
        self.assertEqual(raw.text, "THURSDAY 1.10.26")

    def test_past_event_is_skipped_even_when_low_confidence(self):
        raw = self._process(self._raw(), start=timezone.now() - timedelta(days=2), confidence=0.2)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "past_event"))

    def test_low_confidence_upcoming_event_is_held(self):
        raw = self._process(self._raw(), confidence=0.2)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("needs_review", "low_confidence"))
        self.assertFalse(Event.objects.exists())

    def test_date_only_event_publishes_with_time_unknown(self):
        raw = self._process(self._raw(), start_time_unknown=True)
        event = Event.objects.get(raw_message=raw)
        self.assertEqual(event.status, "published")
        self.assertTrue(event.start_time_unknown)

    def test_failed_extraction_keeps_images_for_a_rerun(self):
        from ingestion.tasks import process_raw_message

        raw = self._raw(raw_payload={"organizer": "IKSK", "images": ["aGVsbG8="]})
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.side_effect = RuntimeError("router down")
            process_raw_message(raw.id)
        raw.refresh_from_db()
        self.assertEqual(raw.extraction_status, "failed")
        self.assertEqual(raw.raw_payload["images"], ["aGVsbG8="])

    def test_unnamed_organizer_is_held_not_invented(self):
        raw = self._process(self._raw(raw_payload={}, channel_id="-100888"), organizer_name="Unknown")
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("needs_review", "no_organizer"))
        self.assertFalse(Profile.objects.filter(name__iexact="unknown").exists())

    def test_event_outside_berlin_is_skipped(self):
        raw = self._process(self._raw(), in_berlin_area=False)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "not_berlin"))
        self.assertFalse(Event.objects.exists())
