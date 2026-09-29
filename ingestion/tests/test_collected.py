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
from ingestion.schemas import EventDraft
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

    def _process(self, raw, **draft_kwargs):
        from ingestion.tasks import process_raw_message

        draft = dict(title="Bondage Jam", organizer_name="IKSK", start=self.start, confidence=0.9)
        draft.update(draft_kwargs)
        result = MagicMock()
        result.output = EventDraft(**draft)
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
            patch("ingestion.extraction.event_announcement_score", return_value=0.99),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        raw.refresh_from_db()
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

    def test_non_event_post_is_wiped_and_never_extracted(self):
        from ingestion.tasks import process_raw_message

        raw = self._raw(
            source_type="telegram_private_group", channel_id="-100777", sender_id="4242", text="Anyone for a taxi?"
        )
        with (
            patch("ingestion.extraction.event_announcement_score", return_value=0.1),
            patch("ingestion.extraction.Agent") as MockAgent,
        ):
            process_raw_message(raw.id)
        raw.refresh_from_db()
        MockAgent.assert_not_called()
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "not_event"))
        self.assertEqual((raw.text, raw.raw_payload, raw.enriched_payload, raw.sender_id), ("", {}, {}, ""))
        self.assertEqual(raw.message_id, "m1")  # the bare id stays so a re-collect does not re-classify
        self.assertFalse(Event.objects.exists())
