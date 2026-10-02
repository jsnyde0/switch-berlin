"""
Collected-event feed (sb-7wzb.2, Track A walk): collector rows enter the
RawMessage seam through the staff-only API verb, and the pipeline lands each
extracted event by claim state (ADR-017 D4) at the source-derived tier
(ADR-012 D2).

Postgres-only: the duplicate check runs TrigramSimilarity.
"""

import base64
import io
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from events.models import Event, EventImage
from ingestion.models import ExtractionAttempt, RawMessage
from ingestion.schemas import CollectedEvents, EventDraft
from ingestion.tests.consolidation_fakes import judge, same_as_first
from organizers.models import Profile, ProfileClaim
from syndication.models import IdentityToken

User = get_user_model()

_PG_ONLY = unittest.skipIf(
    connection.vendor == "sqlite",
    "the duplicate check uses TrigramSimilarity (pg_trgm).",
)


def _flyer_b64(width=3000, height=2000, color="crimson") -> str:
    """A real JPEG flyer as the Telegram collector ships it: base64 in raw_payload["images"]."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode()


def _row(**kwargs):
    row = {
        "source_type": "website",
        "channel_id": "iksk-berlin.de",
        "message_id": "https://iksk-berlin.de/bondage-jam#2026-10-01",
        "text": "Bondage Jam, Thursday 1 October 19-23, IKSK",
        "raw_payload": {"source": "IKSK program page", "default_organizer": "IKSK"},
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
        self.assertEqual(raw.raw_payload["default_organizer"], "IKSK")
        self.assertEqual(mock_task.call_count, 2)

    def test_recollected_row_is_reported_not_duplicated(self):
        with patch("ingestion.collected.async_task") as mock_task:
            self._post([_row()])
            resp = self._post([_row()])
        self.assertEqual(
            resp.json(), {"created": 0, "already_collected": 1, "re_read": 0, "same_listing": 0, "re_run": 0}
        )
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
    @classmethod
    def setUpClass(cls):
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        cls.media_root = Path(media.name)
        cls.enterClassContext(override_settings(MEDIA_ROOT=media.name))
        super().setUpClass()

    def setUp(self):
        self.start = timezone.now() + timedelta(days=3)
        self.iksk = Profile.objects.create(name="IKSK", slug="iksk", status="approved")

    def _draft(self, **draft_kwargs):
        draft = dict(title="Bondage Jam", start=self.start, confidence=0.9)
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
            judge(same_as_first),  # a candidate is the same event
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        raw.refresh_from_db()
        return MockAgent

    def test_collector_page_text_and_url_enrichment_both_reach_the_extractor(self):
        from ingestion.tasks import process_raw_message

        raw = self._raw(enriched_payload={"url_content": "COLLECTOR PAGE TEXT"})
        result = MagicMock()
        result.output = CollectedEvents(post_kind="announcement", events=[self._draft()])
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={"url_content": "ENRICHED LINK TEXT"}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        prompt = str(MockAgent.return_value.run_sync.call_args)
        self.assertIn("COLLECTOR PAGE TEXT", prompt)
        self.assertIn("ENRICHED LINK TEXT", prompt)

    def _run_faithful_model(self, raw, link_text):
        """Run the pipeline with a model that obeys the description rule: it copies the
        link prose out of the prompt it was sent, or returns "" when the prompt holds none."""
        from ingestion.tasks import process_raw_message

        def run_sync(parts):
            prompt = parts[0]
            self.sent_prompt = prompt
            description = link_text if link_text and link_text in prompt else ""
            result = MagicMock()
            result.output = CollectedEvents(post_kind="announcement", events=[self._draft(description=description)])
            return result

        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.side_effect = run_sync
            process_raw_message(raw.id)
        return Event.objects.get()

    def test_prompt_asks_for_the_organizers_own_prose_capped_and_never_invented(self):
        from ingestion.extraction import COLLECTED_PROMPT_VERSION, DESCRIPTION_CAP_CHARS

        prose = "An open evening for rope practice. Bring your own ropes, newcomers welcome. " * 12
        self.assertGreaterEqual(len(prose), 500)
        raw = self._raw(enriched_payload={"url_content": prose})
        event = self._run_faithful_model(raw, prose)
        self.assertIn("copied unchanged", self.sent_prompt)
        self.assertIn(f"at most {DESCRIPTION_CAP_CHARS}", self.sent_prompt)
        self.assertIn("never write one yourself", self.sent_prompt)
        self.assertIn(prose, self.sent_prompt)
        self.assertEqual(event.description, prose)
        self.assertEqual(COLLECTED_PROMPT_VERSION, "collected-v6")
        attempt = ExtractionAttempt.objects.get(raw_message=raw)
        self.assertEqual(attempt.prompt_version, "collected-v6")

    def test_row_without_prose_lands_an_empty_description(self):
        raw = self._raw(enriched_payload={})
        event = self._run_faithful_model(raw, "")
        self.assertEqual(event.description, "")

    def _process(self, raw, **draft_kwargs):
        draft = self._draft(**draft_kwargs)
        output = (
            draft
            if raw.source_type == "telegram_bot_forward"
            else CollectedEvents(post_kind="announcement", events=[draft])
        )
        self._run(raw, output)
        return raw

    def _raw(self, **kwargs):
        defaults = dict(
            source_type="website",
            channel_id="iksk-berlin.de",
            message_id="m1",
            text="Bondage Jam",
            raw_payload={"default_organizer": "IKSK"},
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

    def test_claimed_organizer_lands_draft_for_manager(self):
        manager = User.objects.create_user(username="manager", password="pw")
        ProfileClaim.objects.create(profile=self.iksk, user=manager)
        raw = self._process(self._raw())
        self.assertEqual(Event.objects.get(raw_message=raw).status, "draft")

    def test_collect_only_row_never_publishes(self):
        raw = self._process(self._raw(collect_only=True, source_type="telegram_telethon", channel_id="@party"))
        self.assertEqual(Event.objects.get(raw_message=raw).status, "draft")

    def test_unknown_organizer_gets_reachable_unclaimed_profile(self):
        raw = self._process(self._raw(raw_payload={}, channel_id="-100999"), explicit_organizer="Fist Them Berlin")
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
        self._run(raw, CollectedEvents(post_kind="other", events=[]))
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "not_event"))
        self.assertEqual((raw.text, raw.raw_payload, raw.enriched_payload, raw.sender_id), ("", {}, {}, ""))
        self.assertEqual(raw.message_id, "m1")  # the bare id stays so a re-collect does not re-extract
        self.assertFalse(Event.objects.exists())

    def test_post_announcing_several_events_lands_each(self):
        Profile.objects.create(name="Till & Shirka", slug="till-shirka", status="approved")  # config names must exist
        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@TillTailorShirka",
            raw_payload={"default_organizer": "Till & Shirka"},
        )
        drafts = [
            self._draft(title="Tantra Evening"),
            self._draft(title="Shibari Basics", start=self.start + timedelta(days=1)),
            self._draft(title="Old Workshop", start=timezone.now() - timedelta(days=2)),
        ]
        self._run(raw, CollectedEvents(post_kind="announcement", events=drafts))
        titles = set(Event.objects.filter(raw_message=raw).values_list("title", flat=True))
        self.assertEqual(titles, {"Tantra Evening", "Shibari Basics"})
        self.assertEqual(Profile.objects.filter(name="Till & Shirka").count(), 1)  # one organizer, not one per event
        self.assertEqual(raw.extraction_status, "extracted")  # the best per-event outcome
        self.assertEqual(sorted(a.error for a in raw.attempts.all()), ["", "", "past_event"])

    def test_images_reach_the_extractor_and_are_dropped_after(self):
        from pydantic_ai import BinaryContent

        flyer, back = _flyer_b64(800, 600), _flyer_b64(800, 600, "navy")
        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@IKSKBerlin",
            text="THURSDAY 1.10.26",
            raw_payload={"default_organizer": "IKSK", "images": [flyer, back]},
        )
        agent = self._run(raw, CollectedEvents(post_kind="announcement", events=[self._draft()]))
        (parts,), _ = agent.return_value.run_sync.call_args
        self.assertIn("THURSDAY 1.10.26", parts[0])
        self.assertEqual(
            [(p.data, p.media_type) for p in parts[1:]],
            [(base64.b64decode(flyer), "image/jpeg"), (base64.b64decode(back), "image/jpeg")],
        )
        self.assertTrue(all(isinstance(p, BinaryContent) for p in parts[1:]))
        self.assertEqual(raw.raw_payload, {"default_organizer": "IKSK"})  # image bytes do not outlive the pipeline
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

        raw = self._raw(raw_payload={"default_organizer": "IKSK", "images": ["aGVsbG8="]})
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
        raw = self._process(self._raw(raw_payload={}, channel_id="-100888"), explicit_organizer="Unknown")
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("needs_review", "no_organizer"))
        self.assertFalse(Profile.objects.filter(name__iexact="unknown").exists())

    def test_event_outside_berlin_is_skipped(self):
        raw = self._process(self._raw(), in_berlin_area=False)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("skipped", "not_berlin"))
        self.assertFalse(Event.objects.exists())

    def test_online_only_event_is_kept_without_a_venue(self):
        from venues.models import Venue

        Venue.objects.create(name="IKSK", slug="iksk")
        raw = self._raw(raw_payload={"default_organizer": "IKSK", "venue": "IKSK"})
        self._process(raw, presence="online", in_berlin_area=False, venue_name="Zoom", category="talk")
        event = Event.objects.get(raw_message=raw)
        self.assertEqual((event.presence, event.venue, event.location_note), ("online", None, "Zoom"))
        self.assertEqual((event.category, event.timezone, event.status), ("talk", "Europe/Berlin", "published"))

    def test_a_post_about_an_event_that_announces_none_keeps_its_text_and_kind(self):
        text = "We lost some helpers from our Retreat-Team and would love one more person."
        raw = self._raw(text=text)
        self._run(raw, CollectedEvents(post_kind="about_event", events=[]))
        self.assertEqual((raw.extraction_status, raw.extraction_error, raw.text), ("skipped", "about_event", text))
        self.assertEqual(raw.attempts.get().post_kind, "about_event")
        self.assertFalse(Event.objects.exists())

    def test_the_posts_link_becomes_a_link_row_of_its_source(self):
        raw = self._process(self._raw(), external_url="https://www.eventbrite.com/e/ecstatikink-1010-tickets-1")
        event = Event.objects.get(raw_message=raw)
        [link] = event.links.all()
        self.assertEqual(
            (link.url, link.raw_message, link.site),
            ("https://www.eventbrite.com/e/ecstatikink-1010-tickets-1", raw, "eventbrite.com"),
        )
        self.assertEqual(event.external_url, "")
        self.assertEqual(raw.attempts.get().post_kind, "announcement")

    def test_a_link_that_is_not_a_url_is_left_out(self):
        raw = self._process(self._raw(), external_url="see bio")
        self.assertFalse(Event.objects.get(raw_message=raw).links.exists())

    def _flyer_raw(self, *images, **kwargs):
        return self._raw(
            source_type="telegram_private_channel",
            channel_id="-100555",
            text="",
            raw_payload={"default_organizer": "IKSK", "images": list(images)},
            **kwargs,
        )

    def test_flyer_is_kept_as_one_downsized_cover(self):
        flyer = _flyer_b64(3000, 2000)
        raw = self._process(self._flyer_raw(flyer, _flyer_b64(900, 900, "navy")))
        event = Event.objects.get(raw_message=raw)
        cover = EventImage.objects.get(event=event)  # one cover, not one per attachment
        self.assertTrue(cover.is_cover)
        self.assertTrue(cover.image.name.startswith("events/"))
        with cover.image.open("rb") as f:
            stored = f.read()
        with Image.open(io.BytesIO(stored)) as img:
            self.assertLessEqual(max(img.size), 1600)
            self.assertEqual(img.size, (1600, 1067))  # aspect kept
            self.assertGreater(img.getpixel((800, 500))[0], 150)  # the first attachment, the crimson flyer
        self.assertNotEqual(stored, base64.b64decode(flyer))
        # The original bytes are kept nowhere: not on the row, not in storage.
        self.assertNotIn("images", raw.raw_payload)
        media = [p for p in Path(cover.image.storage.location).rglob("*") if p.is_file()]
        self.assertEqual([p.read_bytes() for p in media].count(base64.b64decode(flyer)), 0)

    def test_small_flyer_is_re_encoded_not_copied(self):
        flyer = _flyer_b64(800, 600)
        raw = self._process(self._flyer_raw(flyer))
        cover = EventImage.objects.get(event__raw_message=raw)
        with cover.image.open("rb") as f:
            stored = f.read()
        self.assertNotEqual(stored, base64.b64decode(flyer))
        with Image.open(io.BytesIO(stored)) as img:
            self.assertEqual(img.size, (800, 600))

    def test_post_without_flyer_gets_no_image(self):
        raw = self._process(self._raw(source_type="telegram_telethon", channel_id="@IKSKBerlin"))
        self.assertTrue(Event.objects.filter(raw_message=raw).exists())
        self.assertFalse(EventImage.objects.exists())

    def test_duplicate_and_second_ingest_never_add_a_second_cover(self):
        flyer = _flyer_b64()
        self._process(self._flyer_raw(flyer, message_id="m1"))
        self.assertEqual(EventImage.objects.count(), 1)
        again = self._process(self._flyer_raw(flyer, message_id="m2"))
        self.assertEqual(again.extraction_status, "duplicate")
        other = self._process(
            self._raw(
                source_type="telegram_telethon",
                channel_id="@IKSKBerlin",
                message_id="m3",
                raw_payload={"default_organizer": "IKSK", "images": [flyer]},
            )
        )
        self.assertEqual(other.extraction_status, "duplicate")
        self.assertEqual(EventImage.objects.count(), 1)
        self.assertEqual(EventImage.objects.filter(is_cover=True).count(), 1)

    def test_one_flyer_covers_each_event_of_a_multi_event_post(self):
        raw = self._flyer_raw(_flyer_b64())
        drafts = [
            self._draft(title="Bondage Jam"),
            self._draft(title="Rope Social", start=self.start + timedelta(days=1)),
        ]
        self._run(raw, CollectedEvents(post_kind="announcement", events=drafts))
        self.assertEqual(
            sorted(EventImage.objects.filter(is_cover=True).values_list("event__title", flat=True)),
            ["Bondage Jam", "Rope Social"],
        )

    def test_private_channel_flyer_rides_its_events_tier(self):
        raw = self._process(self._flyer_raw(_flyer_b64()))
        cover = EventImage.objects.get(event__raw_message=raw)
        self.assertEqual(cover.event.visibility, "semi_public")

    def test_undecodable_flyer_fails_loud_and_keeps_the_row_whole(self):
        raw = self._process(self._flyer_raw("aGVsbG8="))
        self.assertEqual(raw.extraction_status, "failed")
        self.assertEqual(raw.raw_payload["images"], ["aGVsbG8="])
        self.assertFalse(Event.objects.exists())

    def test_storage_failure_mid_landing_leaves_nothing_behind(self):
        from django.core.files.storage import FileSystemStorage

        real_save, calls = FileSystemStorage._save, []

        def save_then_fail(storage, name, content):
            calls.append(name)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_save(storage, name, content)

        flyer = _flyer_b64()
        raw = self._flyer_raw(flyer)
        drafts = [
            self._draft(title="Bondage Jam"),
            self._draft(title="Rope Social", start=self.start + timedelta(days=1)),
        ]
        before = {p for p in self.media_root.rglob("*") if p.is_file()}
        with patch.object(FileSystemStorage, "_save", save_then_fail):
            self._run(raw, CollectedEvents(post_kind="announcement", events=drafts))
        self.assertEqual(len(calls), 2)  # the first cover was written before the second failed
        self.assertEqual(raw.extraction_status, "failed")
        self.assertEqual(raw.raw_payload["images"], [flyer])  # whole row kept for a re-run
        self.assertFalse(Event.objects.exists())
        self.assertFalse(EventImage.objects.exists())
        self.assertEqual({p for p in self.media_root.rglob("*") if p.is_file()}, before)  # no orphaned file


class ModelCallRetryTest(TestCase):
    """ADR-008 D4 (FIRM): a transport error is retried up to twice; a reply that does not parse never is."""

    def test_the_router_client_retries_transport_errors_twice(self):
        from ingestion.extraction import router_model

        self.assertEqual(router_model("m").client.max_retries, 2)

    def test_both_collector_calls_never_retry_a_bad_reply(self):
        from ingestion.extraction import consolidate, extract_collected_events
        from ingestion.schemas import Consolidation

        with patch("ingestion.extraction.Agent") as MockAgent:
            MockAgent.return_value.run_sync.return_value.output = CollectedEvents(post_kind="other", events=[])
            extract_collected_events("t", [], {})
            MockAgent.return_value.run_sync.return_value.output = Consolidation(decisions=[])
            consolidate([])
        self.assertEqual([c.kwargs["retries"] for c in MockAgent.call_args_list], [0, 0])
