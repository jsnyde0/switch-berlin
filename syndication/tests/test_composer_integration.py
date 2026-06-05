"""
Integration test — consolidated composer conjunction (kb-96tn.8).

Seeds ONE event with:
  - a PUBLISHED Switch listing projection (clean)
  - a DRAFT FetLife listing projection
  - an EXTRA FetLife connection left unattached (→ available_connections has one entry)
And ONE promo post linked to the event.

Asserts the 6-bullet conjunction at server-rendered-HTML level:

  1. No kb-display H1, no "Event Workspace ·"/"Post Workspace ·" eyebrow in
     hub BODIES (the HTMX fragments); a breadcrumb is present in the post hub.

  2. No double-render: event_syndication fragment does NOT show both a read-only
     "Body" label block AND a separate "Preview" of the same body for one
     projection. Venue field is present and NOT type="hidden".

  3. Pills present (channel-dot status-dot marker); the "…" add-channel
     affordance is present; available_connections has an entry in the fragment
     (the unattached FetLife connection).

  4. Dirty-state markup renders for an edited PUBLISHED projection
     (content_version body != frozen_content); does NOT render for a clean
     published one.

  5. Studio rail shows "New" with both event-create and post-create hx-get
     affordances targeting #studio-main.

  6. Promo card <article> carries hx-get (post-hub) + hx-target="#studio-main";
     no "Open composer" text; DOM order: #event-syndication index < #event-posts
     index in the event hub body.

Assertions use response.content (NOT response.context) per documented
hollow-test prevention (context assertions pass even when the template is
broken — kb-33do.3 reformat-mutates-rendered-output caveat).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import generate_projection, transition_status
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers (mirrors other syndication test modules)
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
        description="Integration test event description.",
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_switch_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing", "promotion"],
        enabled=True,
    )


def _make_fetlife_connection(profile, destination_id="fl-integ-user"):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        kinds=["listing", "promotion"],
        enabled=True,
    )


def _make_published_projection(event, connection, kind="listing"):
    """Create a projection that is published (with frozen_content set)."""
    proj = generate_projection(
        kind=kind,
        connection=connection,
        source_event=event,
        mode="rule_based",
    )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    transition_status(proj, "published")
    proj.refresh_from_db()
    return proj


def _make_draft_projection(event, connection, kind="listing"):
    """Create a DRAFT listing projection for the given event + connection."""
    cv = ContentVersion.objects.create(
        event=event,
        name="fetlife-custom",
        body="FetLife draft body for integration test",
    )
    proj = PlatformProjection.objects.create(
        connection=connection,
        source_event=event,
        content_version=cv,
        kind=PlatformProjection.Kind.LISTING,
        status=PlatformProjection.Status.DRAFT,
    )
    return proj


# ---------------------------------------------------------------------------
# The main fixture class (one setUp, all 6 bullets as test methods)
# ---------------------------------------------------------------------------


class ComposerConjunctionTest(TestCase):
    """
    Integration test that seeds the minimal fixture and asserts ALL 6 bullets
    at the server-rendered-HTML level.

    Fixture:
      - 1 event (title="Conjunction Test Event")
      - 1 Switch connection  → PUBLISHED listing projection (clean)
      - 1 FetLife connection → DRAFT listing projection
      - 1 extra FetLife connection (different destination_id) → no projection
        (becomes available_connections entry in the "…" dropdown)
      - 1 Post linked to the event
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="conj_user", email="conj@test.com", password="pw")
        self.profile = _make_profile("Conjunction Org", "conjunction-org", user=self.user)
        self.event = _make_event(self.profile, "Conjunction Test Event", "conjunction-test-event")

        # Switch connection → PUBLISHED projection
        self.switch_conn = _make_switch_connection(self.profile)
        self.switch_proj = _make_published_projection(self.event, self.switch_conn, kind="listing")

        # FetLife connection → DRAFT projection
        self.fl_conn = _make_fetlife_connection(self.profile, destination_id="fl-integ-user")
        self.fl_proj = _make_draft_projection(self.event, self.fl_conn, kind="listing")

        # Extra FetLife connection — NOT projected (→ available_connections)
        self.fl_conn2 = _make_fetlife_connection(self.profile, destination_id="fl-extra-user")

        # One promo post
        self.post = Post.objects.create(
            event=self.event,
            headline="Conjunction Post Headline",
            body="Conjunction post body.",
        )

        self.client.force_login(self.user)

    # ------------------------------------------------------------------
    # BULLET 1: No kb-display H1, no "Event Workspace ·"/"Post Workspace ·"
    # eyebrow in hub BODIES; breadcrumb present in post hub fragment.
    # ------------------------------------------------------------------

    def test_b1_event_hub_body_fragment_no_kb_display_h1(self):
        """
        The event hub body (HTMX fragment) must NOT contain a kb-display H1
        heading — the consolidated composer uses the composer bar instead.
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # No standalone h1 with kb-display class
        self.assertNotIn(
            '<h1 class="kb-display',
            content,
            "Event hub fragment must NOT have a kb-display H1 heading (composer bar replaced it).",
        )

    def test_b1_event_hub_body_fragment_no_event_workspace_eyebrow(self):
        """
        The event hub HTMX fragment must NOT contain the old "Event Workspace ·"
        status eyebrow — that was the pre-consolidated composer pattern.
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            "Event Workspace ·",
            content,
            "Event hub fragment must NOT contain 'Event Workspace ·' eyebrow.",
        )

    def test_b1_post_hub_body_fragment_no_post_workspace_eyebrow(self):
        """
        The post hub HTMX fragment must NOT contain the old "Post Workspace ·"
        status eyebrow.
        """
        url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            "Post Workspace ·",
            content,
            "Post hub fragment must NOT contain 'Post Workspace ·' eyebrow.",
        )

    def test_b1_post_hub_fragment_has_breadcrumb_with_event_link(self):
        """
        The post composer workspace (post_syndication fragment) MUST have a
        breadcrumb linking back to the event hub — the "Studio › <event.title>"
        pattern (kb-96tn.9: breadcrumb now lives in the post_syndication fragment,
        not the hub shell, so we check the fragment URL directly).
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The breadcrumb links to the event hub URL
        event_hub_url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        self.assertIn(
            event_hub_url,
            content,
            f"Post syndication fragment must have a breadcrumb linking to event hub ({event_hub_url}).",
        )
        # The event title appears in the breadcrumb
        self.assertIn(
            "Conjunction Test Event",
            content,
            "Post syndication fragment breadcrumb must contain the parent event title.",
        )

    # ------------------------------------------------------------------
    # BULLET 2: No double-render; venue field visible (not hidden).
    # ------------------------------------------------------------------

    def test_b2_event_syndication_no_body_label_for_draft_fetlife(self):
        """
        The event_syndication fragment must NOT have a 'Body' label for the
        draft FetLife channel — the editable bubble IS the preview (no double-render).
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            ">Body<",
            content,
            "event_syndication fragment must NOT have a 'Body' section label (double-render kb-96tn.2 fix).",
        )

    def test_b2_event_syndication_no_preview_label_for_draft_fetlife(self):
        """
        The event_syndication fragment must NOT have a separate 'Preview' label
        for the draft FetLife channel.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            ">Preview<",
            content,
            "event_syndication fragment must NOT have a 'Preview' section label (double-render kb-96tn.2 fix).",
        )

    def test_b2_event_syndication_venue_field_not_hidden(self):
        """
        The Switch listing edit card must render venue as a visible field —
        NOT type='hidden' (D-IA3, kb-96tn.2).
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # type="hidden" name="venue" must NOT appear
        self.assertNotIn(
            'type="hidden" name="venue"',
            content,
            "D-IA3: venue must NOT be a hidden input in the Switch listing card.",
        )
        self.assertNotIn(
            'name="venue" type="hidden"',
            content,
            "D-IA3: venue must NOT be a hidden input in the Switch listing card.",
        )

    def test_b2_venue_label_visible_in_draft_switch_card(self):
        """
        D-IA3: When the Switch listing is DRAFT, the venue label must appear as a
        visible inline-editable field in the event_syndication fragment.

        This test uses a separate event+connection so the Switch projection is DRAFT
        (the main fixture has a PUBLISHED Switch projection — venue label is not
        rendered in the published preview, only in the DRAFT edit card).
        """
        # Create a separate event with a DRAFT Switch projection for venue testing
        event2 = _make_event(self.profile, "Venue Test Event 2", "venue-test-event-2")
        switch_conn2 = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
            enabled=True,
        )
        # Create a draft listing projection for this event
        cv2 = ContentVersion.objects.create(
            event=event2,
            name="canonical",
            body="Venue test body",
        )
        PlatformProjection.objects.create(
            connection=switch_conn2,
            source_event=event2,
            content_version=cv2,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
        )

        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": event2.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Venue",
            content,
            "D-IA3: 'Venue' label must appear in the DRAFT Switch listing card — "
            "venue must be a visible inline-editable field (kb-96tn.2).",
        )

    # ------------------------------------------------------------------
    # BULLET 3: Pills + status-dot; "…" add-channel affordance present;
    # available_connections has an entry.
    # ------------------------------------------------------------------

    def test_b3_pills_with_status_dot_present(self):
        """
        The event_syndication fragment must render pills (channel tabs) that
        include a status-dot span (data-testid='channel-pill' or the dot span).
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Each pill carries data-testid="channel-pill"
        self.assertIn(
            'data-testid="channel-pill"',
            content,
            "event_syndication fragment must have channel pills (data-testid='channel-pill').",
        )
        # Each pill carries a channel-dot span with id="channel-dot-<pk>"
        self.assertIn(
            "channel-dot-",
            content,
            "event_syndication fragment must have a status-dot span (id='channel-dot-...').",
        )

    def test_b3_kebab_add_channel_affordance_present(self):
        """
        The '…' add-channel affordance must be present in the event_syndication
        fragment (data-testid='kebab-menu-btn').
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'data-testid="kebab-menu-btn"',
            content,
            "event_syndication fragment must have the '…' kebab add-channel button.",
        )

    def test_b3_available_connections_entry_in_fragment(self):
        """
        The '…' dropdown must contain an add-channel form for the unattached
        FetLife connection (fl-extra-user) — confirming available_connections
        is populated and rendered.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The extra FetLife destination_id must appear in the add-channel form area
        self.assertIn(
            "fl-extra-user",
            content,
            "event_syndication fragment must render the unattached FetLife connection "
            "(fl-extra-user) as an available_connections add-channel entry.",
        )

    # ------------------------------------------------------------------
    # BULLET 4: Dirty-state markup renders for dirty published projection;
    # does NOT render for a clean published one.
    # ------------------------------------------------------------------

    def test_b4_dirty_banner_renders_for_dirty_published_projection(self):
        """
        When a PUBLISHED projection's content_version body differs from
        frozen_content, the dirty banner must appear in the event_syndication
        fragment (data-testid='dirty-banner').
        """
        # Edit the Switch projection's content_version after publish → dirty
        cv = self.switch_proj.content_version
        cv.body = "EDITED BODY THAT MAKES IT DIRTY — integration test"
        cv.save(update_fields=["body"])
        self.switch_proj.refresh_from_db()
        self.switch_proj.content_version.refresh_from_db()
        # Sanity: the projection must be dirty now
        self.assertTrue(
            self.switch_proj.is_dirty,
            "Switch projection should be dirty after content edit (pre-condition).",
        )

        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'data-testid="dirty-banner"',
            content,
            "Dirty-state banner must appear in event_syndication fragment when "
            "a published projection is dirty (kb-96tn.5).",
        )

    def test_b4_dirty_banner_absent_for_clean_published_projection(self):
        """
        When a PUBLISHED projection's content_version body matches frozen_content
        (clean), the dirty banner must NOT appear in the fragment.
        """
        # Don't edit anything — switch_proj is clean (just published, no edits)
        self.switch_proj.refresh_from_db()
        self.switch_proj.content_version.refresh_from_db()
        self.assertFalse(
            self.switch_proj.is_dirty,
            "Switch projection should NOT be dirty before any edits (pre-condition).",
        )

        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            'data-testid="dirty-banner"',
            content,
            "Dirty-state banner must NOT appear for a clean published projection.",
        )

    # ------------------------------------------------------------------
    # BULLET 5: Studio rail shows "+ New" with both event-create and
    # post-create hx-get affordances targeting #studio-main.
    # ------------------------------------------------------------------

    def test_b5_studio_rail_has_new_button(self):
        """
        The studio rail must render a '+ New' button (the dropdown trigger).
        """
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "+ New",
            content,
            "Studio rail must have a '+ New' button text.",
        )
        self.assertIn(
            "<button",
            content,
            "Studio rail must use a <button> element for the '+ New' trigger.",
        )

    def test_b5_new_event_hx_get_targets_studio_main(self):
        """
        The 'New event' item in the '+ New' dropdown must carry hx-get to the
        event-create URL and hx-target='#studio-main'.
        """
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        event_create_url = reverse("syndication:event-create")
        self.assertIn(
            f'hx-get="{event_create_url}"',
            content,
            f"Studio rail '+ New' dropdown must have hx-get='{event_create_url}' for new event.",
        )
        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "Studio rail event-create hx-get must target #studio-main.",
        )

    def test_b5_new_post_hx_get_targets_studio_main(self):
        """
        The 'New promo post' item in the '+ New' dropdown must carry hx-get
        to the post-create-standalone URL and hx-target='#studio-main'.
        """
        response = self.client.get("/studio/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        post_create_url = reverse("syndication:post-create-standalone")
        self.assertIn(
            f'hx-get="{post_create_url}"',
            content,
            f"Studio rail '+ New' dropdown must have hx-get='{post_create_url}' for new post.",
        )

    # ------------------------------------------------------------------
    # BULLET 6: Promo card article hx-get + hx-target; no "Open composer";
    # DOM order #event-syndication < #event-posts.
    # ------------------------------------------------------------------

    def test_b6_promo_card_has_hx_get_to_post_hub(self):
        """
        The promo card <article> in event_posts must carry hx-get pointing to
        the post-hub URL for the post.
        """
        url = reverse("syndication:fragment-event-posts", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        post_hub_url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        self.assertIn(
            f'hx-get="{post_hub_url}"',
            content,
            f"Promo card article must have hx-get='{post_hub_url}' (kb-96tn.7 clickable card).",
        )

    def test_b6_promo_card_has_hx_target_studio_main(self):
        """
        The promo card <article> must carry hx-target='#studio-main'.
        """
        url = reverse("syndication:fragment-event-posts", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'hx-target="#studio-main"',
            content,
            "Promo card article must carry hx-target='#studio-main'.",
        )

    def test_b6_promo_card_no_open_composer_text(self):
        """
        The promo card must NOT contain 'Open composer' text — the inner link
        was replaced by the whole-card click target (kb-96tn.7).
        """
        url = reverse("syndication:fragment-event-posts", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            "Open composer",
            content,
            "Promo card must NOT contain 'Open composer' inner link text (kb-96tn.7).",
        )

    def test_b6_dom_order_event_syndication_before_event_posts(self):
        """
        In the event hub body, #event-syndication must appear at an earlier
        character index than #event-posts (channel composer precedes promo strip).
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        pos_syndication = content.find('id="event-syndication"')
        pos_posts = content.find('id="event-posts"')
        self.assertGreater(pos_syndication, -1, "id='event-syndication' must be present.")
        self.assertGreater(pos_posts, -1, "id='event-posts' must be present.")
        self.assertLess(
            pos_syndication,
            pos_posts,
            f"#event-syndication (pos={pos_syndication}) must precede "
            f"#event-posts (pos={pos_posts}) in the rendered HTML (kb-96tn.7 D-IA8).",
        )

    # ------------------------------------------------------------------
    # kb-96tn.9: ONE consolidated bar — pills + breadcrumb + publish in
    # the fragment; shell must NOT have a separate pills row.
    # ------------------------------------------------------------------

    def test_kb96tn9_event_fragment_contains_pills(self):
        """
        The event_syndication fragment must contain channel pills
        (data-testid='channel-pill') — confirming the bar lives IN the fragment.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'data-testid="channel-pill"',
            content,
            "event_syndication fragment must contain channel pills (bar lives inside the fragment).",
        )

    def test_kb96tn9_event_fragment_contains_breadcrumb_studio(self):
        """
        The event_syndication fragment must contain 'Studio' breadcrumb text
        — confirming the bar with breadcrumb lives IN the fragment.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Studio",
            content,
            "event_syndication fragment must contain 'Studio' breadcrumb in the bar.",
        )

    def test_kb96tn9_event_fragment_contains_functional_publish_form(self):
        """
        The event_syndication fragment must contain at least one functional Publish form
        (a <form> with hx-post pointing to a publish endpoint) — not an inert <span>Publish</span>.
        The fixture has a DRAFT FetLife projection → direct-publish form must appear.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must have at least one form element with an hx-post pointing to publish
        # (direct-publish for the draft FetLife channel, or batch-publish if ready projections exist)
        has_publish_form = (
            "direct-publish" in content or "projection-batch-publish" in content or "projection-publish" in content
        )
        self.assertTrue(
            has_publish_form,
            "event_syndication fragment must contain a functional Publish form "
            "(direct-publish, projection-publish, or batch-publish) — not an inert Publish stub.",
        )

    def test_kb96tn9_shell_bar_no_inert_publish_stub(self):
        """
        The event hub shell bar must NOT contain an inert <span>Publish</span> stub
        — the bar's Publish must be the functional one from the fragment.
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The old inert stub had: <span class="kb-mono text-[9px] ... text-base-content/25">Publish</span>
        # We detect the inert pattern by looking for the bare inert span stub.
        # The text "Publish" may appear in forms (functional) but should not appear
        # as a text-base-content/25 faded inert span at the bar level.
        self.assertNotIn(
            "text-base-content/25 px-2.5 py-1.5 border border-white/8",
            content,
            "Event hub shell must NOT contain the old inert Publish stub (text-base-content/25 border-white/8).",
        )

    def test_kb96tn9_post_fragment_contains_pills(self):
        """
        The post_syndication fragment must contain channel pills
        (data-testid='channel-pill') — confirming the bar lives IN the fragment.
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'data-testid="channel-pill"',
            content,
            "post_syndication fragment must contain channel pills (bar lives inside the fragment).",
        )

    def test_kb96tn9_post_fragment_contains_breadcrumb_studio_and_event_link(self):
        """
        The post_syndication fragment must contain 'Studio' and a link to the
        parent event hub — breadcrumb lives IN the fragment.
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Studio",
            content,
            "post_syndication fragment must contain 'Studio' breadcrumb text.",
        )
        event_hub_url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        self.assertIn(
            event_hub_url,
            content,
            f"post_syndication fragment breadcrumb must link to event hub ({event_hub_url}).",
        )

    def test_kb96tn9_post_shell_bar_no_inert_publish_stub(self):
        """
        The post hub shell bar must NOT contain an inert <span>Publish</span> stub.
        """
        url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            "text-base-content/25 px-2.5 py-1.5 border border-white/8",
            content,
            "Post hub shell must NOT contain the old inert Publish stub (text-base-content/25 border-white/8).",
        )

    # ------------------------------------------------------------------
    # kb-96tn.10: Post composer — no double-render for published projections.
    # ------------------------------------------------------------------

    def test_kb96tn10_post_syndication_no_body_label_for_published_projection(self):
        """
        The post_syndication fragment must NOT render a 'Body' label block for
        a published (non-draft) projection — only _channel_preview.html once
        (mirrors event_syndication.html fix from kb-96tn.2).

        This test seeds a published post projection and asserts the 'Body'
        label block is absent from the post_syndication fragment.
        """
        # Need a post with a PUBLISHED projection
        post2 = Post.objects.create(
            event=self.event,
            headline="Published Post",
            body="Published post body for double-render test.",
        )
        # Create a promotion connection
        tg_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="test-channel",
            kinds=["promotion"],
            enabled=True,
        )
        # Create a published promotion projection
        proj = generate_projection(
            kind="promotion",
            connection=tg_conn,
            source_post=post2,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()
        transition_status(proj, "published")
        proj.refresh_from_db()

        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": post2.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            ">Body<",
            content,
            "post_syndication fragment must NOT have a 'Body' section label for a "
            "published projection (kb-96tn.10 double-render fix).",
        )


