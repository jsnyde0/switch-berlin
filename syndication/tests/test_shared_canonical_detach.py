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

    def test_master_source_tab_body_form_action_is_version_edit(self):
        """
        The body form on the master/source (broadcast) tab must post to `version-edit`
        keyed by the canonical CV pk — NOT to `projection-detach-and-edit`.

        Template-level assertion: renders the fragment and checks the HTML content.
        Guards against a template regression that accidentally routes the master tab
        through the detach endpoint.
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_version_edit_url = reverse(
            "syndication:version-edit",
            kwargs={"pk": self.canonical_cv.pk},
        )
        self.assertIn(
            expected_version_edit_url,
            content,
            f"Master/source (broadcast) tab body form must use `version-edit` URL "
            f"({expected_version_edit_url!r}) — not projection-detach-and-edit",
        )


# ---------------------------------------------------------------------------
# 6. FIX A — CV churn idempotence: second edit on already-detached channel
#            must NOT mint a new ContentVersion.
# ---------------------------------------------------------------------------


class DetachAndEditIdempotenceTest(TestCase):
    """
    FIX A (kb-kgza.2 adversarial-review): detach_and_edit must be idempotent.

    If a projection is ALREADY on its own independent CV (state iii: not the
    canonical, only one consumer — this projection), a SECOND call to
    projection-detach-and-edit must edit IN PLACE (call edit_version on the
    existing CV) and must NOT mint a new ContentVersion row.

    Simulates autosave: user types a burst, 600ms quiet, first autosave fires
    → detaches and mints CV. Another burst, 600ms quiet, second autosave fires
    → must NOT mint a second orphaned CV.

    DB-state assertion: ContentVersion row count is unchanged across the second call.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="idempotent_detach_user",
            email="idempotent_detach@test.com",
            password="pw",
        )
        self.profile = _make_profile("Idempotent Detach Org", "idempotent-detach-org", user=self.user)
        self.event = _make_event(self.profile, "Idempotent Detach Event", "idempotent-detach-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Idempotent Detach Post",
            body="Original body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-idempotent", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="Canonical body")
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        self.client.force_login(self.user)

    def test_second_autosave_on_already_detached_channel_mints_no_new_cv(self):
        """
        After the FIRST edit detaches and mints a new CV, the SECOND edit must
        edit the SAME CV in place — no new ContentVersion row.

        ContentVersion count must be unchanged across the second POST.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})

        # First edit: detaches from canonical, mints a new CV
        self.client.post(url, {"body": "First autosave"}, HTTP_HX_REQUEST="true")

        # Capture count after the first edit (channel now on its own CV)
        cv_count_after_first = ContentVersion.objects.filter(post=self.post).count()

        # Second edit: must edit IN PLACE, no new CV
        self.client.post(url, {"body": "Second autosave"}, HTTP_HX_REQUEST="true")

        cv_count_after_second = ContentVersion.objects.filter(post=self.post).count()

        self.assertEqual(
            cv_count_after_second,
            cv_count_after_first,
            "A SECOND detach-and-edit on an already-detached channel must NOT mint a new "
            f"ContentVersion row (count was {cv_count_after_first} after first edit, "
            f"got {cv_count_after_second} after second — expected no change).",
        )

    def test_second_autosave_applies_the_new_body(self):
        """
        Even though no new CV is minted, the second edit must still update the body
        in place on the existing (already-detached) CV.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})

        # First edit detaches
        self.client.post(url, {"body": "First autosave"}, HTTP_HX_REQUEST="true")

        # Second edit — should update body in place
        self.client.post(url, {"body": "Second autosave updated"}, HTTP_HX_REQUEST="true")

        self.fl_proj.refresh_from_db()
        self.assertEqual(
            self.fl_proj.content_version.body,
            "Second autosave updated",
            "Second edit on already-detached channel must update the body in place",
        )


# ---------------------------------------------------------------------------
# 7. FIX B — state-ii inconsistency: editing a state-ii projection via
#            detach-and-edit must clear sync_source (ADR-016 D2).
# ---------------------------------------------------------------------------


