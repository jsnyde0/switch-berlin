"""A person's save records the collector-owned groups they changed (ADR-007 D10, sb-7wzb.30 ruling 3)."""

import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from events.models import Event
from events.person_edits import record_person_edit
from organizers.models import Profile


class PersonEditTest(TestCase):
    def setUp(self):
        self.org = Profile.objects.create(name="O", slug="o", status="approved")
        self.event = Event.objects.create(
            title="Jam", slug="jam", organizer=self.org, start=timezone.now() + timedelta(days=2), description="D"
        )

    def test_fields_map_to_their_groups(self):
        record_person_edit(self.event, ["start", "location_note", "slug"])
        self.event.refresh_from_db()
        self.assertEqual(self.event.edited_groups, ["date", "place"])

    def test_admin_save_records_what_the_person_changed(self):
        from events.tests.test_admin import EventAdminTest

        staff = get_user_model().objects.create_superuser(username="s", password="pw", email="s@x.de")
        self.client.force_login(staff)
        data = EventAdminTest._event_post_data(None, self.event, status=self.event.status)
        data.update(description="Edited by staff.", organizer=self.org.pk)
        response = self.client.post(f"/admin/events/event/{self.event.id}/change/", data=data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.description, "Edited by staff.")
        self.assertIn("description", self.event.edited_groups)
        self.assertNotIn("title", self.event.edited_groups)

    def test_syndication_update_records_only_changed_fields(self):
        from syndication.services import update_event

        with patch("syndication.authz.can_edit", return_value=True):
            update_event(None, self.event, title="Jam", description="New words")
        self.event.refresh_from_db()
        self.assertEqual(self.event.edited_groups, ["description"])

    def test_admin_save_of_the_organizers_inline_records_the_organizers_group(self):
        from events.tests.test_admin import EventAdminTest

        staff = get_user_model().objects.create_superuser(username="s2", password="pw", email="s2@x.de")
        self.client.force_login(staff)
        other = Profile.objects.create(name="Other", slug="other", status="approved")
        data = EventAdminTest._event_post_data(None, self.event, status=self.event.status)
        data.update(
            {
                "event_organizer_set-TOTAL_FORMS": "1",
                "event_organizer_set-0-profile": other.pk,
                "event_organizer_set-0-order": "1",
                "description": self.event.description,
            }
        )
        response = self.client.post(f"/admin/events/event/{self.event.id}/change/", data=data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertIn("organizers", self.event.edited_groups)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CoverSourceBackfillTest(TestCase):
    """events 0023 gives a collected event's cover its event's raw message as source (ruling 24)."""

    def test_collected_covers_get_their_events_source_and_uploads_stay_sourceless(self):
        import importlib

        from django.apps import apps
        from django.core.files.base import ContentFile

        from events.models import EventImage
        from ingestion.models import RawMessage

        migration = importlib.import_module("events.migrations.0023_eventimage_source")
        org = Profile.objects.create(name="O", slug="o", status="approved")
        raw = RawMessage.objects.create(source_type="telegram_private_group", channel_id="-1", raw_payload={})
        collected = Event.objects.create(title="C", slug="c", organizer=org, start=timezone.now(), raw_message=raw)
        own = Event.objects.create(title="P", slug="p", organizer=org, start=timezone.now())
        images = []
        for event in (collected, own):
            img = EventImage(event=event, is_cover=True)
            img.image.save("x.webp", ContentFile(b"x"), save=True)
            images.append(img)
        migration.backfill_collected_cover_sources(apps, None)
        for img in images:
            img.refresh_from_db()
        self.assertEqual((images[0].raw_message, images[1].raw_message), (raw, None))
