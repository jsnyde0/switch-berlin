"""
Copies of one collected event consolidate (ADR-007 D10, sb-7wzb.30): code finds
candidates (dates overlap AND one more signal), one model call judges which
existing event a draft is and writes it out in full; the event is rewritten from
it, a person's edit never overwritten. A re-collected row whose text changed is
read again and pairs with its own events (sb-7wzb.16); a website re-listing is
caught before any extraction call. The model call is scripted here
(consolidation_fakes); the real model is scored by the eval set
(ingestion/tests/test_consolidation_eval.py).

Postgres-only: candidate finding and pairing run pg_trgm similarity.
"""

import base64
import io
import tempfile
import unittest
from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from events.models import Event, EventArtist, EventImage, EventLink, EventOrganizer
from ingestion.collected import _similarity, find_candidates, ingest_collected_rows
from ingestion.models import ExtractionAttempt, RawMessage
from ingestion.schemas import CollectedEvents, Consolidation, Decision, EventDraft
from ingestion.tests.consolidation_fakes import all_new, as_draft, judge, same_as_first
from organizers.models import Profile, ProfileClaim
from venues.models import Venue

User = get_user_model()

_PG_ONLY = unittest.skipIf(connection.vendor == "sqlite", "candidate finding uses pg_trgm similarity.")

_BERLIN = ZoneInfo("Europe/Berlin")

# What collect.py puts on an IKSK row (website and @IKSKBerlin) from collector_sources.toml.
_IKSK = {"default_organizer": "IKSK", "venue": "IKSK", "venue_run_by": "IKSK"}


def _flyer_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "crimson").save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


