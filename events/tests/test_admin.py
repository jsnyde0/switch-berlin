from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from ingestion.models import ExtractionAttempt, RawMessage
from organizers.models import Profile

User = get_user_model()


class EventAdminTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(self.superuser)
        self.organizer = Profile.objects.create(
            name="Test Org", slug="test-org-admin"
        )

    def _make_event(self, status="draft", **kwargs):
        defaults = dict(
            title="Test Event",
            slug="test-event-admin",
            organizer=self.organizer,
            start=timezone.now() + timedelta(days=1),
            status=status,
        )
        defaults.update(kwargs)
        return Event.objects.create(**defaults)

    def _event_post_data(self, event, status="published"):
        return {
            "title": event.title,
            "slug": event.slug,
            "status": status,
            "start_0": event.start.strftime("%Y-%m-%d"),
            "start_1": event.start.strftime("%H:%M:%S"),
            "currency": event.currency,
            "attendance_count": str(event.attendance_count),
            "interested_count": str(event.interested_count),
            "rating_count": str(event.rating_count),
            "images-TOTAL_FORMS": "0",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "1000",
            # EventOrganizerInline formset management form
            "event_organizer_set-TOTAL_FORMS": "0",
            "event_organizer_set-INITIAL_FORMS": "0",
            "event_organizer_set-MIN_NUM_FORMS": "0",
            "event_organizer_set-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        }

    def test_event_changelist_defaults_to_draft_filter(self):
        draft_event = self._make_event(status="draft")
        published_event = self._make_event(
            status="published", slug="pub-event-admin", title="Published Event Only"
        )
        response = self.client.get("/admin/events/event/")
        self.assertEqual(response.status_code, 200)
        # Draft event should be in results; published should not
        self.assertContains(response, draft_event.title)
        self.assertNotContains(response, published_event.title)

    def test_change_form_includes_extraction_data(self):
        raw = RawMessage.objects.create(
            source_type="telegram_bot_forward", raw_payload={}, sender_id="123"
        )
        event = self._make_event(raw_message=raw)
        ExtractionAttempt.objects.create(
            raw_message=raw,
            event=event,
            model_name="claude-opus-4-7",
            prompt_version="v1",
            raw_response={"title": "Test"},
            extracted_draft={"title": "Test", "confidence": 0.9},
            confidence_score=0.9,
            success=True,
        )
        response = self.client.get(f"/admin/events/event/{event.id}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"extracted-draft-data", response.content)

    def test_consent_captured_on_first_publish(self):
        self.organizer.consent_recorded_at = None
        self.organizer.save()
        event = self._make_event(status="draft")
        post_data = self._event_post_data(event, status="published")
        post_data["organizer"] = self.organizer.pk
        self.client.post(
            f"/admin/events/event/{event.id}/change/",
            data=post_data,
            follow=True,
        )
        self.organizer.refresh_from_db()
        self.assertIsNotNone(self.organizer.consent_recorded_at)
        self.assertEqual(self.organizer.consent_method, "telegram_forward_implied")

    def test_bulk_publish_captures_consent(self):
        """Bulk publish action should capture consent for organizer's first event."""
        self.organizer.consent_recorded_at = None
        self.organizer.save()
        event = self._make_event(status="draft")
        self.client.post(
            "/admin/events/event/",
            data={
                "action": "publish_events",
                "_selected_action": [str(event.pk)],
                "select_across": "0",
                "index": "0",
            },
        )
        self.organizer.refresh_from_db()
        self.assertIsNotNone(self.organizer.consent_recorded_at)
        self.assertEqual(self.organizer.consent_method, "telegram_forward_implied")

    def test_publish_selected_action_publishes_draft_events(self):
        """publish_selected action sets draft events to published status."""
        event = self._make_event(status="draft", slug="draft-to-publish-admin")
        self.client.post(
            "/admin/events/event/",
            data={
                "action": "publish_selected",
                "_selected_action": [str(event.pk)],
                "select_across": "0",
                "index": "0",
            },
        )
        event.refresh_from_db()
        self.assertEqual(event.status, "published")

    def test_publish_selected_action_skips_non_draft_events(self):
        """publish_selected action does not change non-draft events."""
        event = self._make_event(status="review", slug="review-event-admin")
        self.client.post(
            "/admin/events/event/",
            data={
                "action": "publish_selected",
                "_selected_action": [str(event.pk)],
                "select_across": "0",
                "index": "0",
            },
        )
        event.refresh_from_db()
        self.assertEqual(event.status, "review")

    def test_consent_not_overwritten_on_second_publish(self):
        original_time = timezone.now() - timedelta(days=10)
        self.organizer.consent_recorded_at = original_time
        self.organizer.consent_method = "explicit_opt_in"
        self.organizer.save()
        event = self._make_event(status="draft")
        post_data = self._event_post_data(event, status="published")
        post_data["organizer"] = self.organizer.pk
        self.client.post(
            f"/admin/events/event/{event.id}/change/",
            data=post_data,
            follow=True,
        )
        self.organizer.refresh_from_db()
        # consent_recorded_at should not have changed (already set)
        self.assertEqual(
            self.organizer.consent_recorded_at.date(), original_time.date()
        )
        self.assertEqual(self.organizer.consent_method, "explicit_opt_in")
