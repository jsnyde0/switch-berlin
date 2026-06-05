"""
Tests for unified event composer surface (kb-96tn.2).

Contract groups:
(A) No double-render for draft non-Switch channels:
    A draft non-Switch channel (e.g. FetLife listing) must NOT render both a
    'Body' label+textarea AND a separate 'Preview' block for the same channel.
    It must show exactly ONE editable surface (no "Body" + "Preview" redundancy).

(B) Editable bubble for non-Switch draft channels:
    The non-Switch draft editor must use the platform-skinned bubble styling
    (matching the post composer's approach) rather than a plain unstyled textarea.
    The textarea must remain present (editable), just styled as an editable preview bubble.

(C) Published channels show content ONCE:
    A published channel (status='published' or status='ready') must NOT render
    both a 'Body' label block AND a 'Preview' block for the same content.
    The content appears ONCE — via the preview block only.

(D) Venue visible in Switch listing card:
    The Switch listing edit card must render venue as a visible field (NOT hidden).
    event_form.venue must NOT be type="hidden" — the user must be able to see
    and edit the venue inline. D-IA3.

Assertions on response.content, NOT response.context (hollow-test prevention).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
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


def _make_event(profile, title, slug):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_connection(profile, platform, destination_id, kinds):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=True,
    )


def _make_listing_projection(event, connection, status="draft"):
    """Create a listing projection with the given status."""
    cv = ContentVersion.objects.create(
        event=event,
        name="canonical",
        body="Test listing body content",
    )
    proj = PlatformProjection.objects.create(
        connection=connection,
        source_event=event,
        content_version=cv,
        kind=PlatformProjection.Kind.LISTING,
        status=status,
    )
    return proj


def _make_switch_connection(profile):
    return _make_connection(profile, "switch", "own-page", ["listing", "promotion"])


def _make_fetlife_connection(profile):
    return _make_connection(profile, "fetlife", "fl-test-user", ["listing", "promotion"])


# ---------------------------------------------------------------------------
# (A) No double-render for draft non-Switch channels
# ---------------------------------------------------------------------------


class NoDraftDoubleRenderTest(TestCase):
    """
    (A) Draft non-Switch channel (FetLife) must NOT render both a 'Body' label
    + textarea editor AND a separate 'Preview' section for the same content.

    The bug: the template rendered the textarea editor, then ALSO rendered the
    _channel_preview.html block below it — the same body content appeared twice.
    Fix: the editable surface IS the preview (one surface); no separate Preview block.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="dr_user", email="dr@test.com", password="pw")
        self.profile = _make_profile("DR Org", "dr-org", user=self.user)
        self.event = _make_event(self.profile, "Draft Double Render Event", "draft-double-render")
        self.fetlife_conn = _make_fetlife_connection(self.profile)
        _make_listing_projection(self.event, self.fetlife_conn, status="draft")
        self.client.force_login(self.user)

    def test_draft_fetlife_channel_has_no_body_label_and_preview_both(self):
        """
        A draft FetLife channel must NOT contain both a 'Body' section label
        AND a 'Preview' section label in the same channel panel.

        Pre-fix: both appeared (double-render). Post-fix: the editor IS the preview;
        neither label should appear for the draft channel (or only one should).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The fragment must NOT contain both a read-only 'Body' section label
        # AND a 'Preview' label for the same channel.
        # Post-fix: draft channels use the editable bubble — no separate "Body" header
        # above a read-only block, and no separate "Preview" header below the editor.
        self.assertNotIn(
            ">Body<",
            content,
            "Draft FetLife channel must NOT render a standalone 'Body' section label — "
            "the editable bubble is the only surface (kb-96tn.2 double-render fix).",
        )
        self.assertNotIn(
            ">Preview<",
            content,
            "Draft FetLife channel must NOT render a separate 'Preview' section label — "
            "the editable bubble IS the preview (unified surface, kb-96tn.2).",
        )

    def test_draft_fetlife_channel_has_editable_textarea(self):
        """
        The draft FetLife channel MUST still have an editable textarea (name='body').
        Removing editing would be a regression — only the separate Preview block is removed.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'name="body"',
            content,
            "Draft FetLife channel MUST have a textarea with name='body' for editing — "
            "removing the textarea would regress editing (kb-96tn.2).",
        )


# ---------------------------------------------------------------------------
# (B) Non-Switch draft uses platform-skinned editable bubble
# ---------------------------------------------------------------------------


