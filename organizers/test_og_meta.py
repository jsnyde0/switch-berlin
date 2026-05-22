"""Tests for OG meta tags on organizer profile page — gated on PUBLIC_READ_ENABLED."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from organizers.models import Profile

User = get_user_model()


class OrganizerProfileOGMetaTest(TestCase):
    """OG meta tags appear on organizer profile when PUBLIC_READ_ENABLED=True."""

    def setUp(self):
        self.organizer = Profile.objects.create(
            name="Kinky Collective",
            slug="kinky-collective",
            status="approved",
            description="A community organizer for conscious events.",
        )
        self.url = f"/p/{self.organizer.slug}/"

    def _get_with_flag(self, flag_value):
        """GET the organizer profile page with PUBLIC_READ_ENABLED patched."""
        with patch(
            "a_core.context_processors.get_flag",
            return_value=flag_value,
        ):
            return self.client.get(self.url)

    def test_og_title_present_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:title"')
        self.assertContains(response, self.organizer.name)

    def test_og_description_present_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:description"')

    def test_og_url_present_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:url"')

    def test_og_type_profile_when_public_read_enabled(self):
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'content="profile"')

    def test_og_tags_absent_when_public_read_disabled(self):
        response = self._get_with_flag(False)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'property="og:title"')
        self.assertNotContains(response, 'property="og:description"')
        self.assertNotContains(response, 'property="og:url"')
