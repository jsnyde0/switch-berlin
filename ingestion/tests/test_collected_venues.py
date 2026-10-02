"""
Collector venues (sb-7wzb.19, sb-x5xh.2 ruling (b)): a placeholder becomes the
event's location note, a real place matches a Venue by exact normalized name or
is created (address text, no coordinates), and a source's config names its
default venue and who runs it. Venues never create profiles.

Postgres-only: the duplicate check runs TrigramSimilarity.
"""

import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from events.models import Event
from ingestion.models import RawMessage
from ingestion.schemas import CollectedEvents, EventDraft
from organizers.models import Profile
from venues.address import contains_street_address
from venues.models import Venue

_PG_ONLY = unittest.skipIf(
    connection.vendor == "sqlite",
    "the duplicate check uses TrigramSimilarity (pg_trgm).",
)

# What collect.py's collected_row puts on an IKSK row from collector_sources.toml.
_IKSK_PAYLOAD = {"source": "IKSK program page", "default_organizer": "IKSK", "venue": "IKSK", "venue_run_by": "IKSK"}


@_PG_ONLY
class CollectedVenueTest(TestCase):
    def setUp(self):
        self.start = timezone.now() + timedelta(days=3)
        self.iksk = Profile.objects.create(name="IKSK", slug="iksk", status="approved")
        # The source config's default venue must already exist (the collector never creates it).
        self.iksk_venue = Venue.objects.create(name="IKSK", slug="iksk-venue")
        self.n = 0

    def _land(self, venue_name=None, raw_payload=None, source_type="website", text="post", **draft_kwargs):
        """Run one collected row through the pipeline; return its landed Event."""
        from ingestion.tasks import process_raw_message

        self.n += 1
        raw = RawMessage.objects.create(
            source_type=source_type,
            channel_id="iksk-berlin.de" if source_type == "website" else "-100777",
            message_id=f"m{self.n}",
            text=text,
            raw_payload=dict(_IKSK_PAYLOAD) if raw_payload is None else raw_payload,
        )
        draft = dict(
            title=f"Event {self.n}",
            explicit_organizer="IKSK",
            start=self.start + timedelta(days=self.n),
            confidence=0.9,
            venue_name=venue_name,
        )
        draft.update(draft_kwargs)
        result = MagicMock()
        result.output = CollectedEvents(post_kind="announcement", events=[EventDraft(**draft)])
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        return Event.objects.get(raw_message=raw)

    # (1)
    def test_secret_location_becomes_a_note_not_a_venue(self):
        event = self._land("Secret location, Berlin-Mitte")
        self.assertIsNone(event.venue)
        self.assertEqual(event.location_note, "Secret location, Berlin-Mitte")

    def test_online_and_bare_city_names_become_notes(self):
        for where in ("Online (Zoom)", "Zoom", "Berlin", "Vienna", "Location on request"):
            event = self._land(where)
            self.assertIsNone(event.venue, where)
            self.assertEqual(event.location_note, where)

    def test_extracted_location_note_rides_to_the_event(self):
        event = self._land("SOMA House", location_note="Ring the bell twice")
        self.assertEqual((event.venue.name, event.location_note), ("SOMA House", "Ring the bell twice"))

    # (2)
    def test_name_variants_resolve_to_one_venue(self):
        first = self._land("SOMA House").venue
        second = self._land("Soma House").venue
        third = self._land("  soma   house. ").venue
        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertEqual(Venue.objects.filter(name__iexact="soma house").count(), 1)

    def test_an_existing_venue_is_matched_not_recreated(self):
        seeded = Venue.objects.create(name="Soma House", slug="soma-house", address="Seeded 1")
        self.assertEqual(self._land("SOMA HOUSE").venue, seeded)

    def test_existing_venue_whose_name_holds_an_address_is_matched_whole(self):
        seeded = Venue.objects.create(name="IKSK Berlin (Holzmarkt 25, Haus 2)", slug="iksk-holzmarkt")
        self.assertEqual(self._land("IKSK Berlin (Holzmarkt 25, Haus 2)").venue, seeded)
        self.assertEqual(Venue.objects.count(), 2)  # + the source's default venue "IKSK"

    def test_address_inside_a_name_leaves_a_clean_venue_name(self):
        venue = self._land("IKSK Berlin (Holzmarkt 25, Berlin)").venue
        self.assertEqual(venue.name, "IKSK Berlin")
        self.assertEqual(venue.address, "Holzmarkt 25")

    def test_a_nearby_hint_is_a_note_not_a_venue(self):
        event = self._land("Near S Treptower Park")
        self.assertIsNone(event.venue)
        self.assertEqual(event.location_note, "Near S Treptower Park")

    # (3)
    def test_unknown_place_creates_one_venue_without_coordinates_or_runner(self):
        event = self._land("Wandel-Raum", venue_address="Wandelweg 3, 12043 Berlin")
        venue = event.venue
        self.assertEqual(venue.name, "Wandel-Raum")
        self.assertEqual(venue.address, "Wandelweg 3, 12043 Berlin")
        self.assertIsNone(venue.run_by)
        self.assertIsNone(venue.latitude)
        self.assertIsNone(venue.longitude)
        self.assertEqual(venue.privacy_mode, "public")
        self._land("Wandel-Raum")
        self.assertEqual(Venue.objects.filter(name="Wandel-Raum").count(), 1)

    # (4)
    def test_source_config_sets_its_venues_runner_and_text_names_win(self):
        event = self._land("Wandel-Raum")
        iksk_venue = Venue.objects.get(name="IKSK")
        self.assertEqual(iksk_venue.run_by, self.iksk)
        self.assertEqual(event.venue.name, "Wandel-Raum")
        self.assertIsNone(event.venue.run_by)

    def test_runner_is_never_overwritten(self):
        other = Profile.objects.create(name="Holzmarkt eG", slug="holzmarkt", status="approved")
        self.iksk_venue.run_by = other
        self.iksk_venue.save()
        self._land(None)
        self.assertEqual(Venue.objects.get(name="IKSK").run_by, other)

    def test_default_venue_named_in_config_must_exist(self):
        payload = {**_IKSK_PAYLOAD, "venue": "IKSK Typo"}
        with self.assertRaises(Event.DoesNotExist):
            self._land(None, raw_payload=payload)
        raw = RawMessage.objects.get(message_id=f"m{self.n}")
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("IKSK Typo", raw.extraction_error)
        self.assertFalse(Venue.objects.filter(name="IKSK Typo").exists())
        self.assertIsNone(Venue.objects.get(name="IKSK").run_by)

    def test_runner_named_in_config_must_exist(self):
        payload = {**_IKSK_PAYLOAD, "venue_run_by": "Nobody Known"}
        with self.assertRaises(Event.DoesNotExist):
            self._land(None, raw_payload=payload)
        raw = RawMessage.objects.get(message_id=f"m{self.n}")
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("Nobody Known", raw.extraction_error)
        self.assertFalse(Profile.objects.filter(name="Nobody Known").exists())

    # (4b) + (4c)
    def test_private_venue_row_keeps_the_address_on_a_private_venue(self):
        event = self._land("Private venue in Pankow, Kastanienallee 5 (shared with ticket holders)")
        self.assertFalse(contains_street_address(event.location_note), event.location_note)
        self.assertNotIn("Kastanienallee", event.location_note)
        self.assertIn("ticket holders", event.location_note)
        self.assertIsNotNone(event.venue)
        self.assertIn("Kastanienallee 5", event.venue.address)
        self.assertNotIn("Kastanienallee", event.venue.name)
        self.assertEqual(event.venue.privacy_mode, "private")

    def test_address_in_an_extracted_note_moves_to_a_venue(self):
        event = self._land(None, location_note="Secret flat, Oranienstraße 12, address on request")
        self.assertNotIn("Oranienstraße", event.location_note)
        self.assertIn("Oranienstraße 12", event.venue.address)
        self.assertEqual(event.venue.privacy_mode, "private")

    def test_restricted_wording_in_the_post_body_makes_the_venue_private(self):
        event = self._land(
            "Wandel-Raum",
            venue_address="Wandelweg 3, 12043 Berlin",
            text="Tantra evening at Wandel-Raum. Exact address on request.",
        )
        self.assertEqual(event.venue.privacy_mode, "private")

    def test_restricted_wording_in_the_link_content_makes_the_venue_private(self):
        from ingestion.tasks import process_raw_message

        raw = RawMessage.objects.create(
            source_type="website",
            channel_id="iksk-berlin.de",
            message_id="linked",
            text="post",
            raw_payload={"default_organizer": "IKSK"},
            enriched_payload={"url_content": "The address is shared with ticket holders."},
        )
        draft = EventDraft(
            title="Linked", explicit_organizer="IKSK", start=self.start, confidence=0.9, venue_name="Wandel-Raum"
        )
        result = MagicMock()
        result.output = CollectedEvents(post_kind="announcement", events=[draft])
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        self.assertEqual(Event.objects.get(raw_message=raw).venue.privacy_mode, "private")

    def test_a_note_left_holding_a_street_address_fails_the_row(self):
        # Two addresses: the first goes to a venue, the second would stay in the note.
        with self.assertRaises(Event.DoesNotExist):
            self._land(None, location_note="Oranienstraße 12 or Kastanienallee 5")
        raw = RawMessage.objects.get(message_id=f"m{self.n}")
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("street address", raw.extraction_error)

    def test_public_website_row_with_open_address_gets_a_public_venue(self):
        event = self._land("Wandel-Raum", venue_address="Wandelweg 3, 12043 Berlin")
        self.assertEqual(event.venue.privacy_mode, "public")

    def test_private_channel_row_creates_a_private_venue(self):
        event = self._land("Wandel-Raum", raw_payload={}, source_type="telegram_private_channel")
        self.assertEqual(event.venue.privacy_mode, "private")

    def test_existing_venue_privacy_is_left_alone(self):
        Venue.objects.create(name="Wandel-Raum", slug="wandel-raum", privacy_mode="public")
        event = self._land("Wandel-Raum", raw_payload={}, source_type="telegram_private_channel")
        self.assertEqual(event.venue.privacy_mode, "public")

    # (4d)
    def test_row_naming_no_place_lands_on_the_source_default_venue(self):
        event = self._land(None)
        self.assertEqual(event.venue, Venue.objects.get(name="IKSK"))
        self.assertEqual(event.location_note, "")

    def test_row_with_a_plain_note_and_no_place_lands_on_the_default_venue(self):
        event = self._land(None, location_note="Ring the bell twice")
        self.assertEqual((event.venue, event.location_note), (self.iksk_venue, "Ring the bell twice"))

    def test_row_with_a_placeholder_note_gets_no_default_venue(self):
        event = self._land(None, location_note="Online (Zoom)")
        self.assertIsNone(event.venue)

    def test_row_naming_a_placeholder_gets_a_note_not_the_default_venue(self):
        event = self._land("Online (Zoom)")
        self.assertIsNone(event.venue)
        self.assertEqual(event.location_note, "Online (Zoom)")

    def test_source_without_default_venue_and_no_place_has_neither(self):
        event = self._land(None, raw_payload={"default_organizer": "IKSK"})
        self.assertIsNone(event.venue)
        self.assertEqual(event.location_note, "")

    # (5)
    def test_no_profile_is_created_from_a_venue(self):
        before = set(Profile.objects.values_list("name", flat=True))
        self._land("Wandel-Raum")
        self._land("Private venue in Pankow, Kastanienallee 5 (shared with ticket holders)")
        self._land(None)
        self.assertEqual(set(Profile.objects.values_list("name", flat=True)), before)


class StreetAddressTest(SimpleTestCase):
    def test_street_addresses_are_recognised(self):
        for text in (
            "Kastanienallee 5",
            "Holzmarktstraße 25, 10243 Berlin",
            "Oranienstr. 12",
            "Holzmarkt 25",
            "Am Flutgraben 3",
            "Revaler Strasse 99",
            "10997 Berlin",
        ):
            self.assertTrue(contains_street_address(text), text)

    def test_placeholders_are_not_addresses(self):
        placeholders = (
            "Secret location, Berlin-Mitte",
            "Online (Zoom)",
            "Private venue in Pankow",
            "SOMA House",
            "2 floors",
        )
        for text in placeholders:
            self.assertFalse(contains_street_address(text), text)

    def test_event_location_note_rejects_a_street_address(self):
        from django.core.exceptions import ValidationError

        event = Event(location_note="Kastanienallee 5")
        with self.assertRaises(ValidationError):
            event.clean_fields(exclude=[f.name for f in Event._meta.fields if f.name != "location_note"])
