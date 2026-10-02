"""
Find the existing event and improve it (sb-7wzb.16): a duplicate match fills the
kept event's gaps, a re-collected row whose text changed is read again, and a
website re-listing is caught before any extraction call.

Matching rule (sb-x5xh.2 ruling (d), sb-7wzb.16 addenda): same Berlin day AND
(similar titles OR (same start AND (same explicit organizer OR same venue))),
never when both sides carry explicit organizers and the sets share none. A
publisher-attributed organizer counts as absent.

Postgres-only: the duplicate check runs TrigramSimilarity.
"""

import base64
import io
import tempfile
import unittest
from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.postgres.search import TrigramSimilarity
from django.db import connection
from django.db.models import Value
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from events.models import Event, EventArtist, EventImage, EventOrganizer
from ingestion.collected import ingest_collected_rows
from ingestion.models import ExtractionAttempt, RawMessage
from ingestion.schemas import CollectedEvents, EventDraft
from organizers.models import Profile, ProfileClaim
from venues.models import Venue

User = get_user_model()

_PG_ONLY = unittest.skipIf(connection.vendor == "sqlite", "the duplicate check uses TrigramSimilarity (pg_trgm).")

_BERLIN = ZoneInfo("Europe/Berlin")

# What collect.py puts on an IKSK row (website and @IKSKBerlin) from collector_sources.toml.
_IKSK = {"organizer": "IKSK", "venue": "IKSK", "venue_run_by": "IKSK"}


def _flyer_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "crimson").save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


