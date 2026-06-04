"""
TDD tests for the per-channel sync mechanism (kb-ide0.4).

Contract groups:
(A) sync_source model field — nullable self-FK on PlatformProjection
(B) sync_from service — snapshot copy + persisted sync_source pointer
(C) detach — editing clears sync_source (no confirm needed)
(D) re-sync — fires cycle-guard raise before copy_from
(E) cycle guard — backend enforced: source whose sync_source is non-null raises
(F) snapshot-no-propagation — editing SOURCE after downstream synced does NOT
    change downstream content
(G) three render states — template renders correct indicator per state
(H) post composer Source anchor — restored as first tab (ADR-010 D1)
(I) sync endpoint — version_copy_from sets sync_source; cycle guard enforced

Assertions on response.content (NOT response.context — hollow per memory).
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
        start=timezone.now(),
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_canonical_cv(event):
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


def _make_projection(conn, event, cv, kind="listing"):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=kind,
        status=PlatformProjection.Status.DRAFT,
        source_event=event,
        content_version=cv,
    )


# ---------------------------------------------------------------------------
# (A) Model field — sync_source nullable self-FK
# ---------------------------------------------------------------------------


class SyncSourceModelFieldTest(TestCase):
    """PlatformProjection.sync_source is a nullable self-FK."""

    def setUp(self):
        self.profile = Profile.objects.create(name="Sync Test Org", slug="sync-test-org")
        self.event = Event.objects.create(
            title="Sync Test Event",
            slug="sync-test-event",
            start=timezone.now(),
        )
        self.cv = _make_canonical_cv(self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-test-user",
            kinds=["listing", "promotion"],
        )

    def test_sync_source_field_exists_and_defaults_to_null(self):
        """sync_source must be nullable and default to None."""
        proj = _make_projection(self.conn_switch, self.event, self.cv)
        fetched = PlatformProjection.objects.get(pk=proj.pk)
        self.assertIsNone(fetched.sync_source)

    def test_sync_source_can_be_set_to_another_projection(self):
        """sync_source can point at another PlatformProjection (self-FK)."""
        source = _make_projection(self.conn_switch, self.event, self.cv)
        # Make an independent CV for the target
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fetlife-copy",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        target = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
            sync_source=source,
        )
        fetched = PlatformProjection.objects.select_related("sync_source").get(pk=target.pk)
        self.assertEqual(fetched.sync_source, source)

    def test_sync_source_set_null_on_source_delete(self):
        """sync_source uses on_delete=SET_NULL — deleting the source nulls the pointer."""
        source = _make_projection(self.conn_switch, self.event, self.cv)
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fetlife-copy-2",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        target = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
            sync_source=source,
        )
        # Delete the source projection — target.sync_source should become NULL
        source_pk = source.pk
        # We need to first remove the source's content_version reference constraints
        # The source projection itself doesn't have a sync_source, so we can delete it.
        # But source's content_version is the canonical CV shared by multiple projections —
        # deleting source projection leaves the canonical CV intact.
        source.delete()
        target.refresh_from_db()
        self.assertIsNone(target.sync_source)
        self.assertIsNone(target.sync_source_id)


# ---------------------------------------------------------------------------
# (B) sync_from service — snapshot + persisted pointer
# ---------------------------------------------------------------------------


class SyncFromServiceTest(TestCase):
    """
    sync_projection_from(user, target_projection, source_projection) service:
    - copies source's current content_version into target (independent row)
    - sets target.sync_source = source_projection
    - does NOT propagate future source edits (snapshot semantics)
    """

    def setUp(self):
        self.user = _make_user(username="sync_svc_user", email="sync_svc@test.com", password="pw")
        self.profile = _make_profile("Sync Svc Org", "sync-svc-org", user=self.user)
        self.event = _make_event(self.profile, "Sync Svc Event", "sync-svc-event")
        # _make_event already creates an EventOrganizer; no second creation needed
        self.cv = _make_canonical_cv(self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-sync-svc",
            kinds=["listing", "promotion"],
        )
        self.source_proj = _make_projection(self.conn_switch, self.event, self.cv)
        # Give source a non-null body so we can detect the copy
        self.cv.body = "Switch canonical body"
        self.cv.save(update_fields=["body", "updated_at"])

    def _target_proj(self):
        """Create a fresh independent target projection with its own CV."""
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fetlife-target",
            body="Original fetlife content",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        return PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
        )

    def test_sync_from_copies_content_to_target(self):
        """After sync_projection_from, target's content_version body matches source."""
        from syndication.services import sync_projection_from

        target = self._target_proj()
        sync_projection_from(user=self.user, target=target, source=self.source_proj)
        target.refresh_from_db()
        target.content_version.refresh_from_db()
        self.assertEqual(target.content_version.body, "Switch canonical body")

    def test_sync_from_sets_sync_source_on_target(self):
        """After sync_projection_from, target.sync_source == source_proj."""
        from syndication.services import sync_projection_from

        target = self._target_proj()
        sync_projection_from(user=self.user, target=target, source=self.source_proj)
        target.refresh_from_db()
        self.assertEqual(target.sync_source_id, self.source_proj.pk)

    def test_sync_from_creates_independent_copy(self):
        """The new content_version is a NEW row, not the same object as source."""
        from syndication.services import sync_projection_from

        target = self._target_proj()
        original_source_cv_pk = self.source_proj.content_version_id
        sync_projection_from(user=self.user, target=target, source=self.source_proj)
        target.refresh_from_db()
        self.assertNotEqual(target.content_version_id, original_source_cv_pk)


