"""
An event's presence and its collected links on the detail page (ADR-007 D11, sb-7wzb.30):
an online event is marked as such; each link a source gave renders once per URL,
named by its site, through the one outbound-link component.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventLink
from ingestion.models import RawMessage
from organizers.models import Profile


class PresenceAndLinksRenderTest(TestCase):
    def setUp(self):
        self.org = Profile.objects.create(name="Shirka & Till", slug="shirka-till", status="approved")

    def _event(self, **kwargs):
        return Event.objects.create(
            title="Emotional Detox | online intro",
            slug="detox",
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

    def _raw(self, channel):
        return RawMessage.objects.create(source_type="telegram_telethon", channel_id=channel, raw_payload={})

    def test_online_event_is_marked_online(self):
        html = self._detail(self._event(presence="online", location_note="Zoom"))
        self.assertIn(">Online</span>", html)
        self.assertIn("Zoom", html)

    def test_in_person_event_has_no_presence_marker(self):
        html = self._detail(self._event())
        self.assertNotIn(">Online</span>", html)

    def test_each_source_link_renders_once_named_by_its_site(self):
        event = self._event()
        url = "https://www.eventbrite.com/e/ecstatikink-1010-tickets-1995458498084"
        EventLink.objects.create(event=event, url=url, raw_message=self._raw("@a"))
        EventLink.objects.create(event=event, url=url, raw_message=self._raw("@b"))
        EventLink.objects.create(event=event, url="https://t.me/IKSKBerlin/7", raw_message=self._raw("@c"))
        html = self._detail(event)
        self.assertEqual(html.count(f'href="{url}"'), 1)
        self.assertIn("eventbrite.com ↗", html)
        self.assertIn("t.me ↗", html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_organizer_page_link_goes_through_the_outbound_component(self):
        html = self._detail(self._event(external_url="https://shirka-till.de/detox"))
        self.assertRegex(html, r'<a href="https://shirka-till.de/detox"\s+target="_blank"\s+rel="noopener noreferrer"')

    def test_the_organizers_own_link_is_shown_once_not_again_in_the_link_list(self):
        url = "https://shirka-till.de/detox"
        event = self._event(external_url=url)
        EventLink.objects.create(event=event, url=url, raw_message=self._raw("@a"))
        html = self._detail(event)
        self.assertEqual(html.count(f'href="{url}"'), 1)


class CollectedUrlMigrationTest(TestCase):
    """events 0022 copies a collected event's external_url into a link row and blanks nothing (ruling 7)."""

    def test_external_url_is_copied_to_a_link_row_and_left_unchanged(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("events.migrations.0022_presence_timezone_links")
        org = Profile.objects.create(name="O", slug="o", status="approved")
        raw = RawMessage.objects.create(source_type="website", channel_id="x.de", raw_payload={})
        url = "https://x.de/e"
        collected = Event.objects.create(
            title="C", slug="c", organizer=org, start=timezone.now(), raw_message=raw, external_url=url
        )
        own = Event.objects.create(title="P", slug="p", organizer=org, start=timezone.now(), external_url=url)
        migration.copy_collected_urls_to_links(apps, None)
        collected.refresh_from_db()
        own.refresh_from_db()
        self.assertEqual((collected.external_url, own.external_url), (url, url))
        self.assertEqual(
            list(EventLink.objects.values_list("event", "url", "raw_message")), [(collected.id, url, raw.id)]
        )
