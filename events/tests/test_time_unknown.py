"""
Date-only events (sb-7wzb.4, granter ruling C): an event whose source gives a
date but no time carries start_time_unknown and shows "time to be announced"
wherever its start time would show, never a synthesized 00:00 (ADR-008 D3).
"""

from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import Profile


class TimeUnknownRenderTest(TestCase):
    def setUp(self):
        self.org = Profile.objects.create(name="Shirka & Till", slug="shirka-till", status="approved")
        day = (timezone.localtime() + timedelta(days=5)).date()
        self.event = Event.objects.create(
            title="Berlin Temple",
            slug="berlin-temple",
            organizer=self.org,
            start=timezone.make_aware(datetime(day.year, day.month, day.day)),
            start_time_unknown=True,
            status="published",
            published_at=timezone.now(),
        )

    def test_detail_says_time_to_be_announced(self):
        resp = self.client.get(
            reverse("event-detail", kwargs={"org_slug": self.org.slug, "event_slug": self.event.slug})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "time to be announced")
        self.assertNotContains(resp, "00:00")

    def test_list_card_says_time_to_be_announced(self):
        resp = self.client.get(reverse("event-list"))
        self.assertContains(resp, "Berlin Temple")
        self.assertContains(resp, "time to be announced")
        self.assertNotContains(resp, "00:00")

    def test_listing_projection_text_carries_the_date_only(self):
        from syndication.engine import _compose_listing_body

        body = _compose_listing_body(self.event, "telegram")
        self.assertIn(f"Date: {timezone.localtime(self.event.start):%Y-%m-%d} (time to be announced)", body)
        self.assertNotIn("00:00", body)
