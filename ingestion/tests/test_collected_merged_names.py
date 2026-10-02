"""sb-7wzb.25: the collector resolves organizer, venue and source-config names through MergeRecord.

A merged-away duplicate is never recreated (sb-x5xh.2 rule 5), and a source-config
organizer that names no existing Profile fails the row loud instead of creating one.
"""

import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from ingestion.models import RawMessage
from ingestion.schemas import CollectedEvents, EventDraft
from organizers.merge import merge_profiles, merge_venues
from organizers.models import Profile
from venues.models import Venue

_PG_ONLY = unittest.skipIf(connection.vendor == "sqlite", "the collected pipeline needs pg_trgm.")


@_PG_ONLY
class CollectorMergedNamesTest(TestCase):
    def setUp(self):
        self.start = timezone.now() + timedelta(days=3)
        self.n = 0

    def _land(self, payload=None, **draft_kwargs):
        from ingestion.tasks import process_raw_message

        self.n += 1
        raw = RawMessage.objects.create(
            source_type="website",
            channel_id="soma.example",
            message_id=f"m{self.n}",
            text="post",
            raw_payload={"source": "Soma page"} if payload is None else payload,
        )
        draft = EventDraft(
            **{
                "title": f"Event {self.n}",
                "start": self.start + timedelta(days=self.n),
                "confidence": 0.9,
                **draft_kwargs,
            }
        )
        result = MagicMock()
        result.output = CollectedEvents(post_kind="announcement", events=[draft])
        with (
            patch("ingestion.extraction.Agent") as MockAgent,
            patch("ingestion.enrichment.enrich_urls", return_value={}),
        ):
            MockAgent.return_value.run_sync.return_value = result
            process_raw_message(raw.id)
        raw.refresh_from_db()
        return raw, Event.objects.filter(raw_message=raw).first()

    def _merged_profiles(self):
        winner = Profile.objects.create(name="Soma House", slug="soma-house", status="approved")
        loser = Profile.objects.create(name="SOMA House Berlin", slug="soma-house-berlin", status="approved")
        merge_profiles(winner, loser, None)
        return winner

    def _merged_venues(self):
        winner = Venue.objects.create(name="Club A", slug="club-a")
        loser = Venue.objects.create(name="Club A Berlin", slug="club-a-berlin")
        merge_venues(winner, loser, None)
        return winner

    # (1)
    def test_explicit_organizer_naming_a_merged_profile_lands_on_the_winner(self):
        winner = self._merged_profiles()
        _, event = self._land(explicit_organizer="SOMA House Berlin")
        self.assertEqual(event.organizer, winner)
        self.assertEqual(Profile.objects.count(), 1)

    def test_default_organizer_naming_a_merged_profile_lands_on_the_winner(self):
        winner = self._merged_profiles()
        _, event = self._land({"source": "Soma page", "default_organizer": "SOMA House Berlin"})
        self.assertEqual(event.organizer, winner)
        self.assertEqual(Profile.objects.count(), 1)

    # (2)
    def test_venue_naming_a_merged_venue_lands_on_the_winner(self):
        winner = self._merged_venues()
        _, event = self._land(
            {"source": "Soma page", "default_organizer": "poster", "poster": "Tina"}, venue_name="Club A Berlin"
        )
        self.assertEqual(event.venue, winner)
        self.assertEqual(Venue.objects.count(), 1)

    # (3)
    def test_source_config_venue_naming_a_merged_venue_resolves_to_the_winner(self):
        winner = self._merged_venues()
        host = Profile.objects.create(name="Club Crew", slug="club-crew", status="approved")
        _, event = self._land(
            {
                "source": "Soma page",
                "default_organizer": "Club Crew",
                "venue": "Club A Berlin",
                "venue_run_by": "Club Crew",
            }
        )
        self.assertEqual(event.venue, winner)
        winner.refresh_from_db()
        self.assertEqual(winner.run_by, host)

    def test_source_config_venue_run_by_naming_a_merged_profile_resolves_to_the_winner(self):
        winner = self._merged_profiles()
        venue = Venue.objects.create(name="Soma Space", slug="soma-space")
        self._land(
            {
                "source": "Soma page",
                "default_organizer": "Soma House",
                "venue": "Soma Space",
                "venue_run_by": "SOMA House Berlin",
            }
        )
        venue.refresh_from_db()
        self.assertEqual(venue.run_by, winner)

    def test_source_config_organizer_naming_no_profile_fails_the_row_and_creates_nothing(self):
        raw, event = self._land({"source": "Soma page", "default_organizer": "Typo House"})
        self.assertIsNone(event)
        self.assertEqual(raw.extraction_status, "failed")
        self.assertIn("Typo House", raw.extraction_error)
        self.assertEqual(Profile.objects.count(), 0)


class ExtractionPromptTest(TestCase):
    def test_both_prompts_carry_the_people_rules(self):
        from ingestion.extraction import PEOPLE_RULES, extract_collected_events, extract_event_draft

        with patch("ingestion.extraction.Agent") as MockAgent, patch("ingestion.extraction.router_model"):
            MockAgent.return_value.run_sync.return_value.output = CollectedEvents(post_kind="other", events=[])
            extract_collected_events("text", [], {})
            parts = MockAgent.return_value.run_sync.call_args.args[0]
            self.assertTrue(PEOPLE_RULES.strip())
            self.assertIn(PEOPLE_RULES, parts[0])
            MockAgent.return_value.run_sync.reset_mock()
            MockAgent.return_value.run_sync.return_value.output = EventDraft(
                title="t", start=timezone.now(), confidence=0.9
            )
            extract_event_draft("text", {})
            self.assertIn(PEOPLE_RULES, MockAgent.return_value.run_sync.call_args.args[0])
