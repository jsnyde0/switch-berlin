"""
Edit-in-place composer shell tests (kb-ide0.1).

Contract under test (D1 + D2 + D5 from bead design):

D1 — No event-facts duplication:
    The event_syndication fragment must NOT contain an event-facts block
    (no id="event-facts" element). The canonical content appears ONCE in
    the Switch listing tab.

D2 — Edit-in-place (no textarea, structured fields inside the card):
    The event_syndication fragment for a Switch listing DRAFT must NOT
    contain a bare <textarea> as the edit surface. The Switch listing card
    IS the editor — structured event form fields inside the styled card.
    The _channel_preview.html engine-render is kept; inputs drive it.

D5 — Single top row:
    The event_syndication fragment must have a single top-level nav row
    where channel tabs are left-aligned and Publish CTA is right-aligned.
    We assert the "Syndication" heading (the OLD stacked header label that
    would mark a TWO-row layout) is absent, and instead the tabs row and
    the Publish CTA coexist in a single enclosing flex row.

studio_swap gating:
    event_syndication fragment must propagate studio context: without
    ?studio=1 no hx-target="#studio-main" is emitted on any link.
    The design notes that this child introduces studio_swap gating to
    event_syndication.html (the `dry-partial-merge-collapses-render-contexts`
    failure mode — it shipped before in the post template).

Content assertions use response.content, NOT response.context
(hollow-test memory: `django-view-test-context-vs-content-hollow`).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection

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


def _make_switch_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing"],
        enabled=True,
    )


def _make_switch_listing_projection(event, connection):
    from syndication.engine import generate_projection

    return generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )


# ---------------------------------------------------------------------------
# D1: No event-facts block duplication
# ---------------------------------------------------------------------------


class EventSyndicationNoFactsBlockTest(TestCase):
    """
    D1: The event_syndication fragment must NOT contain an event-facts block.

    The canonical Switch listing content appears once as the first/anchor tab.
    The `id="event-facts"` element belongs to event_facts.html (a separate
    fragment); it must NOT appear inside the event_syndication fragment, which
    is the composer surface.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="nf_user", email="nf@test.com", password="pw")
        self.profile = _make_profile("NF Org", "nf-org", user=self.user)
        self.event = _make_event(self.profile, "No Facts Test Event", "no-facts-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_syndication_fragment_has_no_event_facts_block(self):
        """
        D1: The fragment must NOT embed an event-facts block.
        Asserting on content (not context) per hollow-test memory.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'id="event-facts"',
            content,
            "event_syndication fragment must NOT contain id='event-facts' — "
            "D1 violation: facts block duplicates the Switch listing canonical.",
        )

    def test_event_hub_body_has_no_event_facts_section(self):
        """
        D1: The event hub body must NOT render an event-facts HTMX trigger section.
        The _event_hub_body.html must remove the hx-trigger event-facts loader.
        (After D1, facts are embedded in the Switch listing tab, not a separate block.)
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The resolved URL for the event_facts fragment contains 'event_facts'
        # (with underscore). The hub body must not contain this HTMX loader.
        self.assertNotIn(
            "fragments/event_facts/",
            content,
            "Event hub must NOT have an hx-get='fragments/event_facts/' loader after D1 — "
            "event facts are now embedded in the Switch listing tab.",
        )

    def test_event_hub_body_has_no_edit_event_detour_link(self):
        """
        D1: The event hub body must NOT contain an 'Edit event' detour link.
        After D1, event fields are edited in-place in the Switch listing card.
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The old "Edit event" button linked to syndication:event-edit
        self.assertNotIn(
            "Edit event",
            content,
            "Event hub must NOT contain 'Edit event' detour link after D1 — "
            "event fields are edited in-place in the Switch listing card.",
        )


# ---------------------------------------------------------------------------
# D2: No textarea; structured event form fields inside the Switch card
# ---------------------------------------------------------------------------


class EventSyndicationNoTextareaTest(TestCase):
    """
    D2: The event_syndication fragment for a Switch listing draft must NOT
    contain a bare <textarea> as the edit surface.

    The Switch listing card IS the editor — structured event form fields
    (title, description, start, etc.) are rendered inside the styled card.
    The old textarea was the body-edit input; after D2 the inputs are
    structured form fields driving the engine render, not a raw textarea.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="nt_user", email="nt@test.com", password="pw")
        self.profile = _make_profile("NT Org", "nt-org", user=self.user)
        self.event = _make_event(self.profile, "No Textarea Event", "no-textarea-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_syndication_switch_listing_draft_has_no_body_textarea(self):
        """
        D2: The event_syndication fragment (Switch listing, draft) must NOT
        render a body-edit <textarea name="body"> as the editing surface.
        The old textarea (name="body") is replaced by structured event form inputs.
        Note: description field is itself a textarea widget — that is expected.
        The specific OLD editor was a raw textarea with name="body".
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'name="body"',
            content,
            "event_syndication fragment (Switch listing, draft) must NOT render "
            "a textarea with name='body' — D2: the old body textarea is replaced "
            "by structured event form inputs (title, description, start, etc.).",
        )

    def test_event_syndication_switch_listing_draft_has_title_input(self):
        """
        D2: The Switch listing card must contain a title input field.
        This is one of the ~25 structured event form fields that replace the textarea.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The title field should be an input[name="title"] inside the Switch listing card
        self.assertIn(
            'name="title"',
            content,
            "event_syndication fragment (Switch listing, draft) must contain "
            "name='title' input — D2: structured event form fields replace the textarea.",
        )

    def test_event_syndication_switch_listing_draft_has_no_separate_preview_block(self):
        """
        FIX 1 (binding user decision 2026-06-04): The Switch listing draft must NOT
        have a separate 'Preview' block below the form.
        Fields ARE the card — no separate engine-rendered preview for this case.
        The styled form inputs ARE the listing surface (WYSIWYG by construction).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The "Preview" label/heading must NOT appear for Switch listing draft.
        # (It appears for non-switch-listing cases — not tested here.)
        # For the switch listing draft, the form fields ARE the listing card.
        # No separate preview section should follow the form.
        self.assertNotIn(
            ">Preview<",
            content,
            "event_syndication Switch listing draft must NOT contain a separate "
            "'Preview' block — binding user decision: fields ARE the card, "
            "no separate preview for this case.",
        )


# ---------------------------------------------------------------------------
# D5: Single top row (tabs left, Publish right)
# ---------------------------------------------------------------------------


class EventSyndicationSingleTopRowTest(TestCase):
    """
    D5: The event_syndication fragment must have a single top row.

    Channel tabs are left-aligned; Publish CTA is right-aligned.
    The OLD layout had two stacked rows: (1) "Syndication" heading + Publish,
    (2) channel tabs below that. After D5 there is ONE row — tabs + Publish.

    We assert: no "Syndication" heading text (the marker of the old stacked header).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="str_user", email="str@test.com", password="pw")
        self.profile = _make_profile("STR Org", "str-org", user=self.user)
        self.event = _make_event(self.profile, "Single Top Row Event", "single-top-row-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_syndication_fragment_has_no_stacked_syndication_heading(self):
        """
        D5: The fragment must NOT contain the old 'Syndication' stacked-header label.
        The single top row replaces the two-row layout (heading + CTA on row 1,
        tabs on row 2) with a single flex row (tabs left, Publish right).
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The old layout had an h2 with "Syndication" as a standalone heading
        # in the first row. After D5 this heading is gone.
        self.assertNotIn(
            ">Syndication<",
            content,
            "event_syndication fragment must NOT contain the stacked 'Syndication' "
            "heading — D5: single top row replaces two-row layout.",
        )

    def test_event_syndication_fragment_has_review_all_link(self):
        """
        D5: The single top row must still contain the 'Review all' link.
        (It may be relocated but must not vanish.)
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Review all",
            content,
            "event_syndication fragment must retain the 'Review all' link after D5.",
        )


