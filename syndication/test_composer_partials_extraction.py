"""
Render-regression tests for kb-kgza.9: shared-partial extraction from
event_syndication.html and post_syndication.html.

These tests lock the rendered HTML markers of the picker, editor, and breadcrumb
regions BEFORE and AFTER extraction.  They assert on response.content.decode()
NOT on response.context (hollow-test prevention per memory
django-view-test-context-vs-content-hollow).

Coverage:
- Event composer: draft + published projections, channel states: canonical-shared,
  synced-from-peer, custom.
- Post composer: same states.

The tests must be GREEN against the current (pre-extraction) code; they must
STAY GREEN after extraction (any diff = behaviour changed).

Harness target (kb-kgza.9): Signal = these tests.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
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


def _make_listing_projection(conn, event, cv, sync_source=None, status="draft"):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        source_event=event,
        content_version=cv,
        sync_source=sync_source,
    )


def _make_promotion_projection(conn, post, cv, sync_source=None, status="draft"):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=status,
        source_post=post,
        content_version=cv,
        sync_source=sync_source,
    )


def _make_canonical_cv(event=None, post=None, body="canonical body"):
    if event is not None:
        cv, _ = ContentVersion.objects.get_or_create(
            event=event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE, "body": body},
        )
    else:
        cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE, "body": body},
        )
    return cv


# ---------------------------------------------------------------------------
# Event composer: breadcrumb region
# ---------------------------------------------------------------------------


class EventBreadcrumbRegionTest(TestCase):
    """
    Breadcrumb region in event_syndication.html renders 'Studio' (no link).

    The event composer's breadcrumb is simpler than the post composer's:
    it shows only the word 'Studio' as a static label, no link, no event title.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_bc_user", email="evt_bc@test.com", password="pw")
        self.profile = _make_profile("Evt BC Org", "evt-bc-org", user=self.user)
        self.event = _make_event(self.profile, "BC Event", "bc-event")
        conn = _make_connection(self.profile, "fetlife", "fl-bc-evt", ["listing"])
        cv = _make_canonical_cv(event=self.event, body="bc event body")
        _make_listing_projection(conn, self.event, cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_breadcrumb_contains_studio_text(self):
        """Event breadcrumb renders 'Studio' text."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Studio", content)

    def test_event_breadcrumb_has_no_event_hub_link(self):
        """
        Event composer breadcrumb does NOT link to event-hub —
        it is a plain static label.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The event composer shows only 'Studio' — no '›' separator
        # The post composer shows 'Studio › event.title' with a link.
        # The event breadcrumb div should not contain a '›' separator character.
        # Find the breadcrumb div region in the content.
        # We look for the flex-1 div containing 'Studio' and check there's no › there.
        # This assertion reflects the CURRENT intentional difference.
        breadcrumb_idx = content.find("Studio")
        self.assertGreater(breadcrumb_idx, -1)
        # The breadcrumb region (next ~300 chars after 'Studio') should not contain '›'.
        breadcrumb_region = content[breadcrumb_idx : breadcrumb_idx + 300]
        self.assertNotIn("›", breadcrumb_region)


# ---------------------------------------------------------------------------
# Post composer: breadcrumb region
# ---------------------------------------------------------------------------


class PostBreadcrumbRegionTest(TestCase):
    """
    Breadcrumb region in post_syndication.html renders 'Studio › event.title'
    with a link back to the event hub.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_bc_user", email="post_bc@test.com", password="pw")
        self.profile = _make_profile("Post BC Org", "post-bc-org", user=self.user)
        self.event = _make_event(self.profile, "BC Post Event", "bc-post-event")
        self.post = Post.objects.create(event=self.event, headline="BC Post", body="bc post body")
        conn = _make_connection(self.profile, "fetlife", "fl-bc-post", ["promotion"])
        cv = _make_canonical_cv(post=self.post, body="bc post body")
        _make_promotion_projection(conn, self.post, cv)
        # Canonical CV required for source panel
        _make_canonical_cv(post=self.post)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_post_breadcrumb_contains_studio_text(self):
        """Post breadcrumb renders 'Studio' text."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Studio", content)

    def test_post_breadcrumb_contains_event_title(self):
        """Post breadcrumb renders event title as a link back to the event hub."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("BC Post Event", content)

    def test_post_breadcrumb_contains_separator_and_hub_link(self):
        """Post breadcrumb contains '›' separator and link to event hub."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("›", content)
        # Link to event hub must be present
        event_hub_url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        self.assertIn(event_hub_url, content)


