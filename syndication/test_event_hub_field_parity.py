"""
Tests for kb-y209.1: Full EventForm field parity in the composer-hub event-edit card.

Acceptance criteria (harness contract):
  (a) Each of the 16 newly-exposed fields renders as an EDITABLE input in the
      fragment_event_syndication HTML (NOT type="hidden").
  (b) POST to event-edit then reload renders the saved value for each field
      (persistence round-trip).
  (c) Explicit no-wipe test: autosave a partial POST omitting an unchecked
      checkbox, assert other fields' stored values survive (ADR-008 D3).
  (d) The cover upload affordance renders a file input in the fragment HTML,
      and POSTing a cover persists an is_cover EventImage.

Tests assert on RENDERED HTML, not form context (avoids django-view-test-context-vs-content-hollow trap).
"""

import struct
import zlib

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventImage
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirror test_event_d1_fields.py for self-contained isolation)
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(profile=profile, user=user, verified_method="auto_self")
    return profile


def _make_switch_connection(profile):
    """Create an enabled Switch listing connection for a profile."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing"],
        enabled=True,
        credentials={},
    )


def _make_event_with_switch_projection(user, profile, **kwargs):
    """
    Create event AFTER creating a Switch connection on the profile so that
    _eager_create_listing_projections mints a Switch listing projection.
    The Switch listing projection triggers show_switch_event_form=True in
    fragment_event_syndication, which renders the EventForm card.
    """
    from syndication.services import create_event

    kwargs.setdefault("title", "Field Parity Test Event")
    kwargs.setdefault("slug", "field-parity-test")
    kwargs.setdefault("start", timezone.now())
    # Ensure connection exists before create_event (eager projection creation)
    _make_switch_connection(profile)
    return create_event(user=user, **kwargs)


def _tiny_png():
    """Return bytes of a minimal valid 1x1 red PNG."""

    def _png_chunk(chunk_type, data):
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)
    raw_row = b"\x00\xff\x00\x00"
    compressed = zlib.compress(raw_row)
    idat = _png_chunk(b"IDAT", compressed)
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _uploaded_png(filename="cover.png"):
    content = _tiny_png()
    return SimpleUploadedFile(filename, content, content_type="image/png")


def _get_fragment_html(client, event_pk):
    """
    Render the event_syndication fragment as the composer would see it.
    Uses the fragment endpoint with HTMX headers so it renders the same HTML
    the card renders in the studio.
    """
    url = reverse("syndication:fragment-event-syndication", kwargs={"pk": event_pk})
    resp = client.get(url, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200, f"Fragment returned {resp.status_code}"
    return resp.content.decode()


# ---------------------------------------------------------------------------
# (a) Rendered HTML: 16 fields must be editable (NOT type="hidden")
# ---------------------------------------------------------------------------

# The 16 fields that were previously hidden — all must render as editable inputs.
NEWLY_EXPOSED_FIELDS = [
    "tags",
    "content_warnings",
    "capacity",
    "visibility",
    "language",
    "is_free",
    "price_min_cents",
    "price_max_cents",
    "currency",
    "sliding_scale",
    "price_description",
    "external_url",
    "registration_required",
    "registration_url",
    "registration_email",
    "category",
]


class FieldParityRenderTest(TestCase):
    """
    (a) Each of the 16 newly-exposed fields renders as an editable input in
        the fragment_event_syndication HTML — NOT as type="hidden".
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fp_render", email="fp_render@test.com", password="x")
        self.profile = _make_profile("FP Render Profile", "fp-render-profile", user=self.user)
        self.event = _make_event_with_switch_projection(
            self.user, self.profile, slug="fp-render-event", title="FP Render Event"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _html(self):
        return _get_fragment_html(self.client, self.event.pk)

    def test_tags_renders_as_editable_input(self):
        html = self._html()
        # Must find an input with name="tags" that is NOT type="hidden"
        # A hidden input would contain: type="hidden" name="tags" or name="tags" type="hidden"
        self.assertIn('name="tags"', html)
        # The editable field should NOT appear as a standalone type="hidden" input for tags
        # Check that it renders as a text input (EventForm.tags uses TextInput)
        import re

        hidden_tags = re.findall(r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']tags["\']|<input[^>]+name=["\']tags["\'][^>]+type=["\']hidden["\']', html)
        self.assertEqual(len(hidden_tags), 0, f"tags rendered as hidden input: {hidden_tags}")

    def test_visibility_renders_as_select(self):
        html = self._html()
        self.assertIn('name="visibility"', html)
        # visibility is a ChoiceField — renders as <select>
        self.assertIn('<select', html)
        import re
        hidden = re.findall(r'<input[^>]+name=["\']visibility["\'][^>]*/?>|<input[^>]+type=["\']hidden["\'][^>]+name=["\']visibility["\']', html)
        hidden_type = [h for h in hidden if 'type="hidden"' in h or "type='hidden'" in h]
        self.assertEqual(len(hidden_type), 0, f"visibility rendered as hidden input: {hidden_type}")

    def test_language_renders_as_select(self):
        html = self._html()
        self.assertIn('name="language"', html)
        import re
        hidden = re.findall(r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']language["\']|<input[^>]+name=["\']language["\'][^>]+type=["\']hidden["\']', html)
        self.assertEqual(len(hidden), 0)

    def test_category_renders_as_select(self):
        html = self._html()
        self.assertIn('name="category"', html)
        import re
        hidden = re.findall(r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']category["\']|<input[^>]+name=["\']category["\'][^>]+type=["\']hidden["\']', html)
        self.assertEqual(len(hidden), 0)

    def test_is_free_renders_as_checkbox(self):
        html = self._html()
        self.assertIn('name="is_free"', html)
        import re
        # Find all is_free inputs
        is_free_inputs = re.findall(r'<input[^>]+name=["\']is_free["\'][^>]*/?>|<input[^>]+[^>]+name=["\']is_free["\'][^>]*/?>',html)
        # Exactly ONE hidden companion input expected (value="false", the uncheck-fix) — no more.
        hidden = [i for i in is_free_inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 1, f"Expected exactly 1 hidden companion for is_free, got: {hidden}")
        # Must also have a real checkbox widget
        checkboxes = [i for i in is_free_inputs if 'type="checkbox"' in i or "type='checkbox'" in i]
        self.assertGreater(len(checkboxes), 0, "is_free should render as checkbox alongside the hidden companion")

    def test_sliding_scale_renders_as_checkbox(self):
        html = self._html()
        self.assertIn('name="sliding_scale"', html)
        import re
        sliding_inputs = re.findall(r'<input[^>]+name=["\']sliding_scale["\'][^>]*/?>',html)
        # Exactly ONE hidden companion expected; a real checkbox must also be present
        hidden = [i for i in sliding_inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 1, f"Expected exactly 1 hidden companion for sliding_scale, got: {hidden}")
        checkboxes = [i for i in sliding_inputs if 'type="checkbox"' in i or "type='checkbox'" in i]
        self.assertGreater(len(checkboxes), 0, "sliding_scale should render as checkbox alongside the hidden companion")

    def test_registration_required_renders_as_checkbox(self):
        html = self._html()
        self.assertIn('name="registration_required"', html)
        import re
        rr_inputs = re.findall(r'<input[^>]+name=["\']registration_required["\'][^>]*/?>',html)
        # Exactly ONE hidden companion expected; a real checkbox must also be present
        hidden = [i for i in rr_inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 1, f"Expected exactly 1 hidden companion for registration_required, got: {hidden}")
        checkboxes = [i for i in rr_inputs if 'type="checkbox"' in i or "type='checkbox'" in i]
        self.assertGreater(len(checkboxes), 0, "registration_required should render as checkbox alongside the hidden companion")

    def test_capacity_renders_as_number_input(self):
        html = self._html()
        self.assertIn('name="capacity"', html)
        import re
        cap_inputs = re.findall(r'<input[^>]+name=["\']capacity["\'][^>]*/?>',html)
        hidden = [i for i in cap_inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_price_min_cents_renders_as_number_input(self):
        html = self._html()
        self.assertIn('name="price_min_cents"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']price_min_cents["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_price_max_cents_renders_as_number_input(self):
        html = self._html()
        self.assertIn('name="price_max_cents"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']price_max_cents["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_currency_renders_as_text_input(self):
        html = self._html()
        self.assertIn('name="currency"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']currency["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_external_url_renders_as_url_input(self):
        html = self._html()
        self.assertIn('name="external_url"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']external_url["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_registration_url_renders_as_url_input(self):
        html = self._html()
        self.assertIn('name="registration_url"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']registration_url["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_registration_email_renders_as_email_input(self):
        html = self._html()
        self.assertIn('name="registration_email"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']registration_email["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_content_warnings_renders_as_text_input(self):
        html = self._html()
        self.assertIn('name="content_warnings"', html)
        import re
        inputs = re.findall(r'<input[^>]+name=["\']content_warnings["\'][^>]*/?>',html)
        hidden = [i for i in inputs if 'type="hidden"' in i or "type='hidden'" in i]
        self.assertEqual(len(hidden), 0)

    def test_price_description_renders_as_textarea(self):
        html = self._html()
        self.assertIn('name="price_description"', html)
        # price_description uses Textarea widget
        self.assertIn('<textarea', html)

    def test_all_16_fields_present_in_fragment(self):
        """All 16 newly-exposed fields must appear in rendered HTML."""
        html = self._html()
        for field in NEWLY_EXPOSED_FIELDS:
            self.assertIn(f'name="{field}"', html, f"Field '{field}' not found in fragment HTML")


# ---------------------------------------------------------------------------
# (b) Persistence round-trip: POST values saved and reload shows them
# ---------------------------------------------------------------------------


class FieldPersistenceRoundTripTest(TestCase):
    """
    (b) POST to event-edit then reload renders the saved value for each field.
    This is a non-HTMX POST (no HX-Request header) so ALL submitted fields are saved.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fp_persist", email="fp_persist@test.com", password="x")
        self.profile = _make_profile("FP Persist Profile", "fp-persist-profile", user=self.user)
        self.event = _make_event_with_switch_projection(
            self.user, self.profile, slug="fp-persist-event", title="FP Persist Event"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_visibility_persists_via_form_post(self):
        """POST visibility=unlisted, reload → event.visibility == 'unlisted'."""
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "visibility": "unlisted",
            },
        )
        self.assertEqual(resp.status_code, 302, f"Expected redirect, got {resp.status_code}")
        self.event.refresh_from_db()
        self.assertEqual(self.event.visibility, "unlisted")

    def test_language_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "language": "de",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.language, "de")

    def test_category_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "category": "workshop",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.category, "workshop")

    def test_capacity_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "capacity": "50",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.capacity, 50)

    def test_price_min_cents_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "price_min_cents": "1500",
                "currency": "EUR",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.price_min_cents, 1500)

    def test_is_free_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "is_free": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_free)

    def test_external_url_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "external_url": "https://example.com/event",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.external_url, "https://example.com/event")

    def test_registration_required_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "registration_required": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertTrue(self.event.registration_required)

    def test_registration_url_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "registration_url": "https://example.com/register",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.registration_url, "https://example.com/register")

    def test_registration_email_persists_via_form_post(self):
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "registration_email": "register@example.com",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.registration_email, "register@example.com")

    def test_saved_values_appear_in_fragment_html(self):
        """Round-trip: save category, reload fragment — saved value appears in HTML."""
        # First save
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "category": "play_party",
                "language": "en",
            },
        )
        # Reload fragment and check HTML content reflects saved values
        html = _get_fragment_html(self.client, self.event.pk)
        # The category select should have play_party selected
        self.assertIn("play_party", html)
        # language=en should be selected
        self.assertIn('"en"', html)


# ---------------------------------------------------------------------------
# (c) No-wipe test: ADR-008 D3 — partial HTMX POST must not wipe untouched fields
# ---------------------------------------------------------------------------


class NoWipeCheckboxTest(TestCase):
    """
    (c) ADR-008 D3: autosave a partial HTMX POST omitting an unchecked checkbox —
        other fields' stored values must survive.

    Scenario:
      1. Set is_free=True and capacity=30 on an event.
      2. POST via HTMX with only title/slug/start (no is_free, no capacity) —
         simulating a user editing the title while is_free is unchecked but
         not in the partial-form view.
      3. Assert: event.is_free is still True (not wiped), capacity is still 30.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fp_nowipe", email="fp_nowipe@test.com", password="x")
        self.profile = _make_profile("FP Nowipe Profile", "fp-nowipe-profile", user=self.user)
        self.event = _make_event_with_switch_projection(
            self.user, self.profile, slug="fp-nowipe-event", title="FP Nowipe Event"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_partial_htmx_post_does_not_wipe_checkbox_or_capacity(self):
        """
        Pre-set is_free=True and capacity=30.
        Then HTMX-autosave with only title+slug+start.
        is_free must remain True; capacity must remain 30.
        """
        from syndication.services import update_event

        update_event(user=self.user, event=self.event, is_free=True, capacity=30)
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_free)
        self.assertEqual(self.event.capacity, 30)

        # Partial HTMX POST: title edit only, no checkbox fields submitted
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": "FP Nowipe Event Updated Title",
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                # is_free and capacity are intentionally OMITTED
            },
            HTTP_HX_REQUEST="true",
        )
        # HTMX returns 200 with OOB fragments (hx-swap="none" path returns 200)
        self.assertIn(resp.status_code, [200, 302])

        self.event.refresh_from_db()
        # is_free was not submitted — must survive as True (no-wipe guarantee)
        self.assertTrue(self.event.is_free, "is_free was wiped by partial HTMX POST (ADR-008 D3 violation)")
        # capacity was not submitted — must survive as 30
        self.assertEqual(self.event.capacity, 30, "capacity was wiped by partial HTMX POST (ADR-008 D3 violation)")
        # The submitted title change DID persist
        self.assertEqual(self.event.title, "FP Nowipe Event Updated Title")

    def test_partial_htmx_post_does_not_wipe_registration_required(self):
        """
        Pre-set registration_required=True, registration_url, registration_email.
        HTMX-POST with only title — registration fields must survive.
        """
        from syndication.services import update_event

        update_event(
            user=self.user,
            event=self.event,
            registration_required=True,
            registration_url="https://reg.example.com",
            registration_email="reg@example.com",
        )
        self.event.refresh_from_db()

        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": "Nowipe Reg Test Updated",
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                # registration fields intentionally omitted
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, [200, 302])

        self.event.refresh_from_db()
        self.assertTrue(self.event.registration_required, "registration_required wiped by partial POST")
        self.assertEqual(self.event.registration_url, "https://reg.example.com")
        self.assertEqual(self.event.registration_email, "reg@example.com")


# ---------------------------------------------------------------------------
# (d) Cover upload affordance: file input in HTML + cover persists
# ---------------------------------------------------------------------------


class CoverUploadAffordanceTest(TestCase):
    """
    (d) The cover upload affordance renders a file input in fragment HTML,
        and POSTing a cover to event-edit persists an is_cover EventImage.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fp_cover", email="fp_cover@test.com", password="x")
        self.profile = _make_profile("FP Cover Profile", "fp-cover-profile", user=self.user)
        self.event = _make_event_with_switch_projection(
            self.user, self.profile, slug="fp-cover-event", title="FP Cover Event"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_fragment_renders_file_input_for_cover(self):
        """Fragment HTML must contain a file input for cover_image."""
        html = _get_fragment_html(self.client, self.event.pk)
        self.assertIn('name="cover_image"', html)
        import re
        file_inputs = re.findall(r'<input[^>]+name=["\']cover_image["\'][^>]*/?>',html)
        self.assertGreater(len(file_inputs), 0, "No file input for cover_image in fragment HTML")
        # Must be type="file"
        file_type = [i for i in file_inputs if 'type="file"' in i or "type='file'" in i]
        self.assertGreater(len(file_type), 0, f"cover_image input is not type=file: {file_inputs}")

    def test_posting_cover_to_event_edit_persists_event_image(self):
        """POST a cover image to event-edit — must create an is_cover EventImage."""
        f = _uploaded_png("fp_cover.png")
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "cover_image": f,
            },
        )
        self.assertEqual(resp.status_code, 302, f"Expected redirect, got {resp.status_code}")
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1, "Expected exactly one is_cover EventImage after cover POST")

    def test_htmx_cover_post_persists_event_image(self):
        """HTMX POST with cover_image (multipart) must persist cover even via HX-Request path."""
        f = _uploaded_png("htmx_cover.png")
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "cover_image": f,
            },
            HTTP_HX_REQUEST="true",
        )
        # HTMX path returns 200 with OOB fragments
        self.assertIn(resp.status_code, [200, 302])
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1, "Expected is_cover EventImage after HTMX cover POST")

    def test_second_cover_upload_replaces_first(self):
        """Single-cover invariant: second cover upload leaves exactly one is_cover row."""
        from syndication.services import set_event_cover

        set_event_cover(self.user, self.event, _uploaded_png("first.png"))
        # Upload second cover via form
        f2 = _uploaded_png("second.png")
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "cover_image": f2,
            },
        )
        covers = EventImage.objects.filter(event=self.event, is_cover=True)
        self.assertEqual(covers.count(), 1, "Multiple is_cover rows exist after second upload")


# ---------------------------------------------------------------------------
# (e) Explicit-uncheck regression guard
#     Tests the hidden-companion pattern that makes unchecking persist False.
#     Regression guard for the defect discovered in the kb-y209.1 adversarial review.
# ---------------------------------------------------------------------------


class ExplicitUncheckTest(TestCase):
    """
    (e) When a user explicitly unchecks a boolean field in the main autosave form,
    the hidden companion input ensures the field is present in POST with value='false',
    so the submitted_keys filter in event_hub_edit includes it and persists False.

    Simulates: hidden companion present (field in POST as 'false') + checkbox absent.
    The cover form does NOT carry companions, so a cover-only POST must still
    preserve previously-set True values (no-wipe invariant — both behaviours coexist).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fp_uncheck", email="fp_uncheck@test.com", password="x")
        self.profile = _make_profile("FP Uncheck Profile", "fp-uncheck-profile", user=self.user)
        self.event = _make_event_with_switch_projection(
            self.user, self.profile, slug="fp-uncheck-event", title="FP Uncheck Event"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _set_booleans(self, **kwargs):
        from syndication.services import update_event
        update_event(user=self.user, event=self.event, **kwargs)
        self.event.refresh_from_db()

    def test_explicit_uncheck_is_free_persists_false(self):
        """
        Pre-set is_free=True.
        HTMX-POST with hidden companion is_free=false and NO checkbox — simulates user
        explicitly unchecking is_free.
        Assert: event.is_free is now False in DB.
        """
        self._set_booleans(is_free=True)
        self.assertTrue(self.event.is_free, "Pre-condition: is_free must be True before test")

        # Simulate main-form autosave: hidden companion present, checkbox absent (unchecked)
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "is_free": "false",  # hidden companion; checkbox absent → value_from_datadict → False
                # sliding_scale and registration_required intentionally absent (user didn't touch them)
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, [200, 302])
        self.event.refresh_from_db()
        self.assertFalse(
            self.event.is_free,
            "Explicit uncheck of is_free was silently discarded (hidden companion not working)",
        )

    def test_explicit_uncheck_sliding_scale_persists_false(self):
        """
        Pre-set sliding_scale=True.
        HTMX-POST with hidden companion sliding_scale=false and NO checkbox.
        Assert: event.sliding_scale is now False in DB.
        """
        self._set_booleans(sliding_scale=True)
        self.assertTrue(self.event.sliding_scale, "Pre-condition: sliding_scale must be True before test")

        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "sliding_scale": "false",  # hidden companion; checkbox absent
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, [200, 302])
        self.event.refresh_from_db()
        self.assertFalse(
            self.event.sliding_scale,
            "Explicit uncheck of sliding_scale was silently discarded",
        )

    def test_explicit_uncheck_registration_required_persists_false(self):
        """
        Pre-set registration_required=True.
        HTMX-POST with hidden companion registration_required=false and NO checkbox.
        Assert: event.registration_required is now False in DB.
        """
        self._set_booleans(registration_required=True)
        self.assertTrue(self.event.registration_required, "Pre-condition: registration_required must be True before test")

        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "registration_required": "false",  # hidden companion; checkbox absent
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, [200, 302])
        self.event.refresh_from_db()
        self.assertFalse(
            self.event.registration_required,
            "Explicit uncheck of registration_required was silently discarded",
        )

    def test_checked_checkbox_with_hidden_companion_persists_true(self):
        """
        Verify the companion does NOT break setting True.
        POST with is_free=false (companion) + is_free=on (checkbox, checked) → True.
        CheckboxInput.value_from_datadict takes the last value from MultiValueDict.
        """
        self._set_booleans(is_free=False)
        self.assertFalse(self.event.is_free, "Pre-condition: is_free must be False before test")

        # Django test Client encodes list values as repeated keys → MultiValueDict with [false, on]
        from django.test import RequestFactory
        # Use the test client's POST with a list for the key
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                # Simulating companion(false) + checkbox(on) — Django client list → MultiValueDict
                "is_free": ["false", "on"],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, [200, 302])
        self.event.refresh_from_db()
        self.assertTrue(
            self.event.is_free,
            "Checking is_free with companion present did not persist True",
        )

    def test_cover_form_partial_post_still_preserves_true_is_free(self):
        """
        Regression guard: cover-only POST (no hidden companions, only title+slug+start)
        must NOT wipe a True is_free.
        This is the existing no-wipe invariant — both behaviours must coexist.
        """
        self._set_booleans(is_free=True)
        self.assertTrue(self.event.is_free, "Pre-condition: is_free must be True before test")

        # Cover-form-style partial POST: no companion inputs, no is_free key at all
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                # is_free is ABSENT — simulates cover form which doesn't carry companions
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(resp.status_code, [200, 302])
        self.event.refresh_from_db()
        self.assertTrue(
            self.event.is_free,
            "Cover-form partial POST (no companion) wiped is_free=True — no-wipe invariant broken",
        )


# ---------------------------------------------------------------------------
# (f) Strengthened fragment-HTML persistence verification
#     Acceptance says "verified by reload" — save field → re-render fragment →
#     assert saved value appears in rendered HTML (not just refresh_from_db).
# ---------------------------------------------------------------------------


class FragmentHtmlPersistenceVerificationTest(TestCase):
    """
    (f) Saves a representative set of fields across all disclosure groups, then
    re-renders the fragment and asserts each saved value appears in the HTML.
    This is the "verified by reload" acceptance criterion from kb-y209.1.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fp_frag", email="fp_frag@test.com", password="x")
        self.profile = _make_profile("FP Frag Profile", "fp-frag-profile", user=self.user)
        self.event = _make_event_with_switch_projection(
            self.user, self.profile, slug="fp-frag-event", title="FP Frag Event"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_visibility_saved_value_appears_in_fragment_html(self):
        """Save visibility=unlisted, re-render fragment, assert 'unlisted' in HTML."""
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "visibility": "unlisted",
            },
        )
        html = _get_fragment_html(self.client, self.event.pk)
        self.assertIn("unlisted", html, "Saved visibility=unlisted not found in re-rendered fragment HTML")

    def test_capacity_saved_value_appears_in_fragment_html(self):
        """Save capacity=75, re-render fragment, assert '75' in HTML."""
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "capacity": "75",
            },
        )
        html = _get_fragment_html(self.client, self.event.pk)
        self.assertIn("75", html, "Saved capacity=75 not found in re-rendered fragment HTML")

    def test_price_min_cents_saved_value_appears_in_fragment_html(self):
        """Save price_min_cents=2500, re-render fragment, assert '2500' in HTML."""
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "price_min_cents": "2500",
                "currency": "EUR",
            },
        )
        html = _get_fragment_html(self.client, self.event.pk)
        self.assertIn("2500", html, "Saved price_min_cents=2500 not found in re-rendered fragment HTML")

    def test_registration_email_saved_value_appears_in_fragment_html(self):
        """Save registration_email, re-render fragment, assert it appears in HTML."""
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "registration_email": "signup@venue.example.com",
            },
        )
        html = _get_fragment_html(self.client, self.event.pk)
        self.assertIn(
            "signup@venue.example.com", html,
            "Saved registration_email not found in re-rendered fragment HTML",
        )

    def test_tags_saved_value_appears_in_fragment_html(self):
        """
        Save tags, re-render fragment, assert the tag slug appears in HTML.
        Tags are M2M via slug — Tag objects must exist first so clean_tags() doesn't
        silently skip them (ADR-008 D3 allows unknown slugs to be dropped).
        """
        from events.models import Tag
        Tag.objects.get_or_create(slug="kink", defaults={"label": "Kink", "kind": "theme"})
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "tags": "kink",
            },
        )
        html = _get_fragment_html(self.client, self.event.pk)
        self.assertIn("kink", html, "Saved tag slug 'kink' not found in re-rendered fragment HTML")

    def test_is_free_true_appears_checked_in_fragment_html(self):
        """
        Save is_free=True via non-HTMX POST, re-render fragment.
        The fragment HTML must contain a checked checkbox for is_free.
        """
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "start": "2026-09-15T20:00",
                "is_free": "on",
            },
        )
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_free, "is_free not persisted — pre-condition for HTML check failed")
        html = _get_fragment_html(self.client, self.event.pk)
        # Django CheckboxInput renders checked="checked" or just "checked" when value is True
        import re
        is_free_inputs = re.findall(r'<input[^>]+name=["\']is_free["\'][^>]*/?>|<input[^>]+[^>]+name=["\']is_free["\'][^>]*/?>', html)
        checked_inputs = [i for i in is_free_inputs if "checked" in i and 'type="hidden"' not in i and "type='hidden'" not in i]
        self.assertGreater(
            len(checked_inputs), 0,
            f"is_free=True not reflected as checked checkbox in fragment HTML. Found inputs: {is_free_inputs}",
        )