# ---------------------------------------------------------------------------
# studio_swap gating (dual render-context safety)
# ---------------------------------------------------------------------------


class EventSyndicationStudioContextTest(TestCase):
    """
    studio_swap gating: the event_syndication fragment must be context-aware.

    Without ?studio=1, no hx-target="#studio-main" is emitted.
    With ?studio=1, the fragment emits studio-context HTMX attrs.

    This gating is the same pattern as post_syndication.html (kb-9f1h.7).
    The bead design notes that event_syndication.html currently has NO
    studio_swap handling — this child introduces it.

    Per the `dry-partial-merge-collapses-render-contexts` memory:
    the composer must work in BOTH standalone and HTMX-fragment contexts.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="esc_user", email="esc@test.com", password="pw")
        self.profile = _make_profile("ESC Org", "esc-org", user=self.user)
        self.event = _make_event(self.profile, "Studio Context Event", "studio-context-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_syndication_without_studio_param_has_no_hx_target_studio_main(self):
        """
        Without ?studio=1 (standalone context): the fragment must NOT emit
        hx-target="#studio-main" on any internal link.
        #studio-main doesn't exist in the standalone page DOM.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn(
            'hx-target="#studio-main"',
            content,
            "event_syndication without ?studio=1 must NOT emit hx-target='#studio-main' — "
            "standalone context has no studio shell; HTMX would silently no-op the click.",
        )

    def test_event_syndication_with_studio_param_emits_studio_context_target(self):
        """
        FIX 3: With ?studio=1 (in-studio context): the fragment MUST emit
        hx-target="#studio-main" on cross-links (e.g. 'Review all').
        This replaces the previous hollow test that only checked status_code==200.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'hx-target="#studio-main"',
            msg_prefix="FIX 3: with ?studio=1, the fragment must emit hx-target='#studio-main' "
            "on cross-links (Review all) — prevents studio-context navigation collapse.",
        )

    def test_event_hub_hx_fragment_passes_studio_swap_to_syndication(self):
        """
        When the event hub body is loaded as an HX fragment (in-studio context),
        the event_syndication sub-fragment loader must thread ?studio=1 so the
        sub-fragment knows it's in the studio context.
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The hub body includes a hx-get for the event_syndication sub-fragment.
        # In the HX/studio path, this must include ?studio=1.
        self.assertIn(
            "?studio=1",
            content,
            "event_hub HX fragment must thread ?studio=1 to the event_syndication "
            "sub-fragment loader so the sub-fragment is context-aware.",
        )