# ---------------------------------------------------------------------------
# Event composer: sync picker — state (i) canonical/shared channel
# ---------------------------------------------------------------------------


class EventSyncPickerCanonicalStateTest(TestCase):
    """
    Sync picker in event_syndication.html for a canonical-shared (state i) channel.

    State (i): projection.content_version.name == 'canonical' AND sync_source is NULL.
    The picker renders the 'Shared' badge + 'Customize →' button.
    The Copy-from picker (state i/ii) renders directly (no discard modal).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_sync_i_user", email="evt_sync_i@test.com", password="pw")
        self.profile = _make_profile("Evt Sync I Org", "evt-sync-i-org", user=self.user)
        self.event = _make_event(self.profile, "Sync I Event", "sync-i-event")
        self.conn_switch = _make_connection(self.profile, "switch", "own-page", ["listing"])
        self.conn_fl = _make_connection(self.profile, "fetlife", "fl-sync-i", ["listing"])
        # Switch has the canonical CV (state i)
        self.canonical_cv = _make_canonical_cv(event=self.event, body="canonical switch body")
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        # FetLife also uses the canonical CV (also state i — shared)
        self.fl_proj = _make_listing_projection(self.conn_fl, self.event, self.canonical_cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_shared_badge_present(self):
        """State (i): 'Shared' badge must be visible in rendered output."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Shared", content)

    def test_customize_button_present(self):
        """State (i): 'Customize →' affordance must be visible."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Customize", content)

    def test_copy_from_form_has_correct_hx_target(self):
        """
        Copy-from form (state i/ii) must point hx-target at #event-syndication.
        This ensures the fragment refreshes the correct section.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The copy-from endpoint is /syndication/projections/<pk>/copy-from/
        # Check that the copy-from URL and hx-target are both present
        self.assertIn("copy-from", content)
        self.assertIn('hx-target="#event-syndication"', content)


# ---------------------------------------------------------------------------
# Event composer: sync picker — state (ii) synced-from-peer channel
# ---------------------------------------------------------------------------


class EventSyncPickerSyncedStateTest(TestCase):
    """
    Sync picker in event_syndication.html for a synced-from-peer (state ii) channel.

    State (ii): projection has sync_source set (own CV, sync_source NOT NULL).
    The picker renders 'Synced from <platform>' + '· editing detaches'.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_sync_ii_user", email="evt_sync_ii@test.com", password="pw")
        self.profile = _make_profile("Evt Sync II Org", "evt-sync-ii-org", user=self.user)
        self.event = _make_event(self.profile, "Sync II Event", "sync-ii-event")
        self.conn_switch = _make_connection(self.profile, "switch", "own-page", ["listing"])
        self.conn_fl = _make_connection(self.profile, "fetlife", "fl-sync-ii", ["listing"])
        self.canonical_cv = _make_canonical_cv(event=self.event, body="switch body for state ii")
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        # FetLife has its own CV, synced from switch (state ii)
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-sync-ii-cv",
            body="copied switch body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_listing_projection(self.conn_fl, self.event, self.fl_cv, sync_source=self.switch_proj)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_synced_from_badge_present(self):
        """State (ii): 'Synced from' badge must be visible."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Synced from", content)

    def test_editing_detaches_text_present(self):
        """State (ii): '· editing detaches' hint must be visible."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("editing detaches", content)

    def test_reset_button_present(self):
        """State (ii): Reset button must be present for synced channels."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Reset", content)


