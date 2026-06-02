"""
TDD tests for kb-a4u.19: Event D1 field completion.
Covers:
  Part 1 — category CharField (model field + migration + form/API wiring)
  Part 2 — cover-image upload authoring (set_event_cover service + web form + API endpoint)

Acceptance criteria tested:
  (a) Event.category field exists with v0 choices; migration clean.
  (b) category persists + reads back via web EventForm AND JSON API.
  (c) cover upload creates EventImage(is_cover=True) via web form AND API cover endpoint.
  (d) single-cover invariant: second cover upload leaves exactly one is_cover=True row.
  (e) can_edit gate: non-claimant blocked (PermissionError / 403).
  (f) invalid image (oversize or bad extension) raises (fails loud).
"""

import struct
import zlib

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventImage
from organizers.models import Profile, ProfileClaim

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(user, **kwargs):
    """Create event via service (grants user organizer rights)."""
    from syndication.services import create_event

    kwargs.setdefault("title", "Test Event")
    kwargs.setdefault("slug", "test-event")
    kwargs.setdefault("start", timezone.now())
    return create_event(user=user, **kwargs)


def _tiny_png():
    """
    Return bytes of a minimal valid 1x1 red PNG.
    Pure byte-construction — no Pillow dependency.
    """

    def _png_chunk(chunk_type, data):
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    ihdr = _png_chunk(b"IHDR", ihdr_data)
    # Single RGB pixel (red=255, green=0, blue=0), filter byte 0
    raw_row = b"\x00\xff\x00\x00"
    compressed = zlib.compress(raw_row)
    idat = _png_chunk(b"IDAT", compressed)
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _uploaded_png(filename="cover.png", size=None):
    """Return SimpleUploadedFile with valid PNG content."""
    content = _tiny_png()
    if size is not None:
        # Pad to desired size (still a valid file header, validators check size attr)
        content = content + b"\x00" * (size - len(content))
    f = SimpleUploadedFile(filename, content, content_type="image/png")
    # Manually set size attr since SimpleUploadedFile uses len(content)
    f.size = size if size is not None else len(content)
    return f


def _get_identity_token_for(user):
    """Full pairing flow → identity token."""
    import json

    from syndication.test_api import _register_and_get_api_key

    api_key = _register_and_get_api_key(user)
    c = Client()
    resp = c.post(
        "/api/agents/token",
        data=json.dumps({"api_key": api_key}),
        content_type="application/json",
    )
    return json.loads(resp.content)["identity_token"]


# ---------------------------------------------------------------------------
# Part 1a: Event.category field + choices
# ---------------------------------------------------------------------------


class EventCategoryFieldTest(TestCase):
    """Event model has category CharField with v0 vocabulary."""

    def test_category_field_exists_and_is_blank_by_default(self):
        user = _make_vouched_user(username="cat_u1", email="cat_u1@test.com", password="x")
        _make_profile("Cat Profile 1", "cat-profile-1", user=user)
        event = _make_event(user)
        self.assertEqual(event.category, "")

    def test_category_can_be_set_to_v0_choices(self):
        user = _make_vouched_user(username="cat_u2", email="cat_u2@test.com", password="x")
        _make_profile("Cat Profile 2", "cat-profile-2", user=user)
        v0_values = [
            "play_party",
            "workshop",
            "munch",
            "performance",
            "social",
            "festival",
            "other",
        ]
        for i, val in enumerate(v0_values):
            event = _make_event(user, slug=f"cat-event-{i}")
            event.category = val
            event.save(update_fields=["category"])
            event.refresh_from_db()
            self.assertEqual(event.category, val)

    def test_category_field_has_choices(self):
        from events.models import Event

        field = Event._meta.get_field("category")
        choices_keys = [c[0] for c in field.choices]
        self.assertIn("play_party", choices_keys)
        self.assertIn("workshop", choices_keys)
        self.assertIn("munch", choices_keys)
        self.assertIn("performance", choices_keys)
        self.assertIn("social", choices_keys)
        self.assertIn("festival", choices_keys)
        self.assertIn("other", choices_keys)

    def test_category_blank_is_true(self):
        from events.models import Event

        field = Event._meta.get_field("category")
        self.assertTrue(field.blank)


# ---------------------------------------------------------------------------
# Part 1b: category via EventForm (web path)
# ---------------------------------------------------------------------------