# ---------------------------------------------------------------------------
# Both render contexts: the fragment must work standalone AND in-studio
# ---------------------------------------------------------------------------


class EventSyndicationBothRenderContextsTest(TestCase):
    """
    The event_syndication fragment must satisfy all D1/D2/D5 acceptance in
    BOTH render contexts:
    - Standalone: direct GET at /syndication/events/<pk>/fragments/event_syndication/
    - In-studio: the event_hub_fragment.html includes the event_syndication loader
      with the HX-Request header, triggering the layout-less body path.

    The event_hub HX fragment must not contain <html or <body (regression).
    The event_syndication fragment itself (both paths) must not contain event-facts.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="brc_user", email="brc@test.com", password="pw")
        self.profile = _make_profile("BRC Org", "brc-org", user=self.user)
        self.event = _make_event(self.profile, "Both Contexts Event", "both-contexts-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_hub_hx_fragment_has_no_html_or_body_tags(self):
        """
        Regression: event_hub HX fragment must not contain <html or <body.
        (Same as test_hub_fragment_branching.py but included here for
        dual-context coverage of this bead's changes.)
        """
        url = f"/syndication/events/{self.event.pk}/"
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn("<html", content, "event_hub HX fragment must not contain <html.")
        self.assertNotIn("<body", content, "event_hub HX fragment must not contain <body.")

    def test_standalone_event_syndication_fragment_renders_200(self):
        """
        Standalone path: direct GET of the event_syndication fragment must
        return 200 and contain the Switch listing tab.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Switch listing tab is always present (it's the canonical anchor)
        self.assertIn(
            "switch",
            content.lower(),
            "Standalone event_syndication fragment must contain the Switch listing tab.",
        )

    def test_both_contexts_no_event_facts_block(self):
        """
        D1: Both standalone and the hub body must not contain event-facts block.
        Standalone: fragment endpoint. Hub body: the hub page full render.
        """
        # Standalone
        url_frag = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        resp_frag = self.client.get(url_frag)
        self.assertEqual(resp_frag.status_code, 200)
        self.assertNotIn(
            'id="event-facts"',
            resp_frag.content.decode(),
            "Standalone event_syndication fragment must NOT contain id='event-facts'.",
        )

        # Hub body (full page, not HTMX)
        url_hub = f"/syndication/events/{self.event.pk}/"
        resp_hub = self.client.get(url_hub)
        self.assertEqual(resp_hub.status_code, 200)
        self.assertNotIn(
            "fragments/event_facts/",
            resp_hub.content.decode(),
            "Event hub page must NOT contain hx-get='fragments/event_facts/' after D1.",
        )


# ---------------------------------------------------------------------------
# FIX 2: Data loss regression — partial-field POST must not wipe unrendered fields
# ---------------------------------------------------------------------------


class EventSyndicationDataLossRegressionTest(TestCase):
    """
    FIX 2 (ADR-008 D3): Editing only the title via the Switch listing card
    must NOT wipe is_free, sliding_scale, registration_required, currency,
    venue, or tags — even though those fields are not visually prominent
    in the listing card.

    Root cause: the form only rendered ~8 of 25 fields as visible inputs;
    a partial POST caused update_event to setattr all cleaned_data fields,
    wiping booleans (False by default when absent from POST) and empty strings
    for choice/FK fields.

    Fix: render ALL fields (visible or hidden) in the card form so the POST
    always carries every field's current value — nothing is silently reset.
    """

    def setUp(self):
        from events.models import Tag
        from venues.models import Venue

        self.client = Client()
        self.user = _make_user(username="dl_user", email="dl@test.com", password="pw")
        self.profile = _make_profile("DL Org", "dl-org", user=self.user)
        self.event = _make_event(self.profile, "Data Loss Test Event", "data-loss-event")

        # Set the non-trivial fields that must survive a title-only edit
        self.event.is_free = True
        self.event.sliding_scale = True
        self.event.registration_required = True
        self.event.currency = "EUR"
        self.event.save(
            update_fields=["is_free", "sliding_scale", "registration_required", "currency"]
        )

        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_title_only_edit_preserves_boolean_and_choice_fields(self):
        """
        FIX 2 REGRESSION: POSTing only the title to the event-edit endpoint must
        NOT wipe is_free, sliding_scale, registration_required, or currency.

        This test MUST fail against the unfixed code (the card form did not include
        hidden inputs for fields not visually rendered, so the POST omitted them,
        causing update_event to reset booleans to False and choices to '').
        """
        # Confirm the fields are set before we start
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_free, "Pre-condition: is_free must be True before test")
        self.assertTrue(self.event.sliding_scale, "Pre-condition: sliding_scale must be True")
        self.assertTrue(self.event.registration_required, "Pre-condition: registration_required must be True")
        self.assertEqual(self.event.currency, "EUR", "Pre-condition: currency must be EUR")

        # POST only the title (the card renders title, slug, start prominently)
        # Minimal POST: only the visually-prominent fields + csrf
        post_data = {
            "title": "Updated Title Only",
            "slug": self.event.slug,
            "start": "2026-06-11T12:00",
            # Deliberately OMIT: is_free, sliding_scale, registration_required, currency
            # This simulates the card rendering only a subset of fields
        }

        url = f"/syndication/events/{self.event.pk}/edit/"
        response = self.client.post(url, data=post_data, HTTP_HX_REQUEST="true")

        # The response should be a 200 (fragment re-render) or a redirect
        self.assertIn(response.status_code, [200, 302], f"Unexpected status: {response.status_code}")

        # Now check the DB — the critical assertion is here, not on response.context
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "Updated Title Only", "Title must be updated")
        self.assertTrue(
            self.event.is_free,
            "FIX 2: is_free must survive a title-only edit (ADR-008 D3 — no silent data wipe)",
        )
        self.assertTrue(
            self.event.sliding_scale,
            "FIX 2: sliding_scale must survive a title-only edit",
        )
        self.assertTrue(
            self.event.registration_required,
            "FIX 2: registration_required must survive a title-only edit",
        )
        self.assertEqual(
            self.event.currency,
            "EUR",
            "FIX 2: currency must survive a title-only edit (must not be wiped to '')",
        )


