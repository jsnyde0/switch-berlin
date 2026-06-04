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
        self.fl_proj = _make_listing_projection(
            self.conn_fetlife, self.event, self.fl_cv, sync_source=self.source_proj
        )
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
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife, self.post, self.fl_cv, sync_source=self.tg_proj
        )
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
        self.fl_proj = _make_listing_projection(
            self.conn_fetlife, self.event, self.fl_cv, sync_source=self.switch_proj
        )

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
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife, self.post, self.fl_cv, sync_source=self.tg_proj
        )
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
        self.fl_proj = _make_listing_projection(
            self.conn_fetlife, self.event, self.fl_cv, sync_source=None
        )
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
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife, self.post, self.fl_cv, sync_source=None
        )
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
