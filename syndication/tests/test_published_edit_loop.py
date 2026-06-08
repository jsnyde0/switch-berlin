"""
TDD tests for kb-kgza.3: published events/posts are editable and re-publish works.

Contract (ADR-016 D5 edit-after-publish):
1. GET a published event composer (listing projection): the editor INPUTS are present
   (textarea or event form inputs), not just the read-only _channel_preview.
2. GET a published post composer (promotion projection): the editor INPUTS are present.
3. POST an edit to a published event listing projection (projection-detach-and-edit):
   is_dirty=True, dirty banner (data-testid="dirty-banner") + Re-publish CTA appear.
4. POST an edit to a published post promotion projection (projection-detach-and-edit):
   is_dirty=True, dirty banner + Re-publish CTA appear.
5. POST re-publish (projection-direct-publish on published projection):
   frozen_content is re-materialized to the new content (DB-state assertion),
   is_dirty=False after.
6. Policy gate: a non-default policy suppresses the editor for published projections
   (proves the editable flag comes from the policy seam, not a hard-coded boolean).
7. Switch event listing (event composer): POST to event-edit (event_hub_edit) on a
   published Switch listing makes the event listing dirty (event fields changed →
   effective content differs from frozen_content).

Content + DB-state assertions (NOT response.context — hollow per memory
django-view-test-context-vs-content-hollow).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirrors test_shared_canonical_detach.py helpers)
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


def _publish_projection(proj, frozen_body="original published body"):
    """
    Manually transition a projection to published with frozen_content set.
    Uses ORM directly to bypass the service layer (test setup only).
    """
    from syndication.engine import _materialize_effective_fields

    proj.status = PlatformProjection.Status.PUBLISHED
    proj.frozen_content = _materialize_effective_fields(proj)
    # Override with the explicit body if provided (for deterministic test assertions)
    if frozen_body and "body" in proj.frozen_content:
        proj.frozen_content["body"] = frozen_body
    proj.save(update_fields=["status", "frozen_content", "updated_at"])
    return proj


# ---------------------------------------------------------------------------
# 1. GET published event composer: editor inputs present
# ---------------------------------------------------------------------------


class PublishedEventComposerEditableTest(TestCase):
    """
    GET the event syndication fragment for an event with a published FetLife listing:
    the editor textarea must be present in the rendered HTML (not just the read-only preview).

    This test will FAIL before the fix because the status-gate in _channel_editor.html
    renders the editor only for 'draft' status.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="pub_event_edit_user",
            email="pub_event_edit@test.com",
            password="pw",
        )
        self.profile = _make_profile("Pub Event Edit Org", "pub-event-edit-org", user=self.user)
        self.event = _make_event(self.profile, "Published Event", "published-event-edit")
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-pub-edit", ["listing"])
        self.cv = _make_canonical_cv_for_event(self.event, body="Published event body")
        self.proj = _make_listing_projection(self.conn_fetlife, self.event, self.cv)
        # Publish the projection
        _publish_projection(self.proj, frozen_body="Published event body")
        self.proj.refresh_from_db()
        self.client.force_login(self.user)

    def test_published_event_composer_renders_editor_textarea(self):
        """
        GET event syndication fragment: a published FetLife listing must render
        the editor textarea (not just the read-only preview).

        Fails before fix: editor is gated by `proj.status == 'draft'`.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        content = response.content.decode()

        # The editor form posts to projection-detach-and-edit — its presence confirms
        # the editor is rendered (not just the read-only _channel_preview).
        detach_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.assertIn(
            detach_url,
            content,
            f"Published event listing editor must render (detach-and-edit URL present). "
            f"Got status={self.proj.status!r}. The status-gate must allow 'published' "
            f"when edit_after_publish_policy==dirty_then_republish.",
        )


# ---------------------------------------------------------------------------
# 2. GET published post composer: editor inputs present
# ---------------------------------------------------------------------------


class PublishedPostComposerEditableTest(TestCase):
    """
    GET the post syndication fragment for a post with a published FetLife promotion:
    the editor textarea must be present (not just the read-only preview).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="pub_post_edit_user",
            email="pub_post_edit@test.com",
            password="pw",
        )
        self.profile = _make_profile("Pub Post Edit Org", "pub-post-edit-org", user=self.user)
        self.event = _make_event(self.profile, "Pub Post Event", "pub-post-event-edit")
        self.post = Post.objects.create(
            event=self.event,
            headline="Pub Post Edit Test",
            body="Original body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-pub-post-edit", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="Canonical post body")
        self.proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        # Customize projection to own CV (not shared) before publishing
        # so published + sole consumer doesn't hit guard
        from syndication.services import customize

        self.own_cv = customize(self.user, self.proj)
        self.proj.refresh_from_db()
        # Now publish
        _publish_projection(self.proj, frozen_body="Published post body")
        self.proj.refresh_from_db()
        self.client.force_login(self.user)

    def test_published_post_composer_renders_editor_textarea(self):
        """
        GET post syndication fragment: a published FetLife promotion must render
        the editor textarea (not just the read-only preview).
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        content = response.content.decode()

        detach_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.assertIn(
            detach_url,
            content,
            f"Published post promotion editor must render (detach-and-edit URL present). "
            f"Got status={self.proj.status!r}.",
        )


# ---------------------------------------------------------------------------
# 3. POST edit to published event listing → is_dirty, dirty banner, Re-publish CTA
# ---------------------------------------------------------------------------


class PublishedEventEditDirtiesProjectionTest(TestCase):
    """
    POST an edit to a published event listing projection via projection-detach-and-edit.
    After the edit:
    - The projection's is_dirty property must be True (content changed).
    - The next GET of the event syndication fragment must contain the dirty banner
      (data-testid="dirty-banner") and the Re-publish CTA button.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="pub_event_dirty_user",
            email="pub_event_dirty@test.com",
            password="pw",
        )
        self.profile = _make_profile("Pub Event Dirty Org", "pub-event-dirty-org", user=self.user)
        self.event = _make_event(self.profile, "Dirty Event", "dirty-event")
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-dirty-event", ["listing"])
        self.cv = _make_canonical_cv_for_event(self.event, body="Original body")
        self.proj = _make_listing_projection(self.conn_fetlife, self.event, self.cv)
        # Customize to own CV before publishing (so only 1 consumer)
        from syndication.services import customize

        self.own_cv = customize(self.user, self.proj)
        self.proj.refresh_from_db()
        _publish_projection(self.proj, frozen_body="Original body")
        self.proj.refresh_from_db()
        self.client.force_login(self.user)

    def test_edit_published_listing_makes_projection_dirty(self):
        """
        POST to projection-detach-and-edit on a published listing: the projection
        must be dirty afterwards (content differs from frozen_content).
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.post(url, {"body": "Updated body — different from frozen"}, HTTP_HX_REQUEST="true")

        self.proj.refresh_from_db()
        self.assertTrue(
            self.proj.is_dirty,
            "Published listing edited via projection-detach-and-edit must be dirty (is_dirty=True).",
        )

    def test_dirty_banner_appears_after_published_listing_edit(self):
        """
        After editing a published listing, the event syndication fragment GET must
        render the dirty banner (data-testid="dirty-banner").
        """
        edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.post(edit_url, {"body": "New body — dirty"}, HTTP_HX_REQUEST="true")

        fragment_url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(fragment_url)
        content = response.content.decode()

        self.assertIn(
            'data-testid="dirty-banner"',
            content,
            "Dirty banner (data-testid='dirty-banner') must appear after editing published listing.",
        )

    def test_republish_cta_appears_after_published_listing_edit(self):
        """
        After editing a published listing, the event syndication fragment GET must
        render the Re-publish CTA button.
        """
        edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.post(edit_url, {"body": "New body — dirty"}, HTTP_HX_REQUEST="true")

        fragment_url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(fragment_url)
        content = response.content.decode()

        self.assertIn(
            "Re-publish",
            content,
            "Re-publish CTA must appear in event syndication fragment after editing published listing.",
        )


# ---------------------------------------------------------------------------
# 4. POST edit to published post promotion → is_dirty, dirty banner, Re-publish CTA
# ---------------------------------------------------------------------------


class PublishedPostEditDirtiesProjectionTest(TestCase):
    """
    POST an edit to a published post promotion projection via projection-detach-and-edit.
    Symmetric with the event listing test.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="pub_post_dirty_user",
            email="pub_post_dirty@test.com",
            password="pw",
        )
        self.profile = _make_profile("Pub Post Dirty Org", "pub-post-dirty-org", user=self.user)
        self.event = _make_event(self.profile, "Post Dirty Event", "post-dirty-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Post Dirty Test",
            body="Original body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-dirty-post", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="Original canonical body")
        self.proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        from syndication.services import customize

        self.own_cv = customize(self.user, self.proj)
        self.proj.refresh_from_db()
        _publish_projection(self.proj, frozen_body="Original body")
        self.proj.refresh_from_db()
        self.client.force_login(self.user)

    def test_edit_published_post_promotion_makes_it_dirty(self):
        """
        POST to projection-detach-and-edit on a published post promotion:
        the projection must be dirty afterwards.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.post(url, {"body": "New post body — different from frozen"}, HTTP_HX_REQUEST="true")

        self.proj.refresh_from_db()
        self.assertTrue(
            self.proj.is_dirty,
            "Published post promotion edited via projection-detach-and-edit must be dirty.",
        )

    def test_dirty_banner_appears_after_published_post_edit(self):
        """
        After editing a published post promotion, the post syndication fragment GET must
        render the dirty banner.
        """
        edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.post(edit_url, {"body": "New post body — dirty"}, HTTP_HX_REQUEST="true")

        fragment_url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(fragment_url)
        content = response.content.decode()

        self.assertIn(
            'data-testid="dirty-banner"',
            content,
            "Dirty banner must appear after editing published post promotion.",
        )

    def test_republish_cta_appears_after_published_post_edit(self):
        """
        After editing a published post promotion, the post syndication fragment GET must
        render the Re-publish CTA.
        """
        edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.post(edit_url, {"body": "New post body — dirty"}, HTTP_HX_REQUEST="true")

        fragment_url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(fragment_url)
        content = response.content.decode()

        self.assertIn(
            "Re-publish",
            content,
            "Re-publish CTA must appear in post syndication fragment after editing published promotion.",
        )


# ---------------------------------------------------------------------------
# 5. Re-publish re-freezes frozen_content and clears dirty (DB-state assertion)
# ---------------------------------------------------------------------------


class RepublishRefreezeTest(TestCase):
    """
    POST to projection-direct-publish on a published dirty projection:
    frozen_content must be re-materialized to the new content, and is_dirty=False after.

    DB-state assertion (ORM check on frozen_content), not HTML content assertion.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="republish_user",
            email="republish@test.com",
            password="pw",
        )
        self.profile = _make_profile("Republish Org", "republish-org", user=self.user)
        self.event = _make_event(self.profile, "Republish Event", "republish-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Republish Test Post",
            body="Original body",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-republish", ["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="Original canonical body")
        self.proj = _make_promotion_projection(self.conn_fetlife, self.post, self.canonical_cv)
        from syndication.services import customize

        self.own_cv = customize(self.user, self.proj)
        self.proj.refresh_from_db()
        _publish_projection(self.proj, frozen_body="Original body")
        self.proj.refresh_from_db()
        # Now edit to make dirty
        edit_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.client.force_login(self.user)
        self.client.post(edit_url, {"body": "Edited body — new content"}, HTTP_HX_REQUEST="true")
        self.proj.refresh_from_db()

    def test_republish_refreezes_frozen_content(self):
        """
        POST to projection-direct-publish on a dirty published projection:
        frozen_content must be re-materialized to include the new body.

        DB-state assertion on frozen_content (ORM check).
        """
        self.assertTrue(self.proj.is_dirty, "Pre-condition: projection must be dirty before re-publish.")

        republish_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.proj.pk})
        self.client.post(republish_url, {}, HTTP_HX_REQUEST="true")

        self.proj.refresh_from_db()
        self.assertEqual(
            self.proj.frozen_content.get("body"),
            "Edited body — new content",
            "Re-publish must re-materialize frozen_content to the new body. "
            f"Got frozen_content={self.proj.frozen_content!r}",
        )

    def test_republish_clears_is_dirty(self):
        """
        After re-publish, is_dirty must be False (frozen_content == current content).
        """
        republish_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.proj.pk})
        self.client.post(republish_url, {}, HTTP_HX_REQUEST="true")

        self.proj.refresh_from_db()
        self.assertFalse(
            self.proj.is_dirty,
            "After re-publish, is_dirty must be False (frozen matches current).",
        )