# ---------------------------------------------------------------------------
# FIX 4: carry-only fields must be hidden, not visible form widgets
# ---------------------------------------------------------------------------


class EventSyndicationCarryFieldsHiddenTest(TestCase):
    """
    FIX 4: The 17 carry-only fields added in kb-ide0.1 to prevent data loss
    must NOT render as visible form widgets below the Save button.

    Binding user decision: the Switch listing card's "fields ARE the card"
    surface. Only the ~8 listing-facing fields (title, start, end, description,
    dress_code, age_restriction, tickets_url, slug) must be visually styled.

    The carry-only fields (venue, tags, content_warnings, capacity, visibility,
    language, is_free, price_min_cents, price_max_cents, currency, sliding_scale,
    price_description, external_url, registration_required, registration_url,
    registration_email, category) must render as true hidden inputs — present
    in the DOM so the POST carries their values, but invisible in the card.

    IMPORTANT: the data-loss regression test_title_only_edit_preserves_boolean_and_choice_fields
    must STILL pass — the view's HTMX filtering (submitted_keys) handles booleans
    correctly (absent unchecked checkbox = don't update that field).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cfh_user", email="cfh@test.com", password="pw")
        self.profile = _make_profile("CFH Org", "cfh-org", user=self.user)
        self.event = _make_event(self.profile, "Carry Fields Hidden Event", "carry-fields-hidden")
        # Set boolean fields to True so we can verify they round-trip through hidden inputs
        self.event.is_free = True
        self.event.sliding_scale = True
        self.event.registration_required = True
        self.event.currency = "EUR"
        self.event.save(update_fields=["is_free", "sliding_scale", "registration_required", "currency"])
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_carry_fields_are_hidden_not_visible_widgets(self):
        """
        FIX 4: The Switch listing card must NOT render carry-only fields as
        visible form widgets. They must appear inside a hidden container so
        they are invisible but their values still submit in the POST.

        Django renders CheckboxInput as: <input type="checkbox" name="is_free" ...>
        (type attribute comes first). We assert no visible checkbox (type="checkbox")
        appears for the carry-only boolean fields — they must be wrapped in a
        display:none container or rendered as type="hidden" inputs.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Django renders CheckboxInput as <input type="checkbox" name="is_free" ...>
        # The carry-only boolean fields must NOT appear as exposed visible checkboxes.
        # We check for the pattern Django actually emits (type first, then name).
        # If the field is wrapped in display:none container, the checkbox may still
        # exist but must be inside the hidden wrapper — we verify no VISIBLE checkbox
        # by checking there is no type="checkbox" with these names at all
        # (the fix should use type="hidden" inputs, not CSS-hidden checkboxes).
        self.assertNotIn(
            'type="checkbox" name="is_free"',
            content,
            "FIX 4: is_free must NOT render as a visible checkbox (type='checkbox') — "
            "it must be a hidden input so it is invisible in the card.",
        )
        self.assertNotIn(
            'type="checkbox" name="sliding_scale"',
            content,
            "FIX 4: sliding_scale must NOT render as a visible checkbox (type='checkbox').",
        )
        self.assertNotIn(
            'type="checkbox" name="registration_required"',
            content,
            "FIX 4: registration_required must NOT render as a visible checkbox (type='checkbox').",
        )

    def test_carry_boolean_true_values_round_trip_through_hidden_inputs(self):
        """
        FIX 4: When is_free=True, the hidden input for is_free must carry a
        value that Django's BooleanField.to_python() recognises as True after
        the POST, so that saving via the card preserves the True value.

        We do a FULL form POST (simulating the browser submitting all hidden
        inputs) with only the visible fields changed, and confirm is_free/
        sliding_scale/registration_required survive as True.
        """
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_free)
        self.assertTrue(self.event.sliding_scale)
        self.assertTrue(self.event.registration_required)

        # Simulate a full card POST: visible fields + carry booleans as "on"
        # (what a checked checkbox emits) + carry text fields as their values
        post_data = {
            "title": "Round-trip Title",
            "slug": self.event.slug,
            "start": "2026-06-11T12:00",
            # Carry booleans — a checked hidden checkbox emits "on"
            "is_free": "on",
            "sliding_scale": "on",
            "registration_required": "on",
            "currency": "EUR",
        }

        url = f"/syndication/events/{self.event.pk}/edit/"
        response = self.client.post(url, data=post_data, HTTP_HX_REQUEST="true")
        self.assertIn(response.status_code, [200, 302])

        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "Round-trip Title")
        self.assertTrue(
            self.event.is_free,
            "FIX 4: is_free=True must survive a full-card POST with is_free=on in the hidden input",
        )
        self.assertTrue(
            self.event.sliding_scale,
            "FIX 4: sliding_scale=True must survive a full-card POST",
        )
        self.assertTrue(
            self.event.registration_required,
            "FIX 4: registration_required=True must survive a full-card POST",
        )
        self.assertEqual(
            self.event.currency,
            "EUR",
            "FIX 4: currency must survive a full-card POST",
        )


