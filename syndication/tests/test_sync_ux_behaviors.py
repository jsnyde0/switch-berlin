"""
TDD tests for the three sync UX behaviors wired in kb-ide0.4 (view/template level).

Contract groups:
(J) Detach-on-edit (acceptance bullet 4)
    - POST to version-edit on a projection whose sync_source IS NOT NULL
      must clear sync_source and re-render the fragment showing "Custom".
(K) Cycle-guard picker (acceptance bullet 6, UI half)
    - The source picker in event_syndication and post_syndication must
      EXCLUDE projections whose sync_source IS NOT NULL.
    - A projection must NOT offer ITSELF as a source.
(L) Discard-confirm modal (acceptance bullet 5)
    - The template must carry Alpine x-data state for the "Discard edits?"
      confirm modal; the modal trigger must appear for synced channels that
      have their own edits (state iii — custom).
(M) OOB sync-bar update on autosave (kb-lprn)
    - POST to version-edit (the autosave endpoint) must return an
      hx-swap-oob="true" sync-bar fragment so the badge updates from the
      server's truth after the save round-trip — NO optimistic client flip.
    - Detach case (own-page channel with sync_source set, after edit):
      OOB fragment must contain "Custom".
    - Broadcast case (promotion channel sharing canonical CV, after edit):
      OOB fragment must NOT show "Custom" — the canonical/synced state is
      authoritative and editing does not detach shared-CV channels.

All assertions on response.content (NOT response.context — hollow per memory).
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
# Helpers (mirror test_sync_mechanism.py setup helpers)
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
    event = Event.objects.create(title=title, slug=slug, start=timezone.now())
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_canonical_cv(event=None, post=None):
    if event is not None:
        cv, _ = ContentVersion.objects.get_or_create(
            event=event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
    else:
        cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
    return cv


def _make_listing_projection(conn, event, cv, sync_source=None):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.LISTING,
        status=PlatformProjection.Status.DRAFT,
        source_event=event,
        content_version=cv,
        sync_source=sync_source,
    )


def _make_promotion_projection(conn, post, cv, sync_source=None):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=PlatformProjection.Status.DRAFT,
        source_post=post,
        content_version=cv,
        sync_source=sync_source,
    )


# ---------------------------------------------------------------------------
# (J) Detach-on-edit — event composer
# ---------------------------------------------------------------------------


class DetachOnEditEventComposerTest(TestCase):
    """
    POST to version-edit on a projection whose sync_source IS NOT NULL must:
    1. Clear sync_source (projection.sync_source becomes None after the edit).
    2. Re-render the event_syndication fragment showing "Custom" indicator.

    Acceptance bullet 4 — event composer side.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="detach_edit_evt", email="dee@test.com", password="pw")
        self.profile = _make_profile("Detach Edit Event Org", "detach-edit-evt-org", user=self.user)
        self.event = _make_event(self.profile, "Detach Edit Event", "detach-edit-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)
        self.canonical_cv.body = "Switch body"
        self.canonical_cv.save(update_fields=["body", "updated_at"])

        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-detach-edit",
            kinds=["listing"],
        )
        self.source_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)

        # FetLife has its own CV and is synced from switch (state ii)
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-detach-edit-cv",
            body="copied switch body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.fl_cv, sync_source=self.source_proj)
        self.client.force_login(self.user)

    def test_edit_synced_projection_clears_sync_source(self):
        """
        POST to version-edit on a synced projection clears sync_source.
        Assertion: after the POST, projection.sync_source is None.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        self.client.post(url, {"body": "edited content — now custom"})
        self.fl_proj.refresh_from_db()
        self.assertIsNone(self.fl_proj.sync_source)

    def test_edit_synced_projection_fragment_shows_custom(self):
        """
        After POSTing version-edit on a synced projection, the re-rendered
        fragment response carries "Custom" indicator (state iii).
        Assertion on response.content.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        # Use HTMX header so the view returns the fragment (not a redirect)
        response = self.client.post(
            url,
            {"body": "edited content — now custom"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Custom", content)

    def test_edit_unsynced_projection_does_not_touch_sync_source(self):
        """
        POST to version-edit on a projection with sync_source NULL (already custom)
        must NOT change anything about sync_source (no spurious write).
        """
        # Detach first so fl_proj starts with sync_source=None
        self.fl_proj.sync_source = None
        self.fl_proj.save(update_fields=["sync_source", "updated_at"])

        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        self.client.post(url, {"body": "further edit"})
        self.fl_proj.refresh_from_db()
        self.assertIsNone(self.fl_proj.sync_source)


# ---------------------------------------------------------------------------
# (J) Detach-on-edit — post composer
# ---------------------------------------------------------------------------


class DetachOnEditPostComposerTest(TestCase):
    """
    POST to version-edit on a post-composer projection whose sync_source IS NOT NULL must:
    1. Clear sync_source.
    2. Re-render the post_syndication fragment showing "Custom" indicator.

    Acceptance bullet 4 — post composer side.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="detach_edit_post", email="dep@test.com", password="pw")
        self.profile = _make_profile("Detach Edit Post Org", "detach-edit-post-org", user=self.user)
        self.event = _make_event(self.profile, "Detach Edit Post Event", "detach-edit-post-event")
        self.post = Post.objects.create(event=self.event, headline="Test post", body="Original body")

        # Create canonical CV for the post (the Source anchor)
        self.source_cv = _make_canonical_cv(post=self.post)
        self.source_cv.body = "canonical post body"
        self.source_cv.save(update_fields=["body", "updated_at"])

        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-detach-edit",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-detach-edit-post",
            kinds=["promotion"],
        )

        # Telegram is the "source" projection (synced from canonical; no sync_source itself)
        self.tg_cv = ContentVersion.objects.create(
            post=self.post,
            name="tg-detach-edit-cv",
            body="telegram-copy",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.tg_cv)

        # FetLife is synced FROM telegram (state ii — has sync_source)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-detach-edit-post-cv",
            body="fetlife-copy",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.fl_cv, sync_source=self.tg_proj)
        self.client.force_login(self.user)

    def test_post_composer_edit_synced_projection_clears_sync_source(self):
        """
        POST to version-edit on a synced post-composer projection clears sync_source.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        self.client.post(url, {"body": "custom fetlife content"})
        self.fl_proj.refresh_from_db()
        self.assertIsNone(self.fl_proj.sync_source)

    def test_post_composer_edit_synced_projection_fragment_shows_custom(self):
        """
        After POSTing version-edit on a synced post projection, the re-rendered
        fragment shows "Custom" indicator.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        response = self.client.post(
            url,
            {"body": "custom fetlife content"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Custom", content)


# ---------------------------------------------------------------------------
# (K) Cycle-guard picker — event composer
# ---------------------------------------------------------------------------


class CycleGuardPickerEventComposerTest(TestCase):
    """
    The "Copy from" source picker in event_syndication must EXCLUDE projections
    whose sync_source IS NOT NULL (only independent channels are offerable).
    A projection must also NOT offer ITSELF as a source option.

    Acceptance bullet 6 (UI half) — event composer.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="picker_evt_user", email="pe@test.com", password="pw")
        self.profile = _make_profile("Picker Event Org", "picker-evt-org", user=self.user)
        self.event = _make_event(self.profile, "Picker Event", "picker-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)

        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-picker",
            kinds=["listing"],
        )
        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-picker",
            kinds=["listing"],
        )

        # Switch: independent (sync_source=None)
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)

        # FetLife: synced FROM switch (sync_source IS NOT NULL)
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-picker-cv",
            body="fl body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.fl_cv, sync_source=self.switch_proj)

        # Telegram: a third independent projection
        self.tg_cv = ContentVersion.objects.create(
            event=self.event,
            name="tg-picker-cv",
            body="tg body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = _make_listing_projection(self.conn_telegram, self.event, self.tg_cv)

        self.client.force_login(self.user)

    def _get_fragment(self):
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        return self.client.get(url)

    def test_synced_projection_not_in_picker_options(self):
        """
        FetLife is synced (sync_source IS NOT NULL) — it must NOT appear as an
        option in Telegram's source picker (or Switch's or any picker).
        The picker uses source_projection_pk (projection pks); fl_proj.pk must
        not be present as an option value.
        """
        response = self._get_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # fl_proj.pk must not appear as a picker option (synced — excluded)
        fl_proj_pk_str = str(self.fl_proj.pk)
        self.assertNotIn(f'value="{fl_proj_pk_str}"', content)

    def test_independent_projection_appears_in_picker_options(self):
        """
        Switch is independent (sync_source=None) — it MUST appear as an option
        in the Telegram picker.
        The picker now uses source_projection_pk (projection pks), not CV pks.
        """
        response = self._get_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The picker renders projection pks as option values (source_projection_pk path)
        switch_proj_pk_str = str(self.switch_proj.pk)
        self.assertIn(f'value="{switch_proj_pk_str}"', content)


# ---------------------------------------------------------------------------
# (K) Cycle-guard picker — post composer
# ---------------------------------------------------------------------------


class CycleGuardPickerPostComposerTest(TestCase):
    """
    The "Copy from" source picker in post_syndication must EXCLUDE projections
    whose sync_source IS NOT NULL — only independent channels are offerable.

    Acceptance bullet 6 (UI half) — post composer.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="picker_post_user", email="pp@test.com", password="pw")
        self.profile = _make_profile("Picker Post Org", "picker-post-org", user=self.user)
        self.event = _make_event(self.profile, "Picker Post Event", "picker-post-event")
        self.post = Post.objects.create(event=self.event, headline="Picker post", body="Picker body")

        self.source_cv = _make_canonical_cv(post=self.post)
        self.source_cv.body = "canonical"
        self.source_cv.save(update_fields=["body", "updated_at"])

        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-post-picker",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-post-picker",
            kinds=["promotion"],
        )

        # Telegram: independent
        self.tg_cv = ContentVersion.objects.create(
            post=self.post,
            name="tg-post-picker-cv",
            body="tg body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.tg_cv)

        # FetLife: synced FROM telegram (sync_source IS NOT NULL)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-post-picker-cv",
            body="fl body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.fl_cv, sync_source=self.tg_proj)
        self.client.force_login(self.user)

    def _get_fragment(self):
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        return self.client.get(url)

    def test_synced_projection_not_in_post_picker_options(self):
        """
        FetLife is synced (sync_source IS NOT NULL) — it must NOT appear as an
        option in Telegram's source picker in the post composer.
        The picker uses source_projection_pk (projection pks); fl_proj.pk must
        not be present as an option value.
        """
        response = self._get_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # fl_proj.pk must not appear as a picker option (synced — excluded)
        fl_proj_pk_str = str(self.fl_proj.pk)
        self.assertNotIn(f'value="{fl_proj_pk_str}"', content)

    def test_independent_projection_appears_in_post_picker(self):
        """
        Telegram is independent (sync_source=None) — it MUST appear as an
        option in FetLife's picker in the post composer.
        The picker now uses source_projection_pk (projection pks), not CV pks.
        """
        response = self._get_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The picker renders projection pks as option values (source_projection_pk path)
        tg_proj_pk_str = str(self.tg_proj.pk)
        self.assertIn(f'value="{tg_proj_pk_str}"', content)


# ---------------------------------------------------------------------------
# (L) Discard-confirm modal — Alpine state presence
# ---------------------------------------------------------------------------


class DiscardConfirmModalPresenceTest(TestCase):
    """
    The template must carry Alpine x-data state for the "Discard edits?" confirm
    modal. The modal markup must be present in the fragment for channels in state (iii)
    (custom / detached — has own edits, sync_source is NULL but was previously synced).

    We test for presence of the modal trigger markup in the response content.
    The modal itself is Alpine-driven (x-data, x-show, @click) — no server round-trip.

    Acceptance bullet 5.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="modal_user", email="modal@test.com", password="pw")
        self.profile = _make_profile("Modal Org", "modal-org", user=self.user)
        self.event = _make_event(self.profile, "Modal Event", "modal-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)

        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-modal",
            kinds=["listing"],
        )
        # FetLife with own CV and no sync_source — state (iii): Custom
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-modal-cv",
            body="custom fl body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.fl_cv, sync_source=None)
        self.client.force_login(self.user)

    def _get_event_fragment(self):
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        return self.client.get(url)

    def test_event_composer_modal_state_present_for_custom_channel(self):
        """
        When a channel is in state (iii) custom (own CV, sync_source NULL),
        the fragment must carry Alpine modal state so re-sync can trigger the
        discard-confirm flow. The section x-data must include confirmResync or
        the picker area must have x-data with modal state.
        """
        response = self._get_event_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The modal must be present: look for the discard-confirm modal trigger.
        # The modal is Alpine-driven — we check for its Alpine presence.
        # Acceptable patterns: "confirmResync", "Discard", "discard"
        # The exact attribute name is implementation-specific; we test for a meaningful marker.
        has_modal = "confirmResync" in content or "Discard" in content or "discard" in content
        self.assertTrue(
            has_modal,
            "Modal discard-confirm state must be present in the fragment for a custom channel. "
            f"Expected 'confirmResync' or 'Discard' or 'discard' in content. "
            f"Fragment excerpt: {content[:3000]!r}",
        )