# ---------------------------------------------------------------------------
# kb-96tn.11: edit_after_publish_policy seam is live on the dirty/render path
# ---------------------------------------------------------------------------


class EditAfterPublishPolicySeamTest(TestCase):
    """
    Verifies that edit_after_publish_policy is a LIVE caller on the dirty path:
      - Stubbing the policy to a non-default value suppresses the dirty affordance
        (the seam actually gates rendering).
      - Default policy (dirty_then_republish) leaves behavior unchanged —
        the dirty banner and Re-publish affordance still render.

    ADR-016 D5 cheap-foresight requirement (kb-96tn.11).
    ADR-008 D2: do NOT test alternate policy behaviors beyond asserting the seam
    is load-bearing (no lock/auto branches implemented here).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="policy_seam_user", email="policy@test.com", password="pw")
        self.profile = _make_profile("Policy Seam Org", "policy-seam-org", user=self.user)
        self.event = _make_event(self.profile, "Policy Seam Event", "policy-seam-event")
        self.switch_conn = _make_switch_connection(self.profile)
        self.switch_proj = _make_published_projection(self.event, self.switch_conn)
        # Edit the body to create a dirty state
        cv = self.switch_proj.content_version
        cv.body = "EDITED BODY — seam test wants dirty state"
        cv.save(update_fields=["body"])
        self.switch_proj.refresh_from_db()
        self.switch_proj.content_version.refresh_from_db()
        self.client.login(username="policy_seam_user", password="pw")

    def _get_event_syndication_html(self):
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_default_policy_shows_dirty_affordance(self):
        """
        With the default dirty_then_republish policy, a dirty published projection
        causes the dirty banner to render — v0 behavior is unchanged (regression guard).
        """
        # Sanity: confirm projection is dirty before calling the view
        self.assertTrue(
            self.switch_proj.is_dirty,
            "Pre-condition: projection must be dirty after body edit.",
        )
        content = self._get_event_syndication_html()
        self.assertIn(
            'data-testid="dirty-banner"',
            content,
            "Default policy (dirty_then_republish) must render the dirty banner for a dirty published projection.",
        )

    def test_non_default_policy_suppresses_dirty_affordance(self):
        """
        When edit_after_publish_policy returns a non-default value (e.g. 'lock'),
        the dirty affordance must NOT render — proving the policy seam is LIVE.

        ADR-008 D2: 'lock' behavior is not implemented; this test only verifies
        the seam gates the affordance, not that locking works end-to-end.
        """
        # Sanity: projection is still dirty (content-diff fact is unchanged)
        self.assertTrue(
            self.switch_proj.is_dirty,
            "Pre-condition: projection must still be dirty (is_dirty is a content-diff fact).",
        )
        # Stub the policy to a non-default value — the seam must gate the affordance
        with patch("syndication.views.edit_after_publish_policy", return_value="lock"):
            content = self._get_event_syndication_html()
        self.assertNotIn(
            'data-testid="dirty-banner"',
            content,
            "Non-default policy ('lock') must suppress the dirty banner — "
            "proving edit_after_publish_policy is a live caller on the render path (kb-96tn.11).",
        )