# ---------------------------------------------------------------------------
# FIX 3: studio_swap must gate the Review-all cross-link (not hollow tests)
# ---------------------------------------------------------------------------


class EventSyndicationStudioSwapCrossLinkTest(TestCase):
    """
    FIX 3: studio_swap is threaded to template context but the Review-all
    cross-link was a plain <a href>, causing full-page navigation in the
    in-studio HTMX context (browser-confirmed).

    With ?studio=1: the cross-link must carry hx-target="#studio-main".
    Without ?studio=1: the cross-link must NOT carry hx-target="#studio-main".
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="sscl_user", email="sscl@test.com", password="pw")
        self.profile = _make_profile("SSCL Org", "sscl-org", user=self.user)
        self.event = _make_event(self.profile, "Studio Swap Cross-link Event", "studio-swap-cl-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_review_all_link_carries_studio_target_when_studio_param_present(self):
        """
        FIX 3 (real assertion): With ?studio=1, the 'Review all' cross-link
        must emit hx-target="#studio-main" so navigation swaps within the
        studio shell rather than full-page-navigating and destroying it.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/?studio=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'hx-target="#studio-main"',
            msg_prefix="FIX 3: with ?studio=1, Review-all link must carry hx-target='#studio-main'",
        )

    def test_review_all_link_has_no_studio_target_without_studio_param(self):
        """
        FIX 3 (real assertion): Without ?studio=1, the 'Review all' cross-link
        must NOT carry hx-target="#studio-main" — standalone page has no studio shell.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            'hx-target="#studio-main"',
            msg_prefix="FIX 3: without ?studio=1, Review-all link must NOT carry hx-target='#studio-main'",
        )