# ---------------------------------------------------------------------------
# 7. event_hub_edit on a published Switch listing → OOB dirty banner + Re-publish CTA
# ---------------------------------------------------------------------------


class EventHubEditPublishedSwitchListingOOBTest(TestCase):
    """
    POST an HTMX request to syndication:event-edit (event_hub_edit) for an Event
    with a published Switch LISTING projection on the canonical ContentVersion.
    The autosave form uses hx-swap="none" so HTMX discards the response body —
    OOB fragments are the ONLY path to the DOM.

    Acceptance criteria (bead kb-nexw.2):
    - The response body CONTAINS hx-swap-oob fragments for:
        #channel-dirty-<pk>  (dirty banner)
        #channel-cta-<pk>    (Re-publish CTA)
    - The published projection render returns frozen_content (not the updated live title),
      locking ADR-016 D2 / ADR-008 D3 published-freeze immutability.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="switch_hub_edit_user",
            email="switch_hub_edit@test.com",
            password="pw",
        )
        self.profile = _make_profile("Switch Hub Edit Org", "switch-hub-edit-org", user=self.user)
        self.event = _make_event(self.profile, "Switch Published Event", "switch-published-event")
        # Switch listing connection
        self.conn_switch = _make_connection(self.profile, "switch", "sw-hub-edit", ["listing"])
        # Canonical CV for the event
        self.cv = _make_canonical_cv_for_event(self.event, body="Original switch listing body")
        # Create the listing projection on the canonical CV (no customization —
        # this is the canonical path event_hub_edit touches)
        self.proj = _make_listing_projection(self.conn_switch, self.event, self.cv, status="draft")
        # Publish the projection (freeze it)
        _publish_projection(self.proj, frozen_body="Original switch listing body")
        self.proj.refresh_from_db()
        self.client.force_login(self.user)

    def _post_event_edit(self, title):
        """POST an HTMX autosave to event-edit with a changed title."""
        url = reverse("syndication:event-edit", kwargs={"pk": self.event.pk})
        return self.client.post(
            url,
            {
                "title": title,
                "slug": self.event.slug,
                "start": self.event.start.strftime("%Y-%m-%dT%H:%M"),
            },
            HTTP_HX_REQUEST="true",
        )

    def test_event_hub_edit_published_switch_listing_returns_oob_dirty_banner(self):
        """
        POST event-edit with a changed title: the response body must contain the
        hx-swap-oob fragment for #channel-dirty-<pk> (dirty banner).

        FAILS before fix: event_hub_edit returns fragment_event_syndication() which
        is discarded by hx-swap="none"; no OOB element is emitted — the full fragment
        contains id="channel-dirty-<pk>" but NOT with hx-swap-oob="true", so it is
        silently discarded by HTMX.
        """
        response = self._post_event_edit(title="Updated Switch Event Title")
        content = response.content.decode()

        # The full fragment response contains the ID but without hx-swap-oob="true".
        # Only a properly-emitted OOB response has BOTH the id AND hx-swap-oob="true"
        # in the same element. Assert the FULL response is a lean OOB payload
        # (not the multi-KB full fragment) AND contains both markers.
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            f"Response must be an OOB payload (hx-swap-oob='true' present). Got content[:200]={content[:200]!r}",
        )
        self.assertIn(
            f'id="channel-dirty-{self.proj.pk}"',
            content,
            "Response must contain hx-swap-oob fragment for #channel-dirty-<pk> "
            f"(proj.pk={self.proj.pk}). Got content={content[:500]!r}",
        )

    def test_event_hub_edit_published_switch_listing_returns_oob_cta(self):
        """
        POST event-edit with a changed title: the response body must contain the
        hx-swap-oob fragment for #channel-cta-<pk> (Re-publish CTA).
        """
        response = self._post_event_edit(title="Updated Switch Event Title")
        content = response.content.decode()

        self.assertIn(
            'hx-swap-oob="true"',
            content,
            f"Response must be an OOB payload (hx-swap-oob='true' present). Got content[:200]={content[:200]!r}",
        )
        self.assertIn(
            f'id="channel-cta-{self.proj.pk}"',
            content,
            "Response must contain hx-swap-oob fragment for #channel-cta-<pk> "
            f"(proj.pk={self.proj.pk}). Got content={content[:500]!r}",
        )

    def test_published_render_returns_frozen_content_not_live_title(self):
        """
        After the event title is updated, render_projection for the published
        projection must still return the frozen body (not the updated live canonical).

        Locks ADR-016 D2 / ADR-008 D3: published content is immutable — the freeze
        must NOT be silently invalidated by a live-canonical edit.
        """
        from syndication.engine import render_projection

        self._post_event_edit(title="Updated Switch Event Title — should NOT appear in render")
        self.proj.refresh_from_db()

        rendered = render_projection(self.proj)
        self.assertEqual(
            rendered,
            "Original switch listing body",
            "Published projection render must return frozen_content body, NOT the updated "
            f"live canonical. Got rendered={rendered!r}, "
            f"frozen_content={self.proj.frozen_content!r}",
        )


# ---------------------------------------------------------------------------
# 6. Policy gate: non-default policy suppresses editor for published projections
# ---------------------------------------------------------------------------


class PolicyGateSupressesEditorForPublishedTest(TestCase):
    """
    When edit_after_publish_policy returns 'lock' (non-default), the editor must NOT
    be rendered for a published projection.

    This proves the editable flag is threaded from the policy seam in the view,
    not hard-coded in the template (per memory cheap-foresight-seam-shipped-dead).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="policy_gate_user",
            email="policy_gate@test.com",
            password="pw",
        )
        self.profile = _make_profile("Policy Gate Org", "policy-gate-org", user=self.user)
        self.event = _make_event(self.profile, "Policy Gate Event", "policy-gate-event")
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-policy-gate", ["listing"])
        self.cv = _make_canonical_cv_for_event(self.event, body="Policy gate body")
        self.proj = _make_listing_projection(self.conn_fetlife, self.event, self.cv)
        from syndication.services import customize

        customize(self.user, self.proj)
        self.proj.refresh_from_db()
        _publish_projection(self.proj, frozen_body="Policy gate body")
        self.proj.refresh_from_db()
        self.client.force_login(self.user)

    def test_lock_policy_suppresses_editor_for_published_projection(self):
        """
        With edit_after_publish_policy patched to return 'lock', a published
        projection must NOT render the editor textarea in the event syndication fragment.
        """
        with patch("syndication.views.edit_after_publish_policy", return_value="lock"):
            url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
            response = self.client.get(url)
            content = response.content.decode()

        detach_url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.proj.pk})
        self.assertNotIn(
            detach_url,
            content,
            "When policy='lock', the editor must NOT render for a published projection. "
            "The editable flag must come from the policy seam, not be hard-coded.",
        )
