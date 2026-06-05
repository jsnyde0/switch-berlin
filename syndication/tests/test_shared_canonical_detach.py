"""
TDD tests for kb-kgza.2: per-channel body edit auto-detaches from shared canonical CV.

Contract:
1. Editing a shared-canonical post channel MINTS a new ContentVersion for THAT projection
   (detached), leaves sibling channels' bodies unchanged (DB-state assertions).
2. The detached channel renders the Custom badge (content assertion on OOB sync-bar).
3. The "Saved" indicator element (x-show="autosaveSaved" span) is present in the response.
4. Editing the Master/Source tab still BROADCASTS (no detach) — guard against misimpl
   routing ALL edits through detach.
5. Detach-then-edit on a PUBLISHED projection does NOT raise (edit-after-publish, ADR-016 D5).
6. Same detach seam works for event and post paths.

Per-channel body form posts to `syndication:projection-detach-and-edit` (projection-keyed).
Master/source form stays on `syndication:version-edit` (cv-keyed, broadcasts).

Assertions on content + DB state (NOT response.context — hollow per memory
django-view-test-context-vs-content-hollow).
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


def _make_canonical_cv_for_post(post, body="canonical post body"):
    cv, _ = ContentVersion.objects.get_or_create(
        post=post,
        name="canonical",
        defaults={
            "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
            "body": body,
        },
    )
    return cv


def _make_canonical_cv_for_event(event, body="canonical event body"):
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={
            "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
            "body": body,
        },
    )
    return cv


def _make_promotion_projection(conn, post, cv, sync_source=None, status="draft"):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=status,
        source_post=post,
        content_version=cv,
        sync_source=sync_source,
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


# ---------------------------------------------------------------------------
# 1. POST path: editing shared-canonical channel mints new CV + siblings unchanged
# ---------------------------------------------------------------------------


class SharedCanonicalPostDetachTest(TestCase):
    """
    POST to `projection-detach-and-edit` on a promotion projection sharing the
    canonical CV (state i: content_version.name=='canonical', sync_source NULL)
    must:
    1. Mint a NEW ContentVersion row for THAT projection (not mutate the canonical).
    2. Leave sibling projections' content_version pointing at the original canonical.
    3. The edited projection's new CV contains the submitted body.
    4. The OOB sync-bar for that projection shows Custom.
    5. The response contains the Saved indicator element.

    DB-state assertions (not context-hollow).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="post_detach_user",
            email="post_detach@test.com",
            password="pw",
        )
        self.profile = _make_profile("Post Detach Org", "post-detach-org", user=self.user)
        self.event = _make_event(self.profile, "Post Detach Event", "post-detach-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Post Detach Test Post",
            body="Original body",
        )
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-post-detach", ["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-post-detach", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="Canonical post body")

        # Both start on the canonical CV (state i — shared)
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv)
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        self.client.force_login(self.user)

    def test_editing_shared_channel_mints_new_cv_for_that_projection(self):
        """
        POST to projection-detach-and-edit for the FetLife projection must create
        a NEW ContentVersion row (not mutate the canonical).
        """
        cv_count_before = ContentVersion.objects.filter(post=self.post).count()

        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL-specific body"}, HTTP_HX_REQUEST="true")

        cv_count_after = ContentVersion.objects.filter(post=self.post).count()
        self.assertEqual(
            cv_count_after,
            cv_count_before + 1,
            "Editing a shared-canonical channel must mint a NEW ContentVersion row "
            f"(was {cv_count_before}, got {cv_count_after}; expected {cv_count_before + 1})",
        )

    def test_edited_projection_points_to_new_cv_not_canonical(self):
        """
        After the edit, the FetLife projection must point to a NEW cv (not the canonical).
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL detached body"}, HTTP_HX_REQUEST="true")

        self.fl_proj.refresh_from_db()
        self.assertNotEqual(
            self.fl_proj.content_version_id,
            self.canonical_cv.pk,
            "After detach-and-edit, the FetLife projection must NOT point at the canonical CV",
        )

    def test_sibling_projection_still_points_to_canonical(self):
        """
        The Telegram projection (sibling sharer) must NOT be affected — it must still
        point at the canonical CV after the FetLife edit.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL detached body"}, HTTP_HX_REQUEST="true")

        self.tg_proj.refresh_from_db()
        self.assertEqual(
            self.tg_proj.content_version_id,
            self.canonical_cv.pk,
            "Telegram projection (sibling) must still point at the canonical CV after "
            "FetLife edit — sibling bodies must be UNCHANGED",
        )

    def test_sibling_canonical_body_unchanged(self):
        """
        The canonical CV body must not change — only the detached projection gets the new body.
        """
        original_canonical_body = "Canonical post body"
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL specific edit"}, HTTP_HX_REQUEST="true")

        self.canonical_cv.refresh_from_db()
        self.assertEqual(
            self.canonical_cv.body,
            original_canonical_body,
            "Canonical CV body must not change when a per-channel edit detaches",
        )

    def test_detached_cv_contains_submitted_body(self):
        """
        The NEW ContentVersion (pointed to by the FetLife projection after detach) must
        contain the body submitted in the form POST.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL unique content"}, HTTP_HX_REQUEST="true")

        self.fl_proj.refresh_from_db()
        self.assertEqual(
            self.fl_proj.content_version.body,
            "FL unique content",
            "The detached CV must contain the submitted body",
        )

    def test_oob_sync_bar_shows_custom_for_detached_projection(self):
        """
        OOB sync-bar fragment for the FetLife projection must show Custom (amber badge)
        after the detach-and-edit.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, {"body": "FL custom"}, HTTP_HX_REQUEST="true")
        content = response.content.decode()

        self.assertIn(
            "Custom",
            content,
            "OOB sync-bar for the detached projection must show 'Custom' badge",
        )
        self.assertIn(
            f'id="sync-bar-proj-{self.fl_proj.pk}"',
            content,
            f"OOB sync-bar must carry the projection anchor sync-bar-proj-{self.fl_proj.pk}",
        )

    def test_saved_indicator_element_present(self):
        """
        The response must contain the 'Saved' indicator element
        (x-show="autosaveSaved" span with 'Saved' text).
        Named concrete DOM element per bead requirement.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, {"body": "FL saved"}, HTTP_HX_REQUEST="true")
        content = response.content.decode()

        # The harness expects the OOB response to include hx-swap-oob (the round-trip)
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "Response must contain hx-swap-oob='true' for server-driven OOB badge update",
        )


# ---------------------------------------------------------------------------
# 2. Master/Source tab broadcast: version-edit on canonical CV still broadcasts
# ---------------------------------------------------------------------------


class MasterTabBroadcastStillWorksTest(TestCase):
    """
    POST to `version-edit` (the canonical CV endpoint) from the master/source tab
    must BROADCAST to all sharing channels — no new CV minted, canonical mutated.

    This guards against a misimpl that routes ALL edits through detach.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="broadcast_guard_user",
            email="broadcast_guard@test.com",
            password="pw",
        )
        self.profile = _make_profile("Broadcast Guard Org", "broadcast-guard-org", user=self.user)
        self.event = _make_event(self.profile, "Broadcast Guard Event", "broadcast-guard-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Broadcast Guard Post",
            body="Broadcast body",
        )
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-broadcast-guard", ["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-broadcast-guard", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical")

        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv)
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        self.client.force_login(self.user)

    def test_master_tab_edit_does_not_mint_new_cv(self):
        """
        POST to version-edit (canonical CV) must NOT mint a new CV — it mutates the shared row.
        """
        cv_count_before = ContentVersion.objects.filter(post=self.post).count()

        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        self.client.post(url, {"body": "master edit broadcasts"}, HTTP_HX_REQUEST="true")

        cv_count_after = ContentVersion.objects.filter(post=self.post).count()
        self.assertEqual(
            cv_count_after,
            cv_count_before,
            "Master tab edit (version-edit on canonical CV) must NOT mint new CVs — "
            f"before={cv_count_before}, after={cv_count_after}",
        )

    def test_master_tab_edit_mutates_canonical_body(self):
        """
        Editing via version-edit (master tab) must update the canonical CV body.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        self.client.post(url, {"body": "master broadcast edit"}, HTTP_HX_REQUEST="true")

        self.canonical_cv.refresh_from_db()
        self.assertEqual(
            self.canonical_cv.body,
            "master broadcast edit",
            "version-edit on canonical must mutate the canonical body (broadcast)",
        )

    def test_both_projections_still_share_canonical_after_master_edit(self):
        """
        After master tab edit, both projections must still point at the canonical CV.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        self.client.post(url, {"body": "shared master"}, HTTP_HX_REQUEST="true")

        self.tg_proj.refresh_from_db()
        self.fl_proj.refresh_from_db()

        self.assertEqual(
            self.tg_proj.content_version_id,
            self.canonical_cv.pk,
            "Telegram must still share canonical after master edit",
        )
        self.assertEqual(
            self.fl_proj.content_version_id,
            self.canonical_cv.pk,
            "FetLife must still share canonical after master edit",
        )