class EventCategoryWebFormTest(TestCase):
    """category wired through EventForm and create/update_event service."""

    def setUp(self):
        self.user = _make_vouched_user(username="cat_web", email="cat_web@test.com", password="x")
        _make_profile("Cat Web Profile", "cat-web-profile", user=self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_create_event_via_form_persists_category(self):
        resp = self.client.post(
            "/syndication/events/new/",
            {
                "title": "Cat Create Test",
                "slug": "cat-create-test",
                "start": "2026-06-01T20:00",
                "category": "workshop",
            },
        )
        # Expect redirect (302) on success
        self.assertEqual(resp.status_code, 302)
        event = Event.objects.get(slug="cat-create-test")
        self.assertEqual(event.category, "workshop")

    def test_edit_event_via_form_persists_category(self):
        event = _make_event(self.user, slug="cat-edit-test", title="Cat Edit")
        resp = self.client.post(
            f"/syndication/events/{event.pk}/edit/",
            {
                "title": event.title,
                "slug": event.slug,
                "start": "2026-06-01T20:00",
                "category": "social",
            },
        )
        self.assertEqual(resp.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.category, "social")

    def test_category_field_in_event_form(self):
        from syndication.forms import EventForm

        form = EventForm()
        self.assertIn("category", form.fields)


# ---------------------------------------------------------------------------
# Part 1c: category via JSON API (create / patch / read)
# ---------------------------------------------------------------------------


class EventCategoryAPITest(TestCase):
    """category wired through EventCreateIn, EventUpdateIn, EventOut."""

    def setUp(self):
        self.user = _make_vouched_user(username="cat_api", email="cat_api@test.com", password="x")
        _make_profile("Cat API Profile", "cat-api-profile", user=self.user)
        self.token = _get_identity_token_for(self.user)
        self.client = Client()

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_create_event_via_api_with_category(self):
        import json

        resp = self.client.post(
            "/api/events/",
            data=json.dumps(
                {
                    "title": "Cat API Create",
                    "slug": "cat-api-create",
                    "start": "2026-06-01T20:00:00",
                    "category": "festival",
                }
            ),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.content)
        self.assertEqual(data["category"], "festival")
        event = Event.objects.get(slug="cat-api-create")
        self.assertEqual(event.category, "festival")

    def test_patch_event_via_api_updates_category(self):
        import json

        event = _make_event(self.user, slug="cat-api-patch")
        resp = self.client.patch(
            f"/api/events/{event.pk}/",
            data=json.dumps({"category": "munch"}),
            content_type="application/json",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["category"], "munch")
        event.refresh_from_db()
        self.assertEqual(event.category, "munch")

    def test_get_event_via_api_includes_category(self):
        import json

        event = _make_event(self.user, slug="cat-api-get")
        event.category = "play_party"
        event.save(update_fields=["category"])
        resp = self.client.get(
            f"/api/events/{event.pk}/",
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn("category", data)
        self.assertEqual(data["category"], "play_party")


# ---------------------------------------------------------------------------
# Part 2a: set_event_cover service — web path
# ---------------------------------------------------------------------------


class SetEventCoverServiceTest(TestCase):
    """set_event_cover creates/replaces is_cover=True EventImage."""

    def setUp(self):
        self.user = _make_vouched_user(username="cover_svc", email="cover_svc@test.com", password="x")
        _make_profile("Cover Svc Profile", "cover-svc-profile", user=self.user)
        self.event = _make_event(self.user, slug="cover-svc-event")

    def test_set_cover_creates_event_image(self):
        from syndication.services import set_event_cover

        f = _uploaded_png()
        set_event_cover(self.user, self.event, f)
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1)

    def test_set_cover_single_invariant(self):
        """Second upload replaces first — never more than one is_cover=True row."""
        from syndication.services import set_event_cover

        f1 = _uploaded_png("first.png")
        set_event_cover(self.user, self.event, f1)
        f2 = _uploaded_png("second.png")
        set_event_cover(self.user, self.event, f2)
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1)

    def test_set_cover_raises_permission_error_for_non_claimant(self):
        from syndication.services import set_event_cover

        other_user = _make_vouched_user(username="cover_other", email="cover_other@test.com", password="x")
        _make_profile("Other Profile", "other-profile", user=other_user)
        f = _uploaded_png()
        with self.assertRaises(PermissionError):
            set_event_cover(other_user, self.event, f)

    def test_set_cover_rejects_oversize_image(self):
        from django.core.exceptions import ValidationError

        from a_core.validators import MAX_IMAGE_SIZE
        from syndication.services import set_event_cover

        oversize = _uploaded_png(size=MAX_IMAGE_SIZE + 1)
        with self.assertRaises(ValidationError):
            set_event_cover(self.user, self.event, oversize)

    def test_set_cover_rejects_bad_extension(self):
        from django.core.exceptions import ValidationError

        from syndication.services import set_event_cover

        bad_file = SimpleUploadedFile("cover.gif", b"GIF89a fake", content_type="image/gif")
        with self.assertRaises(ValidationError):
            set_event_cover(self.user, self.event, bad_file)