# ---------------------------------------------------------------------------
# (C) Detach — editing clears sync_source
# ---------------------------------------------------------------------------


class DetachOnSyncSourceTest(TestCase):
    """
    detach_sync_source(projection) clears sync_source without confirmation.
    Used when a user edits a synced channel.
    """

    def setUp(self):
        self.user = _make_user(username="detach_user", email="detach@test.com", password="pw")
        self.profile = _make_profile("Detach Org", "detach-org", user=self.user)
        self.event = _make_event(self.profile, "Detach Event", "detach-event")
        self.cv = _make_canonical_cv(self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-detach",
            kinds=["listing"],
        )
        self.source = _make_projection(self.conn_switch, self.event, self.cv)
        # Set up a synced target
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-copy",
            body="copied body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.target = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
            sync_source=self.source,
        )

    def test_detach_clears_sync_source(self):
        """detach_sync_source clears projection.sync_source to None."""
        from syndication.services import detach_sync_source

        detach_sync_source(self.target)
        self.target.refresh_from_db()
        self.assertIsNone(self.target.sync_source)

    def test_detach_leaves_content_version_unchanged(self):
        """detach_sync_source does NOT change the content_version (independent copy stays)."""
        from syndication.services import detach_sync_source

        original_cv_pk = self.target.content_version_id
        detach_sync_source(self.target)
        self.target.refresh_from_db()
        self.assertEqual(self.target.content_version_id, original_cv_pk)


# ---------------------------------------------------------------------------
# (D) Re-sync — cycle guard RAISES before copy_from
# ---------------------------------------------------------------------------


class ResyncCycleGuardTest(TestCase):
    """
    sync_projection_from RAISES ValueError if the source's own sync_source is
    non-null (cycle guard — backend enforced per ADR-008 D3).
    """

    def setUp(self):
        self.user = _make_user(username="cycle_user", email="cycle@test.com", password="pw")
        self.profile = _make_profile("Cycle Org", "cycle-org", user=self.user)
        self.event = _make_event(self.profile, "Cycle Event", "cycle-event")
        self.cv = _make_canonical_cv(self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-cycle",
            kinds=["listing"],
        )
        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-cycle",
            kinds=["promotion"],
        )
        self.independent_proj = _make_projection(self.conn_switch, self.event, self.cv)
        # fetlife syncs FROM switch (independent_proj)
        fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-copy",
            body="copied",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.synced_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=fl_cv,
            sync_source=self.independent_proj,
        )

    def test_cycle_guard_raises_when_source_is_itself_synced(self):
        """sync_projection_from raises ValueError if source.sync_source is non-null."""
        from syndication.services import sync_projection_from

        # Build a third target (listing) that tries to sync from synced_proj (which is already synced)
        conn_tt = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="tickettailor",
            destination_id="tt-cycle",
            kinds=["listing"],
        )
        tg_cv = ContentVersion.objects.create(
            event=self.event,
            name="tt-target",
            body="tickettailor content",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        target = PlatformProjection.objects.create(
            connection=conn_tt,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=tg_cv,
        )
        with self.assertRaises(ValueError) as ctx:
            sync_projection_from(user=self.user, target=target, source=self.synced_proj)
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_cycle_guard_allows_sync_from_independent_source(self):
        """sync_projection_from succeeds when source.sync_source IS NULL."""
        from syndication.services import sync_projection_from

        conn_tt = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="tickettailor",
            destination_id="tt-ok",
            kinds=["listing"],
        )
        tg_cv = ContentVersion.objects.create(
            event=self.event,
            name="tt-ok",
            body="tt content",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        target = PlatformProjection.objects.create(
            connection=conn_tt,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=tg_cv,
        )
        # This should NOT raise — source_proj (independent_proj) has sync_source=None
        sync_projection_from(user=self.user, target=target, source=self.independent_proj)
        target.refresh_from_db()
        self.assertEqual(target.sync_source_id, self.independent_proj.pk)


# ---------------------------------------------------------------------------
# (E) Snapshot-no-propagation — source edits don't bleed to downstream
# ---------------------------------------------------------------------------


class SnapshotNoPropagationTest(TestCase):
    """
    After sync_projection_from, editing the SOURCE's content_version does NOT
    change the downstream (synced) projection's content (no live propagation).
    """

    def setUp(self):
        self.user = _make_user(username="snapshot_user", email="snapshot@test.com", password="pw")
        self.profile = _make_profile("Snapshot Org", "snapshot-org", user=self.user)
        self.event = _make_event(self.profile, "Snapshot Event", "snapshot-event")
        self.cv = _make_canonical_cv(self.event)
        self.cv.body = "original source body"
        self.cv.save(update_fields=["body", "updated_at"])
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-snapshot",
            kinds=["listing"],
        )
        self.source = _make_projection(self.conn_switch, self.event, self.cv)
        # Create target and sync it
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-snapshot",
            body="old fetlife content",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.target = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
        )

    def test_source_edit_does_not_propagate_to_synced_downstream(self):
        """
        Editing source's CV body after a sync does NOT change target's CV body.
        This verifies snapshot semantics (no live propagation).
        """
        from syndication.services import edit_version, sync_projection_from

        # Step 1: sync target from source
        sync_projection_from(user=self.user, target=self.target, source=self.source)
        self.target.refresh_from_db()
        downstream_cv_pk = self.target.content_version_id

        # Capture synced body
        downstream_cv = ContentVersion.objects.get(pk=downstream_cv_pk)
        synced_body = downstream_cv.body

        # Step 2: edit the SOURCE's content_version
        edit_version(user=self.user, version=self.source.content_version, body="UPDATED SOURCE BODY")

        # Step 3: downstream's CV must NOT have changed
        downstream_cv.refresh_from_db()
        self.assertEqual(downstream_cv.body, synced_body)
        self.assertNotEqual(downstream_cv.body, "UPDATED SOURCE BODY")