# ---------------------------------------------------------------------------
# Event composer: sync picker — state (iii) custom channel (discard confirm)
# ---------------------------------------------------------------------------


class EventSyncPickerCustomStateTest(TestCase):
    """
    Sync picker in event_syndication.html for a custom (state iii) channel.

    State (iii): own CV, sync_source NULL, content_version.name != 'canonical'.
    The picker renders the discard-confirm modal with 'Sync from' dropdown.
    Alpine x-data confirmResync must be present.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_sync_iii_user", email="evt_sync_iii@test.com", password="pw")
        self.profile = _make_profile("Evt Sync III Org", "evt-sync-iii-org", user=self.user)
        self.event = _make_event(self.profile, "Sync III Event", "sync-iii-event")
        self.conn_switch = _make_connection(self.profile, "switch", "own-page", ["listing"])
        self.conn_fl = _make_connection(self.profile, "fetlife", "fl-sync-iii", ["listing"])
        self.canonical_cv = _make_canonical_cv(event=self.event, body="switch body for state iii")
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        # FetLife has its own CV, NO sync_source (custom state)
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-sync-iii-custom",
            body="my custom fetlife body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        # State iii: own CV + sync_source NULL
        self.fl_proj = _make_listing_projection(self.conn_fl, self.event, self.fl_cv, sync_source=None)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_custom_badge_present(self):
        """State (iii): 'Custom' badge must be visible."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Custom", content)

    def test_discard_modal_alpine_state_present(self):
        """State (iii): Alpine confirmResync state must be in the rendered HTML."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("confirmResync", content)

    def test_sync_from_label_present(self):
        """State (iii): 'Sync from' label must be present (not 'Copy from')."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Sync from", content)

    def test_discard_and_resync_button_present(self):
        """State (iii): 'Discard and re-sync' button must be present inside the modal."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Discard and re-sync", content)

    def test_discard_confirm_modal_version_copy_from_url(self):
        """State (iii): Discard modal form must POST to version-copy-from endpoint."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        version_copy_from_url = reverse("syndication:version-copy-from", kwargs={"pk": self.fl_proj.pk})
        self.assertIn(version_copy_from_url, content)

    def test_discard_confirm_hx_target_is_event_syndication(self):
        """State (iii): Discard modal form hx-target must be #event-syndication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The discard modal form must point at the event section, not post section
        self.assertIn('hx-target="#event-syndication"', content)
        self.assertNotIn('hx-target="#post-syndication"', content)

    def test_resync_select_id_uses_event_prefix(self):
        """
        State (iii): resync select uses id='resync-select-<pk>' (no '-post-' in ID).
        This preserves the CURRENT event_syndication.html behavior (intentional divergence
        vs post_syndication.html which uses 'resync-select-post-<pk>').
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        expected_id = f"resync-select-{self.fl_proj.pk}"
        self.assertIn(f'id="{expected_id}"', content)
        # Must NOT use the post variant
        self.assertNotIn(f'id="resync-select-post-{self.fl_proj.pk}"', content)


# ---------------------------------------------------------------------------
# Event composer: channel editor — published projection (status gate + CTA)
# ---------------------------------------------------------------------------