# ---------------------------------------------------------------------------
# Part 2b: cover upload via web form (event_create + event_hub_edit views)
# ---------------------------------------------------------------------------


class CoverImageWebFormTest(TestCase):
    """Cover upload wired through event_create / event_hub_edit views."""

    def setUp(self):
        self.user = _make_vouched_user(username="cover_web", email="cover_web@test.com", password="x")
        _make_profile("Cover Web Profile", "cover-web-profile", user=self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_create_event_form_has_cover_image_field(self):
        from syndication.forms import EventForm

        form = EventForm()
        self.assertIn("cover_image", form.fields)

    def test_create_event_with_cover_stores_image(self):
        f = _uploaded_png()
        resp = self.client.post(
            "/syndication/events/new/",
            {
                "title": "Cover Create Test",
                "slug": "cover-create-test",
                "start": "2026-06-01T20:00",
                "cover_image": f,
            },
        )
        self.assertEqual(resp.status_code, 302)
        event = Event.objects.get(slug="cover-create-test")
        covers = EventImage.objects.filter(event=event, is_cover=True)
        self.assertEqual(covers.count(), 1)

    def test_edit_event_with_cover_replaces_existing(self):
        event = _make_event(self.user, slug="cover-edit-test", title="Cover Edit")
        # Upload first cover via service
        from syndication.services import set_event_cover

        set_event_cover(self.user, event, _uploaded_png("first.png"))
        # Now edit via form with a new cover
        f2 = _uploaded_png("second.png")
        resp = self.client.post(
            f"/syndication/events/{event.pk}/edit/",
            {
                "title": event.title,
                "slug": event.slug,
                "start": "2026-06-01T20:00",
                "cover_image": f2,
            },
        )
        self.assertEqual(resp.status_code, 302)
        covers = EventImage.objects.filter(event=event, is_cover=True)
        self.assertEqual(covers.count(), 1)


# ---------------------------------------------------------------------------
# Part 2c: cover upload via API endpoint POST /events/{id}/cover
# ---------------------------------------------------------------------------


class CoverImageAPITest(TestCase):
    """Cover upload via multipart API endpoint."""

    def setUp(self):
        self.user = _make_vouched_user(username="cover_api", email="cover_api@test.com", password="x")
        _make_profile("Cover API Profile", "cover-api-profile", user=self.user)
        self.event = _make_event(self.user, slug="cover-api-event")
        self.token = _get_identity_token_for(self.user)
        self.client = Client()

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_upload_cover_creates_event_image(self):
        f = _uploaded_png()
        resp = self.client.post(
            f"/api/events/{self.event.pk}/cover",
            data={"file": f},
            **self._auth_header(),
        )
        self.assertEqual(resp.status_code, 200)
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1)

    def test_upload_cover_single_invariant_via_api(self):
        f1 = _uploaded_png("a.png")
        self.client.post(
            f"/api/events/{self.event.pk}/cover",
            data={"file": f1},
            **self._auth_header(),
        )
        f2 = _uploaded_png("b.png")
        self.client.post(
            f"/api/events/{self.event.pk}/cover",
            data={"file": f2},
            **self._auth_header(),
        )
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1)

    def test_upload_cover_blocked_for_non_claimant(self):
        other_user = _make_vouched_user(username="cov_api_other", email="cov_api_other@test.com", password="x")
        _make_profile("Cov API Other", "cov-api-other", user=other_user)
        other_token = _get_identity_token_for(other_user)
        f = _uploaded_png()
        resp = self.client.post(
            f"/api/events/{self.event.pk}/cover",
            data={"file": f},
            HTTP_AUTHORIZATION=f"Bearer {other_token}",
        )
        self.assertEqual(resp.status_code, 403)

    def test_upload_cover_rejects_bad_extension_via_api(self):
        bad_file = SimpleUploadedFile("cover.gif", b"GIF89a fake", content_type="image/gif")
        resp = self.client.post(
            f"/api/events/{self.event.pk}/cover",
            data={"file": bad_file},
            **self._auth_header(),
        )
        self.assertIn(resp.status_code, [400, 422])

    def test_upload_cover_rejects_oversize_via_api(self):
        from a_core.validators import MAX_IMAGE_SIZE

        oversize = _uploaded_png(size=MAX_IMAGE_SIZE + 1)
        resp = self.client.post(
            f"/api/events/{self.event.pk}/cover",
            data={"file": oversize},
            **self._auth_header(),
        )
        self.assertIn(resp.status_code, [400, 422])