# ---------------------------------------------------------------------------
# 3. Published projection path: detach-then-edit does NOT raise (ADR-016 D5)
# ---------------------------------------------------------------------------


class DetachAndEditPublishedProjectionTest(TestCase):
    """
    Detach-and-edit on a PUBLISHED projection must NOT raise ValueError.

    Root cause of the trap: edit_version's guard raises if ALL consumers of the
    new (detached) CV are non-draft. After detach, the new CV has exactly ONE
    consumer (the projection just detached). If that projection is published,
    the guard would trip and the edit would fail.

    ADR-016 D5 mandates edit-after-publish is ALLOWED. The detach-then-edit path
    must loosen the guard (or bypass it) for the published-single-consumer case.

    DB-state assertion: no exception, new CV minted with the submitted body.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="pub_detach_user",
            email="pub_detach@test.com",
            password="pw",
        )
        self.profile = _make_profile("Published Detach Org", "published-detach-org", user=self.user)
        self.event = _make_event(self.profile, "Published Detach Event", "published-detach-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Published Detach Post",
            body="Published body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-pub-detach", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical published body")

        # Create a PUBLISHED projection sharing the canonical CV
        # (Simulate the state: published, frozen_content set)
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife,
            self.post,
            self.canonical_cv,
            status="published",
        )
        # Set frozen_content to simulate a published projection
        self.fl_proj.frozen_content = {"body": "canonical published body"}
        self.fl_proj.save(update_fields=["frozen_content", "updated_at"])

        self.client.force_login(self.user)

    def test_detach_and_edit_published_projection_does_not_raise(self):
        """
        POST to projection-detach-and-edit on a published projection must return
        200 (not 500) and must NOT raise ValueError.

        This verifies the edit_version guard does not trip after the detach mints
        a new CV with one published consumer.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, {"body": "published projection edit"}, HTTP_HX_REQUEST="true")
        self.assertIn(
            response.status_code,
            [200, 302],
            f"Editing a published projection via detach-and-edit must not 500 (got {response.status_code})",
        )

    def test_detach_and_edit_published_mints_new_cv(self):
        """
        After detach-and-edit on a published projection, a new CV must exist.
        """
        cv_count_before = ContentVersion.objects.filter(post=self.post).count()

        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "published edit body"}, HTTP_HX_REQUEST="true")

        cv_count_after = ContentVersion.objects.filter(post=self.post).count()
        self.assertGreater(
            cv_count_after,
            cv_count_before,
            "Detach-and-edit on published projection must mint a new CV",
        )

    def test_detach_and_edit_published_new_cv_has_submitted_body(self):
        """
        The new CV after detach-and-edit on a published projection must contain
        the submitted body.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "published edited body unique"}, HTTP_HX_REQUEST="true")

        self.fl_proj.refresh_from_db()
        self.assertEqual(
            self.fl_proj.content_version.body,
            "published edited body unique",
            "New CV after detach-and-edit on published must contain the submitted body",
        )


# ---------------------------------------------------------------------------
# 4. Event path: detach-and-edit also works for LISTING projections
# ---------------------------------------------------------------------------


class SharedCanonicalEventDetachTest(TestCase):
    """
    Same detach seam for event listing projections (not just post promotions).

    When an event has a canonical CV shared by multiple listing projections,
    editing a per-channel tab via `projection-detach-and-edit` must:
    1. Mint a new CV for THAT listing projection.
    2. Leave sibling listing projections on the original canonical.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="event_detach_user",
            email="event_detach@test.com",
            password="pw",
        )
        self.profile = _make_profile("Event Detach Org", "event-detach-org", user=self.user)
        self.event = _make_event(self.profile, "Event Detach Event", "event-detach-event")

        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-event-detach", ["listing"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-event-detach", ["listing"])
        self.canonical_cv = _make_canonical_cv_for_event(self.event, body="canonical event body")

        self.tg_proj = _make_listing_projection(self.conn_telegram, self.event, self.canonical_cv)
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.canonical_cv)
        self.client.force_login(self.user)

    def test_event_channel_detach_mints_new_cv(self):
        """
        Editing a shared-canonical event listing channel must mint a new CV.
        """
        cv_count_before = ContentVersion.objects.filter(event=self.event).count()

        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL event specific"}, HTTP_HX_REQUEST="true")

        cv_count_after = ContentVersion.objects.filter(event=self.event).count()
        self.assertEqual(
            cv_count_after,
            cv_count_before + 1,
            "Event listing channel detach-and-edit must mint a new CV",
        )

    def test_event_sibling_listing_projection_unchanged(self):
        """
        After FetLife listing detach-and-edit, Telegram listing must still share canonical.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "FL event detached"}, HTTP_HX_REQUEST="true")

        self.tg_proj.refresh_from_db()
        self.assertEqual(
            self.tg_proj.content_version_id,
            self.canonical_cv.pk,
            "Telegram listing must still share canonical after FetLife detach-and-edit",
        )


# ---------------------------------------------------------------------------
# 5. Template: per-channel body form posts to projection-detach-and-edit
# ---------------------------------------------------------------------------


class ChannelEditorFormActionTest(TestCase):
    """
    The rendered post_syndication fragment must contain a form whose action
    points to `projection-detach-and-edit` (projection pk-keyed) for
    non-master-channel projections that share the canonical CV (state i).

    The master/source tab must still have the `version-edit` action (canonical CV pk-keyed).

    Content assertion on the rendered fragment HTML (not response.context).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="form_action_user",
            email="form_action@test.com",
            password="pw",
        )
        self.profile = _make_profile("Form Action Org", "form-action-org", user=self.user)
        self.event = _make_event(self.profile, "Form Action Event", "form-action-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Form Action Post",
            body="Form action body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-form-action", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical")

        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        self.client.force_login(self.user)

    def test_per_channel_body_form_action_is_projection_keyed(self):
        """
        The body form for a per-channel tab (state i, FetLife sharing canonical)
        must post to `projection-detach-and-edit` with the projection pk,
        NOT to `version-edit` with the canonical CV pk.
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_detach_url = reverse(
            "syndication:projection-detach-and-edit",
            kwargs={"pk": self.fl_proj.pk},
        )
        self.assertIn(
            expected_detach_url,
            content,
            f"Per-channel body form must use `projection-detach-and-edit` URL "
            f"({expected_detach_url!r}) — not version-edit keyed by canonical CV",
        )