class EventChannelEditorPublishedTest(TestCase):
    """
    Channel editor in event_syndication.html for a PUBLISHED projection.

    Published projections:
    - Do NOT show the draft body editor (status gate).
    - Do show the channel preview (via _channel_preview.html).
    - Show Publish/Re-publish CTA if can_publish.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_pub_user", email="evt_pub@test.com", password="pw")
        self.profile = _make_profile("Evt Pub Org", "evt-pub-org", user=self.user)
        self.event = _make_event(self.profile, "Pub Event", "pub-event")
        self.conn = _make_connection(self.profile, "fetlife", "fl-pub-evt", ["listing"])
        self.cv = _make_canonical_cv(event=self.event, body="published event body")
        self.proj = _make_listing_projection(self.conn, self.event, self.cv, status="published")
        # Freeze content so is_dirty check doesn't raise (frozen_content is a JSONField dict)
        self.proj.frozen_content = {"body": self.cv.body}
        self.proj.save(update_fields=["frozen_content"])
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_channel_pill_has_published_status(self):
        """Published projection: channel pill carries data-status='published'."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('data-status="published"', content)

    def test_version_edit_form_not_shown_for_published(self):
        """
        Published projection: the body editor form (action=version-edit) must NOT
        be rendered (status gate: only draft shows the editor).
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        version_edit_url = reverse("syndication:version-edit", kwargs={"pk": self.cv.pk})
        # The version-edit form should NOT be in the output for published
        self.assertNotIn(f'action="{version_edit_url}"', content)

    def test_selected_pk_hidden_input_in_cta_area(self):
        """
        CTA area: selected_pk hidden input must be present (wired to Alpine selectedPk).
        Used by all publish forms to reopen the correct tab after submission.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="selected_pk"', content)
        self.assertIn(':value="selectedPk"', content)


# ---------------------------------------------------------------------------
# Event composer: channel editor — draft projection (body form present)
# ---------------------------------------------------------------------------