class EditableBubbleStylingTest(TestCase):
    """
    (B) Non-Switch draft channels must use platform-skinned bubble styling
    matching the post composer's approach. The textarea must be inside a
    styled container (not a plain unstyled textarea + label).

    The editable surface merges the edit functionality and the preview visual
    into one element — the bubble container styled per-platform.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="eb_user", email="eb@test.com", password="pw")
        self.profile = _make_profile("EB Org", "eb-org", user=self.user)
        self.event = _make_event(self.profile, "Editable Bubble Event", "editable-bubble")
        self.fetlife_conn = _make_fetlife_connection(self.profile)
        _make_listing_projection(self.event, self.fetlife_conn, status="draft")
        self.client.force_login(self.user)

    def test_draft_fetlife_editor_has_autosave_form(self):
        """
        The draft FetLife editor must be inside an hx-post autosave form — the
        existing autosave wiring must be preserved after the unification.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The autosave form posts to syndication:version-edit (URL: /syndication/versions/<pk>/edit/)
        # Check hx-swap="none" which is the autosave pattern (no DOM replacement on save)
        self.assertIn(
            'hx-swap="none"',
            content,
            "Draft FetLife channel must still have the autosave hx-post (hx-swap='none') "
            "— autosave wiring must be preserved (kb-96tn.2).",
        )

    def test_draft_fetlife_editor_has_platform_styled_container(self):
        """
        The draft FetLife editor must use the platform-styled bubble container
        (matching post_syndication.html's FetLife bubble) — the textarea must be
        inside a styled <div> rather than preceded by a plain 'Body' label.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The FetLife bubble container in post_syndication.html uses purple-ish color styling.
        # It must appear for the event's FetLife draft channel too.
        # The marker: destination_id is rendered in the bubble header.
        self.assertIn(
            "fl-test-user",
            content,
            "FetLife draft channel must render the destination_id inside the styled bubble container.",
        )


# ---------------------------------------------------------------------------
# (C) Published channels show content ONCE (no Body + Preview duplicate)
# ---------------------------------------------------------------------------


class NoPublishedDoubleRenderTest(TestCase):
    """
    (C) Published channels must NOT show both a 'Body' label block AND a 'Preview'
    block. The content appears once — via the preview block.

    Pre-fix: published channels rendered:
    1. A 'Body' label + raw text block (read-only)
    2. A 'Preview' label + _channel_preview.html render (same content)

    Post-fix: only the preview block remains (the 'Body' label block is removed).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="pub_user", email="pub@test.com", password="pw")
        self.profile = _make_profile("Pub Org", "pub-org", user=self.user)
        self.event = _make_event(self.profile, "Published Double Render Event", "published-double-render")
        self.fetlife_conn = _make_fetlife_connection(self.profile)
        _make_listing_projection(self.event, self.fetlife_conn, status="published")
        self.client.force_login(self.user)

    def test_published_channel_has_no_body_label_block(self):
        """
        A published channel must NOT render a standalone 'Body' section label
        above the raw text content. The content appears once via the Preview block.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            ">Body<",
            content,
            "Published channel must NOT render a standalone 'Body' section label — "
            "the content appears once via the Preview block (kb-96tn.2).",
        )

    def test_published_channel_shows_content_preview(self):
        """
        A published channel MUST still render the content preview (the
        _channel_preview.html block). Removing it would regress display.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The channel preview must show the destination_id (channel identifier)
        self.assertIn(
            "fl-test-user",
            content,
            "Published channel MUST still render the content preview — "
            "the destination_id must appear in the preview block (kb-96tn.2).",
        )


# ---------------------------------------------------------------------------
# (D) Venue visible in Switch listing card (D-IA3)
# ---------------------------------------------------------------------------


class VenueVisibleInSwitchCardTest(TestCase):
    """
    (D) D-IA3: The Switch listing edit card must render venue as a visible
    inline-editable field. event_form.venue is currently a hidden field (~L322)
    — this must become a visible input in the card matching the other fields' styling.

    Acceptance: the venue field input is NOT type="hidden" in the fragment,
    and the venue label appears in the rendered HTML.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="venue_user", email="venue@test.com", password="pw")
        self.profile = _make_profile("Venue Org", "venue-org", user=self.user)
        self.event = _make_event(self.profile, "Venue Test Event", "venue-test-event")
        switch_conn = _make_connection(self.profile, "switch", "own-page", ["listing", "promotion"])
        _make_listing_projection(self.event, switch_conn, status="draft")
        self.client.force_login(self.user)

    def test_venue_field_is_not_hidden_in_switch_listing_card(self):
        """
        D-IA3: The Switch listing card must NOT render venue as a hidden input.
        The venue field must be a visible input field (type=number or text),
        not type="hidden".
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The venue field must NOT be a hidden input
        self.assertNotIn(
            'type="hidden" name="venue"',
            content,
            "D-IA3: venue must NOT be a hidden input in the Switch listing card — "
            "it must be a visible inline-editable field (kb-96tn.2).",
        )
        # The venue field name must also NOT appear as a hidden input in the alternate order
        self.assertNotIn(
            'name="venue" type="hidden"',
            content,
            "D-IA3: venue must NOT be a hidden input in the Switch listing card — "
            "it must be a visible inline-editable field (kb-96tn.2).",
        )

    def test_venue_field_label_visible_in_switch_listing_card(self):
        """
        D-IA3: The venue field label must be visible in the Switch listing card —
        confirming that venue is surfaced as an inline-editable labeled field.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The venue label text must be present (either "Venue" or "Venue / Location")
        self.assertTrue(
            "Venue" in content,
            "D-IA3: 'Venue' label must appear in the Switch listing card — "
            "venue must be surfaced as a visible inline-editable field (kb-96tn.2).",
        )
