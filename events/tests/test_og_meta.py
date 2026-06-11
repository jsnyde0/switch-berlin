"""Tests for OG meta tags on event detail page — gated on PUBLIC_READ_ENABLED."""

import re
import struct
import tempfile
import zlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
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

    def test_og_image_default_when_no_cover(self):
        """An event with no cover renders og:image pointing at the site-level default asset."""
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:image"')
        self.assertContains(response, "og-default.png")

    def test_og_image_cover_url_when_cover_set(self):
        """Cover event renders og:image with the absolute cover URL (rendered HTML check)."""
        cover = self._create_cover_image()
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:image"')
        self.assertContains(response, cover.image.url)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CardImageUrlResolverTest(TestCase):
    """events.og.card_image_url returns the right URL for cover and no-cover cases."""

    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        # Simulate Django's request.scheme / get_host
        self.request.META["SERVER_NAME"] = "testserver"
        self.request.META["SERVER_PORT"] = "80"

        self.organizer = Profile.objects.create(
            name="Resolver Org",
            slug="resolver-org",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Resolver Night",
            slug="resolver-night",
            organizer=self.organizer,
            start=timezone.now() + timezone.timedelta(days=3),
            status="published",
            description="Resolver test event.",
        )

    def _create_cover_image(self):
        cover = EventImage(event=self.event, is_cover=True, order=0)
        cover.image.save("cover.png", _uploaded_png(), save=True)
        return cover

    def test_resolver_returns_cover_url_when_cover_exists(self):
        """card_image_url returns the absolute cover image URL when a cover is set."""
        from events.og import card_image_url

        cover = self._create_cover_image()
        url = card_image_url(self.event, self.request)
        # Must be absolute and contain the cover image path
        self.assertIn(cover.image.url, url)
        self.assertTrue(url.startswith("http"))

    def test_resolver_returns_default_url_when_no_cover(self):
        """card_image_url returns the site default absolute URL when no cover is set."""
        from events.og import card_image_url

        url = card_image_url(self.event, self.request)
        self.assertIn("og-default.png", url)
        self.assertTrue(url.startswith("http"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class LivePageOGImageEqualsResolverTest(TestCase):
    """
    The live event-detail page's rendered og:image content must be byte-EQUAL
    to card_image_url(event, request) — for both cover and no-cover events.

    This proves the single resolution point (ADR-003): the live page and the
    studio preview both consume card_image_url(), so preview == reality is
    structurally guaranteed.
    """

    def setUp(self):
        self.organizer = Profile.objects.create(
            name="Equality Org",
            slug="equality-org",
            status="approved",
        )
        self.event = Event.objects.create(
            title="Equality Night",
            slug="equality-night",
            organizer=self.organizer,
            start=timezone.now() + timezone.timedelta(days=3),
            status="published",
            description="Equality resolution test event.",
        )
        self.url = f"/events/{self.organizer.slug}/{self.event.slug}/"

    def _get_with_flag(self, flag_value):
        with patch(
            "a_core.context_processors.get_flag",
            return_value=flag_value,
        ):
            return self.client.get(self.url)

    def _extract_og_image_content(self, response):
        """Extract the content attribute from <meta property="og:image" ...> in the HTML."""
        html = response.content.decode("utf-8")
        # Match <meta property="og:image" content="..." />
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        self.assertIsNotNone(m, "og:image meta tag not found in rendered HTML")
        return m.group(1)

    def _create_cover_image(self):
        cover = EventImage(event=self.event, is_cover=True, order=0)
        cover.image.save("cover.png", _uploaded_png(), save=True)
        return cover

    def test_live_og_image_equals_resolver_for_cover_event(self):
        """
        For a cover event, the rendered og:image content is byte-EQUAL to
        card_image_url(event, request).
        """
        from events.og import card_image_url

        self._create_cover_image()
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)

        rendered_url = self._extract_og_image_content(response)
        resolver_url = card_image_url(self.event, response.wsgi_request)

        self.assertEqual(
            rendered_url,
            resolver_url,
            msg=(
                f"Live og:image ({rendered_url!r}) does not equal "
                f"card_image_url() ({resolver_url!r}) — parallel implementation detected."
            ),
        )

    def test_live_og_image_equals_resolver_for_no_cover_event(self):
        """
        For a no-cover event, the rendered og:image content is byte-EQUAL to
        card_image_url(event, request).
        """
        from events.og import card_image_url

        # No cover image created — uses default
        response = self._get_with_flag(True)
        self.assertEqual(response.status_code, 200)

        rendered_url = self._extract_og_image_content(response)
        resolver_url = card_image_url(self.event, response.wsgi_request)

        self.assertEqual(
            rendered_url,
            resolver_url,
            msg=(
                f"Live og:image ({rendered_url!r}) does not equal "
                f"card_image_url() ({resolver_url!r}) — parallel implementation detected."
            ),
        )