@_PG_ONLY
class FillGapsMergeTest(TestCase):
    @classmethod
    def setUpClass(cls):
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        cls.enterClassContext(override_settings(MEDIA_ROOT=media.name))
        super().setUpClass()

    def setUp(self):
        day = timezone.localdate() + timedelta(days=3)
        self.start = datetime.combine(day, time(19, 0), tzinfo=_BERLIN)
        self.iksk = Profile.objects.create(name="IKSK", slug="iksk", status="approved")
        self.iksk_venue = Venue.objects.create(name="IKSK", slug="iksk-venue")
        self.n = 0
        self.extract_calls = 0

    # -- helpers -----------------------------------------------------------

    def _raw(self, channel="iksk-berlin.de", payload=None, **kwargs):
        self.n += 1
        defaults = dict(
            source_type="website" if "." in channel else "telegram_telethon",
            channel_id=channel,
            message_id=f"m{self.n}",
            text=f"post {self.n}",
            raw_payload=dict(_IKSK) if payload is None else payload,
        )
        defaults.update(kwargs)
        return RawMessage.objects.create(**defaults)

    def _extract(self, raw, *drafts):
        """Run the pipeline on `raw` with the extractor returning `drafts` (EventDraft kwargs)."""
        from ingestion.tasks import process_raw_message

        events = [EventDraft(**{"title": "Bondage Jam", "start": self.start, "confidence": 0.9, **d}) for d in drafts]
        result = MagicMock()
        result.output = CollectedEvents(events=events)
        with patch("ingestion.extraction.Agent") as MockAgent:  # row texts carry no URL: enrichment fetches nothing
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        self.extract_calls += MockAgent.return_value.run_sync.call_count
        raw.refresh_from_db()
        return raw

    def _land(self, channel="iksk-berlin.de", payload=None, raw_kwargs=None, **draft):
        raw = self._extract(self._raw(channel, payload, **(raw_kwargs or {})), draft)
        return raw, raw.attempts.order_by("-id").first().event

    def _organizers(self, event):
        return [(r.profile.name, r.is_primary, r.attribution) for r in event.event_organizer_set.order_by("order")]

    def _snapshot(self, event):
        event = Event.objects.get(pk=event.pk)
        fields = {
            f.attname: getattr(event, f.attname) for f in Event._meta.concrete_fields if f.attname != "updated_at"
        }
        fields["organizers"] = self._organizers(event)
        fields["tags"] = list(event.tags.values_list("slug", flat=True))
        fields["images"] = event.images.count()
        fields["artists"] = list(event.artist_credits.values_list("name", flat=True))
        return fields

    # -- (a) fill gaps -----------------------------------------------------

    def test_a_duplicate_fills_an_empty_description_and_leaves_filled_fields_byte_identical(self):
        _, event = self._land(external_url="https://iksk-berlin.de/bondage-jam", price_min_cents=1500)
        before = self._snapshot(event)
        self.assertEqual(before["description"], "")

        raw, kept = self._land(
            "@IKSKBerlin",
            description="Rope practice for all levels. Bring your own rope.",
            external_url="https://t.me/IKSKBerlin/1",
            price_min_cents=2000,
        )

        after = self._snapshot(event)
        self.assertEqual(after.pop("description"), "Rope practice for all levels. Bring your own rope.")
        before.pop("description")
        self.assertEqual(after, before)
        self.assertEqual(raw.extraction_status, "duplicate")
        self.assertEqual(kept, event)
        self.assertEqual(Event.objects.count(), 1)

    def test_a_duplicate_fills_price_url_tags_artists_and_cover_when_empty(self):
        from events.models import Tag

        Tag.objects.create(label="Rope", slug="rope")
        _, event = self._land()
        self._land(
            "@IKSKBerlin",
            raw_kwargs={"raw_payload": {**_IKSK, "images": [_flyer_b64()]}},
            price_min_cents=1500,
            price_max_cents=2500,
            external_url="https://iksk-berlin.de/jam",
            tags=["rope"],
            artist_names=["Mal"],
        )
        event.refresh_from_db()
        self.assertEqual((event.price_min_cents, event.price_max_cents), (1500, 2500))
        self.assertEqual(event.external_url, "https://iksk-berlin.de/jam")
        self.assertEqual(list(event.tags.values_list("slug", flat=True)), ["rope"])
        self.assertEqual(list(event.artist_credits.values_list("name", flat=True)), ["Mal"])
        self.assertEqual(event.images.filter(is_cover=True).count(), 1)

    def test_a_duplicate_never_adds_a_second_cover(self):
        _, event = self._land(raw_kwargs={"raw_payload": {**_IKSK, "images": [_flyer_b64()]}})
        self._land("@IKSKBerlin", raw_kwargs={"raw_payload": {**_IKSK, "images": [_flyer_b64()]}})
        self.assertEqual(EventImage.objects.filter(event=event).count(), 1)

    def test_a_merge_is_recorded_on_the_duplicates_attempt(self):
        _, event = self._land()
        raw, _ = self._land("@IKSKBerlin", description="Long text")
        attempt = raw.attempts.get()
        self.assertEqual(attempt.event, event)
        self.assertIn("description", attempt.error)

    # -- (b) claimed or organizer-edited events are never touched -----------

    def test_b_claimed_event_never_changes_on_a_duplicate_match(self):
        _, event = self._land()
        ProfileClaim.objects.create(profile=self.iksk, user=User.objects.create_user(username="m", password="pw"))
        before = self._snapshot(event)
        raw, kept = self._land("@IKSKBerlin", description="Filled by the second source", explicit_organizer="Lu")
        self.assertEqual(self._snapshot(event), before)
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))

    def test_b_event_made_by_a_person_never_changes_on_a_duplicate_match(self):
        event = Event.objects.create(title="Bondage Jam", slug="bj", start=self.start, status="published")
        before = self._snapshot(event)
        raw, kept = self._land("@IKSKBerlin", description="Filled by the collector")
        self.assertEqual(self._snapshot(event), before)
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))

    def test_b_wins_over_e3_claimed_event_keeps_its_publisher_organizer_row(self):
        _, event = self._land("@IKSKBerlin", title="IKSK Friday")
        ProfileClaim.objects.create(profile=self.iksk, user=User.objects.create_user(username="m", password="pw"))
        self._land(title="Pelvic Work", explicit_organizer="Visionary Body")
        self.assertIn(("IKSK", True, "publisher"), self._organizers(event))

    # -- (c) re-read rows whose text changed --------------------------------

    def _row(self, text, url_content="", **kwargs):
        row = {
            "source_type": "website",
            "channel_id": "iksk-berlin.de",
            "message_id": "2026-10-09|19 00 - 23 00 Bondage Jam",
            "text": text,
            "raw_payload": dict(_IKSK),
        }
        if url_content:
            row["enriched_payload"] = {"url_content": url_content}
        row.update(kwargs)
        return row

    def _ingest(self, *rows):
        with patch("ingestion.collected.async_task") as task:
            result = ingest_collected_rows(list(rows))
        return result, task.call_count

    def test_c_unchanged_row_is_already_collected(self):
        self._ingest(self._row("Bondage Jam", "page"))
        result, enqueued = self._ingest(self._row("Bondage Jam", "page"))
        self.assertEqual(result, {"created": 0, "already_collected": 1, "re_read": 0, "same_listing": 0})
        self.assertEqual(enqueued, 0)

    def test_c_row_with_changed_text_is_re_extracted_and_fills_gaps(self):
        self._ingest(self._row("Bondage Jam"))
        raw = self._extract(RawMessage.objects.get(), {})
        event = Event.objects.get(raw_message=raw)
        self.assertEqual(event.description, "")

        result, enqueued = self._ingest(self._row("Bondage Jam", "The full page: rope, safety, tea."))
        self.assertEqual(result["re_read"], 1)
        self.assertEqual(enqueued, 1)
        raw.refresh_from_db()
        self.assertEqual(
            (raw.extraction_status, raw.enriched_payload),
            ("pending", {"url_content": "The full page: rope, safety, tea."}),
        )

        self._extract(raw, {"description": "Rope, safety, tea."})
        event.refresh_from_db()
        self.assertEqual(event.description, "Rope, safety, tea.")
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_c_a_sources_own_update_replaces_what_it_said_before(self):
        self._ingest(self._row("Bondage Jam 19-23"))
        raw = self._extract(RawMessage.objects.get(), {"description": "Jam."})
        self._ingest(self._row("Bondage Jam 19-23", "Long page"))
        self._extract(raw, {"description": "A long description from the detail page."})
        self.assertEqual(Event.objects.get().description, "A long description from the detail page.")

    def test_c_a_persons_edit_survives_the_sources_update(self):
        self._ingest(self._row("Bondage Jam 19-23"))
        raw = self._extract(RawMessage.objects.get(), {"description": "Jam."})
        Event.objects.update(description="Edited by staff.")
        self._ingest(self._row("Bondage Jam 19-23", "Long page"))
        self._extract(raw, {"description": "A long description from the detail page."})
        self.assertEqual(Event.objects.get().description, "Edited by staff.")

    def test_c_row_collected_before_hashing_is_re_read_only_when_its_text_differs(self):
        old = self._raw(message_id="old", text="Bondage Jam with the page inlined", extraction_status="extracted")
        same = self._raw(message_id="same", text="Same text", extraction_status="extracted")
        wiped = self._raw(message_id="wiped", text="", extraction_status="skipped", extraction_error="not_event")
        result, enqueued = self._ingest(
            self._row("Bondage Jam", "page", message_id="old"),
            self._row("Same text", "", message_id="same"),
            self._row("A post about nothing", "", message_id="wiped"),
        )
        self.assertEqual((result["re_read"], result["already_collected"], enqueued), (1, 2, 1))
        for raw in (old, same, wiped):
            raw.refresh_from_db()
            self.assertEqual(len(raw.content_hash), 64)
        self.assertEqual(old.extraction_status, "pending")

    def test_c_wiped_row_keeps_its_hash_and_is_re_read_when_it_changes(self):
        self._ingest(self._row("Nothing here"))
        raw = self._extract(RawMessage.objects.get())  # no drafts: wiped
        self.assertEqual((raw.text, raw.extraction_error), ("", "not_event"))
        self.assertEqual(self._ingest(self._row("Nothing here"))[0]["already_collected"], 1)
        self.assertEqual(self._ingest(self._row("Now it is a party"))[0]["re_read"], 1)

    # -- (d) pre-AI website dedup ------------------------------------------

    def test_d_website_relisting_differing_in_punctuation_and_case_costs_no_extraction(self):
        day = self.start.date().isoformat()
        first = self._row(
            "19 00 - 23 00 Bondage Jam!",
            message_id="a",
            raw_payload={**_IKSK, "listing": {"date": day, "title": "19 00 - 23 00 Bondage Jam!"}},
        )
        second = self._row(
            "19 00 - 23 00 BONDAGE-JAM",
            message_id="b",
            raw_payload={**_IKSK, "listing": {"date": day, "title": "19 00 - 23 00 BONDAGE-JAM"}},
        )
        self._ingest(first)
        self._extract(RawMessage.objects.get(message_id="a"), {})
        result, enqueued = self._ingest(second)

        self.assertEqual((result["same_listing"], enqueued), (1, 0))
        raw = RawMessage.objects.get(message_id="b")
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("duplicate", "same_listing"))
        self.assertEqual(raw.attempts.get().event, Event.objects.get())
        self.assertEqual(self.extract_calls, 1)
        self.assertEqual(Event.objects.count(), 1)

    def test_d_relisting_in_one_push_is_caught_too(self):
        day = self.start.date().isoformat()
        rows = [
            self._row("x", message_id=m, raw_payload={**_IKSK, "listing": {"date": day, "title": t}})
            for m, t in (("a", "Bondage Jam"), ("b", "bondage  jam."))
        ]
        result, enqueued = self._ingest(*rows)
        self.assertEqual((result["created"], result["same_listing"], enqueued), (1, 1, 1))

    def test_d_other_day_or_other_source_is_not_a_relisting(self):
        day = self.start.date().isoformat()
        other_day = (self.start.date() + timedelta(days=1)).isoformat()
        rows = [
            self._row("x", message_id="a", raw_payload={"listing": {"date": day, "title": "Bondage Jam"}}),
            self._row("x", message_id="b", raw_payload={"listing": {"date": other_day, "title": "Bondage Jam"}}),
            self._row(
                "x",
                message_id="c",
                channel_id="karada-house.de",
                raw_payload={"listing": {"date": day, "title": "Bondage Jam"}},
            ),
        ]
        result, enqueued = self._ingest(*rows)
        self.assertEqual((result["created"], result["same_listing"], enqueued), (3, 0, 3))

    # -- (e) matching rule -------------------------------------------------

    def _assert_dissimilar(self, a, b):
        sim = Event.objects.annotate(s=TrigramSimilarity(Value(a), b)).values_list("s", flat=True).first()
        self.assertLess(sim, 0.4, f"{a!r} vs {b!r} must stay under the title threshold for this test")

    def test_e1_spike_pairs_match_by_same_start_and_same_venue(self):
        for website, telegram in (
            ("PUSSY MASSAGE w/ Lu", "P.U.S.S.Y Massage"),
            ("GIRLS WITH COCKS w/ Micha Stella", "Girls with C**ks"),
        ):
            _, event = self._land(title=website, venue_name="IKSK")
            self._assert_dissimilar(website, telegram)
            raw, kept = self._land("@IKSKBerlin", title=telegram)
            self.assertEqual((raw.extraction_status, kept), ("duplicate", event), website)
            Event.objects.all().delete()

    def test_e2_different_explicit_organizers_stay_separate_even_with_similar_titles(self):
        _, first = self._land(title="Rope Jam", explicit_organizer="Rope Club")
        raw, second = self._land("@IKSKBerlin", title="Rope Jam!", explicit_organizer="Shibari Berlin")
        self.assertEqual(raw.extraction_status, "extracted")
        self.assertNotEqual(first, second)

    def test_e2_explicit_sets_sharing_one_profile_merge_into_one_row_per_profile(self):
        _, event = self._land(title="Rope Jam", explicit_organizer="Rope Club, Lu")
        raw, kept = self._land("@IKSKBerlin", title="Something else", explicit_organizer="Lu & Mal")
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        self.assertEqual(
            self._organizers(event),
            [("Rope Club", True, "explicit"), ("Lu", False, "explicit"), ("Mal", False, "explicit")],
        )

    def _assert_e3(self, event):
        self.assertEqual(self._organizers(event), [("Visionary Body", True, "explicit")])
        self.assertEqual(event.venue, self.iksk_venue)
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(set(ExtractionAttempt.objects.values_list("event", flat=True)), {event.id})

    def test_e3_website_with_explicit_host_absorbs_the_publisher_attributed_telegram_copy(self):
        _, event = self._land(
            title="Pelvic Work. Das Becken II", explicit_organizer="Visionary Body", venue_name="IKSK"
        )
        self._assert_dissimilar("Pelvic Work. Das Becken II", "Friday at IKSK")
        raw, kept = self._land("@IKSKBerlin", title="Friday at IKSK")
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        event.refresh_from_db()
        self._assert_e3(event)

    def test_e3_explicit_host_replaces_the_publisher_row_on_the_telegram_copy(self):
        _, event = self._land("@IKSKBerlin", title="Friday at IKSK")
        self.assertEqual(self._organizers(event), [("IKSK", True, "publisher")])
        raw, kept = self._land(
            title="Pelvic Work. Das Becken II", explicit_organizer="Visionary Body", venue_name="IKSK"
        )
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        event.refresh_from_db()
        self._assert_e3(event)

    def test_e3_blank_attribution_on_a_collected_unclaimed_event_counts_as_publisher(self):
        _, event = self._land("@IKSKBerlin", title="Friday at IKSK")
        EventOrganizer.objects.filter(event=event).update(attribution="")  # collected before 7d39889
        self._land(title="Pelvic Work", explicit_organizer="Visionary Body")
        event.refresh_from_db()
        self._assert_e3(event)

    def test_e_a_row_re_reading_its_own_claimed_event_never_lands_a_second_copy(self):
        # Dev-DB rows 177/189 (2026-10-02): landed under the claimed publisher before 7d39889,
        # re-read after the off-site host became an explicit organizer.
        claimed = Profile.objects.create(name="IKSK Berlin", slug="iksk-berlin", status="approved")
        ProfileClaim.objects.create(profile=claimed, user=User.objects.create_user(username="m", password="pw"))
        raw, event = self._land(payload={"organizer": "IKSK Berlin"}, title="Cali Sessions w/ Ashraf")
        EventOrganizer.objects.filter(event=event).update(attribution="")
        before = self._snapshot(event)
        raw.text = "re-collected"
        raw.save()
        raw = self._extract(raw, {"title": "Cali Sessions w/ Ashraf", "explicit_organizer": "ashrafalali.com"})
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(self._snapshot(event), before)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_e3_blank_attribution_on_a_persons_event_counts_as_explicit(self):
        Event.objects.create(title="Rope Jam", slug="rj", start=self.start, status="published", organizer=self.iksk)
        raw, _ = self._land(title="Rope Jam", explicit_organizer="Shibari Berlin")
        self.assertEqual(raw.extraction_status, "extracted")
        self.assertEqual(Event.objects.count(), 2)

    def test_e4_no_explicit_organizer_and_no_venue_matches_by_title_only(self):
        payload = {"organizer": "IKSK"}  # no default venue
        _, first = self._land(payload=payload, title="Rope Jam")
        raw, _ = self._land("@other", payload=payload, title="Massage Evening")
        self.assertEqual(raw.extraction_status, "extracted")
        raw, kept = self._land("@third", payload=payload, title="ROPE JAM")
        self.assertEqual((raw.extraction_status, kept), ("duplicate", first))

    def test_e_same_start_needs_a_known_time(self):
        midnight = self.start.replace(hour=0)
        self._land(title="Rope Jam", start=midnight, start_time_unknown=True)
        raw, _ = self._land("@IKSKBerlin", title="Massage Evening", start=midnight, start_time_unknown=True)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_e5_needs_review_row_is_never_a_candidate_and_re_enters_when_changed(self):
        held, _ = self._land(title="Rope Jam", confidence=0.2)
        self.assertEqual(held.extraction_status, "needs_review")
        self.assertFalse(Event.objects.exists())
        raw, event = self._land("@IKSKBerlin", title="Rope Jam")
        self.assertEqual(raw.extraction_status, "extracted")

        row = {
            "source_type": "website",
            "channel_id": held.channel_id,
            "message_id": held.message_id,
            "text": "Rope Jam, now with a host",
            "raw_payload": dict(_IKSK),
        }
        result, enqueued = self._ingest(row)
        self.assertEqual((result["re_read"], enqueued), (1, 1))

    # -- one extraction of one row: its drafts are distinct events ----------

    def test_a_post_with_two_hosted_workshops_lands_two_events_intact(self):
        later = self.start + timedelta(hours=2)
        raw = self._extract(
            self._raw("@IKSKBerlin"),
            {
                "title": "Shibari Workshop w/ Anna",
                "explicit_organizer": "Anna Rope",
                "description": "Anna's floor work.",
            },
            {
                "title": "Shibari Workshop w/ Bea",
                "explicit_organizer": "Bea Knots",
                "description": "Bea's suspension basics.",
                "start": later,
            },
        )
        events = list(Event.objects.order_by("start"))
        self.assertEqual(len(events), 2)
        self.assertEqual([e.description for e in events], ["Anna's floor work.", "Bea's suspension basics."])
        self.assertEqual(self._organizers(events[0]), [("Anna Rope", True, "explicit")])
        self.assertEqual(self._organizers(events[1]), [("Bea Knots", True, "explicit")])
        self.assertEqual(raw.extraction_status, "extracted")

    def test_a_post_with_two_events_at_one_start_and_venue_lands_two_events(self):
        self._extract(
            self._raw("@IKSKBerlin"),
            {"title": "Rope Jam", "description": "Ropes.", "price_min_cents": 1000},
            {"title": "Massage Evening", "description": "Oils.", "price_min_cents": 2500},
        )
        events = {e.title: e for e in Event.objects.all()}
        self.assertEqual(set(events), {"Rope Jam", "Massage Evening"})
        self.assertEqual((events["Rope Jam"].description, events["Rope Jam"].price_min_cents), ("Ropes.", 1000))
        self.assertEqual(
            (events["Massage Evening"].description, events["Massage Evening"].price_min_cents), ("Oils.", 2500)
        )
        self.assertEqual({e.venue for e in events.values()}, {self.iksk_venue})

    # -- re-read: drafts pair one-to-one with the row's own events -----------

    def _reread(self, raw, *drafts):
        raw.text = f"{raw.text} (edited)"
        raw.save(update_fields=["text"])
        return self._extract(raw, *drafts)

    def test_re_read_that_moves_the_date_updates_the_one_event(self):
        raw = self._extract(self._raw(), {"title": "Rope Jam", "description": "Ropes."})
        moved = self.start + timedelta(days=1)
        raw = self._reread(raw, {"title": "Rope Jam", "description": "Ropes.", "start": moved})
        event = Event.objects.get()
        self.assertEqual(event.start, moved)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_re_read_of_a_two_event_post_overwrites_per_event_only_what_this_row_wrote(self):
        raw = self._extract(
            self._raw("@IKSKBerlin"),
            {"title": "Rope Jam", "description": "Ropes."},
            {"title": "Massage Evening", "description": "Oils."},
        )
        Event.objects.filter(title="Massage Evening").update(description="Edited by staff.")
        self._reread(
            raw,
            {"title": "Massage Evening", "description": "Warm oils."},
            {"title": "Rope Jam", "description": "Ropes for all levels."},
        )
        events = {e.title: e.description for e in Event.objects.all()}
        self.assertEqual(events, {"Rope Jam": "Ropes for all levels.", "Massage Evening": "Edited by staff."})

    def test_re_read_leaves_an_event_no_draft_pairs_with_and_records_it(self):
        raw = self._extract(
            self._raw("@IKSKBerlin"),
            {"title": "Rope Jam", "description": "Ropes."},
            {"title": "Massage Evening", "description": "Oils."},
        )
        massage = Event.objects.get(title="Massage Evening")
        before = self._snapshot(massage)
        raw = self._reread(raw, {"title": "Rope Jam", "description": "Ropes!"})
        self.assertEqual(Event.objects.count(), 2)
        self.assertEqual(self._snapshot(massage), before)
        self.assertTrue(raw.attempts.filter(event=massage, error="unpaired_on_re_read").exists())

    def test_re_read_never_changes_a_claimed_event_even_to_move_its_date(self):
        raw = self._extract(self._raw(), {"title": "Rope Jam"})
        event = Event.objects.get()
        ProfileClaim.objects.create(profile=self.iksk, user=User.objects.create_user(username="m", password="pw"))
        before = self._snapshot(event)
        self._reread(raw, {"title": "Rope Jam", "description": "New", "start": self.start + timedelta(days=1)})
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(self._snapshot(event), before)

    # -- residues: images hashed, same_listing only behind a landed event ----

    def test_c_telegram_post_whose_only_change_is_a_new_flyer_is_re_read(self):
        row = self._row("Rope Jam tonight", source_type="telegram_telethon", channel_id="@IKSKBerlin", message_id="7")
        row["raw_payload"] = {**_IKSK, "images": [_flyer_b64()]}
        self._ingest(row)
        RawMessage.objects.update(
            extraction_status="extracted"
        )  # read once; a pending row is re-read by its queued task
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), "navy").save(buf, "JPEG")
        row["raw_payload"] = {**_IKSK, "images": [base64.b64encode(buf.getvalue()).decode()]}
        result, enqueued = self._ingest(row)
        self.assertEqual((result["re_read"], enqueued), (1, 1))

    def test_c_same_text_without_images_keeps_its_hash(self):
        from ingestion.collected import content_hash

        self.assertEqual(content_hash("t", {"url_content": "u"}, []), content_hash("t", {"url_content": "u"}))

    def test_d_relisting_of_a_listing_that_produced_no_event_re_enters_normally(self):
        day = self.start.date().isoformat()
        first = self._row("x", message_id="a", raw_payload={**_IKSK, "listing": {"date": day, "title": "Rope Jam"}})
        self._ingest(first)
        held = self._extract(RawMessage.objects.get(message_id="a"), {"title": "Rope Jam", "confidence": 0.2})
        self.assertEqual(held.extraction_status, "needs_review")
        second = self._row("y", message_id="b", raw_payload={**_IKSK, "listing": {"date": day, "title": "ROPE JAM"}})
        result, enqueued = self._ingest(second)
        self.assertEqual((result["created"], result["same_listing"], enqueued), (1, 0, 1))

    # -- (f) organizer and venue resolved before the duplicate check ----------

    def test_f_duplicate_check_receives_resolved_venue_and_organizer_ids(self):
        Profile.objects.create(name="Visionary Body", slug="vb", status="approved")
        with patch("ingestion.collected.find_duplicate", return_value=None) as spy:
            self._land(title="Pelvic Work", explicit_organizer="Visionary Body", venue_name="IKSK")
        kwargs = spy.call_args.kwargs
        self.assertEqual(kwargs["venue"], self.iksk_venue)
        self.assertEqual(kwargs["explicit"], {Profile.objects.get(name="Visionary Body").id})

    def test_f_a_duplicate_creates_no_profile_or_venue_it_does_not_use(self):
        _, event = self._land(title="Rope Jam", explicit_organizer="Rope Club", venue_name="IKSK")
        self._land("@IKSKBerlin", title="Rope Jam", venue_name="Somewhere New")
        self.assertFalse(Venue.objects.filter(name="Somewhere New").exists())
        self.assertEqual(EventArtist.objects.count(), 0)
