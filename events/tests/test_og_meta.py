"""Tests for OG meta tags on event detail page — gated on PUBLIC_READ_ENABLED."""

import struct
import tempfile
import zlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from events.models import Event, EventImage
from organizers.models import Profile

User = get_user_model()


def _tiny_png():
    """Return bytes of a minimal valid 1x1 red PNG — no Pillow needed."""

    def _png_chunk(chunk_type, data):
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    ihdr = _png_chunk(b"IHDR", ihdr_data)
    raw_row = b"\x00\xff\x00\x00"
    compressed = zlib.compress(raw_row)
    idat = _png_chunk(b"IDAT", compressed)
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _uploaded_png(filename="cover.png"):
    """Return a SimpleUploadedFile with valid PNG content."""
    content = _tiny_png()
    f = SimpleUploadedFile(filename, content, content_type="image/png")
    f.size = len(content)
    return f


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EventDetailOGImageTest(TestCase):
    """og:image meta tag appears when event has a cover image (is_cover=True EventImage)."""

    def setUp(self):
        self.organizer = Profile.objects.create(
            name="Cover Org",
            slug="cover-org",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Cover Night",
            slug="cover-night",
            organizer=self.organizer,
            start=timezone.now() + timezone.timedelta(days=3),
            status="published",
            description="An event with a cover image.",
        )
        self.url = f"/events/{self.organizer.slug}/{self.event.slug}/"

    def _get_with_flag(self, flag_value):
        with patch(
            "a_core.context_processors.get_flag",
            return_value=flag_value,
        ):
            return self.client.get(self.url)

    def _create_cover_image(self):
        """Create an EventImage with is_cover=True directly (no service)."""
        cover = EventImage(event=self.event, is_cover=True, order=0)
        cover.image.save("cover.png", _uploaded_png(), save=True)
        return cover

    def test_og_image_present_when_cover_set(self):
        """After a cover is set, rendered HTML contains <meta property="og:image"> with the URL."""
        cover = self._create_cover_image()
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:image"')
        self.assertContains(response, cover.image.url)

    def test_cover_image_in_context_when_is_cover_image_exists(self):
        """Detail view passes cover_image context var for an event that has an is_cover EventImage."""
        cover = self._create_cover_image()
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("cover_image", response.context)
        self.assertEqual(response.context["cover_image"].pk, cover.pk)

    def test_og_image_absent_when_no_cover(self):
        """An event with no cover renders no og:image meta tag."""
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'property="og:image"')