# ---------------------------------------------------------------------------
# Fix 2: web form surfaces cover error instead of 500 (ADR-008 D3)
# ---------------------------------------------------------------------------


class CoverImageWebFormOversizeTest(TestCase):
    """
    Oversize cover upload through event_create / event_hub_edit views must NOT
    return a 500 — it must re-render the form with a visible cover_image error
    (ADR-008 D3: fail loud, render visible error state).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="cover_oversize_web", email="cover_oversize@test.com", password="x")
        _make_profile("Cover Oversize Profile", "cover-oversize-profile", user=self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def test_event_create_oversize_cover_returns_form_with_error_not_500(self):
        """POST oversize cover to event_create must not 500; must re-render form with cover error."""
        from a_core.validators import MAX_IMAGE_SIZE

        oversize = _uploaded_png(size=MAX_IMAGE_SIZE + 1)
        resp = self.client.post(
            "/syndication/events/new/",
            {
                "title": "Oversize Cover Create",
                "slug": "oversize-cover-create",
                "start": "2026-06-01T20:00",
                "cover_image": oversize,
            },
        )
        # Must NOT be a 500
        self.assertNotEqual(resp.status_code, 500)
        # Must re-render (200) — the form with an error, not a redirect
        self.assertEqual(resp.status_code, 200)
        # If the event was created, there must be no orphaned cover image row
        # (the cover upload failed, so no is_cover=True row should exist)
        if Event.objects.filter(slug="oversize-cover-create").exists():
            self.assertFalse(
                EventImage.objects.filter(event__slug="oversize-cover-create", is_cover=True).exists(),
                "Event was created but has an orphaned cover image row — cover error was not rolled back",
            )
        # Response content must surface the cover error
        content = resp.content.decode()
        self.assertTrue(
            "cover" in content.lower() or "image" in content.lower() or "size" in content.lower(),
            "Expected cover/image/size error in response, got: " + content[:500],
        )

    def test_event_hub_edit_oversize_cover_returns_form_with_error_not_500(self):
        """POST oversize cover to event_hub_edit must not 500; must re-render form with cover error."""
        from a_core.validators import MAX_IMAGE_SIZE

        event = _make_event(self.user, slug="oversize-cover-edit", title="Oversize Cover Edit")
        oversize = _uploaded_png(size=MAX_IMAGE_SIZE + 1)
        resp = self.client.post(
            f"/syndication/events/{event.pk}/edit/",
            {
                "title": event.title,
                "slug": event.slug,
                "start": "2026-06-01T20:00",
                "cover_image": oversize,
            },
        )
        # Must NOT be a 500
        self.assertNotEqual(resp.status_code, 500)
        # Must re-render (200) — the form with an error, not a redirect
        self.assertEqual(resp.status_code, 200)
        # Response content must surface the cover error
        content = resp.content.decode()
        self.assertTrue(
            "cover" in content.lower() or "image" in content.lower() or "size" in content.lower(),
            "Expected cover/image/size error in response, got: " + content[:500],
        )


# ---------------------------------------------------------------------------
# Fix 5: list endpoint includes category in returned event dicts
# ---------------------------------------------------------------------------


class EventListAPIIncludesCategoryTest(TestCase):
    """GET /api/events/ returns category in each event dict (regression guard)."""

    def setUp(self):
        self.user = _make_vouched_user(username="cat_list_api", email="cat_list_api@test.com", password="x")
        _make_profile("Cat List API Profile", "cat-list-api-profile", user=self.user)
        self.token = _get_identity_token_for(self.user)
        self.client = Client()

    def _auth_header(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_list_endpoint_includes_category_for_event_with_category_set(self):
        import json

        _event = _make_event(self.user, slug="cat-list-test", category="workshop")
        resp = self.client.get("/api/events/", **self._auth_header())
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        # data may be a list directly or wrapped — handle both
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "items" in data:
            items = data["items"]
        else:
            items = data
        matching = [e for e in items if e.get("slug") == "cat-list-test"]
        self.assertTrue(len(matching) >= 1, "Expected event with slug 'cat-list-test' in list response")
        self.assertIn("category", matching[0])
        self.assertEqual(matching[0]["category"], "workshop")