class DiscardConfirmModalPostComposerTest(TestCase):
    """
    Post composer: same discard-confirm modal presence requirement for a
    custom channel in state (iii).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="modal_post_user", email="modalpost@test.com", password="pw")
        self.profile = _make_profile("Modal Post Org", "modal-post-org", user=self.user)
        self.event = _make_event(self.profile, "Modal Post Event", "modal-post-event")
        self.post = Post.objects.create(event=self.event, headline="Modal post", body="Modal body")

        self.source_cv = _make_canonical_cv(post=self.post)
        self.source_cv.body = "canonical"
        self.source_cv.save(update_fields=["body", "updated_at"])

        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-modal-post",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-modal-post",
            kinds=["promotion"],
        )

        # Telegram: independent
        self.tg_cv = ContentVersion.objects.create(
            post=self.post,
            name="tg-modal-cv",
            body="tg body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.tg_cv)

        # FetLife: custom (own CV, sync_source NULL) — state (iii)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-modal-cv",
            body="custom fl body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.fl_cv, sync_source=None)
        self.client.force_login(self.user)

    def _get_post_fragment(self):
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        return self.client.get(url)

    def test_post_composer_modal_state_present_for_custom_channel(self):
        """
        Post composer: when a channel is in state (iii) custom, the fragment must
        carry Alpine modal state for the discard-confirm flow.
        """
        response = self._get_post_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        has_modal = "confirmResync" in content or "Discard" in content or "discard" in content
        self.assertTrue(
            has_modal,
            "Modal discard-confirm state must be present in the post fragment for a custom channel. "
            f"Expected 'confirmResync' or 'Discard' or 'discard' in content. "
            f"Fragment excerpt: {content[:3000]!r}",
        )


# ---------------------------------------------------------------------------
# (M) OOB sync-bar update on autosave — kb-lprn
# ---------------------------------------------------------------------------


class OOBSyncBarOnAutosaveDetachTest(TestCase):
    """
    (M) Detach case: POST to version-edit on a channel with sync_source SET
    (own CV, state ii — "Synced from <peer>") must return a response whose
    CONTENT contains:
    - hx-swap-oob="true" (the server-driven OOB fragment mechanism)
    - A sync-bar element keyed by projection pk (id="sync-bar-proj-<pk>")
    - "Custom" text inside that OOB fragment (the server confirms detach)

    This is falsifiable: before the fix, version_edit returns a full-fragment
    response with hx-swap=none; the OOB mechanism is absent from the content.
    After the fix, the OOB sync-bar fragment is present in the response.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="oob_detach_user", email="oob_detach@test.com", password="pw")
        self.profile = _make_profile("OOB Detach Org", "oob-detach-org", user=self.user)
        self.event = _make_event(self.profile, "OOB Detach Event", "oob-detach-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)
        self.canonical_cv.body = "Switch body"
        self.canonical_cv.save(update_fields=["body", "updated_at"])

        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-oob-detach",
            kinds=["listing"],
        )
        self.source_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)

        # FetLife has its OWN CV and is synced from switch (state ii — "Synced from switch")
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-oob-detach-cv",
            body="copied switch body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.fl_cv, sync_source=self.source_proj)
        self.client.force_login(self.user)

    def test_autosave_detach_response_contains_oob_sync_bar_with_custom(self):
        """
        POST to version-edit for the FetLife CV (which has sync_source set)
        must return response content containing:
        1. hx-swap-oob="true" — the OOB mechanism is present
        2. id="sync-bar-proj-<fl_proj.pk>" — the per-projection anchor
        3. "Custom" — the server-confirmed detach badge text

        Falsifiable: before the fix the response is a full page fragment
        with no hx-swap-oob attribute in the content. After the fix the OOB
        sync-bar element is present.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        response = self.client.post(
            url,
            {"body": "edited — now custom"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # 1. OOB mechanism must be present in the response body
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "Response must contain hx-swap-oob='true' for the server-driven OOB badge update",
        )

        # 2. Per-projection sync-bar anchor must be present
        expected_id = f'id="sync-bar-proj-{self.fl_proj.pk}"'
        self.assertIn(
            expected_id,
            content,
            f"Response must contain the per-projection sync-bar anchor {expected_id!r}",
        )

        # 3. Server confirms detach → "Custom" badge must appear in the OOB fragment
        self.assertIn(
            "Custom",
            content,
            "OOB sync-bar fragment must show 'Custom' after editing a synced (detach-on-edit) channel",
        )


class OOBSyncBarOnAutosaveBroadcastTest(TestCase):
    """
    (M) Broadcast case: POST to version-edit on the CANONICAL ContentVersion
    (shared by promotion projections — single-row sharing per ADR-016 D2)
    must return a response whose CONTENT contains:
    - hx-swap-oob="true" with the sync-bar for the affected projection(s)
    - The canonical/synced badge (NOT "Custom") — editing a shared CV does
      not detach; it broadcasts to all sharers.

    This distinguishes the server-driven approach from the naive optimistic
    flip: the server knows editing a shared CV doesn't detach, so it returns
    the correct (non-Custom) badge. A blind optimistic flip would lie.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="oob_broadcast_user", email="oob_broadcast@test.com", password="pw")
        self.profile = _make_profile("OOB Broadcast Org", "oob-broadcast-org", user=self.user)
        self.event = _make_event(self.profile, "OOB Broadcast Event", "oob-broadcast-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="OOB Broadcast Post",
            body="Broadcast body",
        )

        # Canonical CV for the post — SHARED by promotion projections
        self.canonical_cv = _make_canonical_cv(post=self.post)
        self.canonical_cv.body = "canonical post body"
        self.canonical_cv.save(update_fields=["body", "updated_at"])

        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-oob-broadcast",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-oob-broadcast",
            kinds=["promotion"],
        )

        # Both projections SHARE the canonical CV (broadcast semantics — ADR-016 D2)
        # No sync_source — they are both on the canonical row, state (i)
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv)
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        self.client.force_login(self.user)

    def test_autosave_broadcast_response_contains_oob_sync_bar_not_custom(self):
        """
        POST to version-edit for the canonical (shared) CV must:
        1. Return hx-swap-oob="true" with the OOB sync-bar fragment(s)
        2. NOT show "Custom" in the sync-bar fragment — editing the shared
           canonical CV does NOT detach any projection (they all still share it,
           sync_source stays NULL, state stays (i) "Synced").

        Falsifiable: a naive optimistic flip would mark this "Custom"; the
        server-driven OOB response correctly shows the canonical/synced state.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(
            url,
            {"body": "edited canonical — stays synced"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # 1. OOB mechanism must be present
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "Response must contain hx-swap-oob='true' for the server-driven OOB badge update",
        )

        # 2. BOTH per-projection sync-bar anchors must be present — both telegram
        # AND fetlife share the canonical CV, so version_edit must re-render BOTH.
        # A dropped sharer (e.g. only telegram returned) must fail this test.
        has_tg_anchor = f'id="sync-bar-proj-{self.tg_proj.pk}"' in content
        has_fl_anchor = f'id="sync-bar-proj-{self.fl_proj.pk}"' in content
        self.assertTrue(
            has_tg_anchor and has_fl_anchor,
            f"Response must contain BOTH sync-bar anchors: "
            f"telegram (sync-bar-proj-{self.tg_proj.pk}, present={has_tg_anchor}) "
            f"AND fetlife (sync-bar-proj-{self.fl_proj.pk}, present={has_fl_anchor}). "
            f"Both projections share the canonical CV — version_edit must re-render both. "
            f"Content excerpt: {content[:2000]!r}",
        )

        # 3. "Custom" must NOT appear in any OOB sync-bar for shared-CV projections
        # (editing the shared canonical does NOT detach — it broadcasts)
        # Note: we check absence of the amber "Custom" badge specifically.
        # The word "Custom" may appear in comments; look for the badge text span.
        # Use the distinctive amber class as a discriminator.
        custom_badge_marker = 'text-amber-300/70">Custom'
        self.assertNotIn(
            custom_badge_marker,
            content,
            "OOB sync-bar fragment must NOT show 'Custom' badge after editing a shared "
            "canonical CV — broadcast edit does not detach",
        )


class OOBSyncBarOnAutosavePostDetachTest(TestCase):
    """
    (M) Post/promotion detach case: POST to version-edit on a PROMOTION projection
    that is in state (ii) — own CV + sync_source SET ("Synced from <peer>") — must
    return a response whose CONTENT contains:
    - hx-swap-oob="true" (the OOB mechanism)
    - id="sync-bar-proj-<pk>" for the post projection
    - "Custom" badge text (server confirms detach after edit)
    - The POST fragment target "#post-syndication" in the OOB fragment (Customize/Reset
      forms must point at the correct full-fragment target, not #event-syndication)

    This exercises the path repaired by Repair 1 (three-state post inline badge):
    before Repair 1 the OOB partial already has 3 states, but if the partial were
    missing state-(ii), a re-render of the INLINE post fragment (not OOB) would
    oscillate between "Synced from peer" (OOB) and "Custom" (inline fallback).

    The test covers the OOB response path. A separate inline assertion verifies
    the three-state fix in the rendered post fragment (see
    test_post_inline_sync_bar_three_states).

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="oob_post_detach_user",
            email="oob_post_detach@test.com",
            password="pw",
        )
        self.profile = _make_profile("OOB Post Detach Org", "oob-post-detach-org", user=self.user)
        self.event = _make_event(self.profile, "OOB Post Detach Event", "oob-post-detach-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="OOB Post Detach Post",
            body="Source post body",
        )

        # Canonical CV for the post (the "source" anchor)
        self.canonical_cv = _make_canonical_cv(post=self.post)
        self.canonical_cv.body = "canonical source body"
        self.canonical_cv.save(update_fields=["body", "updated_at"])

        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-post-detach-source",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-post-detach-target",
            kinds=["promotion"],
        )

        # Telegram projection: state (i) — on canonical CV (the "source")
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv)

        # FetLife projection: state (ii) — own CV + sync_source = telegram (Synced from telegram)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-post-detach-cv",
            body="copied telegram body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife,
            self.post,
            self.fl_cv,
            sync_source=self.tg_proj,
        )
        self.client.force_login(self.user)

    def test_autosave_post_detach_response_contains_oob_custom_with_post_target(self):
        """
        POST to version-edit for the FetLife promotion CV (state ii — sync_source set)
        must return response content with:
        1. hx-swap-oob="true" — OOB mechanism present
        2. id="sync-bar-proj-<fl_proj.pk>" — per-projection anchor for the post projection
        3. "Custom" — server confirms detach badge
        4. "#post-syndication" — the full-fragment target in the Customize/Reset forms
           (not "#event-syndication", since this is a PROMOTION projection)

        Falsifiable: if the OOB partial only has two branches (canonical → Synced,
        else → Custom), a state-(ii) projection (sync_source set) that has its own
        CV would ALSO render as "Custom" in the OOB response — the test would pass.
        But the inline post fragment (which DID only have two branches before Repair 1)
        would mis-render "Custom" instead of "Synced from peer" on the next full
        fragment refresh, causing oscillation. The companion inline test
        (test_post_inline_sync_bar_state_ii_shows_synced_from) locks the inline fix.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.fl_cv.pk})
        response = self.client.post(
            url,
            {"body": "edited fl post — now custom"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # 1. OOB mechanism must be present
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "Response must contain hx-swap-oob='true' for the server-driven OOB badge update",
        )

        # 2. Per-projection sync-bar anchor for the post (fetlife) projection
        expected_id = f'id="sync-bar-proj-{self.fl_proj.pk}"'
        self.assertIn(
            expected_id,
            content,
            f"Response must contain the per-projection sync-bar anchor {expected_id!r} "
            f"for the post/promotion projection",
        )

        # 3. Server confirms detach → "Custom" badge must appear in the OOB fragment
        self.assertIn(
            "Custom",
            content,
            "OOB sync-bar fragment must show 'Custom' after editing a synced-from-peer "
            "promotion projection (detach-on-edit for post channels)",
        )

        # 4. The full-fragment target must be "#post-syndication" (not "#event-syndication")
        # — the OOB fragment's Customize/Reset forms must point at the POST fragment
        self.assertIn(
            "#post-syndication",
            content,
            "OOB sync-bar for a PROMOTION projection must use '#post-syndication' as "
            "fragment_target, not '#event-syndication'",
        )


class PostInlineSyncBarStateIITest(TestCase):
    """
    Inline post_syndication fragment test: a promotion projection in state (ii)
    (own CV + sync_source SET) must render "Synced from <platform>" in the inline
    sync bar, NOT "Custom".

    Before Repair 1, the post_syndication.html inline only had two branches:
      canonical → "Synced"
      else      → "Custom"
    so a state-(ii) projection (own CV, not canonical) would render "Custom"
    incorrectly, causing badge oscillation (OOB says "Synced from X", next full
    fragment render says "Custom").

    After Repair 1 (shared _sync_bar.html partial with three states), the inline
    must render "Synced from fetlife" for a state-(ii) telegram-sourced FetLife projection.

    Assertions on response.content (NOT response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="post_inline_state2_user",
            email="post_inline_state2@test.com",
            password="pw",
        )
        self.profile = _make_profile("Post Inline State2 Org", "post-inline-state2-org", user=self.user)
        self.event = _make_event(self.profile, "Post Inline State2 Event", "post-inline-state2-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Post Inline State2 Post",
            body="Source post body",
        )

        self.canonical_cv = _make_canonical_cv(post=self.post)
        self.canonical_cv.body = "canonical source body"
        self.canonical_cv.save(update_fields=["body", "updated_at"])

        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-state2-source",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-state2-target",
            kinds=["promotion"],
        )

        # Telegram: state (i) — shares canonical CV
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv)

        # FetLife: state (ii) — own CV + sync_source = telegram
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-state2-cv",
            body="synced-from-telegram body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife,
            self.post,
            self.fl_cv,
            sync_source=self.tg_proj,
        )
        self.client.force_login(self.user)

    def test_post_inline_sync_bar_state_ii_shows_synced_from(self):
        """
        GET the post_syndication fragment — the inline sync bar for the FetLife
        projection (state ii: own CV + sync_source set) must render
        "Synced from telegram", NOT "Custom".

        Falsifiable: before Repair 1 (two-branch post inline), the FetLife projection
        in state (ii) falls into the else-branch and renders "Custom". After Repair 1
        (shared three-state partial), it renders "Synced from telegram".
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # State (ii) must render "Synced from" (with the source platform name)
        self.assertIn(
            "Synced from",
            content,
            "Post inline sync bar for state-(ii) projection (own CV + sync_source set) "
            "must show 'Synced from' — not 'Custom'. Before Repair 1 it incorrectly "
            "fell into the else-branch and showed 'Custom'.",
        )

        # The source platform (telegram) must be named
        self.assertIn(
            "telegram",
            content,
            "Post inline sync bar must name the source platform 'telegram' for state-(ii) "
            "projection synced from telegram",
        )

        # "Custom" (amber badge) must NOT appear — the projection is NOT detached
        custom_badge_marker = 'text-amber-300/70">Custom'
        self.assertNotIn(
            custom_badge_marker,
            content,
            "Post inline sync bar must NOT show 'Custom' badge for a state-(ii) projection "
            "(own CV + sync_source set). The projection is synced from a peer, not detached.",
        )