class EventChannelEditorDraftTest(TestCase):
    """
    Channel editor in event_syndication.html for a DRAFT projection.

    Draft non-Switch projections:
    - Show the body editor form (action=version-edit).
    - Show the autosave 'Saved' indicator.
    - Show the Publish CTA (can_publish).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="evt_draft_user", email="evt_draft@test.com", password="pw")
        self.profile = _make_profile("Evt Draft Org", "evt-draft-org", user=self.user)
        self.event = _make_event(self.profile, "Draft Event", "draft-event")
        self.conn = _make_connection(self.profile, "fetlife", "fl-draft-evt", ["listing"])
        self.cv = _make_canonical_cv(event=self.event, body="draft event body")
        self.proj = _make_listing_projection(self.conn, self.event, self.cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_version_edit_form_shown_for_draft(self):
        """
        Draft: body editor form must use projection-detach-and-edit (projection-keyed).
        kb-kgza.2: per-channel body form now routes to projection-detach-and-edit
        so editing auto-detaches from the shared canonical CV (ADR-016 D2).
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        detach_edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.assertIn(f'action="{detach_edit_url}"', content)

    def test_draft_body_editor_hx_target_is_none(self):
        """
        Draft body editor uses hx-swap='none' (autosave, no DOM replacement).
        The hx-swap='none' must be present on the projection-detach-and-edit form.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('hx-swap="none"', content)

    def test_publish_cta_present_for_draft(self):
        """Draft: Publish CTA must be present (direct-publish or publish endpoint)."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        publish_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.proj.pk})
        self.assertIn(publish_url, content)

    def test_publish_form_hx_target_is_event_syndication(self):
        """Publish CTA form must target #event-syndication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Every form that modifies projection state must target #event-syndication
        self.assertIn('hx-target="#event-syndication"', content)
        self.assertNotIn('hx-target="#post-syndication"', content)


# ---------------------------------------------------------------------------
# Post composer: sync picker — state (iii) custom channel (discard confirm)
# ---------------------------------------------------------------------------


class PostSyncPickerCustomStateTest(TestCase):
    """
    Sync picker in post_syndication.html for a custom (state iii) channel.

    State (iii): own CV, sync_source NULL, content_version.name != 'canonical'.
    The picker renders the discard-confirm modal.
    hx-target must be #post-syndication (not #event-syndication).
    resync-select uses 'resync-select-post-<pk>' ID prefix.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_sync_iii_user", email="post_sync_iii@test.com", password="pw")
        self.profile = _make_profile("Post Sync III Org", "post-sync-iii-org", user=self.user)
        self.event = _make_event(self.profile, "Post Sync III Event", "post-sync-iii-event")
        self.post = Post.objects.create(event=self.event, headline="Sync III Post", body="sync iii post body")
        self.source_cv = _make_canonical_cv(post=self.post, body="canonical post body")

        # Two promotion channels
        self.conn_tg = _make_connection(self.profile, "telegram", "tg-sync-iii", ["promotion"])
        self.conn_fl = _make_connection(self.profile, "fetlife", "fl-sync-iii-post", ["promotion"])

        # Telegram uses canonical CV (state i)
        self.tg_cv = ContentVersion.objects.create(
            post=self.post,
            name="tg-sync-iii-cv",
            body="tg body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = _make_promotion_projection(self.conn_tg, self.post, self.tg_cv)

        # FetLife has its own CV, NO sync_source (state iii: custom)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-sync-iii-post-custom",
            body="my custom fetlife post",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_promotion_projection(self.conn_fl, self.post, self.fl_cv, sync_source=None)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_custom_badge_present(self):
        """State (iii): 'Custom' badge must be visible."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Custom", content)

    def test_discard_modal_alpine_state_present(self):
        """State (iii): Alpine confirmResync state must be in the rendered HTML."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("confirmResync", content)

    def test_discard_confirm_hx_target_is_post_syndication(self):
        """State (iii): Discard modal form hx-target must be #post-syndication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('hx-target="#post-syndication"', content)
        self.assertNotIn('hx-target="#event-syndication"', content)

    def test_resync_select_id_uses_post_prefix(self):
        """
        State (iii): resync select uses id='resync-select-post-<pk>' (includes '-post-').
        This preserves the CURRENT post_syndication.html behavior (intentional divergence
        vs event_syndication.html which uses 'resync-select-<pk>').
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        expected_id = f"resync-select-post-{self.fl_proj.pk}"
        self.assertIn(f'id="{expected_id}"', content)
        # Must NOT use the bare event variant (resync-select-<pk> without '-post-')
        self.assertNotIn(f'id="resync-select-{self.fl_proj.pk}"', content)


# ---------------------------------------------------------------------------
# Post composer: channel editor — draft projection (body form present)
# ---------------------------------------------------------------------------


class PostChannelEditorDraftTest(TestCase):
    """
    Channel editor in post_syndication.html for a DRAFT projection.

    Draft projections:
    - Show the body editor form (action=version-edit).
    - Autosave with hx-swap='none'.
    - Publish CTA targeting #post-syndication.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_draft_user", email="post_draft@test.com", password="pw")
        self.profile = _make_profile("Post Draft Org", "post-draft-org", user=self.user)
        self.event = _make_event(self.profile, "Post Draft Event", "post-draft-event")
        self.post = Post.objects.create(event=self.event, headline="Draft Post", body="draft post body")
        self.source_cv = _make_canonical_cv(post=self.post, body="canonical post body")
        self.conn = _make_connection(self.profile, "fetlife", "fl-post-draft", ["promotion"])
        self.cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-post-draft-cv",
            body="draft post body for fl",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.proj = _make_promotion_projection(self.conn, self.post, self.cv)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_version_edit_form_shown_for_draft(self):
        """
        Draft: body editor form must use projection-detach-and-edit (projection-keyed).
        kb-kgza.2: per-channel body form now routes to projection-detach-and-edit
        so editing auto-detaches from the shared canonical CV (ADR-016 D2).
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        detach_edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.assertIn(f'action="{detach_edit_url}"', content)

    def test_publish_form_hx_target_is_post_syndication(self):
        """Publish CTA form must target #post-syndication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('hx-target="#post-syndication"', content)
        self.assertNotIn('hx-target="#event-syndication"', content)

    def test_publish_cta_present_for_draft(self):
        """Draft: Publish CTA must be present."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        publish_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.proj.pk})
        self.assertIn(publish_url, content)


# ---------------------------------------------------------------------------
# Post composer: channel editor — published projection (CTA region)
# ---------------------------------------------------------------------------


class PostChannelEditorPublishedTest(TestCase):
    """
    Channel editor in post_syndication.html for a PUBLISHED projection.

    Published projections:
    - Do NOT show the draft body editor.
    - Show the preview via _channel_preview.html.
    - CTA region shows Re-publish if dirty, or correct publish state.
    - fragment_target must be #post-syndication in all forms.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_pub_user", email="post_pub@test.com", password="pw")
        self.profile = _make_profile("Post Pub Org", "post-pub-org", user=self.user)
        self.event = _make_event(self.profile, "Post Pub Event", "post-pub-event")
        self.post = Post.objects.create(event=self.event, headline="Pub Post", body="pub post body")
        self.source_cv = _make_canonical_cv(post=self.post, body="canonical post body")
        self.conn = _make_connection(self.profile, "fetlife", "fl-post-pub", ["promotion"])
        self.cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-post-pub-cv",
            body="pub post body for fl",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.proj = _make_promotion_projection(self.conn, self.post, self.cv, status="published")
        # Freeze content so is_dirty doesn't raise (frozen_content is a JSONField dict)
        self.proj.frozen_content = {"body": self.cv.body}
        self.proj.save(update_fields=["frozen_content"])
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_published_pill_status_present(self):
        """Published projection: channel pill carries data-status='published'."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('data-status="published"', content)

    def test_version_edit_form_not_shown_for_published(self):
        """
        Published projection: the draft body editor form (action=version-edit)
        must NOT be rendered.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        version_edit_url = reverse("syndication:version-edit", kwargs={"pk": self.cv.pk})
        self.assertNotIn(f'action="{version_edit_url}"', content)

    def test_all_forms_target_post_syndication(self):
        """All hx-target attrs in the post fragment must be #post-syndication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # No form should point at the event fragment
        self.assertNotIn('hx-target="#event-syndication"', content)


# ---------------------------------------------------------------------------
# Post composer: sync picker — state (i) canonical/shared (Copy-from direct)
# ---------------------------------------------------------------------------


class PostSyncPickerCanonicalStateTest(TestCase):
    """
    Sync picker in post_syndication.html for canonical/synced state (state i/ii).
    The 'Copy from' form renders directly (no discard modal).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_sync_i_user", email="post_sync_i@test.com", password="pw")
        self.profile = _make_profile("Post Sync I Org", "post-sync-i-org", user=self.user)
        self.event = _make_event(self.profile, "Post Sync I Event", "post-sync-i-event")
        self.post = Post.objects.create(event=self.event, headline="Sync I Post", body="sync i post body")
        self.source_cv = _make_canonical_cv(post=self.post, body="canonical post body")

        # Two channels — both using canonical CV (state i)
        self.conn_tg = _make_connection(self.profile, "telegram", "tg-sync-i-post", ["promotion"])
        self.conn_fl = _make_connection(self.profile, "fetlife", "fl-sync-i-post", ["promotion"])

        # Both projections use the canonical CV
        self.tg_proj = _make_promotion_projection(self.conn_tg, self.post, self.source_cv)
        self.fl_proj = _make_promotion_projection(self.conn_fl, self.post, self.source_cv)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_copy_from_label_present(self):
        """State (i/ii): 'Copy from' label must be present (no modal for state i)."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Copy from", content)

    def test_copy_from_apply_button_present(self):
        """State (i/ii): 'Apply' button must be present."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Apply", content)

    def test_copy_from_form_hx_target_is_post_syndication(self):
        """Copy-from form targets #post-syndication."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('hx-target="#post-syndication"', content)
