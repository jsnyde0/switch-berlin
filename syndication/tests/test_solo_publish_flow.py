"""
Tests for the solo publish flow (kb-ide0.2).

Contract under test (D6 from bead design):

1. No Approve gate — the Approve button must NOT appear in the event_syndication
   or post_syndication fragment for a draft projection.

2. One Publish CTA — clicking Publish on a draft projection must drive an
   INTERNAL draft→ready→published sequence:
   - approve_projection is called first (materializes frozen_content at draft→ready)
   - publish_projection is called second (ready→published)
   - Result: proj.status == 'published' AND proj.frozen_content is not None
   - NO direct draft→published edge is used (engine enforces this via _LEGAL_TRANSITIONS)

3. Autosave — the version-edit endpoint persists WITHOUT clicking Save;
   autosave must NOT fire for non-draft projections (gated at template layer).

Content assertions use response.content, NOT response.context
(hollow-test memory: `django-view-test-context-vs-content-hollow`).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import generate_projection
from syndication.models import PlatformConnection, PlatformProjection

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


def _make_telegram_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id="@testchannel",
        kinds=["promotion"],
        enabled=True,
    )


def _make_switch_listing_projection(event, connection):
    return generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )


def _make_fetlife_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id="fl-test",
        kinds=["promotion"],
        enabled=True,
    )


# ---------------------------------------------------------------------------
# 1. No Approve gate — DOM assertions
# ---------------------------------------------------------------------------


class NoApproveButtonTest(TestCase):
    """
    D6: The event_syndication fragment must NOT contain an 'Approve' button
    for a draft projection.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="na_user", email="na@test.com", password="pw")
        self.profile = _make_profile("NA Org", "na-org", user=self.user)
        self.event = _make_event(self.profile, "Solo Flow Test Event", "solo-flow-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_syndication_draft_has_no_approve_button(self):
        """
        D6: The event_syndication fragment (draft) must NOT contain 'Approve'.
        The Approve gate is removed; only one Publish CTA is shown.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "Approve",
            msg_prefix=(
                "event_syndication fragment (draft) must NOT contain 'Approve' — "
                "D6: the Approve gate is removed from the solo flow."
            ),
        )

    def test_event_syndication_draft_has_publish_cta(self):
        """
        D6: The event_syndication fragment (draft) MUST contain a Publish CTA.
        After removing Approve, a single Publish CTA replaces it.
        """
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Publish",
            msg_prefix=(
                "event_syndication fragment (draft) must contain 'Publish' — "
                "D6: one Publish CTA replaces the two-step Approve+Publish flow."
            ),
        )


class PostSyndicationNoApproveButtonTest(TestCase):
    """
    D6: The post_syndication fragment must NOT contain an 'Approve' button
    for a draft projection.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="pna_user", email="pna@test.com", password="pw")
        self.profile = _make_profile("PNA Org", "pna-org", user=self.user)
        self.event = _make_event(self.profile, "PNA Event", "pna-event")
        conn = _make_fetlife_connection(self.profile)
        # Create a promo post
        from syndication.models import Post

        self.post = Post.objects.create(
            event=self.event,
            headline="Test Post",
            body="Test body",
        )
        generate_projection(
            kind="promotion",
            connection=conn,
            source_post=self.post,
            mode="rule_based",
        )
        self.client.force_login(self.user)

    def test_post_syndication_draft_has_no_approve_button(self):
        """
        D6: The post_syndication fragment (draft) must NOT contain 'Approve'.
        """
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "Approve",
            msg_prefix=(
                "post_syndication fragment (draft) must NOT contain 'Approve' — "
                "D6: the Approve gate is removed from the solo flow."
            ),
        )


# ---------------------------------------------------------------------------
# 2. Publish lifecycle — DB assertions
# ---------------------------------------------------------------------------


