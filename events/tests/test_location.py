"""
Where an event happens (sb-x5xh.6, ruling sb-x5xh.2 (b)): a venue is one real
place that may be run by a profile; anything that is not a real place is a
free-text location note, shown where the venue would be (after it when both
exist). A note-only event has no map pin.
"""

import json
import re
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from venues.models import Venue


class EventLocationRenderTest(TestCase):
    def setUp(self):
        self.org = Profile.objects.create(name="Shirka & Till", slug="shirka-till", status="approved")
        self.iksk = Profile.objects.create(name="IKSK", slug="iksk", status="approved")

    def _event(self, **kwargs):
        return Event.objects.create(
            title="Berlin Temple",
            slug="berlin-temple",
            organizer=self.org,
            start=timezone.now() + timedelta(days=5),
            status="published",
            published_at=timezone.now(),
            **kwargs,
        )

    def _detail(self, event):
        resp = self.client.get(reverse("event-detail", kwargs={"org_slug": self.org.slug, "event_slug": event.slug}))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_venue_run_by_a_profile_links_to_that_profile(self):
        venue = Venue.objects.create(name="IKSK Studio", slug="iksk-studio", run_by=self.iksk)
        html = self._detail(self._event(venue=venue))
        self.assertIn(f'href="{reverse("organizer-profile", kwargs={"slug": "iksk"})}"', html)
        self.assertIn("IKSK Studio", html)

    def test_venue_without_run_by_renders_plain_name(self):
        venue = Venue.objects.create(name="Some Loft", slug="some-loft")
        html = self._detail(self._event(venue=venue))
        self.assertIn("Some Loft", html)
        self.assertNotIn(reverse("organizer-profile", kwargs={"slug": "iksk"}), html)

    def test_location_note_without_venue_renders_the_note(self):
        html = self._detail(self._event(location_note="Secret location, Mitte"))
        self.assertIn("Secret location, Mitte", html)

    def test_venue_and_note_render_venue_then_note(self):
        venue = Venue.objects.create(name="IKSK Studio", slug="iksk-studio", run_by=self.iksk)
        html = self._detail(self._event(venue=venue, location_note="Back entrance, ring twice"))
        self.assertLess(html.index("IKSK Studio"), html.index("Back entrance, ring twice"))

    def test_note_only_event_has_no_map_pin(self):
        self._event(location_note="Secret location, Mitte")
        resp = self.client.get(reverse("event-list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Berlin Temple", content)
        match = re.search(r'id="markers-data" type="application/json">(.*?)</script>', content, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1))["features"], [])
