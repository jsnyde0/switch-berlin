"""A person's save records the collector-owned groups they changed (ADR-007 D10, sb-7wzb.30 ruling 3)."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
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