class PublishLifecycleTest(TestCase):
    """
    D6: Publish CTA on a draft projection must drive draft→ready→published
    internally: frozen_content is materialized AND status is 'published'.

    This tests the SERVICE function directly (not the view) to ensure the
    two-step sequence is correct regardless of HTTP plumbing.
    """

    def setUp(self):
        self.user = _make_user(username="pl_user", email="pl@test.com", password="pw")
        self.profile = _make_profile("PL Org", "pl-org", user=self.user)
        self.event = _make_event(self.profile, "PL Event", "pl-event")
        self.switch_conn = _make_switch_connection(self.profile)
        self.proj = _make_switch_listing_projection(self.event, self.switch_conn)

    def test_direct_publish_from_draft_sets_published_with_frozen_content(self):
        """
        D6 + ADR-008 D3: Calling publish_projection_direct on a draft projection must:
        - Set status to 'published'
        - Materialize frozen_content (non-None) — freeze happened at draft→ready

        The two-step (approve then publish) must be transparent to the caller.
        """
        from syndication.services import publish_projection_direct

        self.assertEqual(self.proj.status, "draft")
        self.assertIsNone(self.proj.frozen_content)

        publish_projection_direct(user=self.user, projection=self.proj)

        # Reload from DB to confirm persistence
        self.proj.refresh_from_db()

        self.assertEqual(
            self.proj.status,
            "published",
            "publish_projection_direct must transition status to 'published'.",
        )
        self.assertIsNotNone(
            self.proj.frozen_content,
            "publish_projection_direct must materialize frozen_content — "
            "ADR-008 D3: no published row with null frozen_content.",
        )

    def test_direct_publish_from_ready_also_works(self):
        """
        D6: If a projection is already in 'ready' state (e.g. batch flow pre-approved it),
        calling publish_projection_direct should still publish it.
        """
        from syndication.services import approve_projection, publish_projection_direct

        # Pre-approve to move to ready
        approve_projection(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "ready")

        publish_projection_direct(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()

        self.assertEqual(self.proj.status, "published")
        self.assertIsNotNone(self.proj.frozen_content)

    def test_no_direct_draft_to_published_edge(self):
        """
        D6: The engine must NOT have a direct draft→published edge.
        Attempting a direct transition must raise ValueError.

        This is a guard test ensuring _LEGAL_TRANSITIONS is intact and
        no shortcut was added (ADR-008 D3).
        """
        from syndication.engine import transition_status

        with self.assertRaises(ValueError, msg="Engine must reject draft→published direct transition"):
            transition_status(self.proj, "published")

    def test_view_direct_publish_from_draft_sets_published_with_frozen_content(self):
        """
        D6: The view endpoint for direct-publish on a draft projection must
        result in status='published' AND frozen_content is not None in the DB.
        """
        client = Client()
        client.force_login(self.user)

        url = f"/syndication/projections/{self.proj.pk}/direct-publish/"
        response = client.post(url)

        # Should redirect or return fragment (2xx or 302)
        self.assertIn(response.status_code, [200, 302])

        self.proj.refresh_from_db()
        self.assertEqual(
            self.proj.status,
            "published",
            "Direct-publish view must result in status='published' in the DB.",
        )
        self.assertIsNotNone(
            self.proj.frozen_content,
            "Direct-publish view must materialize frozen_content — "
            "ADR-008 D3: no published row with null frozen_content.",
        )


# ---------------------------------------------------------------------------
# 3. Autosave — no Save button; debounced autosave on version-edit endpoint
# ---------------------------------------------------------------------------


class AutosaveTest(TestCase):
    """
    D6: The autosave endpoint (version-edit) persists WITHOUT clicking a Save button.
    The version-edit textarea form must NOT have an explicit Save button.
    Autosave must NOT be active for non-draft projections.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="as_user", email="as@test.com", password="pw")
        self.profile = _make_profile("AS Org", "as-org", user=self.user)
        self.event = _make_event(self.profile, "AS Event", "as-event")
        # For autosave we need a non-switch-listing (textarea form)
        self.tg_conn = _make_telegram_connection(self.profile)
        self.client.force_login(self.user)

    def _make_promo_post_with_projection(self):
        from syndication.models import Post

        post = Post.objects.create(
            event=self.event,
            headline="Autosave Post",
            body="Original body text",
        )
        proj = generate_projection(
            kind="promotion",
            connection=self.tg_conn,
            source_post=post,
            mode="rule_based",
        )
        return post, proj

    def test_no_save_button_in_non_switch_listing_textarea_form(self):
        """
        D6: The event_syndication fragment for a non-switch-listing draft must NOT
        have an explicit 'Save' button — autosave replaces it.

        We use a Telegram promotion projection (which uses the textarea form path).
        """
        from syndication.models import Post

        post = Post.objects.create(
            event=self.event,
            headline="AS Post",
            body="Some body",
        )
        generate_projection(
            kind="promotion",
            connection=self.tg_conn,
            source_post=post,
            mode="rule_based",
        )

        url = f"/syndication/posts/{post.pk}/fragments/post_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            ">Save<",
            msg_prefix=(
                "post_syndication fragment (draft, non-switch-listing) must NOT "
                "contain a 'Save' button — D6: autosave replaces explicit save."
            ),
        )

    def test_autosave_persists_body_without_save_button(self):
        """
        D6: Posting to the version-edit endpoint (simulating autosave debounce)
        persists the body WITHOUT requiring an explicit Save button click.

        This simulates what HTMX autosave does: POST the body with hx-swap="none".
        The persisted value must survive a reload.
        """
        post, proj = self._make_promo_post_with_projection()
        cv = proj.content_version

        # Simulate autosave: POST to version-edit with new body
        url = f"/syndication/versions/{cv.pk}/edit/"
        response = self.client.post(
            url,
            {"body": "Autosaved body content"},
            HTTP_HX_REQUEST="true",
        )

        # Autosave with hx-swap="none" should succeed (200 or similar)
        self.assertIn(response.status_code, [200, 204])

        # The body must persist in the DB
        cv.refresh_from_db()
        self.assertEqual(
            cv.body,
            "Autosaved body content",
            "version-edit endpoint must persist the body — autosave must work without Save button.",
        )

    def test_autosave_not_active_for_published_projection(self):
        """
        D6: Autosave must NOT fire for a published projection.
        The version-edit endpoint raises ValueError when all consumers are non-draft.

        The template layer gates autosave on proj.status == 'draft'.
        We verify the service-layer guard: edit_version raises for non-draft consumers.

        Uses a fetlife connection (attestation path — no external API call needed).
        """
        from syndication.models import Post
        from syndication.services import edit_version, publish_projection_direct

        fl_conn = _make_fetlife_connection(self.profile)
        post = Post.objects.create(
            event=self.event,
            headline="FL Autosave Post",
            body="Original FL body",
        )
        proj = generate_projection(
            kind="promotion",
            connection=fl_conn,
            source_post=post,
            mode="rule_based",
        )
        cv = proj.content_version

        # Publish the projection (drive through draft→ready→published)
        # FetLife uses the attestation path — no external API calls
        publish_projection_direct(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

        # Now try to edit the version — must raise (all consumers non-draft)
        with self.assertRaises(ValueError, msg="edit_version must raise when all consumers are published"):
            edit_version(user=self.user, version=cv, body="Should not persist")

    def test_event_syndication_switch_listing_has_no_save_button(self):
        """
        D6: The Switch listing draft form (event-edit endpoint) must NOT have
        an explicit 'Save' button — autosave replaces it.
        """
        switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, switch_conn)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            ">Save<",
            msg_prefix=(
                "event_syndication Switch listing draft must NOT contain a 'Save' "
                "button — D6: autosave replaces explicit save."
            ),
        )


# ---------------------------------------------------------------------------
# 4. review_all surface — D6 consistency (no Approve gate)
# ---------------------------------------------------------------------------


class ReviewAllNoApproveButtonTest(TestCase):
    """
    D6: The review_all surface must NOT show an 'Approve' button for a draft
    projection. It must show a direct 'Publish' CTA instead (matching the
    composer-fragment reconciliation applied in 14acb3f).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ra_user", email="ra@test.com", password="pw")
        self.profile = _make_profile("RA Org", "ra-org", user=self.user)
        self.event = _make_event(self.profile, "Review-All Test Event", "review-all-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_review_all_draft_has_no_approve_button(self):
        """
        D6: GET review_all with a draft projection must NOT contain 'Approve'.
        The Approve button was the D6 violation on this surface — it must be
        replaced with the direct-publish CTA.
        """
        url = f"/syndication/events/{self.event.pk}/review-all/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "Approve",
            msg_prefix=(
                "review_all (draft) must NOT contain 'Approve' — "
                "D6: Approve gate removed; direct-publish CTA replaces it."
            ),
        )

    def test_review_all_draft_has_publish_cta(self):
        """
        D6: GET review_all with a draft projection MUST contain a 'Publish' CTA.
        The direct-publish CTA replaces the removed Approve button.
        """
        url = f"/syndication/events/{self.event.pk}/review-all/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Publish",
            msg_prefix=(
                "review_all (draft) must contain 'Publish' — "
                "D6: direct-publish CTA present for draft projections."
            ),
        )