# ---------------------------------------------------------------------------
# (F) Three render states — template assertions on response.content
# ---------------------------------------------------------------------------


class ThreeRenderStatesTemplateTest(TestCase):
    """
    The event_syndication template must render the correct state indicator for:
    (i)  sync_source IS NULL AND content_version IS the shared canonical → "Synced from canonical"
    (ii) sync_source IS NOT NULL → "Synced from <channel>"
    (iii) own content_version AND sync_source IS NULL (was once synced, now detached) → "Custom"

    Assertions on response.content, NOT response.context.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="render_state_user", email="rs@test.com", password="pw")
        self.profile = _make_profile("Render State Org", "render-state-org", user=self.user)
        self.event = _make_event(self.profile, "Render State Event", "render-state-event")
        self.cv = _make_canonical_cv(self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-rs",
            kinds=["listing", "promotion"],
        )
        self.client.force_login(self.user)

    def _get_fragment(self, event):
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": event.pk})
        return self.client.get(url)

    def test_state_i_canonical_sharing_shows_synced_indicator(self):
        """
        State (i): projection on canonical CV + sync_source NULL → shows "Synced" indicator.
        The Switch projection always starts on the canonical and has no sync_source.
        """
        _make_projection(self.conn_switch, self.event, self.cv)
        response = self._get_fragment(self.event)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Switch is on canonical → shows "Synced" indicator (the default state)
        self.assertIn("Synced", content)

    def test_state_ii_sync_source_set_shows_synced_from_channel(self):
        """
        State (ii): projection has its own CV + sync_source set → shows "Synced from <channel>".
        """
        source = _make_projection(self.conn_switch, self.event, self.cv)
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-synced",
            body="copied body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
            sync_source=source,
        )
        response = self._get_fragment(self.event)
        content = response.content.decode()
        # State (ii): FetLife is synced from Switch → shows "Synced from" label
        self.assertIn("Synced from", content)

    def test_state_iii_detached_shows_custom_indicator(self):
        """
        State (iii): own CV AND sync_source NULL (was synced, now detached) → shows "Custom".
        """
        # FetLife with its own CV but no sync_source (detached state)
        own_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-detached",
            body="custom fetlife body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=own_cv,
            sync_source=None,
        )
        response = self._get_fragment(self.event)
        content = response.content.decode()
        # State (iii): FetLife has own CV and no sync_source → shows "Custom"
        self.assertIn("Custom", content)


# ---------------------------------------------------------------------------
# (G) Post composer Source anchor — restored as first tab (ADR-010 D1)
# ---------------------------------------------------------------------------


class PostComposerSourceAnchorTest(TestCase):
    """
    The post_syndication fragment must render a "Source" anchor as the first
    tab (ADR-010 D1 — a Post has no native-home channel, so its canonical is
    an abstract 'Source' anchor). Child C dropped this; D must restore it.

    Assertions on response.content.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="post_source_user", email="ps@test.com", password="pw")
        self.profile = _make_profile("Post Source Org", "post-source-org", user=self.user)
        self.event = _make_event(self.profile, "Post Source Event", "post-source-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Test promo post",
            body="Come to our event!",
        )
        self.conn_telegram = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-ps",
            kinds=["promotion"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-ps",
            kinds=["listing", "promotion"],
        )
        self.client.force_login(self.user)

    def _get_fragment(self):
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        return self.client.get(url)

    def test_post_composer_renders_source_tab_first(self):
        """
        The post_syndication fragment must include a 'Source' tab as the
        first channel tab — the abstract canonical anchor for a Post.
        """
        response = self._get_fragment()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must have a "Source" label as a tab
        self.assertIn("Source", content)

    def test_source_tab_appears_before_other_channel_tabs(self):
        """
        The 'Source' tab appears before Telegram/FetLife tabs in the DOM.
        """
        # Create promotion projections so other channel tabs render
        post_cv, _ = ContentVersion.objects.get_or_create(
            post=self.post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
        PlatformProjection.objects.create(
            connection=self.conn_telegram,
            kind="promotion",
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=post_cv,
        )
        response = self._get_fragment()
        content = response.content.decode()
        # "Source" must appear before "telegram" in the DOM
        source_pos = content.find("Source")
        telegram_pos = content.find("telegram")
        self.assertGreater(source_pos, -1, "Source tab not found in content")
        self.assertGreater(telegram_pos, -1, "Telegram tab not found in content")
        self.assertLess(source_pos, telegram_pos, "Source tab must appear before Telegram tab")


# ---------------------------------------------------------------------------
# (H) Sync endpoint — version_copy_from sets sync_source; cycle guard
# ---------------------------------------------------------------------------


class SyncEndpointTest(TestCase):
    """
    POST to version-copy-from sets projection.sync_source to the source projection.
    Cycle guard: if the SOURCE projection has a non-null sync_source, the endpoint
    must NOT perform the copy and must return a non-200 or error response
    (the exact status/body tested via response.content).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="endpoint_user", email="endpoint@test.com", password="pw")
        self.profile = _make_profile("Endpoint Org", "endpoint-org", user=self.user)
        self.event = _make_event(self.profile, "Endpoint Event", "endpoint-event")
        self.cv = _make_canonical_cv(self.event)
        self.cv.body = "source body text"
        self.cv.save(update_fields=["body", "updated_at"])
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-ep",
            kinds=["listing", "promotion"],
        )
        self.source_proj = _make_projection(self.conn_switch, self.event, self.cv)
        target_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-ep-target",
            body="old fl content",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.target_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind="listing",
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=target_cv,
        )
        self.client.force_login(self.user)

    def _url(self, pk):
        return reverse("syndication:version-copy-from", kwargs={"pk": pk})

    def test_copy_from_endpoint_sets_sync_source(self):
        """
        POST to version-copy-from with source_projection_pk sets target.sync_source.
        """
        response = self.client.post(
            self._url(self.target_proj.pk),
            {"source_projection_pk": self.source_proj.pk},
        )
        # Should redirect or return fragment (200 on HTMX, redirect on plain)
        self.assertIn(response.status_code, [200, 302])
        self.target_proj.refresh_from_db()
        self.assertEqual(self.target_proj.sync_source_id, self.source_proj.pk)

    def test_copy_from_endpoint_cycle_guard_rejects_synced_source(self):
        """
        POST to version-copy-from where source has sync_source set must fail
        (cycle guard — backend enforced, ADR-008 D3).
        The endpoint must surface an error — not silently sync from a chained source.
        """
        # Make source_proj itself synced (non-null sync_source)
        self.source_proj.sync_source = self.source_proj  # self-reference not realistic
        # More realistic: make a third projection the source's source
        third_cv = ContentVersion.objects.create(
            event=self.event,
            name="third-cv",
            body="third body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        conn_tt = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="tickettailor",
            destination_id="tt-ep",
            kinds=["listing"],
        )
        third_proj = _make_projection(conn_tt, self.event, third_cv)
        # Mark source_proj as synced FROM third_proj
        self.source_proj.sync_source = third_proj
        self.source_proj.save(update_fields=["sync_source", "updated_at"])

        response = self.client.post(
            self._url(self.target_proj.pk),
            {"source_projection_pk": self.source_proj.pk},
        )
        # Cycle guard: endpoint must NOT have set sync_source on target to the chained source.
        self.target_proj.refresh_from_db()
        # The target's sync_source must remain None (the sync was rejected)
        self.assertIsNone(self.target_proj.sync_source_id)
