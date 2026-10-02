"""
Collector organizer + artist rule (sb-7wzb.18, ADR-007 D9): the publisher is the
organizer unless the text explicitly names another; every other name is an
artist credit as text; an organizer is never inferred.

Postgres-only: process_raw_message runs the pipeline end to end (pg_trgm duplicate check).
"""

import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventArtist, EventOrganizer
from ingestion.models import RawMessage
from ingestion.schemas import CollectedEvents, EventDraft
from organizers.models import Profile

_PG_ONLY = unittest.skipIf(connection.vendor == "sqlite", "the collected pipeline needs pg_trgm.")

# Dev-DB RawMessage 177 as it stands (2026-10-02): the program row names IKSK as
# host venue; the linked page carries Visionary Body only as site branding.
_ROW_177_TEXT = (
    "Event listed on the IKSK Berlin program (https://iksk-berlin.de/Program).\n"
    "Date: 2026-10-02 (Friday)\n"
    "Entry (time range as 'HH MM - HH MM', then title): 10 - 20 PELVIC WORK. DAS BECKEN II\n"
    "Organizer/host venue: IKSK Berlin, Holzmarkt 25, Berlin\n"
    "Details: https://visionary-body.de/termine/pelvic-work-das-becken-ii-innerer-beziehungsraum-teilearbeit/\n"
)
_ROW_177_PAGE = (
    "Pelvic Work. Das Becken II – Innerer Beziehungsraum/ Teile-Arbeit für Selbstliebe, Lust & Genuss"
    " - Visionary Body\n[![Visionary Body](data:image/svg+xml;base64,...)](https://visionary-body.de/)\n"
    "* [Angebot](#)\n  + [Sexological Bodywork](https://visionary-body.de/somatisches-sexualcoaching/)\n"
)


