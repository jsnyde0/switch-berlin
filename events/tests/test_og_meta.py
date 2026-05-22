"""Tests for OG meta tags on event detail page — gated on PUBLIC_READ_ENABLED."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile

User = get_user_model()


class EventDetailOGMetaTest(TestCase):
    """OG meta tags appear on event detail when PUBLIC_READ_ENABLED=True."""

    def setUp(self):
        self.organizer = Profile.objects.create(
            name="Test Org",
            slug="test-org",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Berlin Kink Night",
            slug="berlin-kink-night",
            organizer=self.organizer,
            start=timezone.now() + timezone.timedelta(days=3),
            status="published",
            description="A great event for the community.",
        )
        self.url = f"/events/{self.organizer.slug}/{self.event.slug}/"

    def _get_with_flag(self, flag_value):
        """GET the event detail page with PUBLIC_READ_ENABLED patched."""
        with patch(
            "a_core.context_processors.get_flag",
            return_value=flag_value,
        ):
            return self.client.get(self.url)

    def test_og_title_present_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:title"')
        self.assertContains(response, self.event.title)

    def test_og_description_present_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:description"')

    def test_og_url_present_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:url"')

    def test_og_type_event_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'content="event"')

    def test_og_tags_absent_when_public_read_disabled(self):
        response = self._get_with_flag(False)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'property="og:title"')
        self.assertNotContains(response, 'property="og:description"')
        self.assertNotContains(response, 'property="og:url"')