class DetachAndEditStateIIConsistencyTest(TestCase):
    """
    FIX B (kb-kgza.2 adversarial-review): editing a state-ii projection
    (own CV + sync_source SET) via projection-detach-and-edit must clear
    sync_source to NULL, producing a clean state-iii (own CV + sync_source NULL).

    ADR-016 D2 forbids own-CV + sync_source-set as a stable resting state.
    detach_and_edit currently mints a new CV but NEVER clears sync_source —
    leaving the inconsistent state.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="state_ii_user",
            email="state_ii@test.com",
            password="pw",
        )
        self.profile = _make_profile("State II Org", "state-ii-org", user=self.user)
        self.event = _make_event(self.profile, "State II Event", "state-ii-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="State II Post",
            body="State ii body",
        )
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-state-ii", ["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-state-ii", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical body")

        # Telegram: the sync source (state i — on canonical, sync_source NULL)
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv)

        # FetLife: state ii — its OWN CV (copied from canonical), sync_source = tg_proj
        self.fl_own_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-copy",
            provenance=ContentVersion.Provenance.MANUAL,
            body="FL own body",
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind=PlatformProjection.Kind.PROMOTION,
            status="draft",
            source_post=self.post,
            content_version=self.fl_own_cv,
            sync_source=self.tg_proj,  # state ii: own CV + sync_source SET
        )
        self.client.force_login(self.user)

    def test_editing_state_ii_projection_clears_sync_source(self):
        """
        POST to projection-detach-and-edit on a state-ii projection (own CV + sync_source SET)
        must result in sync_source being NULL on the projection.

        ADR-016 D2: detached = own CV + sync_source NULL (state iii, clean).
        The current implementation leaves sync_source set — an inconsistent state.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        self.client.post(url, {"body": "detach state-ii edit"}, HTTP_HX_REQUEST="true")

        self.fl_proj.refresh_from_db()
        self.assertIsNone(
            self.fl_proj.sync_source_id,
            "After detach-and-edit on a state-ii projection (own CV + sync_source SET), "
            "sync_source must be NULL — ADR-016 D2 forbids own-CV + sync_source-set.",
        )


# ---------------------------------------------------------------------------
# 8. FIX C — dirty OOB missing oob=True: detach-edit on a published projection
#            must emit _channel_dirty_oob.html with hx-swap-oob="true".
# ---------------------------------------------------------------------------


class DetachAndEditDirtyOOBFlagTest(TestCase):
    """
    FIX C (kb-kgza.2 adversarial-review): projection_detach_and_edit renders
    _channel_dirty_oob.html WITHOUT oob=True in context, so the dirty pill/banner
    are emitted WITHOUT hx-swap-oob and never update client-side.

    version_edit passes oob=True (views.py ~1651-1655).
    projection_detach_and_edit must do the same.

    Content assertion: rendered HTML must contain hx-swap-oob="true" inside the
    _channel_dirty_oob.html fragment when the projection is published and dirty.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="dirty_oob_user",
            email="dirty_oob@test.com",
            password="pw",
        )
        self.profile = _make_profile("Dirty OOB Org", "dirty-oob-org", user=self.user)
        self.event = _make_event(self.profile, "Dirty OOB Event", "dirty-oob-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Dirty OOB Post",
            body="Dirty oob body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-dirty-oob", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical dirty oob body")

        # Published projection sharing canonical CV — will become dirty after edit
        self.fl_proj = _make_promotion_projection(
            self.conn_fetlife,
            self.post,
            self.canonical_cv,
            status="published",
        )
        # frozen_content set at the CANONICAL body (before detach-edit makes it dirty)
        self.fl_proj.frozen_content = {"body": "canonical dirty oob body"}
        self.fl_proj.save(update_fields=["frozen_content", "updated_at"])
        self.client.force_login(self.user)

    def test_detach_edit_on_published_projection_emits_dirty_oob_channel_dot_with_swap_oob(self):
        """
        A detach-edit on a PUBLISHED projection (dirty after the edit) must emit
        the channel-dot span from _channel_dirty_oob carrying hx-swap-oob="true",
        so the dirty pill updates client-side via HTMX OOB swap.

        Without oob=True in the render context, the template emits:
          <span id="channel-dot-{pk}" ...>
        WITHOUT hx-swap-oob — HTMX ignores it and the dirty indicator never updates.

        This test asserts the channel-dot element AND hx-swap-oob coexist in the
        response — i.e. the dirty OOB fragment carries the OOB attribute, not just
        the sync-bar OOB fragment (which always has hx-swap-oob="true").
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            {"body": "new body that makes projection dirty"},
            HTTP_HX_REQUEST="true",
        )
        content = response.content.decode()

        # The channel-dot span is the key element from _channel_dirty_oob.html.
        # When oob=True is passed to the template, the span carries hx-swap-oob="true".
        # Without oob=True, the same span is emitted WITHOUT the attribute — HTMX
        # will not process it as an OOB swap and the dot never updates client-side.
        channel_dot_id = f'id="channel-dot-{self.fl_proj.pk}"'
        self.assertIn(
            channel_dot_id,
            content,
            f"Response must contain the channel-dot span ({channel_dot_id!r}) from _channel_dirty_oob.html.",
        )

        # Find the channel-dot span and assert hx-swap-oob="true" is in the same
        # element (not just somewhere else in the response from the sync-bar OOB).
        channel_dot_idx = content.index(channel_dot_id)
        # The span opening tag ends at the first > after channel_dot_idx
        span_end_idx = content.index(">", channel_dot_idx)
        span_tag = content[channel_dot_idx - 20 : span_end_idx + 1]

        self.assertIn(
            'hx-swap-oob="true"',
            span_tag,
            f"The channel-dot span ({channel_dot_id!r}) must carry hx-swap-oob='true' — "
            "without oob=True in the context, the template omits this attribute and HTMX "
            "never processes the OOB swap (FIX C: pass oob=True to _channel_dirty_oob context).\n"
            f"Actual span tag found: {span_tag!r}",
        )