@_PG_ONLY
class CollectorOrganizerRuleTest(TestCase):
    def setUp(self):
        self.start = timezone.now() + timedelta(days=3)
        self.iksk = Profile.objects.create(name="IKSK Berlin", slug="iksk-berlin", status="approved")

    def _raw(self, **kwargs):
        defaults = dict(
            source_type="website",
            channel_id="iksk-berlin.de",
            message_id="m1",
            text="Bondage Jam",
            raw_payload={"source": "IKSK program page", "default_organizer": "IKSK Berlin"},
        )
        defaults.update(kwargs)
        return RawMessage.objects.create(**defaults)

    def _land(self, raw, **draft_kwargs):
        from ingestion.tasks import process_raw_message

        draft = EventDraft(**{"title": "Bondage Jam", "start": self.start, "confidence": 0.9, **draft_kwargs})
        result = MagicMock()
        result.output = CollectedEvents(events=[draft])
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        raw.refresh_from_db()
        return Event.objects.filter(raw_message=raw).first()

    def _organizers(self, event):
        return [
            (row.profile.name, row.is_primary, row.attribution)
            for row in EventOrganizer.objects.filter(event=event).order_by("order")
        ]

    def _artists(self, event):
        return list(EventArtist.objects.filter(event=event).order_by("order").values_list("name", "profile"))

    # (1) + (7)
    def test_explicit_host_overrides_the_publisher_and_names_go_to_artists(self):
        raw = self._raw(
            text=(
                "Host: Visionary Body · Venue: IKSK Berlin, Holzmarkt 25 · "
                "Modul II mit Mareen Scholl, Juliette Caryl Morgan und Lukas Forstmeyer"
            )
        )
        event = self._land(
            raw,
            explicit_organizer="Visionary Body",
            artist_names=["Mareen Scholl, Juliette Caryl Morgan und Lukas Forstmeyer"],
            venue_name="IKSK Berlin",
            venue_address="Holzmarkt 25",
        )
        self.assertEqual(self._organizers(event), [("Visionary Body", True, "explicit")])
        self.assertEqual(
            self._artists(event),
            [("Mareen Scholl", None), ("Juliette Caryl Morgan", None), ("Lukas Forstmeyer", None)],
        )
        self.assertEqual(
            set(Profile.objects.values_list("name", flat=True)), {"IKSK Berlin", "Visionary Body"}
        )  # the venue made no profile

    # (1b)
    def test_site_branding_is_not_organizer_wording(self):
        raw = self._raw(
            text=_ROW_177_TEXT,
            message_id="2026-10-02|10 - 20 PELVIC WORK. DAS BECKEN II",
            enriched_payload={"url_content": _ROW_177_PAGE},
        )
        event = self._land(raw, title="PELVIC WORK. DAS BECKEN II", explicit_organizer="")
        self.assertEqual(self._organizers(event), [("IKSK Berlin", True, "publisher")])
        self.assertFalse(Profile.objects.filter(name__icontains="visionary").exists())

    # (2) + (7)
    def test_in_house_row_credits_the_publisher_and_the_artist(self):
        event = self._land(self._raw(text="Shibari Basics w/ Lu"), title="Shibari Basics", artist_names=["Lu"])
        self.assertEqual(self._organizers(event), [("IKSK Berlin", True, "publisher")])
        self.assertEqual(self._artists(event), [("Lu", None)])

    # (3) the one chain: explicit -> publisher -> poster -> hold
    def test_explicit_organizer_wins_on_a_board_source(self):
        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@board",
            raw_payload={"source": "Board", "default_organizer": "poster", "poster": "Anna Berg"},
        )
        event = self._land(raw, explicit_organizer="Karada House")
        self.assertEqual(self._organizers(event), [("Karada House", True, "explicit")])

    def test_poster_on_a_board_source_is_the_organizer(self):
        raw = self._raw(
            source_type="telegram_private_group",
            channel_id="board",
            raw_payload={"source": "Board", "default_organizer": "poster", "poster": "Anna Berg"},
        )
        event = self._land(raw, explicit_organizer="")
        self.assertEqual(self._organizers(event), [("Anna Berg", True, "poster")])
        self.assertEqual(event.visibility, "semi_public")

    def test_poster_name_matching_an_existing_profile_reuses_it(self):
        anna = Profile.objects.create(name="Anna Berg", slug="anna-berg", status="approved")
        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@board",
            raw_payload={"source": "Board", "default_organizer": "poster", "poster": "anna  berg"},
        )
        event = self._land(raw)
        self.assertEqual(list(event.organizers.all()), [anna])

    def test_board_row_without_a_poster_name_is_held(self):
        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@board",
            raw_payload={"source": "Board", "default_organizer": "poster"},
        )
        event = self._land(raw)
        self.assertIsNone(event)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("needs_review", "no_organizer"))
        self.assertEqual(Profile.objects.count(), 1)

    def test_numeric_sender_id_never_becomes_a_profile_name(self):
        raw = self._raw(
            source_type="telegram_telethon",
            channel_id="@board",
            sender_id="12345",
            raw_payload={"source": "Board", "default_organizer": "poster"},
        )
        self.assertIsNone(self._land(raw))
        self.assertFalse(Profile.objects.filter(name__contains="12345").exists())

    def test_publisher_on_an_own_channel_source(self):
        event = self._land(self._raw(text="Shibari Basics"), title="Shibari Basics")
        self.assertEqual(self._organizers(event), [("IKSK Berlin", True, "publisher")])

    def test_unset_source_holds_for_review(self):
        raw = self._raw(
            source_type="telegram_telethon", channel_id="@berlinevents", raw_payload={"source": "Berlin events"}
        )
        event = self._land(raw, artist_names=["Lu"])
        self.assertIsNone(event)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("needs_review", "no_organizer"))
        self.assertEqual(Profile.objects.count(), 1)

    def test_configured_sources_use_only_default_organizer(self):
        import tomllib
        from pathlib import Path

        sources = tomllib.loads(Path("tools/switch-cli/collector_sources.toml").read_text())["source"]
        self.assertEqual([s["name"] for s in sources if {"organizer", "aggregator"} & s.keys()], [])

    # (4)
    def test_multi_name_artist_string_yields_one_credit_per_name(self):
        event = self._land(self._raw(), artist_names=["Tina, Ricardo & Mal"])
        self.assertEqual(self._artists(event), [("Tina", None), ("Ricardo", None), ("Mal", None)])
        self.assertFalse(Profile.objects.filter(name__icontains="Ricardo").exists())

    # (4b)
    def test_multi_name_explicit_organizer_yields_one_profile_per_name(self):
        event = self._land(self._raw(), explicit_organizer="Martina Lutz, Ricardo Roehmer & Mal Weeraratne")
        self.assertEqual(
            self._organizers(event),
            [
                ("Martina Lutz", True, "explicit"),
                ("Ricardo Roehmer", False, "explicit"),
                ("Mal Weeraratne", False, "explicit"),
            ],
        )
        self.assertEqual(event.organizer.name, "Martina Lutz")

    def test_explicit_organizer_naming_an_existing_profile_whole_is_not_split(self):
        salt = Profile.objects.create(name="Salt & Pepper", slug="salt-pepper", status="approved")
        event = self._land(self._raw(), explicit_organizer="Salt & Pepper")
        self.assertEqual(event.organizer, salt)
        self.assertEqual(Profile.objects.count(), 2)

    def test_organizer_names_matched_whole_are_still_left_out_of_artists(self):
        Profile.objects.create(name="Martina Lutz, Ricardo Roehmer & Mal Weeraratne", slug="mlrr", status="approved")
        event = self._land(
            self._raw(),
            explicit_organizer="Martina Lutz, Ricardo Roehmer, Mal Weeraratne",
            artist_names=["Martina Lutz", "Ricardo Roehmer", "Mal Weeraratne", "Kim"],
        )
        self.assertEqual(self._artists(event), [("Kim", None)])

    # (5)
    def test_artist_credit_never_links_a_profile_even_when_the_name_exists(self):
        Profile.objects.create(name="Lu", slug="lu", status="approved")
        event = self._land(self._raw(), artist_names=["Lu"])
        self.assertEqual(self._artists(event), [("Lu", None)])

    def test_an_organizer_is_not_repeated_as_artist(self):
        event = self._land(self._raw(), explicit_organizer="Lavinia", artist_names=["Lavinia", "Kim"])
        self.assertEqual(self._artists(event), [("Kim", None)])

    # (6)
    def test_organizer_match_is_exact_normalized_never_fuzzy(self):
        event = self._land(self._raw(), explicit_organizer="IKSK Berlin e.V.")
        self.assertEqual(event.organizer.name, "IKSK Berlin e.V.")
        self.assertEqual(Profile.objects.filter(name__istartswith="IKSK").count(), 2)

    def test_organizer_match_ignores_case_punctuation_and_spacing(self):
        event = self._land(self._raw(), explicit_organizer="  iksk   BERLIN! ")
        self.assertEqual(event.organizer, self.iksk)
        self.assertEqual(self._organizers(event), [("IKSK Berlin", True, "explicit")])

    def test_publisher_from_config_matches_exact_normalized(self):
        raw = self._raw(raw_payload={"source": "IKSK program page", "default_organizer": "iksk berlin"})
        event = self._land(raw)
        self.assertEqual(event.organizer, self.iksk)

    def test_extraction_prompt_carries_no_known_organizer_list(self):
        from ingestion.extraction import COLLECTED_PROMPT, EXTRACTION_PROMPT, _known_names

        self.assertNotIn("{organizer_names}", COLLECTED_PROMPT + EXTRACTION_PROMPT)
        self.assertNotIn("organizer_names", _known_names())

    def test_no_name_without_publisher_is_held(self):
        raw = self._raw(source_type="telegram_telethon", channel_id="@group", raw_payload={"source": "group"})
        event = self._land(raw, explicit_organizer="Unknown", artist_names=["Lu"])
        self.assertIsNone(event)
        self.assertEqual((raw.extraction_status, raw.extraction_error), ("needs_review", "no_organizer"))

    # (8)
    def test_private_channel_artist_names_are_stored_on_a_semi_public_event(self):
        Profile.objects.create(name="Fist Them Berlin", slug="fist-them-berlin", status="approved")
        raw = self._raw(
            source_type="telegram_private_channel",
            channel_id="-100123",
            raw_payload={"source": "Fist Them Berlin", "default_organizer": "Fist Them Berlin"},
        )
        event = self._land(raw, artist_names=["Mal"])
        self.assertEqual(event.visibility, "semi_public")
        self.assertEqual(self._artists(event), [("Mal", None)])
        self.assertEqual(self._organizers(event), [("Fist Them Berlin", True, "publisher")])