@_PG_ONLY
class ConsolidationTest(TestCase):
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
        self.decide = None  # the scripted consolidation judgement; None = no call expected
        self.requests = []

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
        result.output = CollectedEvents(post_kind="announcement", events=events)
        decide = self.decide or (lambda request: self.fail(f"no consolidation call expected: {request}"))
        with (
            patch("ingestion.extraction.Agent") as MockAgent,  # row texts carry no URL: enrichment fetches nothing
            judge(decide) as seen,
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        self.requests += seen
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

    # -- (a) the same event is rewritten from all its announcements ----------

    def test_a_same_event_is_rewritten_from_the_merged_announcement(self):
        _, event = self._land(price_min_cents=1500)
        self.decide = lambda request: same_as_first(
            request, description="Rope practice for all levels. Bring your own rope.", price_min_cents=2000
        )
        raw, kept = self._land(
            "@IKSKBerlin", description="Bring your own rope.", external_url="https://t.me/IKSKBerlin/1"
        )

        event.refresh_from_db()
        self.assertEqual(kept, event)
        self.assertEqual(event.description, "Rope practice for all levels. Bring your own rope.")
        self.assertEqual(event.price_min_cents, 2000)
        self.assertEqual(raw.extraction_status, "duplicate")
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(
            list(EventLink.objects.values_list("url", "raw_message")), [("https://t.me/IKSKBerlin/1", raw.id)]
        )
        self.assertEqual(event.external_url, "")  # the organizer's own field; the collector writes link rows

    def test_a_the_judgement_sees_the_post_event_and_each_candidate_with_its_announcements(self):
        _, event = self._land(description="Ropes.", artist_names=["Mal"])
        self.decide = same_as_first
        self._land("@IKSKBerlin", title="BONDAGE JAM!")
        [request] = self.requests
        [entry] = request
        self.assertEqual(entry["event"]["title"], "BONDAGE JAM!")
        [candidate] = entry["candidates"]
        self.assertEqual(candidate["id"], event.id)
        self.assertEqual(set(candidate["signals"]), {"host", "venue", "title"})
        self.assertEqual(candidate["organizers"], [{"name": "IKSK", "attribution": "publisher"}])
        self.assertEqual(candidate["artists"], ["Mal"])
        self.assertEqual([a["description"] for a in candidate["announcements"]], ["Ropes."])

    def test_a_same_event_gets_tags_artists_cover_and_link(self):
        from events.models import Tag

        Tag.objects.create(label="Rope", slug="rope")
        _, event = self._land()
        self.decide = same_as_first
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
        self.assertEqual(list(event.links.values_list("url", flat=True)), ["https://iksk-berlin.de/jam"])
        self.assertEqual(list(event.tags.values_list("slug", flat=True)), ["rope"])
        self.assertEqual(list(event.artist_credits.values_list("name", flat=True)), ["Mal"])
        self.assertEqual(event.images.filter(is_cover=True).count(), 1)

    def test_a_same_event_never_adds_a_second_cover(self):
        _, event = self._land(raw_kwargs={"raw_payload": {**_IKSK, "images": [_flyer_b64()]}})
        self.decide = same_as_first
        self._land("@IKSKBerlin", raw_kwargs={"raw_payload": {**_IKSK, "images": [_flyer_b64()]}})
        self.assertEqual(EventImage.objects.filter(event=event).count(), 1)

    def test_a_merge_is_recorded_on_the_duplicates_attempt(self):
        _, event = self._land()
        self.decide = same_as_first
        raw, _ = self._land("@IKSKBerlin", description="Long text")
        attempt = raw.attempts.get()
        self.assertEqual(attempt.event, event)
        self.assertIn("description", attempt.error)
        self.assertEqual(attempt.raw_response["decision"]["same_as"], event.id)
        self.assertEqual(attempt.wrote["description"], "Long text")

    def test_a_persons_edit_is_never_overwritten_by_consolidation(self):
        _, event = self._land(description="Ropes.")
        Event.objects.filter(pk=event.pk).update(description="Edited by staff.", price_min_cents=999)
        self.decide = lambda request: same_as_first(request, description="Merged ropes.", price_min_cents=1500)
        self._land("@IKSKBerlin", title="Bondage Jam (all levels)")
        event.refresh_from_db()
        self.assertEqual((event.description, event.price_min_cents), ("Edited by staff.", 999))
        self.assertEqual(event.title, "Bondage Jam (all levels)")  # an unedited field is still rewritten

        # The edit stays protected on every later consolidation.
        self._land("@third", title="Bondage Jam")
        event.refresh_from_db()
        self.assertEqual((event.description, event.price_min_cents), ("Edited by staff.", 999))

    def test_a_an_empty_merged_value_never_blanks_a_filled_field(self):
        _, event = self._land(description="Ropes.", price_min_cents=1500)
        self.decide = lambda request: same_as_first(request, description="", price_min_cents=None)
        self._land("@IKSKBerlin")
        event.refresh_from_db()
        self.assertEqual((event.description, event.price_min_cents), ("Ropes.", 1500))

    def test_a_unsure_judgement_lands_a_new_event_flagged_for_staff(self):
        _, event = self._land()
        self.decide = lambda request: Consolidation(
            decisions=[Decision(draft=0, possibly_same_as=request[0]["candidates"][0]["id"])]
        )
        raw, new = self._land("@IKSKBerlin")
        self.assertNotEqual(new, event)
        self.assertEqual(new.possible_duplicate_of, event)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_a_judgement_naming_a_non_candidate_fails_the_row_loudly(self):
        self._land()
        other = Event.objects.create(title="Elsewhere", slug="e", start=self.start + timedelta(days=9))
        self.decide = lambda request: Consolidation(
            decisions=[Decision(draft=0, same_as=other.id, event=as_draft(request[0]["event"]))]
        )
        raw = self._extract(self._raw("@IKSKBerlin"), {"description": "Copy"})
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("not a candidate", raw.extraction_error)
        self.assertEqual(Event.objects.count(), 2)
        self.assertEqual(Event.objects.get(title="Bondage Jam").description, "")

    def test_a_judgement_giving_one_event_to_two_post_events_fails_the_row(self):
        _, event = self._land()
        self.decide = lambda request: Consolidation(
            decisions=[Decision(draft=e["draft"], same_as=event.id, event=as_draft(e["event"])) for e in request]
        )
        raw = self._extract(self._raw("@IKSKBerlin"), {"title": "Bondage Jam"}, {"title": "Bondage Jam II"})
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("two post events", raw.extraction_error)

    # -- (b) claimed or organizer-edited events are never touched -----------

    def test_b_claimed_event_never_changes_on_a_match(self):
        _, event = self._land()
        ProfileClaim.objects.create(profile=self.iksk, user=User.objects.create_user(username="m", password="pw"))
        before = self._snapshot(event)
        self.decide = same_as_first
        raw, kept = self._land("@IKSKBerlin", description="Filled by the second source", explicit_organizer="Lu")
        self.assertEqual(self._snapshot(event), before)
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        self.assertFalse(EventLink.objects.exists())

    def test_b_event_made_by_a_person_never_changes_on_a_match(self):
        event = Event.objects.create(title="Bondage Jam", slug="bj", start=self.start, status="published")
        before = self._snapshot(event)
        self.decide = same_as_first
        raw, kept = self._land("@IKSKBerlin", description="Filled by the collector")
        self.assertEqual(self._snapshot(event), before)
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))

    def test_b_wins_over_e3_claimed_event_keeps_its_publisher_organizer_row(self):
        _, event = self._land("@IKSKBerlin", title="IKSK Friday")
        ProfileClaim.objects.create(profile=self.iksk, user=User.objects.create_user(username="m", password="pw"))
        self.decide = same_as_first
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

    # -- (e) candidate finding: dates overlap AND one more signal --------------

    def _candidates(self, draft_kwargs, names=("IKSK",), venue=None):
        draft = EventDraft(**{"title": "Bondage Jam", "start": self.start, "confidence": 0.9, **draft_kwargs})
        return {event.title: signals for event, signals in find_candidates(draft, list(names), venue)}

    def _event(self, title, start=None, end=None, organizer=None, venue=None, artists=()):
        event = Event.objects.create(
            title=title, slug=f"e{Event.objects.count()}", start=start or self.start, end=end, venue=venue
        )
        if organizer is not None:
            EventOrganizer.objects.create(event=event, profile=organizer, is_primary=True, attribution="publisher")
        for name in artists:
            EventArtist.objects.create(event=event, name=name)
        return event

    def test_e_overlapping_dates_alone_never_make_a_candidate(self):
        self._event("Massage Evening")
        self.assertEqual(self._candidates({}, names=["Someone Else"]), {})

    def test_e_each_signal_makes_a_candidate_on_overlapping_dates(self):
        till = Profile.objects.create(name="Till & Shirka - sexpositive Workshops", slug="ts", status="approved")
        self._event("Temple Night", organizer=till)
        self._event("Massage Evening", venue=self.iksk_venue)
        self._event("Cacao Ceremony", artists=["Mal"])
        self._event("BONDAGE-JAM!")
        found = self._candidates({"artist_names": ["Mal & Lu"]}, names=["Till & Shirka"], venue=self.iksk_venue)
        self.assertEqual(
            found,
            {
                "Temple Night": ["host"],
                "Massage Evening": ["venue"],
                "Cacao Ceremony": ["artist"],
                "BONDAGE-JAM!": ["title"],
            },
        )

    def test_e_a_shared_long_title_word_is_a_title_signal(self):
        long_title = "Retreat at Spitzmühle near Berlin with Till and Shirka"
        self._event(long_title)
        self.assertLess(_similarity("Spielwiese Temple Retreat", long_title), 0.3)
        self.assertEqual(self._candidates({"title": "Spielwiese Temple Retreat"}, names=[]), {long_title: ["title"]})

    def test_e_dates_overlap_across_a_multi_day_event(self):
        retreat = self._event("Temple Retreat", start=self.start, end=self.start + timedelta(days=3))
        self.assertEqual(
            self._candidates({"title": "Temple Retreat", "start": self.start + timedelta(days=2)}, names=[]),
            {retreat.title: ["title"]},
        )
        self.assertEqual(
            self._candidates({"title": "Temple Retreat", "start": self.start + timedelta(days=4)}, names=[]), {}
        )

    def test_e_a_moved_event_is_found_under_its_old_date(self):
        self._event("Erotic Jam", start=self.start)
        moved = {"title": "The Erotic Jam", "start": self.start - timedelta(days=1), "moved_from": self.start}
        self.assertEqual(self._candidates(moved, names=[]), {"Erotic Jam": ["title"]})
        self.assertEqual(self._candidates({**moved, "moved_from": None}, names=[]), {})

    def test_e_rejected_and_cancelled_events_are_never_candidates(self):
        self._event("Bondage Jam").__class__.objects.update(status="cancelled")
        self.assertEqual(self._candidates({}), {})

    def test_e1_spike_pairs_are_candidates_by_same_venue(self):
        for website, telegram in (
            ("PUSSY MASSAGE w/ Lu", "P.U.S.S.Y Massage"),
            ("GIRLS WITH COCKS w/ Micha Stella", "Girls with C**ks"),
        ):
            _, event = self._land(title=website, venue_name="IKSK")
            self.decide = same_as_first
            raw, kept = self._land("@IKSKBerlin", title=telegram)
            self.assertEqual((raw.extraction_status, kept), ("duplicate", event), website)
            self.decide = None
            Event.objects.all().delete()

    def test_e2_explicit_sets_sharing_one_profile_merge_into_one_row_per_profile(self):
        _, event = self._land(title="Rope Jam", explicit_organizer="Rope Club, Lu")
        self.decide = same_as_first
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
        self.decide = lambda request: same_as_first(request, title="Pelvic Work. Das Becken II")
        raw, kept = self._land("@IKSKBerlin", title="Friday at IKSK")
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        event.refresh_from_db()
        self._assert_e3(event)

    def test_e3_explicit_host_replaces_the_publisher_row_on_the_telegram_copy(self):
        _, event = self._land("@IKSKBerlin", title="Friday at IKSK")
        self.assertEqual(self._organizers(event), [("IKSK", True, "publisher")])
        self.decide = same_as_first
        raw, kept = self._land(
            title="Pelvic Work. Das Becken II", explicit_organizer="Visionary Body", venue_name="IKSK"
        )
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        event.refresh_from_db()
        self._assert_e3(event)

    def test_e3_blank_attribution_on_a_collected_unclaimed_event_counts_as_publisher(self):
        _, event = self._land("@IKSKBerlin", title="Friday at IKSK")
        EventOrganizer.objects.filter(event=event).update(attribution="")  # collected before 7d39889
        self.decide = same_as_first
        self._land(title="Pelvic Work", explicit_organizer="Visionary Body")
        event.refresh_from_db()
        self._assert_e3(event)

    def test_e_a_row_re_reading_its_own_claimed_event_never_lands_a_second_copy(self):
        # Dev-DB rows 177/189 (2026-10-02): landed under the claimed publisher before 7d39889,
        # re-read after the off-site host became an explicit organizer.
        claimed = Profile.objects.create(name="IKSK Berlin", slug="iksk-berlin", status="approved")
        ProfileClaim.objects.create(profile=claimed, user=User.objects.create_user(username="m", password="pw"))
        raw, event = self._land(payload={"default_organizer": "IKSK Berlin"}, title="Cali Sessions w/ Ashraf")
        EventOrganizer.objects.filter(event=event).update(attribution="")
        before = self._snapshot(event)
        raw.text = "re-collected"
        raw.save()
        raw = self._extract(raw, {"title": "Cali Sessions w/ Ashraf", "explicit_organizer": "ashrafalali.com"})
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(self._snapshot(event), before)
        self.assertEqual(raw.extraction_status, "extracted")

    def test_e3_a_persons_event_shows_its_organizer_as_set_by_a_person(self):
        Event.objects.create(title="Rope Jam", slug="rj", start=self.start, status="published", organizer=self.iksk)
        self.decide = all_new
        raw, _ = self._land(title="Rope Jam", explicit_organizer="Shibari Berlin")
        self.assertEqual(raw.extraction_status, "extracted")
        self.assertEqual(Event.objects.count(), 2)
        [[entry]] = self.requests
        self.assertEqual(entry["candidates"][0]["organizers"], [{"name": "IKSK", "attribution": "set by a person"}])

    def test_e4_no_shared_signal_means_no_consolidation_call(self):
        payload = {"default_organizer": "IKSK"}  # no default venue
        _, first = self._land(payload=payload, title="Rope Jam")
        raw, _ = self._land(
            "@other", payload={"default_organizer": "poster", "poster": "Anna"}, title="Massage Evening"
        )
        self.assertEqual(raw.extraction_status, "extracted")
        self.assertEqual(self.requests, [])
        self.decide = same_as_first
        raw, kept = self._land("@third", payload=payload, title="ROPE JAM")
        self.assertEqual((raw.extraction_status, kept), ("duplicate", first))

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

    def test_re_read_with_a_new_event_first_never_lets_it_match_the_paired_event(self):
        raw = self._extract(self._raw("@IKSKBerlin"), {"title": "Rope Jam", "description": "Ropes."})
        raw = self._reread(
            raw,
            {"title": "Massage Evening", "description": "Oils."},
            {"title": "Rope Jam", "description": "Ropes for all."},
        )
        events = {e.title: e for e in Event.objects.all()}
        self.assertEqual(set(events), {"Rope Jam", "Massage Evening"})
        self.assertEqual(events["Rope Jam"].description, "Ropes for all.")
        self.assertEqual(events["Massage Evening"].description, "Oils.")
        self.assertEqual(raw.attempts.filter(event=events["Rope Jam"], error="re_read").count(), 1)

    def test_re_read_draft_tying_between_two_own_events_pairs_with_neither(self):
        raw = self._extract(
            self._raw("@IKSKBerlin"),
            {"title": "Shibari Workshop w/ Anna", "description": "A."},
            {"title": "Shibari Workshop w/ Bea", "description": "B."},
        )
        anna, bea = (Event.objects.get(title__endswith=n) for n in ("Anna", "Bea"))
        with patch("ingestion.collected.find_candidates", return_value=[]) as spy:
            self._reread(raw, {"title": "Shibari Workshop", "description": "New"})
        self.assertEqual(spy.call_count, 1)  # not paired: it went through candidate finding
        self.assertEqual(Event.objects.count(), 3)
        self.assertTrue(raw.attempts.filter(event=anna, error="unpaired_on_re_read").exists())
        self.assertTrue(raw.attempts.filter(event=bea, error="unpaired_on_re_read").exists())

    def test_re_read_paired_draft_that_ends_skipped_still_records_an_attempt(self):
        raw = self._extract(self._raw(), {"title": "Rope Jam"})
        event = Event.objects.get()
        before = self._snapshot(event)
        raw = self._reread(raw, {"title": "Rope Jam", "confidence": 0.2})
        self.assertEqual(self._snapshot(event), before)
        self.assertTrue(raw.attempts.filter(event=event, error="re_read_needs_review: low_confidence").exists())
        self.assertFalse(raw.attempts.filter(event=event, error="unpaired_on_re_read").exists())

    def test_re_read_that_ended_skipped_is_not_what_the_row_said_last_time(self):
        raw = self._extract(self._raw(), {"title": "Rope Jam", "description": "Ropes."})
        raw = self._reread(raw, {"title": "Rope Jam", "description": "Ropes v2.", "confidence": 0.2})
        self._reread(raw, {"title": "Rope Jam", "description": "Ropes v3."})
        self.assertEqual(Event.objects.get().description, "Ropes v3.")

    def test_two_board_posts_by_different_posters_for_the_same_event_still_merge(self):
        board = {"default_organizer": "poster", "venue": "IKSK"}
        _, event = self._land("@board", {**board, "poster": "Anna Berg"}, title="Rope Jam", venue_name="IKSK")
        self.assertEqual(self._organizers(event), [("Anna Berg", True, "poster")])
        self.decide = same_as_first
        raw, kept = self._land("@board2", {**board, "poster": "Bea Roth"}, title="Rope Jam", venue_name="IKSK")
        self.assertEqual((raw.extraction_status, kept), ("duplicate", event))
        self.assertEqual(Event.objects.count(), 1)

    def test_explicit_organizer_replaces_a_poster_row_on_merge(self):
        board = {"default_organizer": "poster", "venue": "IKSK", "poster": "Anna Berg"}
        _, event = self._land("@board", board, title="Rope Jam", venue_name="IKSK")
        self.decide = same_as_first
        self._land("@IKSKBerlin", title="Rope Jam", explicit_organizer="Visionary Body", venue_name="IKSK")
        self.assertEqual(self._organizers(event), [("Visionary Body", True, "explicit")])

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

    # -- (f) organizer and venue resolved before candidate finding, looked up only --

    def test_f_candidate_finding_receives_the_organizer_names_and_the_resolved_venue(self):
        Profile.objects.create(name="Visionary Body", slug="vb", status="approved")
        with patch("ingestion.collected.find_candidates", return_value=[]) as spy:
            self._land(title="Pelvic Work", explicit_organizer="Visionary Body", venue_name="IKSK")
        names, venue = spy.call_args.args[1:3]
        self.assertEqual((names, venue), (["Visionary Body"], self.iksk_venue))

    def test_f_candidate_finding_creates_no_profile_or_venue(self):
        _, event = self._land(title="Rope Jam", explicit_organizer="Rope Club", venue_name="IKSK")
        self.decide = lambda request: same_as_first(request, venue_name="IKSK", explicit_organizer="Rope Club")
        self._land("@IKSKBerlin", title="Rope Jam", venue_name="Somewhere New")
        self.assertFalse(Venue.objects.filter(name="Somewhere New").exists())
        self.assertEqual(EventArtist.objects.count(), 0)

    # -- re-read whose event other posts also announce: the judgement merges ----

    def test_re_read_of_an_event_other_posts_announce_goes_through_the_judgement(self):
        raw, event = self._land(description="Ropes.")
        self.decide = same_as_first
        self._land("@IKSKBerlin", description="Ropes and tea.")
        self.requests.clear()
        self.decide = lambda request: same_as_first(request, description="Ropes, tea and cake.")
        self._reread(raw, {"title": "Bondage Jam", "description": "Ropes and cake."})
        [[entry]] = self.requests
        self.assertEqual(entry["is"], event.id)
        self.assertEqual([a["description"] for a in entry["candidates"][0]["announcements"]], ["Ropes and tea."])
        self.assertEqual(Event.objects.get().description, "Ropes, tea and cake.")