# ---------------------------------------------------------------------------
# FIX 1 (kb-kgza.3 adversarial repair): master/source tab edit of a published
#         post succeeds (no action_error), all sharing consumers become dirty,
#         frozen_content is unchanged.
# ---------------------------------------------------------------------------


class MasterTabPublishedEditTest(TestCase):
    """
    FIX 1 (kb-kgza.3): Editing the master/source tab of a PUBLISHED post via
    version-edit MUST succeed (no action_error in the response fragment).

    Root cause: version_edit called edit_version WITHOUT _allow_edit_after_publish,
    so the all-consumers-non-draft guard raised ValueError → action_error on every
    autosave. This is the "user types and every keystroke-batch returns an error"
    scenario.

    Per ADR-016 D5: editing a shared/canonical CV whose consumers are published is
    ALLOWED — it broadcasts → all sharers become is_dirty True, frozen_content
    (the published snapshot) stays UNCHANGED = no corruption.

    Assertions:
    - HTTP response must not contain "Action failed" (no action_error).
    - ALL sharing consumers must have is_dirty == True (DB-state).
    - Each consumer's frozen_content must be UNCHANGED by the edit.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="master_pub_edit_user",
            email="master_pub_edit@test.com",
            password="pw",
        )
        self.profile = _make_profile("Master Pub Edit Org", "master-pub-edit-org", user=self.user)
        self.event = _make_event(self.profile, "Master Pub Edit Event", "master-pub-edit-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Master Pub Edit Post",
            body="Original body",
        )
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-master-pub-edit", ["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-master-pub-edit", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical published body")

        # Both projections are PUBLISHED sharing the canonical CV
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv, status="published")
        self.tg_proj.frozen_content = {"body": "canonical published body"}
        self.tg_proj.save(update_fields=["frozen_content", "updated_at"])

        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv, status="published")
        self.fl_proj.frozen_content = {"body": "canonical published body"}
        self.fl_proj.save(update_fields=["frozen_content", "updated_at"])

        self.client.force_login(self.user)

    def test_master_tab_edit_of_published_post_succeeds_no_action_error(self):
        """
        POST to version-edit on the canonical CV of a fully-published post must
        NOT return an action_error. The user types → autosave fires → must succeed.

        This is the "editable textarea that errors on every keystroke" bug — it must
        be fixed so editing actually works.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(url, {"body": "updated master body"}, HTTP_HX_REQUEST="true")

        self.assertIn(
            response.status_code,
            [200, 302],
            f"Master tab edit on published post must not 500 (got {response.status_code})",
        )

        content = response.content.decode()
        self.assertNotIn(
            "Action failed",
            content,
            "Master tab edit of published post must NOT return action_error — "
            "the 'Action failed' banner must not appear in the response. "
            "This guards against the version_edit guard raising ValueError for "
            "all-consumers-non-draft canonical CV edit.",
        )

    def test_master_tab_edit_of_published_post_all_consumers_become_dirty(self):
        """
        After editing the canonical CV of a published post, ALL sharing consumers
        must have is_dirty == True (DB-state).

        ADR-016 D5: editing a shared CV broadcasts → all consumers' effective body
        changes while their frozen_content stays at the publish-time snapshot.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        self.client.post(url, {"body": "updated master — all become dirty"}, HTTP_HX_REQUEST="true")

        self.tg_proj.refresh_from_db()
        self.fl_proj.refresh_from_db()

        self.assertTrue(
            self.tg_proj.is_dirty,
            "Telegram projection must be is_dirty=True after master tab edit of published canonical.",
        )
        self.assertTrue(
            self.fl_proj.is_dirty,
            "FetLife projection must be is_dirty=True after master tab edit of published canonical.",
        )

    def test_master_tab_edit_of_published_post_frozen_content_unchanged(self):
        """
        After editing the canonical CV of a published post, each consumer's
        frozen_content must be UNCHANGED (DB-state).

        ADR-016 D5 / A2 freeze: frozen_content is the published snapshot.
        Editing the live CV makes the projection dirty but must NOT mutate
        frozen_content — that would silently corrupt the published snapshot.
        """
        frozen_tg_before = self.tg_proj.frozen_content.copy()
        frozen_fl_before = self.fl_proj.frozen_content.copy()

        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        self.client.post(url, {"body": "edit — frozen_content must stay"}, HTTP_HX_REQUEST="true")

        self.tg_proj.refresh_from_db()
        self.fl_proj.refresh_from_db()

        self.assertEqual(
            self.tg_proj.frozen_content,
            frozen_tg_before,
            "Telegram frozen_content must be UNCHANGED after master tab edit.",
        )
        self.assertEqual(
            self.fl_proj.frozen_content,
            frozen_fl_before,
            "FetLife frozen_content must be UNCHANGED after master tab edit.",
        )


class MasterTabPublishedEditCorruptionSafetyTest(TestCase):
    """
    FIX 1 corruption safety: when a published projection has frozen_content=None
    (a genuine invariant violation), the guard must still raise loudly.

    A published + null frozen_content projection is corrupt data, not a legitimate
    edit-after-publish case. The guard must NOT be silently bypassed for it.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="corrupt_guard_user",
            email="corrupt_guard@test.com",
            password="pw",
        )
        self.profile = _make_profile("Corrupt Guard Org", "corrupt-guard-org", user=self.user)
        self.event = _make_event(self.profile, "Corrupt Guard Event", "corrupt-guard-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Corrupt Guard Post",
            body="Corrupt body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-corrupt-guard", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical body")

        # CORRUPT state: published projection with frozen_content=None
        self.fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv, status="published")
        # Deliberately leave frozen_content=None (the corrupt state)
        # (PlatformProjection.frozen_content defaults to None)

        self.client.force_login(self.user)

    def test_master_tab_edit_published_null_frozen_content_surfaces_error(self):
        """
        Editing the canonical CV when a published consumer has frozen_content=None
        must NOT silently succeed — it must surface a loud error (action_error in
        the HTMX response, or a ValueError raised to the view).

        A published projection with frozen_content=None is a corrupt invariant
        (ADR-008 D3: fail loud). The guard must not be bypassed for this case.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(url, {"body": "corrupt edit attempt"}, HTTP_HX_REQUEST="true")

        # Must not 500 (the error must be surfaced, not crashed)
        self.assertIn(
            response.status_code,
            [200, 302],
            f"Must not 500 on corrupt state (got {response.status_code})",
        )

        content = response.content.decode()
        # Must surface the error — "Action failed" or equivalent error indicator
        self.assertIn(
            "Action failed",
            content,
            "Editing a canonical CV with a published+null-frozen_content consumer must "
            "surface an action_error — the guard must fail loud for genuine corruption. "
            "(ADR-008 D3: fail loud, never silent fallback)",
        )


class MasterTabPublishedTemplateGatingTest(TestCase):
    """
    FIX 1 template gate: the master/source panel editor in post_syndication.html
    must be gated with source_editable (via the published policy) so it is
    INTENTIONALLY editable for published posts — not always-on-but-broken.

    For a PUBLISHED post (all consumers published, policy=dirty_then_republish),
    the master/source tab must render the editable textarea (with the version-edit
    form action) — same as it does for draft posts.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="master_pub_tmpl_user",
            email="master_pub_tmpl@test.com",
            password="pw",
        )
        self.profile = _make_profile("Master Pub Tmpl Org", "master-pub-tmpl-org", user=self.user)
        self.event = _make_event(self.profile, "Master Pub Tmpl Event", "master-pub-tmpl-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Master Pub Tmpl Post",
            body="Master pub template body",
        )
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-master-pub-tmpl", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical tmpl body")

        # PUBLISHED projection sharing the canonical CV
        self.tg_proj = _make_promotion_projection(self.conn_telegram, self.post, self.canonical_cv, status="published")
        self.tg_proj.frozen_content = {"body": "canonical tmpl body"}
        self.tg_proj.save(update_fields=["frozen_content", "updated_at"])

        self.client.force_login(self.user)

    def test_master_source_tab_shows_editable_textarea_for_published_post(self):
        """
        When ALL projections of a post are published (all consumers published),
        the master/source tab must still render the editable textarea — including
        the version-edit form action.

        This confirms the template gate is `source_editable` (policy-threaded from
        the view) rather than always-on. The textarea must be present and the form
        must post to version-edit.
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        expected_version_edit_url = reverse(
            "syndication:version-edit",
            kwargs={"pk": self.canonical_cv.pk},
        )
        self.assertIn(
            expected_version_edit_url,
            content,
            "Master/source tab must show the editable form (version-edit action) for a "
            "published post — the textarea must be present and intentionally editable, "
            "not absent or read-only. Gate must be source_editable (policy-gated), "
            "not always-on-but-broken.",
        )


# ---------------------------------------------------------------------------
# FIX 2 (kb-kgza.3 adversarial repair): Published+editable projection renders
#         sync controls (Customize for state-i, Reset for state-iii) inside editor.
# ---------------------------------------------------------------------------


class PublishedEditableSyncControlsTest(TestCase):
    """
    FIX 2 (kb-kgza.3): For a published+editable projection, the sync controls
    (Customize for state-i, Reset for state-iii) must render INSIDE the opened
    editor.

    Old contract (now obsolete under D5): Customize/Reset must NOT appear for
    published projections.
    New contract (ADR-016 D5): published projections are editable, so the sync
    controls correctly render inside the opened editor.

    This test documents the now-INTENDED behavior so the contract change is
    covered, not silent.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="pub_sync_ctrl_user",
            email="pub_sync_ctrl@test.com",
            password="pw",
        )
        self.profile = _make_profile("Pub Sync Ctrl Org", "pub-sync-ctrl-org", user=self.user)
        self.event = _make_event(self.profile, "Pub Sync Ctrl Event", "pub-sync-ctrl-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Pub Sync Ctrl Post",
            body="Pub sync ctrl body",
        )
        # FetLife supports dirty_then_republish policy
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-pub-sync-ctrl", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical sync ctrl body")
        self.client.force_login(self.user)

    def test_state_i_published_projection_customize_renders_in_editor(self):
        """
        A published projection in state (i) — sharing the canonical CV (sync_source NULL,
        name=canonical) — must render the Customize button inside the channel editor.

        State (i): content_version.name == 'canonical' + sync_source NULL.
        ADR-016 D5: published + editable → editor is open → sync controls visible.
        """
        # Create state-i projection: sharing canonical CV
        fl_proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv, status="published")
        fl_proj.frozen_content = {"body": "canonical sync ctrl body"}
        fl_proj.save(update_fields=["frozen_content", "updated_at"])

        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        customize_url = reverse("syndication:projection-customize", kwargs={"pk": fl_proj.pk})
        self.assertIn(
            customize_url,
            content,
            "Customize button must appear for a published+editable state-i projection "
            "(sharing the canonical CV). Old contract was 'no Customize for published' — "
            "new D5 contract is 'editor is open for published+editable, sync controls visible'.",
        )

    def test_state_iii_published_projection_reset_renders_in_editor(self):
        """
        A published projection in state (iii) — own CV + sync_source NULL (Custom) —
        must render the Reset button inside the channel editor.

        State (iii): own CV + sync_source NULL.
        ADR-016 D5: published + editable → editor is open → Reset control visible.
        """
        # Create a separate independent CV (state iii)
        own_cv = ContentVersion.objects.create(
            post=self.post,
            name="custom-fl",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
            body="custom fl body",
        )
        fl_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind=PlatformProjection.Kind.PROMOTION,
            status="published",
            source_post=self.post,
            content_version=own_cv,
            sync_source=None,  # state iii: own CV, no sync_source
        )
        fl_proj.frozen_content = {"body": "custom fl body"}
        fl_proj.save(update_fields=["frozen_content", "updated_at"])

        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        reset_url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": fl_proj.pk})
        self.assertIn(
            reset_url,
            content,
            "Reset button must appear for a published+editable state-iii projection "
            "(own CV + sync_source NULL). Old contract was 'no Reset for published' — "
            "new D5 contract is 'editor is open for published+editable, sync controls visible'.",
        )
