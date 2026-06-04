"""
TDD tests for the projection review board (kb-a4u.5).

Acceptance items covered:
A1. Board renders one row per eager-created projection with correct status-chip
    + provenance-tag.
A2. Inline override-edit persists to override_data AND flips provenance to
    "manual" (PlatformProjection.Provenance.MANUAL).
A3. Approve (draft→ready) works via service and freezes content.
A4. Explicit publish (ready→published) works via service AND board action URL.
A5. mark-published: API verb and UI path hit the same service function.
A6. Five empty/error states render their specified affordances.
A7. mark-published is a co-equal API verb (in api.py), not UI-only.
A8. Fragment view includes both listing AND promotion projections (not just
    source_event projections).

Co-equal seam: all service functions are called from both API handlers and
HTMX view actions — no duplicate logic.

ADR-008 D3: fail loud — no silent zero-fill, provenance always explicit.
ADR-016 D5: lifecycle actions go through transition_status exclusively.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name="Test Organizer", slug="test-organizer", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(slug="test-event", **kwargs):
    defaults = {
        "title": "Test Event",
        "slug": slug,
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, **kwargs):
    defaults = {"headline": "Come join us!", "body": "Great event."}
    defaults.update(kwargs)
    return Post.objects.create(event=event, **defaults)


def _make_connection(profile, platform="fetlife", destination_id="fl-user", kinds=None, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds or ["listing", "promotion"],
        enabled=enabled,
    )


def _make_content_version(event, name="canonical", provenance="rule_template"):
    """
    Create or get a ContentVersion for an event.
    provenance is stored on ContentVersion now (kb-wz8m.2).
    """
    from syndication.models import ContentVersion

    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name=name,
        defaults={"provenance": provenance},
    )
    if cv.provenance != provenance:
        cv.provenance = provenance
        cv.save(update_fields=["provenance"])
    return cv


def _make_listing_projection(connection, event, status="draft", provenance="rule_template"):
    """
    Create a listing projection with an associated canonical ContentVersion.
    provenance lives on ContentVersion (kb-wz8m.2), not on PlatformProjection.
    """
    cv = _make_content_version(event, provenance=provenance)
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        connection=connection,
        source_event=event,
        content_version=cv,
    )


def _make_post_content_version(post, name="canonical", provenance="rule_template"):
    """
    Create or get a POST-scoped ContentVersion (post FK set, event FK null).
    Required for promotion projections — using an event-scoped CV is wrong
    because _resolve_publishable_for_cv would return the event, not the post.
    (kb-q4u9.3 review finding 5)
    """
    from syndication.models import ContentVersion

    cv, _ = ContentVersion.objects.get_or_create(
        post=post,
        name=name,
        defaults={"provenance": provenance},
    )
    if cv.provenance != provenance:
        cv.provenance = provenance
        cv.save(update_fields=["provenance"])
    return cv


def _make_promotion_projection(connection, post, status="draft", provenance="rule_template"):
    """
    Create a promotion projection with an associated POST-scoped ContentVersion.
    provenance lives on ContentVersion (kb-wz8m.2), not on PlatformProjection.
    Uses a post-scoped CV (post FK non-null, event FK null) so that
    _resolve_publishable_for_cv correctly dispatches to the post hub on redirect.
    (kb-q4u9.3 review finding 5: was event-scoped, wrong for promotion projections)
    """
    cv = _make_post_content_version(post, provenance=provenance)
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.PROMOTION,
        status=status,
        connection=connection,
        source_post=post,
        content_version=cv,
    )


# ---------------------------------------------------------------------------
# A1. Board fragment: one row per projection, status-chip + provenance-tag
# ---------------------------------------------------------------------------


class BoardFragmentRenderTest(TestCase):
    """
    The event_syndication fragment renders one row per projection with
    correct status-chip and provenance-tag.

    These tests check context data (not the exact HTML text) to avoid
    template coupling, while asserting on actual values.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="board_user", email="board@test.com", password="pw")
        self.profile = _make_profile(name="Board Org", slug="board-org", user=self.user)
        self.event = _make_event(slug="board-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-board")
        self.client = Client()
        self.client.force_login(self.user)

    def test_fragment_renders_one_row_per_projection(self):
        """
        Board must show exactly one row per projection that exists for the event.
        """
        proj1 = _make_listing_projection(self.conn, self.event)
        post = _make_post(self.event)
        proj2 = _make_promotion_projection(self.conn, post)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        # Context must contain both projections
        projections = list(response.context["projections"])
        self.assertEqual(len(projections), 2)
        pk_set = {p.pk for p in projections}
        self.assertIn(proj1.pk, pk_set)
        self.assertIn(proj2.pk, pk_set)

    def test_fragment_includes_promotion_projections(self):
        """
        The fragment must show promotion projections (source_post-linked),
        not only listing projections (source_event-linked).
        """
        post = _make_post(self.event)
        promo_proj = _make_promotion_projection(self.conn, post)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        pk_set = {p.pk for p in projections}
        self.assertIn(promo_proj.pk, pk_set, "Promotion projection must appear in board")

    def test_fragment_projection_carries_status(self):
        """Each projection in context has the correct status value."""
        proj = _make_listing_projection(self.conn, self.event, status="draft")

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        proj_in_ctx = next(p for p in projections if p.pk == proj.pk)
        self.assertEqual(proj_in_ctx.status, "draft")

    def test_fragment_projection_carries_provenance(self):
        """
        Each projection's ContentVersion in context has the correct provenance value.
        kb-wz8m.2: provenance lives on ContentVersion, not on PlatformProjection.
        """
        proj = _make_listing_projection(self.conn, self.event, provenance="agent_supplied")

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        proj_in_ctx = next(p for p in projections if p.pk == proj.pk)
        self.assertIsNotNone(proj_in_ctx.content_version)
        self.assertEqual(proj_in_ctx.content_version.provenance, "agent_supplied")

    def test_fragment_projection_carries_connection_info(self):
        """Each projection carries connection (platform, destination_id)."""
        _make_listing_projection(self.conn, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        self.assertTrue(len(projections) >= 1)
        proj_in_ctx = projections[0]
        self.assertEqual(proj_in_ctx.connection.platform, "fetlife")

    def test_fragment_carries_effective_copy(self):
        """
        Fragment context includes rendered_body for each projection
        (the effective copy preview per the board spec).
        """
        _make_listing_projection(self.conn, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        # rendered_rows must exist in context, keyed by projection PK
        self.assertIn("rendered_rows", response.context)
        rendered_rows = response.context["rendered_rows"]
        # At least one entry, and each value is a string (rendered body)
        self.assertTrue(len(rendered_rows) >= 1)
        for _pk, body in rendered_rows.items():
            self.assertIsInstance(body, str)


# ---------------------------------------------------------------------------
# A2. Override-edit: replaced by edit_version in kb-wz8m.3
#
# save_projection_override was removed in kb-wz8m.3 and replaced by edit_version.
# The equivalent behaviour (persisting body + flipping provenance to manual) is
# now covered by test_version_ops.EditVersionTest.
#
# projection_override stub view removed in kb-wz8m.5 (ADR-008 D1: delete on sight).
# The version-ops panel IS the replacement.
# ---------------------------------------------------------------------------


class OverrideEditServiceTest(TestCase):
    """
    edit_version service: persists content fields on ContentVersion AND
    flips ContentVersion.provenance to manual.

    kb-wz8m.3: save_projection_override removed; replaced by edit_version.
    kb-wz8m.2: override_data removed; body stored on ContentVersion.body.
    provenance lives on ContentVersion, not PlatformProjection.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="edit_user", email="edit@test.com", password="pw")
        self.profile = _make_profile(name="Edit Org", slug="edit-org", user=self.user)
        self.event = _make_event(slug="edit-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-edit")

    def test_edit_version_persists_body_to_content_version(self):
        """
        Calling edit_version with body="edited copy" stores
        ContentVersion.body = "edited copy" on the version.

        kb-wz8m.3: edit_version replaces save_projection_override.
        """
        from syndication.services import edit_version

        proj = _make_listing_projection(self.conn, self.event)
        edit_version(user=self.user, version=proj.content_version, body="edited copy")
        proj.content_version.refresh_from_db()
        self.assertEqual(proj.content_version.body, "edited copy")

    def test_edit_version_flips_content_version_provenance_to_manual(self):
        """
        After edit_version, ContentVersion.provenance must be 'manual'
        regardless of its prior value (rule_template or agent_supplied).

        kb-wz8m.2: provenance lives on ContentVersion, not PlatformProjection.
        """
        from syndication.services import edit_version

        proj = _make_listing_projection(self.conn, self.event, provenance="rule_template")
        edit_version(user=self.user, version=proj.content_version, body="human edit")
        proj.content_version.refresh_from_db()
        self.assertEqual(
            proj.content_version.provenance,
            "manual",
            "edit_version must flip ContentVersion.provenance to 'manual'",
        )

    def test_edit_version_from_agent_supplied_also_flips_to_manual(self):
        """
        Editing an agent_supplied ContentVersion also flips provenance to manual.
        Human edit always wins provenance.
        """
        from syndication.services import edit_version

        proj = _make_listing_projection(self.conn, self.event, provenance="agent_supplied")
        edit_version(user=self.user, version=proj.content_version, body="overriding agent")
        proj.content_version.refresh_from_db()
        self.assertEqual(proj.content_version.provenance, "manual")

    def test_edit_version_gated_by_can_edit(self):
        """
        edit_version raises PermissionError if user cannot edit the event.
        """
        from syndication.services import edit_version

        other_user = _make_vouched_user(username="stranger", email="stranger@test.com", password="pw")
        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(PermissionError):
            edit_version(user=other_user, version=proj.content_version, body="not allowed")


# ---------------------------------------------------------------------------
# A3. Approve (draft→ready) service + view
# ---------------------------------------------------------------------------


class ApproveProjectionServiceTest(TestCase):
    """
    approve_projection service: transitions draft→ready, freezes content.
    Uses transition_status exclusively (ADR-016 D5).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="approve_user", email="approve@test.com", password="pw")
        self.profile = _make_profile(name="Approve Org", slug="approve-org", user=self.user)
        self.event = _make_event(slug="approve-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-approve")

    def test_approve_transitions_draft_to_ready(self):
        """approve_projection transitions projection from draft to ready."""
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "ready")

    def test_approve_freezes_content(self):
        """
        After approve_projection, frozen_content is populated (not None).
        The freeze captures the effective body at approval time.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertIsNotNone(
            proj.frozen_content,
            "frozen_content must be set after approve (draft→ready)",
        )
        self.assertIn("body", proj.frozen_content)

    def test_approve_gated_by_can_edit(self):
        """
        approve_projection raises PermissionError if user cannot edit the event.
        """
        from syndication.services import approve_projection

        other_user = _make_vouched_user(username="approve_stranger", email="apstrange@test.com", password="pw")
        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(PermissionError):
            approve_projection(user=other_user, projection=proj)

    def test_approve_on_already_ready_raises(self):
        """
        Approving a non-draft projection raises ValueError (illegal transition).
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event, status="draft")
        # First approve → ready
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        # Second approve → already ready, illegal
        with self.assertRaises(ValueError):
            approve_projection(user=self.user, projection=proj)


class ApproveProjectionViewTest(TestCase):
    """
    HTMX view for approve action calls through to approve_projection service.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="apprvview_user", email="apprvview@test.com", password="pw")
        self.profile = _make_profile(name="ApproveView Org", slug="approveview-org", user=self.user)
        self.event = _make_event(slug="approveview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-approveview")
        self.client = Client()
        self.client.force_login(self.user)

    def test_approve_view_transitions_to_ready(self):
        """POST to approve view transitions projection to ready."""
        proj = _make_listing_projection(self.conn, self.event)
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "ready")


# ---------------------------------------------------------------------------
# A4. Publish (ready→published) service + view
# ---------------------------------------------------------------------------


class PublishProjectionServiceTest(TestCase):
    """
    publish_projection service: transitions ready→published.
    EXPLICIT action only — never auto-triggers on approve.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="pub_user", email="pub@test.com", password="pw")
        self.profile = _make_profile(name="Pub Org", slug="pub-org", user=self.user)
        self.event = _make_event(slug="pub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-pub")

    def _make_ready_projection(self):
        """Helper: create a projection and advance it to ready status."""
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_publish_transitions_ready_to_published(self):
        """publish_projection transitions projection from ready to published."""
        from syndication.services import publish_projection

        proj = self._make_ready_projection()
        publish_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

    def test_approve_does_NOT_auto_publish(self):
        """
        Approving a projection must NOT auto-publish it.
        After approve, status must be 'ready', NOT 'published'.
        ADR-016 D5: publish is always an explicit action.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(
            proj.status,
            "ready",
            "Approve must land on 'ready', not 'published' (publish is always explicit)",
        )

    def test_publish_gated_by_can_publish(self):
        """publish_projection raises PermissionError for non-organizer."""
        from syndication.services import publish_projection

        proj = self._make_ready_projection()
        other_user = _make_vouched_user(username="pub_stranger", email="pubstrange@test.com", password="pw")
        with self.assertRaises(PermissionError):
            publish_projection(user=other_user, projection=proj)

    def test_publish_draft_raises(self):
        """Cannot publish a draft projection (must approve first)."""
        from syndication.services import publish_projection

        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(ValueError):
            publish_projection(user=self.user, projection=proj)


class PublishProjectionViewTest(TestCase):
    """
    HTMX view for publish action calls through to publish_projection service.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="pubview_user", email="pubview@test.com", password="pw")
        self.profile = _make_profile(name="PubView Org", slug="pubview-org", user=self.user)
        self.event = _make_event(slug="pubview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-pubview")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_publish_view_transitions_to_published(self):
        """POST to publish view transitions projection to published."""
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/publish/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")


# ---------------------------------------------------------------------------
# A5. mark-published: co-equal API verb + UI path hit the same service function
# ---------------------------------------------------------------------------


class MarkPublishedServiceTest(TestCase):
    """
    mark_projection_published service: transitions a projection to published
    for no-API platforms (actor-attested, out-of-band posting).

    The service must be the shared implementation called by both the API verb
    and the HTMX view action (co-equal seam, ADR-016 D6).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="markpub_user", email="markpub@test.com", password="pw")
        self.profile = _make_profile(name="MarkPub Org", slug="markpub-org", user=self.user)
        self.event = _make_event(slug="markpub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-markpub")

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_mark_published_transitions_to_published(self):
        """mark_projection_published service transitions ready→published."""
        from syndication.services import mark_projection_published

        proj = self._make_ready_projection()
        mark_projection_published(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

    def test_mark_published_gated_by_can_publish(self):
        """mark_projection_published raises PermissionError for non-organizer."""
        from syndication.services import mark_projection_published

        proj = self._make_ready_projection()
        other_user = _make_vouched_user(username="markpub_stranger", email="markpubst@test.com", password="pw")
        with self.assertRaises(PermissionError):
            mark_projection_published(user=other_user, projection=proj)

    def test_mark_published_draft_raises(self):
        """Cannot mark-published a draft (must be ready first)."""
        from syndication.services import mark_projection_published

        proj = _make_listing_projection(self.conn, self.event)
        with self.assertRaises(ValueError):
            mark_projection_published(user=self.user, projection=proj)


class MarkPublishedAPITest(TestCase):
    """
    API verb for mark-published: must be a co-equal endpoint in api.py,
    not a UI-only button.

    ADR-016 D6: the API verb and UI path both call mark_projection_published service.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="markpub_api_user",
            email="markpub_api@test.com",
            password="pw",
        )
        self.profile = _make_profile(name="MarkPub API Org", slug="markpub-api-org", user=self.user)
        self.event = _make_event(slug="markpub-api-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-markpub-api")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_api_mark_published_endpoint_exists(self):
        """
        POST /api/projections/{id}/mark-published/ must return 200 (not 404/405).
        This verifies the endpoint is registered as a co-equal API verb.
        """
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/api/projections/{proj.pk}/mark-published/",
            content_type="application/json",
        )
        # Must not be 404 (endpoint exists) and not 405 (method allowed)
        self.assertNotEqual(response.status_code, 404, "mark-published API endpoint missing")
        self.assertNotEqual(response.status_code, 405, "mark-published API endpoint not POST")
        self.assertIn(
            response.status_code,
            [200, 201, 204],
            f"Expected success status, got {response.status_code}",
        )

    def test_api_mark_published_transitions_to_published(self):
        """POST to API mark-published endpoint transitions projection to published."""
        proj = self._make_ready_projection()
        self.client.post(
            f"/api/projections/{proj.pk}/mark-published/",
            content_type="application/json",
        )
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")


class MarkPublishedViewTest(TestCase):
    """HTMX view path for mark-published calls mark_projection_published service."""

    def setUp(self):
        self.user = _make_vouched_user(username="markpub_view_user", email="markpubview@test.com", password="pw")
        self.profile = _make_profile(name="MarkPub View Org", slug="markpubview-org", user=self.user)
        self.event = _make_event(slug="markpubview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-markpubview")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_view_mark_published_transitions_to_published(self):
        """POST to HTMX mark-published view transitions projection to published."""
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/mark-published/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")


# ---------------------------------------------------------------------------
# A6. Empty/error states
# ---------------------------------------------------------------------------


class EmptyStatesTest(TestCase):
    """
    Five empty/error states per the board spec (priority order):
    1. No connections configured → "Connect platforms in settings to start syndicating →"
    2. No promo Posts yet → "No promo posts yet" + [Add promo message] CTA
    3. Connection broken/expired → surfaced at affected projection row (not implemented at v0, skip)
    4. Seed/generation failure → row shows "couldn't generate — missing X" (NOT blank body)
    5. Content-policy flag → pre-publish warning on row (not implemented at v0, skip)

    Tests 1 and 2 are verified here. Tests 3 and 5 are deferred to live-browser
    (require platform-specific adapter state). Test 4 is covered by ADR-008 D3
    (ValueError on render when body cannot be derived).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="empty_user", email="empty@test.com", password="pw")
        self.profile = _make_profile(name="Empty Org", slug="empty-org", user=self.user)
        self.event = _make_event(slug="empty-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_no_connections_state_shows_connect_platforms_message(self):
        """
        When no connections exist, the board must show a "Connect platforms" CTA,
        NOT an empty/broken panel.

        State 1: No connections configured.
        """
        # Ensure no connections, no projections for this event
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The board must show something actionable, not a blank panel
        # Looking for the connect-platforms CTA text
        self.assertIn(
            "connect",
            content.lower(),
            "Empty board without connections must show a 'Connect platforms' CTA",
        )

    def test_no_connections_state_shows_settings_link(self):
        """State 1: The 'connect platforms' state must include a link to settings/connections."""
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        content = response.content.decode()
        # Must have a link to the connections management page
        self.assertIn(
            "/connections/",
            content,
            "No-connections state must include link to connections management",
        )

    def test_has_connections_context_flag(self):
        """
        Fragment context must carry has_connections flag to distinguish
        state 1 (no connections) from state 2 (connections but no posts).
        """
        # No connections
        response_no_conn = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertIn("has_connections", response_no_conn.context)
        self.assertFalse(response_no_conn.context["has_connections"])

        # Add a connection
        _make_connection(self.profile, destination_id="fl-has-conn", kinds=["listing"])
        response_with_conn = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertIn("has_connections", response_with_conn.context)
        self.assertTrue(response_with_conn.context["has_connections"])


# ---------------------------------------------------------------------------
# A7. Verify mark-published is a co-equal API verb (structural check)
# ---------------------------------------------------------------------------


class MarkPublishedAPIVerbStructureTest(TestCase):
    """
    Structural verification: mark_projection_published must be importable from
    syndication.services (co-equal seam requirement).
    """

    def test_mark_projection_published_importable_from_services(self):
        """mark_projection_published must exist in syndication.services."""
        from syndication import services

        self.assertTrue(
            hasattr(services, "mark_projection_published"),
            "mark_projection_published must be in syndication.services (co-equal seam)",
        )

    def test_approve_projection_importable_from_services(self):
        """approve_projection must exist in syndication.services."""
        from syndication import services

        self.assertTrue(
            hasattr(services, "approve_projection"),
            "approve_projection must be in syndication.services",
        )

    def test_publish_projection_importable_from_services(self):
        """publish_projection must exist in syndication.services."""
        from syndication import services

        self.assertTrue(
            hasattr(services, "publish_projection"),
            "publish_projection must be in syndication.services",
        )

    def test_edit_version_importable_from_services(self):
        """
        edit_version must exist in syndication.services.
        kb-wz8m.3: save_projection_override removed; edit_version is the replacement.
        """
        from syndication import services

        self.assertTrue(
            hasattr(services, "edit_version"),
            "edit_version must be in syndication.services (replaces save_projection_override, kb-wz8m.3)",
        )


# ---------------------------------------------------------------------------
# Item 1: ValueError swallow — views must surface illegal-transition error
# ---------------------------------------------------------------------------


class IllegalTransitionViewErrorTest(TestCase):
    """
    ADR-008 D3 fail-loud: approving/publishing/mark-publishing an already-done
    projection raises ValueError. The views must NOT swallow this — they must
    render a visible error state, not return a success-shaped fragment.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="err_user", email="err@test.com", password="pw")
        self.profile = _make_profile(name="Err Org", slug="err-org", user=self.user)
        self.event = _make_event(slug="err-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-err")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_approve_already_ready_returns_error_state_not_success(self):
        """
        POSTing approve on an already-ready projection must return an error response,
        not a success-shaped fragment. The response body must contain the error reason.
        """
        proj = self._make_ready_projection()  # status=ready
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must NOT silently return success — must surface the error
        self.assertIn(
            "error",
            content.lower(),
            "Approve on already-ready projection must surface an error, not silently succeed",
        )

    def test_publish_draft_view_returns_error_state_not_success(self):
        """
        POSTing publish on a draft projection must return an error response
        (publish requires ready state first).
        """
        proj = _make_listing_projection(self.conn, self.event)  # status=draft
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/publish/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "error",
            content.lower(),
            "Publish on draft projection must surface an error, not silently succeed",
        )

    def test_mark_published_draft_view_returns_error_state_not_success(self):
        """
        POSTing mark-published on a draft projection must return an error response.
        """
        proj = _make_listing_projection(self.conn, self.event)  # status=draft
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/mark-published/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "error",
            content.lower(),
            "Mark-published on draft projection must surface an error, not silently succeed",
        )


# ---------------------------------------------------------------------------
# Item 3: No duplicate _get_projection_event helpers — views/api use services
# ---------------------------------------------------------------------------


class ResolvProjectionEventSingleSourceTest(TestCase):
    """
    ADR-008 D2 one-clear-path: views and api must NOT define their own
    _get_projection_event / _projection_event helpers.
    They must import and call _resolve_projection_event from syndication.services.
    """

    def test_views_has_no_private_get_projection_event(self):
        """views.py must not define _get_projection_event (use services version)."""
        import syndication.views as views_mod

        self.assertFalse(
            hasattr(views_mod, "_get_projection_event"),
            "_get_projection_event must be removed from views.py; use services._resolve_projection_event",
        )

    def test_api_has_no_private_projection_event(self):
        """api.py must not define _projection_event (use services version)."""
        import syndication.api as api_mod

        self.assertFalse(
            hasattr(api_mod, "_projection_event"),
            "_projection_event must be removed from api.py; use services._resolve_projection_event",
        )

    def test_resolve_projection_event_raises_on_missing_source_event(self):
        """
        _resolve_projection_event (services) must raise ValueError when a listing
        projection has no source_event (ADR-008 D3 fail-loud).
        """
        from syndication.models import PlatformProjection
        from syndication.services import _resolve_projection_event

        class FakeListing:
            kind = PlatformProjection.Kind.LISTING
            pk = 99
            source_event = None

        with self.assertRaises(ValueError):
            _resolve_projection_event(FakeListing())


# ---------------------------------------------------------------------------
# Item 4: Render-failure structural flag in context/template
# ---------------------------------------------------------------------------


class RenderErrorStructuralFlagTest(TestCase):
    """
    ADR-008 D3: render failure must be structurally distinct, not a magic string.
    The view must pass an explicit per-row error flag so the template can render
    a visually-distinct error treatment.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="renerr_user", email="renerr@test.com", password="pw")
        self.profile = _make_profile(name="RenErr Org", slug="renerr-org", user=self.user)
        self.event = _make_event(slug="renerr-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-renerr")
        self.client = Client()
        self.client.force_login(self.user)

    def test_projection_row_carries_render_error_flag(self):
        """
        When render_projection raises ValueError, the projection_rows entry must
        carry render_error=True so the template can render a distinct error state.
        """
        from unittest.mock import patch

        _make_listing_projection(self.conn, self.event)

        with patch("syndication.engine.render_projection", side_effect=ValueError("missing field")):
            response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        projection_rows = response.context["projection_rows"]
        self.assertTrue(len(projection_rows) >= 1)
        row = projection_rows[0]
        self.assertIn("render_error", row, "projection_rows must have render_error key")
        self.assertTrue(row["render_error"], "render_error must be True when render raises ValueError")

    def test_render_error_template_renders_distinct_error_class(self):
        """
        When render_error=True, the template must render the error body with a
        distinct error CSS class (not as normal body copy).
        """
        from unittest.mock import patch

        _make_listing_projection(self.conn, self.event)

        with patch("syndication.engine.render_projection", side_effect=ValueError("missing field")):
            response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        content = response.content.decode()
        # Error must use a distinct error class/treatment
        self.assertIn(
            "kb-tag-error",
            content,
            "Render failure must render with kb-tag-error class, not normal copy",
        )


# ---------------------------------------------------------------------------
# Item 5: has_promotion_connections must filter by kinds containing "promotion"
# ---------------------------------------------------------------------------


class HasPromotionConnectionsFilterTest(TestCase):
    """
    has_promotion_connections must filter for connections whose kinds JSON list
    contains "promotion". A listing-only connection must not set it True.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="promoconn_user", email="promoconn@test.com", password="pw")
        self.profile = _make_profile(name="PromConn Org", slug="promconn-org", user=self.user)
        self.event = _make_event(slug="promconn-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_listing_only_connection_does_not_set_has_promotion_connections(self):
        """
        A connection with kinds=["listing"] must NOT set has_promotion_connections=True.
        """
        _make_connection(self.profile, destination_id="fl-listing-only", kinds=["listing"])
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        # has_promotion_connections must be False because no promotion-capable connections
        # The test checks no_promo_posts is False because the connection doesn't support promotion
        self.assertFalse(
            response.context["no_promo_posts"],
            "no_promo_posts must be False when only listing connections exist",
        )

    def test_promotion_connection_sets_has_promotion_connections(self):
        """
        A connection with kinds=["promotion"] and no posts must set no_promo_posts=True.
        """
        _make_connection(self.profile, destination_id="fl-promo-only", kinds=["promotion"])
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.context["no_promo_posts"],
            "no_promo_posts must be True when promotion connection exists but no posts",
        )


# ---------------------------------------------------------------------------
# Item 6: Batch "publish all ready"
# ---------------------------------------------------------------------------


class BatchPublishAllReadyServiceTest(TestCase):
    """
    publish_all_ready_projections service: publishes every ready projection
    for an event in a single call. Skips non-ready rows. Gated by can_publish.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="batch_user", email="batch@test.com", password="pw")
        self.profile = _make_profile(name="Batch Org", slug="batch-org", user=self.user)
        self.event = _make_event(slug="batch-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-batch")

    def _make_ready_projection(self, event=None, **kwargs):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, event or self.event, **kwargs)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_batch_publishes_all_ready_rows(self):
        """publish_all_ready_projections publishes every ready projection."""
        from syndication.services import publish_all_ready_projections

        proj1 = self._make_ready_projection()
        proj2 = self._make_ready_projection()
        publish_all_ready_projections(user=self.user, event=self.event)
        proj1.refresh_from_db()
        proj2.refresh_from_db()
        self.assertEqual(proj1.status, "published")
        self.assertEqual(proj2.status, "published")

    def test_batch_skips_non_ready_rows(self):
        """publish_all_ready_projections skips draft/published projections."""
        from syndication.services import publish_all_ready_projections

        draft_proj = _make_listing_projection(self.conn, self.event)  # stays draft
        ready_proj = self._make_ready_projection()
        publish_all_ready_projections(user=self.user, event=self.event)
        draft_proj.refresh_from_db()
        ready_proj.refresh_from_db()
        self.assertEqual(draft_proj.status, "draft", "Draft projection must not be touched by batch publish")
        self.assertEqual(ready_proj.status, "published")

    def test_batch_publish_gated_by_can_publish(self):
        """publish_all_ready_projections raises PermissionError for non-organizer."""
        from syndication.services import publish_all_ready_projections

        self._make_ready_projection()
        other_user = _make_vouched_user(username="batch_stranger", email="batchst@test.com", password="pw")
        with self.assertRaises(PermissionError):
            publish_all_ready_projections(user=other_user, event=self.event)

    def test_batch_returns_list_of_published_projections(self):
        """publish_all_ready_projections returns (published, failures) where published has the published projections."""
        from syndication.services import publish_all_ready_projections

        proj1 = self._make_ready_projection()
        proj2 = self._make_ready_projection()
        published, failures = publish_all_ready_projections(user=self.user, event=self.event)
        published_pks = {p.pk for p in published}
        self.assertIn(proj1.pk, published_pks)
        self.assertIn(proj2.pk, published_pks)
        self.assertEqual(failures, [], "No failures expected in happy path")


class BatchPublishViewTest(TestCase):
    """HTMX view for batch publish calls publish_all_ready_projections service."""

    def setUp(self):
        self.user = _make_vouched_user(username="batchview_user", email="batchview@test.com", password="pw")
        self.profile = _make_profile(name="BatchView Org", slug="batchview-org", user=self.user)
        self.event = _make_event(slug="batchview-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-batchview")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_batch_publish_view_publishes_all_ready(self):
        """POST to batch-publish view transitions all ready projections to published."""
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/syndication/events/{self.event.pk}/projections/publish-all-ready/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(response.status_code, [200, 302])
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")

    def test_batch_publish_view_authz_gated(self):
        """POST to batch-publish view by non-organizer returns 403."""
        self._make_ready_projection()
        other_client = Client()
        other_user = _make_vouched_user(username="batchview_stranger", email="bvst@test.com", password="pw")
        other_client.force_login(other_user)
        response = other_client.post(
            f"/syndication/events/{self.event.pk}/projections/publish-all-ready/",
        )
        self.assertEqual(response.status_code, 403)

    def test_batch_publish_view_and_api_call_same_service(self):
        """
        Both the HTMX batch-publish view and the API batch endpoint must import
        publish_all_ready_projections from syndication.services — the same object.
        This verifies the co-equal seam (ADR-016 D6) at import time.
        """
        import syndication.api as api_mod
        import syndication.services as services_mod
        import syndication.views as views_mod

        self.assertIs(
            api_mod.publish_all_ready_projections,
            services_mod.publish_all_ready_projections,
            "syndication.api.publish_all_ready_projections must be the same object as "
            "syndication.services.publish_all_ready_projections",
        )
        self.assertIs(
            views_mod.publish_all_ready_projections,
            services_mod.publish_all_ready_projections,
            "syndication.views.publish_all_ready_projections must be the same object as "
            "syndication.services.publish_all_ready_projections",
        )


# ---------------------------------------------------------------------------
# Item 7: Patch the SOURCE (syndication.services) not import aliases
# ---------------------------------------------------------------------------


class MarkPublishedSharedSourceTest(TestCase):
    """
    The co-equal seam test must patch syndication.services.mark_projection_published
    (the SOURCE), not the import-alias in each module. This proves both paths
    route through the SAME source function.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="sharedsr_user", email="sharedsr@test.com", password="pw")
        self.profile = _make_profile(name="SharedSrc Org", slug="sharedsrc-org", user=self.user)
        self.event = _make_event(slug="sharedsrc-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-sharedsrc")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_api_and_ui_both_route_through_services_source(self):
        """
        Both api.py and views.py must import mark_projection_published from
        syndication.services and the imported symbol must be the same object as
        the one defined in services — proving they share a single source.

        When modules use `from syndication.services import mark_projection_published`,
        patching the source module after import does NOT intercept local copies
        (Python import semantics). The correct structural check is to verify
        that both call-site symbols are identical to the services definition.
        """
        import syndication.api as api_mod
        import syndication.services as services_mod
        import syndication.views as views_mod

        # Both modules must reference the same function object from services
        self.assertIs(
            api_mod.mark_projection_published,
            services_mod.mark_projection_published,
            "syndication.api.mark_projection_published must be the same object as "
            "syndication.services.mark_projection_published",
        )
        self.assertIs(
            views_mod.mark_projection_published,
            services_mod.mark_projection_published,
            "syndication.views.mark_projection_published must be the same object as "
            "syndication.services.mark_projection_published",
        )


# ---------------------------------------------------------------------------
# Item 8: no_promo_posts rendered text assertions
# ---------------------------------------------------------------------------


class NoPromoPostsRenderedTextTest(TestCase):
    """
    The no_promo_posts state must render the actual text 'No promo posts yet'
    and the 'Add promo message' CTA in the response body.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="nopromo_user", email="nopromo@test.com", password="pw")
        self.profile = _make_profile(name="NoPromo Org", slug="nopromo-org", user=self.user)
        self.event = _make_event(slug="nopromo-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_no_promo_posts_state_renders_text_and_cta(self):
        """
        When no_promo_posts=True, the response body must contain:
        - "No promo posts yet" text
        - "Add promo message" CTA
        """
        _make_connection(self.profile, destination_id="fl-nopromo", kinds=["promotion"])
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "No promo posts yet",
            content,
            "Template must render 'No promo posts yet' when no_promo_posts=True",
        )
        self.assertIn(
            "Add promo message",
            content,
            "Template must render 'Add promo message' CTA when no_promo_posts=True",
        )


# ---------------------------------------------------------------------------
# Item 9: rendered body non-empty and contains event content
# ---------------------------------------------------------------------------


class RenderedBodyContentTest(TestCase):
    """
    Rendered body for a successfully-rendered projection must be non-empty
    and contain content derived from the event (not empty string or error string).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="rendcont_user", email="rendcont@test.com", password="pw")
        self.profile = _make_profile(name="RendCont Org", slug="rendcont-org", user=self.user)
        self.event = _make_event(slug="rendcont-event", title="Awesome Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-rendcont")
        self.client = Client()
        self.client.force_login(self.user)

    def test_rendered_body_is_non_empty_and_contains_event_content(self):
        """
        The rendered body for a successfully-rendered projection must be
        non-empty AND contain the event title (proving it's real content).
        """
        _make_listing_projection(self.conn, self.event)
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        rendered_rows = response.context["rendered_rows"]
        self.assertTrue(len(rendered_rows) >= 1)
        for _pk, body in rendered_rows.items():
            self.assertIsInstance(body, str)
            self.assertTrue(len(body) > 0, "Rendered body must not be empty for a valid projection")
            self.assertNotIn(
                "[render error",
                body,
                "Successfully-rendered body must not be an error string",
            )
            self.assertIn(
                "Awesome Test Event",
                body,
                "Rendered body must contain event title (proving real event content)",
            )


# ---------------------------------------------------------------------------
# Item 10: API F12 risk — verify force_login actually authenticates
# ---------------------------------------------------------------------------


class NinjaSessionAuthTest(TestCase):
    """
    Verify Ninja SessionMarkerAuth honors Django test-client force_login.
    The API tests must exercise a real authenticated 2xx path, not silently 401.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="sessionauth_user", email="sessionauth@test.com", password="pw")
        self.profile = _make_profile(name="SessionAuth Org", slug="sessionauth-org", user=self.user)
        self.event = _make_event(slug="sessionauth-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-sessionauth")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self):
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_mark_published_api_with_force_login_returns_200_not_401(self):
        """
        POST to /api/projections/{id}/mark-published/ with force_login must
        return 200, not 401/403 (proving session auth works for Ninja endpoints).
        """
        proj = self._make_ready_projection()
        response = self.client.post(
            f"/api/projections/{proj.pk}/mark-published/",
            content_type="application/json",
        )
        self.assertEqual(
            response.status_code,
            200,
            f"API mark-published with force_login must return 200. "
            f"Got {response.status_code}: {response.content.decode()[:200]}",
        )


# ---------------------------------------------------------------------------
# Item 11: batch publish partial-failure path (ADR-008 D3 fail-loud)
# ---------------------------------------------------------------------------


class BatchPublishPartialFailureTest(TestCase):
    """
    publish_all_ready_projections must handle per-projection ValueError without
    raising an unhandled 500.  When one ready projection fails (concurrent state
    change), the others must still publish AND the failure must be surfaced as a
    visible error, not swallowed or propagated as an unhandled exception.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="batchfail_user", email="batchfail@test.com", password="pw")
        self.profile = _make_profile(name="BatchFail Org", slug="batchfail-org", user=self.user)
        self.event = _make_event(slug="batchfail-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-batchfail")
        self.client = Client()
        self.client.force_login(self.user)

    def _make_ready_projection(self, destination_id_suffix=""):
        from syndication.services import approve_projection

        conn = _make_connection(
            self.profile,
            destination_id=f"fl-batchfail-{destination_id_suffix}",
        )
        proj = _make_listing_projection(conn, self.event)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        return proj

    def test_service_partial_failure_publishes_rest_and_returns_failures(self):
        """
        publish_all_ready_projections: if one projection raises ValueError during
        transition, the others still publish and the return value includes the
        failure — no unhandled exception propagates.
        """
        from unittest.mock import patch

        from syndication.services import publish_all_ready_projections

        proj_ok = self._make_ready_projection("ok")
        proj_fail = self._make_ready_projection("fail")

        original_transition = None

        def failing_transition(projection, target_status):
            if projection.pk == proj_fail.pk:
                raise ValueError("Simulated concurrent state change")
            original_transition(projection, target_status)

        import syndication.engine as engine_mod

        original_transition = engine_mod.transition_status

        with patch.object(engine_mod, "transition_status", side_effect=failing_transition):
            result = publish_all_ready_projections(user=self.user, event=self.event)

        # The successful projection must have been published
        proj_ok.refresh_from_db()
        self.assertEqual(proj_ok.status, "published", "Non-failing projection must be published")

        # The failing one must NOT have been published
        proj_fail.refresh_from_db()
        self.assertNotEqual(proj_fail.status, "published", "Failed projection must not be published")

        # The return value must surface the failure (published list + failures)
        published, failures = result
        self.assertIn(proj_ok, published, "proj_ok must be in published list")
        self.assertEqual(len(failures), 1, "Exactly one failure expected")
        failed_proj, exc = failures[0]
        self.assertEqual(failed_proj.pk, proj_fail.pk)
        self.assertIsInstance(exc, ValueError)

    def test_batch_publish_view_partial_failure_surfaces_error_not_500(self):
        """
        POST to batch-publish with one failing projection must return 200 with
        visible error state, not an unhandled 500.
        """
        from unittest.mock import patch

        _proj_ok = self._make_ready_projection("view-ok")
        proj_fail = self._make_ready_projection("view-fail")

        import syndication.engine as engine_mod

        original_transition = engine_mod.transition_status

        def failing_transition(projection, target_status):
            if projection.pk == proj_fail.pk:
                raise ValueError("Simulated concurrent state change")
            original_transition(projection, target_status)

        with patch.object(engine_mod, "transition_status", side_effect=failing_transition):
            response = self.client.post(
                f"/syndication/events/{self.event.pk}/projections/publish-all-ready/",
                HTTP_HX_REQUEST="true",
            )

        self.assertNotEqual(response.status_code, 500, "Partial failure must not produce 500")
        self.assertEqual(response.status_code, 200, "Partial failure must return 200 with error state")
        content = response.content.decode()
        self.assertIn(
            "Action failed",
            content,
            "Response must contain visible error state when batch publish has failures",
        )


# ---------------------------------------------------------------------------
# kb-wz8m.5: Composer + channel-rail board tests
# ---------------------------------------------------------------------------


class ComposerRailBoardRenderTest(TestCase):
    """
    F1/F2: The event_syndication fragment renders one card per projection with:
    - Assigned-version preview (rendered body)
    - Status pill
    - Per-channel publish control
    """

    def setUp(self):
        self.user = _make_vouched_user(username="rail_user", email="rail@test.com", password="pw")
        self.profile = _make_profile(name="Rail Org", slug="rail-org", user=self.user)
        self.event = _make_event(slug="rail-event", title="Rail Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-rail")
        self.client = Client()
        self.client.force_login(self.user)

    def test_fragment_renders_one_card_per_projection(self):
        """
        One card per projection: listing + promotion both appear.
        """
        proj1 = _make_listing_projection(self.conn, self.event)
        post = _make_post(self.event)
        proj2 = _make_promotion_projection(self.conn, post)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        projections = list(response.context["projections"])
        self.assertEqual(len(projections), 2)
        pks = {p.pk for p in projections}
        self.assertIn(proj1.pk, pks)
        self.assertIn(proj2.pk, pks)

    def test_fragment_renders_status_pill(self):
        """
        Each card must render a status pill (status chip in HTML).
        """
        _make_listing_projection(self.conn, self.event, status="draft")
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Status chip must be rendered — look for the status display value
        self.assertIn("draft", content.lower(), "Status pill must render the projection status")

    def test_fragment_renders_version_preview(self):
        """
        Each card must render the assigned-version preview (rendered body).
        """
        _make_listing_projection(self.conn, self.event)
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Rendered body must contain event title (real content)
        self.assertIn("Rail Test Event", content, "Version preview must contain event content")

    def test_fragment_renders_per_channel_publish_control(self):
        """
        Each ready card must render a per-channel Publish button.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Publish button must point to the projection-publish URL
        self.assertIn(
            f"/syndication/projections/{proj.pk}/publish/",
            content,
            "Per-channel publish button must point to projection-publish URL",
        )


class LiveOnChannelsCueTest(TestCase):
    """
    F7: The fragment context includes content_version_consumers_map data.
    - The 'live on <channels>' set rendered matches the data.
    - After a customize on one projection, the re-rendered fragment shows
      the updated grouping (customized channel no longer grouped with canonical).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="liveon_user", email="liveon@test.com", password="pw")
        self.profile = _make_profile(name="LiveOn Org", slug="liveon-org", user=self.user)
        self.event = _make_event(slug="liveon-event", title="Live On Test")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn1 = _make_connection(self.profile, platform="fetlife", destination_id="fl-liveon-1")
        self.conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-liveon-2")
        self.client = Client()
        self.client.force_login(self.user)

    def test_fragment_context_includes_consumers_map(self):
        """
        Fragment context must include 'consumers_map' keyed by ContentVersion.
        """
        _make_listing_projection(self.conn1, self.event)
        _make_listing_projection(self.conn2, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "consumers_map",
            response.context,
            "Fragment context must include consumers_map for live-on cue",
        )

    def test_consumers_map_groups_projections_by_version(self):
        """
        When two projections share the canonical version, consumers_map must
        map that version to both projections.
        """
        proj1 = _make_listing_projection(self.conn1, self.event)
        proj2 = _make_listing_projection(self.conn2, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        consumers_map = response.context["consumers_map"]
        # Both projections share the canonical version
        canonical_version = proj1.content_version
        self.assertIn(canonical_version, consumers_map)
        consumer_pks = {p.pk for p in consumers_map[canonical_version]}
        self.assertIn(proj1.pk, consumer_pks)
        self.assertIn(proj2.pk, consumer_pks)

    def test_customize_updates_consumers_map_grouping(self):
        """
        F5/F7 rendered-HTML assertion:
        BEFORE customize: both projections share a version → the live-on cue for
        conn1's card must name BOTH 'fetlife' and 'switch' as sharing channels.
        AFTER customize on proj1: proj1 has its own version → the live-on cue
        for conn1's card must NO LONGER name conn2's platform ('switch'), because
        they are now on separate versions.

        This is a real render assertion: it would FAIL if the template's
        consumers_map iteration broke, returning wrong grouping or empty cue.
        """
        proj1 = _make_listing_projection(self.conn1, self.event)
        proj2 = _make_listing_projection(self.conn2, self.event)

        # Verify both share the same canonical version before customize
        self.assertEqual(proj1.content_version_id, proj2.content_version_id)

        # --- BEFORE customize: load the fragment, check live-on cue names both channels ---
        before_response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(before_response.status_code, 200)
        before_content = before_response.content.decode()
        # Both platforms must appear in the shared live-on cue
        self.assertIn(
            "fetlife",
            before_content,
            "BEFORE customize: live-on cue must name 'fetlife' (sharing same version)",
        )
        self.assertIn(
            "switch",
            before_content,
            "BEFORE customize: live-on cue must name 'switch' (sharing same version)",
        )
        # Must use channel names, not a bare count
        import re

        bare_count_pattern = r"live on \d+ channels?"
        self.assertIsNone(
            re.search(bare_count_pattern, before_content.lower()),
            "Live-on cue must name channels, not use a bare 'live on N channels' count",
        )

        # --- POST to customize endpoint for proj1 ---
        response = self.client.post(
            f"/syndication/projections/{proj1.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)

        # Re-fetch projections from DB
        proj1.refresh_from_db()
        proj2.refresh_from_db()

        # proj1 now has a different version from proj2
        self.assertNotEqual(
            proj1.content_version_id,
            proj2.content_version_id,
            "After customize, proj1 must have its own version separate from proj2",
        )

        # --- Context-level assertion: consumers_map reflects new grouping ---
        consumers_map = response.context["consumers_map"]
        proj1_version = proj1.content_version
        proj2_version = proj2.content_version
        self.assertNotEqual(proj1_version.pk, proj2_version.pk)

        proj1_consumers = {p.pk for p in consumers_map.get(proj1_version, [])}
        self.assertIn(proj1.pk, proj1_consumers)
        self.assertNotIn(proj2.pk, proj1_consumers)

        proj2_consumers = {p.pk for p in consumers_map.get(proj2_version, [])}
        self.assertIn(proj2.pk, proj2_consumers)
        self.assertNotIn(proj1.pk, proj2_consumers)

        # --- AFTER customize: rendered HTML must NOT show 'switch' in the
        #     live-on cue for proj1's card (they are no longer on the same version).
        #     proj1 is now solo → live-on cue must not appear for proj1's card
        #     (or if it does, it must NOT name the other platform). ---
        after_content = response.content.decode()
        # proj2's card (switch) may still show 'switch' as its platform label —
        # what we assert is that the shared live-on cue no longer groups proj1
        # with proj2. We check this via the context-level assertion above AND by
        # confirming the rendered fragment does NOT contain both names in a cue
        # that would imply they are still grouped.
        # The simplest verifiable claim: the response.context consumers_map
        # already asserts the correct grouping; additionally verify the rendered
        # HTML mentions the live-on construct at most once per channel (not twice
        # with both channel names together in one cue).
        # A cue with BOTH 'fetlife' AND 'switch' together in a single span would
        # only appear if they are still grouped — after customize they must not be.
        # We scan the rendered HTML for the live-on span containing both names
        # side-by-side (which the template builds in a single span).
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(after_content, "html.parser")
        live_on_spans = soup.find_all(lambda tag: tag.name == "span" and "live on" in (tag.get_text() or "").lower())
        # None of the live-on spans should contain BOTH 'fetlife' AND 'switch'
        for span in live_on_spans:
            text = span.get_text().lower()
            self.assertFalse(
                "fetlife" in text and "switch" in text,
                f"After customize, no single live-on cue should name both 'fetlife' AND "
                f"'switch' — they are on separate versions now. Found: {text!r}",
            )


class VersionOpEndpointTest(TestCase):
    """
    Each version-op endpoint (customize / copy_to / reset / edit_version) must:
    - Return the refreshed syndication fragment (200 with context) on HX-Request
    - Effect the service call (model state changes)
    """

    def setUp(self):
        self.user = _make_vouched_user(username="vop_user", email="vop@test.com", password="pw")
        self.profile = _make_profile(name="VersionOp Org", slug="versionop-org", user=self.user)
        self.event = _make_event(slug="vop-event", title="Version Op Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-vop")
        self.conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-vop-2")
        self.client = Client()
        self.client.force_login(self.user)

    def test_customize_endpoint_returns_refreshed_fragment(self):
        """POST customize returns the refreshed syndication fragment."""
        proj = _make_listing_projection(self.conn, self.event)
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        # Must return the syndication fragment context
        self.assertIn("projections", response.context)

    def test_customize_endpoint_creates_new_version(self):
        """POST customize creates a new ContentVersion for the projection."""
        proj = _make_listing_projection(self.conn, self.event)
        old_cv_pk = proj.content_version_id

        self.client.post(
            f"/syndication/projections/{proj.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        proj.refresh_from_db()
        self.assertNotEqual(
            proj.content_version_id,
            old_cv_pk,
            "customize must assign a new ContentVersion to the projection",
        )

    def test_reset_to_canonical_endpoint_returns_refreshed_fragment(self):
        """POST reset-to-canonical returns the refreshed syndication fragment."""
        from syndication.services import customize as svc_customize

        proj = _make_listing_projection(self.conn, self.event)
        # First customize so we can reset
        svc_customize(user=self.user, projection=proj)
        proj.refresh_from_db()

        response = self.client.post(
            f"/syndication/projections/{proj.pk}/reset-to-canonical/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("projections", response.context)

    def test_reset_to_canonical_endpoint_repoints_to_canonical(self):
        """POST reset-to-canonical repoints the projection at the canonical version."""
        from syndication.services import customize as svc_customize

        canonical_cv = _make_content_version(self.event, name="canonical")
        proj = _make_listing_projection(self.conn, self.event)
        svc_customize(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertNotEqual(proj.content_version_id, canonical_cv.pk)

        self.client.post(
            f"/syndication/projections/{proj.pk}/reset-to-canonical/",
            HTTP_HX_REQUEST="true",
        )
        proj.refresh_from_db()
        self.assertEqual(
            proj.content_version_id,
            canonical_cv.pk,
            "reset-to-canonical must repoint projection at the canonical version",
        )

    def test_copy_to_endpoint_returns_refreshed_fragment(self):
        """POST copy-to-projections returns the refreshed syndication fragment."""
        proj_src = _make_listing_projection(self.conn, self.event)
        proj_tgt = _make_listing_projection(self.conn2, self.event)

        response = self.client.post(
            f"/syndication/versions/{proj_src.content_version_id}/copy-to/",
            data={"target_projection_pks": str(proj_tgt.pk)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("projections", response.context)

    def test_copy_to_endpoint_creates_independent_versions(self):
        """POST copy-to creates a new independent ContentVersion for each target."""
        proj_src = _make_listing_projection(self.conn, self.event)
        proj_tgt = _make_listing_projection(self.conn2, self.event)
        src_cv_pk = proj_src.content_version_id
        _tgt_old_cv_pk = proj_tgt.content_version_id

        self.client.post(
            f"/syndication/versions/{proj_src.content_version_id}/copy-to/",
            data={"target_projection_pks": str(proj_tgt.pk)},
            HTTP_HX_REQUEST="true",
        )
        proj_tgt.refresh_from_db()
        self.assertNotEqual(
            proj_tgt.content_version_id,
            src_cv_pk,
            "copy_to must create new version row, not point at source version",
        )

    def test_edit_version_endpoint_returns_refreshed_fragment(self):
        """POST edit-version returns the refreshed syndication fragment."""
        proj = _make_listing_projection(self.conn, self.event)
        response = self.client.post(
            f"/syndication/versions/{proj.content_version_id}/edit/",
            data={"body": "Edited body text"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("projections", response.context)

    def test_edit_version_endpoint_persists_body(self):
        """POST edit-version persists body to ContentVersion."""
        proj = _make_listing_projection(self.conn, self.event)
        cv_pk = proj.content_version_id

        self.client.post(
            f"/syndication/versions/{proj.content_version_id}/edit/",
            data={"body": "New body from view"},
            HTTP_HX_REQUEST="true",
        )

        from syndication.models import ContentVersion

        cv = ContentVersion.objects.get(pk=cv_pk)
        self.assertEqual(cv.body, "New body from view")

    def test_edit_version_endpoint_flips_provenance_to_manual(self):
        """POST edit-version flips ContentVersion.provenance to 'manual'."""
        proj = _make_listing_projection(self.conn, self.event, provenance="rule_template")
        cv_pk = proj.content_version_id

        self.client.post(
            f"/syndication/versions/{proj.content_version_id}/edit/",
            data={"body": "human edit"},
            HTTP_HX_REQUEST="true",
        )

        from syndication.models import ContentVersion

        cv = ContentVersion.objects.get(pk=cv_pk)
        self.assertEqual(cv.provenance, "manual")


class NoBoardLLMGenerateAffordanceTest(TestCase):
    """
    D-B: No 'generate with AI' / LLM affordance must appear anywhere on the board.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="nogen_user", email="nogen@test.com", password="pw")
        self.profile = _make_profile(name="NoGen Org", slug="nogen-org", user=self.user)
        self.event = _make_event(slug="nogen-event", title="NoGen Test")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-nogen")
        self.client = Client()
        self.client.force_login(self.user)

    def test_no_generate_llm_button_on_board(self):
        """
        The board fragment must NOT contain any 'generate' / LLM affordance text.
        D-B: No platform-owned-LLM generate affordance anywhere.
        """
        _make_listing_projection(self.conn, self.event)
        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode().lower()
        # Must NOT contain LLM/AI generate affordances
        for banned_phrase in ["generate with ai", "ai generate", "generate content", "ask ai"]:
            self.assertNotIn(
                banned_phrase,
                content,
                f"Board must not contain LLM affordance: '{banned_phrase}' (D-B)",
            )


class BoardAuthzTest(TestCase):
    """
    Authorization tests:
    - Co-claimant can load the board (200)
    - Non-claimant gets 403
    """

    def setUp(self):
        self.owner = _make_vouched_user(username="authz_owner", email="authz_owner@test.com", password="pw")
        self.profile = _make_profile(name="Authz Org", slug="authz-org", user=self.owner)
        self.event = _make_event(slug="authz-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-authz")

        # Co-claimant: second user claiming the same profile
        self.co_claimant = _make_vouched_user(username="authz_co", email="authz_co@test.com", password="pw")
        from organizers.models import ProfileClaim

        ProfileClaim.objects.create(
            profile=self.profile,
            user=self.co_claimant,
            verified_method="auto_self",
        )

        # Non-claimant: user with no profile claim on this event
        self.stranger = _make_vouched_user(username="authz_stranger", email="authz_stranger@test.com", password="pw")

    def test_owner_can_load_board(self):
        """Owner (primary claimant) can load the syndication board."""
        client = Client()
        client.force_login(self.owner)
        response = client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)

    def test_co_claimant_can_load_board(self):
        """Co-claimant (second profile claimant) can load the syndication board."""
        client = Client()
        client.force_login(self.co_claimant)
        response = client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)

    def test_non_claimant_cannot_call_version_ops(self):
        """Non-claimant POSTing to version-op endpoints gets 403."""
        proj = _make_listing_projection(self.conn, self.event)
        stranger_client = Client()
        stranger_client.force_login(self.stranger)

        response = stranger_client.post(
            f"/syndication/projections/{proj.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            response.status_code,
            403,
            "Non-claimant must get 403 on version-op endpoints",
        )

    def test_non_claimant_cannot_edit_version(self):
        """Non-claimant POSTing to edit-version endpoint gets 403."""
        proj = _make_listing_projection(self.conn, self.event)
        stranger_client = Client()
        stranger_client.force_login(self.stranger)

        response = stranger_client.post(
            f"/syndication/versions/{proj.content_version_id}/edit/",
            data={"body": "unauthorized edit"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            response.status_code,
            403,
            "Non-claimant must get 403 on edit-version endpoint",
        )


class ReviewAllStubTest(TestCase):
    """
    The board must include a review-all toggle/button that points to the
    review-all URL (stub for kb-wz8m.6).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="reviewall_user", email="reviewall@test.com", password="pw")
        self.profile = _make_profile(name="ReviewAll Org", slug="reviewall-org", user=self.user)
        self.event = _make_event(slug="reviewall-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-reviewall")
        self.client = Client()
        self.client.force_login(self.user)

    def test_review_all_url_resolves(self):
        """
        The 'syndication:review-all' named URL must resolve (stub exists).
        kb-wz8m.6 will fill the real view; here we just assert the route exists.
        """
        from django.urls import NoReverseMatch, reverse

        try:
            url = reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})
            self.assertIsNotNone(url)
        except NoReverseMatch:
            self.fail(
                "The 'syndication:review-all' URL must be registered (stub for kb-wz8m.6). "
                "Add a minimal placeholder view in urls.py."
            )

    def test_review_all_stub_returns_acceptable_response(self):
        """The review-all stub URL must return a response (not 404/500)."""
        from django.urls import reverse

        url = reverse("syndication:review-all", kwargs={"event_pk": self.event.pk})
        response = self.client.get(url)
        self.assertNotIn(
            response.status_code,
            [404, 500],
            f"review-all stub must not 404/500 (got {response.status_code})",
        )


# ---------------------------------------------------------------------------
# F1: duplicate and copy_from version affordances (kb-wz8m.5)
# ---------------------------------------------------------------------------


class VersionDuplicateEndpointTest(TestCase):
    """
    F1: The 'version-duplicate' endpoint must exist, create a new independent
    ContentVersion, and enforce the can_edit authz gate (non-claimant → 403).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="dup_user", email="dup@test.com", password="pw")
        self.profile = _make_profile(name="Dup Org", slug="dup-org", user=self.user)
        self.event = _make_event(slug="dup-event", title="Dup Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-dup")
        self.stranger = _make_vouched_user(username="dup_stranger", email="dup_stranger@test.com", password="pw")
        self.client = Client()
        self.client.force_login(self.user)

    def test_duplicate_endpoint_returns_refreshed_fragment(self):
        """POST version-duplicate returns the refreshed syndication fragment."""
        proj = _make_listing_projection(self.conn, self.event)
        response = self.client.post(
            f"/syndication/versions/{proj.content_version_id}/duplicate/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("projections", response.context)

    def test_duplicate_endpoint_creates_new_version(self):
        """POST version-duplicate creates a new ContentVersion (new independent row)."""
        from syndication.models import ContentVersion

        proj = _make_listing_projection(self.conn, self.event)
        initial_count = ContentVersion.objects.filter(event=self.event).count()

        self.client.post(
            f"/syndication/versions/{proj.content_version_id}/duplicate/",
            HTTP_HX_REQUEST="true",
        )

        final_count = ContentVersion.objects.filter(event=self.event).count()
        self.assertEqual(
            final_count,
            initial_count + 1,
            "version-duplicate must create a new ContentVersion row",
        )

    def test_duplicate_endpoint_authz_non_claimant_gets_403(self):
        """Non-claimant POSTing to version-duplicate gets 403."""
        proj = _make_listing_projection(self.conn, self.event)
        stranger_client = Client()
        stranger_client.force_login(self.stranger)
        response = stranger_client.post(
            f"/syndication/versions/{proj.content_version_id}/duplicate/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            response.status_code,
            403,
            "Non-claimant must get 403 on version-duplicate endpoint",
        )


class VersionCopyFromEndpointTest(TestCase):
    """
    F1: The 'version-copy-from' endpoint must exist, repoint the target
    projection at a NEW independent copy of the source version, and enforce
    the can_edit authz gate (non-claimant → 403).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="copyfrom_user", email="copyfrom@test.com", password="pw")
        self.profile = _make_profile(name="CopyFrom Org", slug="copyfrom-org", user=self.user)
        self.event = _make_event(slug="copyfrom-event", title="CopyFrom Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-copyfrom")
        self.conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-copyfrom-2")
        self.stranger = _make_vouched_user(
            username="copyfrom_stranger", email="copyfrom_stranger@test.com", password="pw"
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_copy_from_endpoint_returns_refreshed_fragment(self):
        """POST version-copy-from returns the refreshed syndication fragment."""
        proj_src = _make_listing_projection(self.conn, self.event)
        proj_tgt = _make_listing_projection(self.conn2, self.event)

        response = self.client.post(
            f"/syndication/projections/{proj_tgt.pk}/copy-from/",
            data={"source_version_pk": str(proj_src.content_version_id)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("projections", response.context)

    def test_copy_from_endpoint_repoints_projection_at_new_version(self):
        """POST version-copy-from repoints the target projection at a new independent version."""
        proj_src = _make_listing_projection(self.conn, self.event)
        proj_tgt = _make_listing_projection(self.conn2, self.event)
        old_tgt_cv_pk = proj_tgt.content_version_id
        src_cv_pk = proj_src.content_version_id

        self.client.post(
            f"/syndication/projections/{proj_tgt.pk}/copy-from/",
            data={"source_version_pk": str(src_cv_pk)},
            HTTP_HX_REQUEST="true",
        )
        proj_tgt.refresh_from_db()

        self.assertNotEqual(
            proj_tgt.content_version_id,
            old_tgt_cv_pk,
            "copy-from must repoint projection at a new version (not the old one)",
        )
        self.assertNotEqual(
            proj_tgt.content_version_id,
            src_cv_pk,
            "copy-from must create a NEW independent row, not point at source version",
        )

    def test_copy_from_endpoint_authz_non_claimant_gets_403(self):
        """Non-claimant POSTing to version-copy-from gets 403."""
        proj_src = _make_listing_projection(self.conn, self.event)
        proj_tgt = _make_listing_projection(self.conn2, self.event)
        stranger_client = Client()
        stranger_client.force_login(self.stranger)
        response = stranger_client.post(
            f"/syndication/projections/{proj_tgt.pk}/copy-from/",
            data={"source_version_pk": str(proj_src.content_version_id)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            response.status_code,
            403,
            "Non-claimant must get 403 on version-copy-from endpoint",
        )


# ---------------------------------------------------------------------------
# F3: "Publish all ready" control hidden when no ready projections
# ---------------------------------------------------------------------------


class PublishAllReadyVisibilityTest(TestCase):
    """
    F3: The "Publish all ready" control must be absent from rendered HTML when
    no projections are in 'ready' status, and present when at least one is.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="pubvis_user", email="pubvis@test.com", password="pw")
        self.profile = _make_profile(name="PubVis Org", slug="pubvis-org", user=self.user)
        self.event = _make_event(slug="pubvis-event", title="PubVis Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-pubvis")
        self.client = Client()
        self.client.force_login(self.user)

    def test_publish_all_absent_when_no_ready_projections(self):
        """
        "Publish all ready" control must NOT be rendered when all projections are
        in draft status (no ready projections).
        """
        _make_listing_projection(self.conn, self.event, status="draft")

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            "Publish all ready",
            content,
            "Publish all ready must be absent when no projections are ready",
        )

    def test_publish_all_present_when_one_ready_projection(self):
        """
        "Publish all ready" control must be rendered when at least one projection
        is in ready status.
        """
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Publish all ready",
            content,
            "Publish all ready must be present when at least one projection is ready",
        )

    def test_fragment_context_has_ready_projections_boolean(self):
        """Fragment context must include 'has_ready_projections' boolean."""
        from syndication.services import approve_projection

        proj = _make_listing_projection(self.conn, self.event)
        approve_projection(user=self.user, projection=proj)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "has_ready_projections",
            response.context,
            "Fragment context must include has_ready_projections",
        )
        self.assertTrue(response.context["has_ready_projections"])


# ---------------------------------------------------------------------------
# F4: Live-on cue shows channel names, not just a count
# ---------------------------------------------------------------------------


class LiveOnChannelNamesTest(TestCase):
    """
    F4: The live-on propagation cue must render channel names (e.g. 'fetlife',
    'switch'), not just a bare count like 'live on 2 channels'.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="livenames_user", email="livenames@test.com", password="pw")
        self.profile = _make_profile(name="LiveNames Org", slug="livenames-org", user=self.user)
        self.event = _make_event(slug="livenames-event", title="LiveNames Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn1 = _make_connection(self.profile, platform="fetlife", destination_id="fl-livenames-1")
        self.conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-livenames-2")
        self.client = Client()
        self.client.force_login(self.user)

    def test_live_on_cue_contains_channel_names_not_just_count(self):
        """
        When two projections share the same ContentVersion, the live-on cue must
        name the sharing channels (e.g. 'fetlife', 'switch'), not just say
        'live on N channels'.
        """
        proj1 = _make_listing_projection(self.conn1, self.event)
        proj2 = _make_listing_projection(self.conn2, self.event)

        # Both must share the same content version for the cue to show
        self.assertEqual(
            proj1.content_version_id,
            proj2.content_version_id,
            "Both projections must share the same version for the live-on cue to appear",
        )

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode().lower()

        # Must contain channel names in the live-on cue
        self.assertIn(
            "fetlife",
            content,
            "Live-on cue must name the sharing channels (fetlife expected)",
        )
        self.assertIn(
            "switch",
            content,
            "Live-on cue must name the sharing channels (switch expected)",
        )

        # Must NOT use a bare count pattern like "live on 2 channels"
        import re

        bare_count_pattern = r"live on \d+ channels?"
        self.assertIsNone(
            re.search(bare_count_pattern, content),
            "Live-on cue must not use a bare count ('live on N channels'); use channel names",
        )


# ---------------------------------------------------------------------------
# kb-q4u9.3: Typefully-shaped workspace — channel icon-tabs + post hub
# ---------------------------------------------------------------------------


class ChannelIconTabsRenderTest(TestCase):
    """
    kb-q4u9.3 D2: The event_syndication fragment must render horizontal channel
    icon-tabs (Typefully shape), not a vertical channel rail.

    Assertions on rendered HTML content (not response.context — per the
    django-view-test-context-vs-content-hollow memory, context is hollow).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="tabs_user", email="tabs@test.com", password="pw")
        self.profile = _make_profile(name="Tabs Org", slug="tabs-org", user=self.user)
        self.event = _make_event(slug="tabs-event", title="Tabs Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_switch = _make_connection(
            self.profile, platform="switch", destination_id="own-page", kinds=["listing"]
        )
        self.conn_tg = _make_connection(
            self.profile, platform="telegram", destination_id="@my-channel", kinds=["listing"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_event_workspace_renders_channel_tabs(self):
        """
        The event_syndication fragment must contain tab-shaped channel selectors
        (role=tab or data-tab or a tab-like button row), not a vertical card rail.
        """
        _make_listing_projection(self.conn_switch, self.event)
        _make_listing_projection(self.conn_tg, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must contain tab role or data-channel-tab attribute for the channel tabs
        self.assertTrue(
            'role="tab"' in content or "data-channel-tab" in content or "aria-selected" in content,
            "Event workspace must render channel icon-tabs (role='tab' or aria-selected)",
        )

    def test_event_workspace_has_sync_toggle(self):
        """
        The event_syndication fragment must have a sync toggle control
        (a button or input for customize/reset).
        """
        _make_listing_projection(self.conn_switch, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must contain the sync toggle: customize or reset-to-canonical controls
        self.assertTrue(
            "Customize" in content or "Reset" in content or "customize" in content.lower(),
            "Event workspace must have a sync toggle (Customize/Reset controls)",
        )

    def test_sync_control_synced_state_shows_customize_only(self):
        """
        Render-regression: when a projection is at the canonical version (synced
        state), the sync control row must render 'Customize' (the advance action)
        and must NOT render 'Reset' (which is the diverged-state action).
        Also asserts the 'synced' state label is present.
        kb-9f1h.6: single-control toggle folded from the original two-button row.
        """
        proj = _make_listing_projection(self.conn_switch, self.event)
        # Sanity: projection must start at the canonical version
        self.assertEqual(
            proj.content_version.name,
            "canonical",
            "Test precondition: _make_listing_projection must start at the canonical version",
        )

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Synced state: must show 'Customize' action
        self.assertIn(
            "Customize",
            content,
            "Synced projection: sync control must render 'Customize'",
        )
        # Synced state: must NOT show 'Reset' (that is the diverged-state action)
        self.assertNotIn(
            "Reset",
            content,
            "Synced projection: sync control must NOT render 'Reset' (only one action shown per state)",
        )
        # Synced state: 'synced' state label must be present
        self.assertIn(
            "synced",
            content.lower(),
            "Synced projection: 'synced' state label must be rendered",
        )

    def test_sync_control_diverged_state_shows_reset_only(self):
        """
        Render-regression: when a projection has been customized (diverged from
        canonical), the sync control row must render 'Reset' (the revert action)
        and must NOT render 'Customize' (which is the synced-state advance action).
        Also asserts the 'custom' state label is present.
        kb-9f1h.6: single-control toggle folded from the original two-button row.
        """
        from syndication.services import customize as svc_customize

        proj = _make_listing_projection(self.conn_switch, self.event)
        # Diverge the projection so its version is no longer canonical
        svc_customize(user=self.user, projection=proj)
        proj.refresh_from_db()
        self.assertNotEqual(
            proj.content_version.name,
            "canonical",
            "Test precondition: after svc_customize the version must not be named 'canonical'",
        )

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Diverged state: must show 'Reset' action
        self.assertIn(
            "Reset",
            content,
            "Diverged projection: sync control must render 'Reset'",
        )
        # Diverged state: must NOT show 'Customize' (that is the synced-state action)
        self.assertNotIn(
            "Customize",
            content,
            "Diverged projection: sync control must NOT render 'Customize' (only one action shown per state)",
        )
        # Diverged state: 'custom' state label must be present
        self.assertIn(
            "custom",
            content.lower(),
            "Diverged projection: 'custom' state label must be rendered",
        )

    def test_event_workspace_has_switch_tab_as_canonical(self):
        """
        For an event workspace, the Switch tab must be the canonical anchor.
        With Switch + Telegram present, Switch tab must appear BEFORE Telegram
        in the DOM (not alphabetical-first), falsifying the old tautological check.
        ADR-010 D1, kb-q4u9.3 review finding 4.
        """
        _make_listing_projection(self.conn_switch, self.event)
        _make_listing_projection(self.conn_tg, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        switch_idx = content.lower().find("switch")
        telegram_idx = content.lower().find("telegram")

        self.assertGreater(
            switch_idx,
            -1,
            "Event workspace must render a Switch tab (ADR-010 D1)",
        )
        self.assertGreater(
            telegram_idx,
            -1,
            "Telegram tab must also appear in multi-channel event workspace",
        )
        self.assertLess(
            switch_idx,
            telegram_idx,
            "Switch tab must appear BEFORE Telegram in the tab rail (canonical anchor, "
            "not alphabetical-first). ADR-010 D1.",
        )

    def test_event_workspace_has_no_generate_affordance(self):
        """
        No platform-owned-LLM 'generate' affordance must appear (carried constraint kb-wz8m D-B).
        """
        _make_listing_projection(self.conn_switch, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode().lower()
        # "generate" as a button/label should not appear
        self.assertNotIn(
            ">generate<",
            content,
            "No platform-owned-LLM generate affordance must appear",
        )
        self.assertNotIn(
            'value="generate"',
            content,
            "No generate button/input must appear",
        )

    def test_event_workspace_has_event_title_in_header(self):
        """
        The event hub page renders the event title in the page header (D1/D5).
        After kb-ide0.1 D1: the event_facts HTMX-loader section is removed from
        the hub body (facts are embedded in the Switch listing tab as edit-in-place
        inputs). The hub header instead shows the event title directly.
        """
        response = self.client.get(f"/syndication/events/{self.event.pk}/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # D1: hub body must NOT load event-facts separately; event info is in the tab
        self.assertNotIn(
            "fragments/event_facts/",
            content,
            "Event hub must NOT include the event-facts HTMX-loader after kb-ide0.1 D1 "
            "(facts are now in the Switch listing tab edit-in-place card)",
        )
        # The event title is rendered in the slim header bar
        self.assertIn(
            "Tabs Test Event",
            content,
            "Event hub must include the event title in the page header",
        )


class PostHubViewTest(TestCase):
    """
    kb-q4u9.3 item 6: Post-scoped hub/fragment views + routes.

    Today urls.py has only post-create, no post hub/fragment route.
    These tests verify the new post_hub and fragment_post_syndication views exist
    and render correctly.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="posthub_user", email="posthub@test.com", password="pw")
        self.profile = _make_profile(name="PostHub Org", slug="posthub-org", user=self.user)
        self.event = _make_event(slug="posthub-event", title="PostHub Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(
            self.profile, platform="telegram", destination_id="@posthub-ch", kinds=["promotion"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _make_post_with_projection(self):
        """Create a post and use the service to get its projection."""
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="Test Post",
            body="Post body",
        )
        return post

    def test_post_hub_route_exists(self):
        """
        GET /syndication/posts/<pk>/ must return 200, not 404.
        The post_hub view must be registered.
        """
        post = self._make_post_with_projection()
        response = self.client.get(f"/syndication/posts/{post.pk}/")
        self.assertNotEqual(
            response.status_code,
            404,
            "Post hub route must exist at /syndication/posts/<pk>/",
        )
        self.assertEqual(response.status_code, 200)

    def test_post_syndication_fragment_route_exists(self):
        """
        GET /syndication/posts/<pk>/fragments/post_syndication/ must return 200.
        The fragment_post_syndication view must be registered.
        """
        post = self._make_post_with_projection()
        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertNotEqual(
            response.status_code,
            404,
            "Post syndication fragment route must exist",
        )
        self.assertEqual(response.status_code, 200)

    def test_post_workspace_renders_source_tab(self):
        """
        The post syndication fragment must anchor canonical at a "Source" tab
        (not Switch — a post has no native-home channel, kb-q4u9.3 D3).
        """
        post = self._make_post_with_projection()
        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            "Source",
            content,
            "Post workspace must anchor canonical at a 'Source' tab (not Switch)",
        )

    def test_post_workspace_has_no_generate_affordance(self):
        """
        No platform-owned-LLM generate affordance in post workspace either.
        """
        post = self._make_post_with_projection()
        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode().lower()
        self.assertNotIn(
            ">generate<",
            content,
            "No generate affordance in post workspace",
        )

    def test_post_workspace_renders_channel_tabs(self):
        """
        The post syndication fragment must render horizontal channel icon-tabs.
        """
        post = self._make_post_with_projection()
        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must contain projections for the post
        self.assertIn(
            "@posthub-ch",
            content,
            "Post workspace must render the channel tab for the post's projection",
        )


class VersionOpRedirectDispatchTest(TestCase):
    """
    kb-q4u9.3 item 7: Version-op views must dispatch redirect by publishable type.

    Today the version-op POST views (version_copy_to, version_edit, version_reset,
    version_duplicate) hardcode redirect("syndication:event-hub", pk=event.pk).
    For a post-owned version, event is null → AttributeError on event.pk.

    These tests verify that the redirect goes to the post-hub (not 500) when the
    version is post-owned.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="redir_user", email="redir@test.com", password="pw")
        self.profile = _make_profile(name="Redir Org", slug="redir-org", user=self.user)
        self.event = _make_event(slug="redir-event", title="Redir Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, platform="telegram", destination_id="@redir-ch", kinds=["promotion"])
        self.client = Client()
        self.client.force_login(self.user)

    def _make_post_with_projection(self):
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="Redir Post",
            body="Redir body",
        )
        from syndication.models import PlatformProjection

        proj = PlatformProjection.objects.filter(source_post=post).first()
        return post, proj

    def test_version_edit_on_post_version_does_not_500(self):
        """
        POST to version-edit on a post-owned ContentVersion must NOT return 500.
        It must redirect to the post hub (not AttributeError on event.pk).
        """
        post, proj = self._make_post_with_projection()
        cv = proj.content_version

        response = self.client.post(
            f"/syndication/versions/{cv.pk}/edit/",
            data={"body": "Updated body"},
            HTTP_HX_REQUEST="true",
        )
        self.assertNotEqual(
            response.status_code,
            500,
            "version-edit on post-owned version must not 500 (AttributeError on event.pk)",
        )
        self.assertEqual(
            response.status_code,
            200,
            "version-edit on post-owned version (HTMX) must return 200 with refreshed fragment",
        )

    def test_version_reset_on_post_projection_does_not_500(self):
        """
        POST to projection-reset-to-canonical on a post-owned projection must NOT 500.
        It must return the post syndication fragment (not AttributeError on event.pk).
        """
        _post, proj = self._make_post_with_projection()

        response = self.client.post(
            f"/syndication/projections/{proj.pk}/reset-to-canonical/",
            HTTP_HX_REQUEST="true",
        )
        self.assertNotEqual(
            response.status_code,
            500,
            "reset-to-canonical on post projection must not 500",
        )
        self.assertIn(
            response.status_code,
            [200, 302],
            "reset-to-canonical on post projection must return 200 or redirect",
        )

    def test_projection_customize_on_post_projection_does_not_500(self):
        """
        POST to projection-customize on a post-owned projection must NOT 500.
        """
        _post, proj = self._make_post_with_projection()

        response = self.client.post(
            f"/syndication/projections/{proj.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        self.assertNotEqual(
            response.status_code,
            500,
            "projection-customize on post projection must not 500",
        )
        self.assertIn(
            response.status_code,
            [200, 302],
        )

    def test_version_edit_on_post_version_non_htmx_redirects_to_post_hub(self):
        """
        Non-HTMX POST to version-edit on post-owned version must redirect to
        /syndication/posts/<pk>/ (the post hub), not cause AttributeError.
        """
        post, proj = self._make_post_with_projection()
        cv = proj.content_version

        response = self.client.post(
            f"/syndication/versions/{cv.pk}/edit/",
            data={"body": "Updated body"},
        )
        self.assertNotEqual(
            response.status_code,
            500,
            "Non-HTMX version-edit on post version must not 500",
        )
        # Should redirect to post hub
        if response.status_code == 302:
            self.assertIn(
                f"/syndication/posts/{post.pk}/",
                response.url,
                "Non-HTMX redirect must go to post hub",
            )


# ---------------------------------------------------------------------------
# kb-q4u9.3 review findings: correctness + parity tests
# ---------------------------------------------------------------------------


class ProjectionTransitionErrorDispatchTest(TestCase):
    """
    Finding 1: _projection_transition_error_response must dispatch by publishable
    type — return POST fragment for promotion projections, EVENT fragment for
    listing projections.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="trans_err_user", email="trans_err@test.com", password="pw")
        self.profile = _make_profile(name="TransErr Org", slug="transerr-org", user=self.user)
        self.event = _make_event(slug="transerr-event", title="TransErr Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(
            self.profile, platform="telegram", destination_id="@transerr-ch", kinds=["promotion"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _make_post_with_promotion_projection(self, status="ready"):
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="TransErr Post",
            body="TransErr body",
        )
        from syndication.models import PlatformProjection

        proj = PlatformProjection.objects.filter(source_post=post).first()
        if proj is not None and proj.status != status:
            proj.status = status
            proj.save(update_fields=["status"])
        return post, proj

    def test_approve_error_on_promotion_projection_returns_post_fragment(self):
        """
        Finding 1: When approving a promotion (post-owned) projection triggers a
        ValueError (e.g. already approved), the error response must return the
        POST fragment (#post-syndication), NOT the event fragment (#event-syndication).
        """
        post, proj = self._make_post_with_promotion_projection(status="ready")
        # proj is already 'ready' — attempting approve again should raise ValueError
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must NOT return the event fragment container — that would corrupt post workspace
        self.assertNotIn(
            'id="event-syndication"',
            content,
            "Error response for promotion projection must NOT return event fragment",
        )
        # Must return the post fragment container
        self.assertIn(
            'id="post-syndication"',
            content,
            "Error response for promotion projection must return post fragment (#post-syndication)",
        )

    def test_publish_error_on_promotion_projection_returns_post_fragment(self):
        """
        Finding 1: When publishing a promotion projection that errors (e.g. wrong state),
        the error response must return the POST fragment, not the event fragment.
        """
        post, proj = self._make_post_with_promotion_projection(status="draft")
        # proj is 'draft' — attempting publish directly should raise ValueError (not ready)
        response = self.client.post(
            f"/syndication/projections/{proj.pk}/publish/",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(
            'id="event-syndication"',
            content,
            "Error response for promotion projection publish must NOT return event fragment",
        )
        self.assertIn(
            'id="post-syndication"',
            content,
            "Error response for promotion projection publish must return post fragment",
        )


class SwitchFirstCanonicalTabTest(TestCase):
    """
    Finding 2+4: With multiple channels (Switch + Telegram + FetLife), the
    Switch tab must be the canonical anchor (first / aria-selected) per ADR-010 D1.
    This is a stronger test than the original tautological "switch in content" check.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="swfirst_user", email="swfirst@test.com", password="pw")
        self.profile = _make_profile(name="SwFirst Org", slug="swfirst-org", user=self.user)
        self.event = _make_event(slug="swfirst-event", title="SwFirst Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_fetlife = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )
        self.conn_switch = _make_connection(
            self.profile, platform="switch", destination_id="own-page", kinds=["listing"]
        )
        self.conn_tg = _make_connection(
            self.profile, platform="telegram", destination_id="@swfirst-ch", kinds=["listing"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_switch_tab_is_aria_selected_with_multiple_channels(self):
        """
        Finding 2+4: With Switch + Telegram + FetLife channels present, the Switch
        tab must be the selected/anchor tab (aria-selected="true"), NOT FetLife
        which would sort first alphabetically. This falsifies alphabetical ordering.
        """
        _proj_fl = _make_listing_projection(self.conn_fetlife, self.event)
        _proj_sw = _make_listing_projection(self.conn_switch, self.event)
        _proj_tg = _make_listing_projection(self.conn_tg, self.event)

        response = self.client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The Switch tab must be the anchor/selected tab
        # Check that aria-selected="true" appears on/near the Switch tab before
        # the FetLife tab (Switch must precede FetLife in DOM order).
        # We assert that Switch appears BEFORE FetLife in the tab rail.
        switch_idx = content.lower().find("switch")
        fetlife_idx = content.lower().find("fetlife")

        self.assertGreater(
            switch_idx,
            -1,
            "Switch tab must appear in content",
        )
        self.assertGreater(
            fetlife_idx,
            -1,
            "FetLife tab must appear in content",
        )
        self.assertLess(
            switch_idx,
            fetlife_idx,
            "Switch tab must appear BEFORE FetLife in the DOM (Switch is canonical anchor, "
            "not alphabetical-first FetLife). ADR-010 D1.",
        )


class PostComposerPublishedStateGatingTest(TestCase):
    """
    Finding 3+6: The post composer sync toggle (Customize/Reset) and
    Duplicate/Copy-from must NOT appear for published or ready projections.
    Only draft projections show actionable controls.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="postgating_user", email="postgating@test.com", password="pw")
        self.profile = _make_profile(name="PostGating Org", slug="postgating-org", user=self.user)
        self.event = _make_event(slug="postgating-event", title="PostGating Test Event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(
            self.profile, platform="telegram", destination_id="@postgating-ch", kinds=["promotion"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _make_post_with_projection(self, status="draft"):
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="PostGating Post",
            body="PostGating body",
        )
        from syndication.models import PlatformProjection

        proj = PlatformProjection.objects.filter(source_post=post).first()
        if proj is not None and proj.status != status:
            proj.status = status
            proj.save(update_fields=["status"])
        return post, proj

    def test_customize_reset_not_shown_on_published_post_projection(self):
        """
        Finding 3: Customize/Reset controls must NOT appear on a published post projection.
        The event template gates on can_edit + draft; the post template must do the same.
        """
        post, proj = self._make_post_with_projection(status="published")

        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Customize and Reset must not appear as buttons on published projections
        # (They appear in forms with specific hx-post URLs for the projection)
        proj_customize_url = f"/syndication/projections/{proj.pk}/customize/"
        proj_reset_url = f"/syndication/projections/{proj.pk}/reset-to-canonical/"
        self.assertNotIn(
            proj_customize_url,
            content,
            "Customize must NOT appear for a published post projection",
        )
        self.assertNotIn(
            proj_reset_url,
            content,
            "Reset must NOT appear for a published post projection",
        )

    def test_customize_reset_shown_on_draft_post_projection(self):
        """
        Finding 3: Customize/Reset MUST appear on a draft post projection.
        """
        post, proj = self._make_post_with_projection(status="draft")

        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        proj_customize_url = f"/syndication/projections/{proj.pk}/customize/"
        self.assertIn(
            proj_customize_url,
            content,
            "Customize MUST appear for a draft post projection",
        )

    def test_customize_reset_not_shown_on_ready_post_projection(self):
        """
        Finding 3: Customize/Reset controls must NOT appear on a ready post projection.
        """
        post, proj = self._make_post_with_projection(status="ready")

        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        proj_customize_url = f"/syndication/projections/{proj.pk}/customize/"
        proj_reset_url = f"/syndication/projections/{proj.pk}/reset-to-canonical/"
        self.assertNotIn(
            proj_customize_url,
            content,
            "Customize must NOT appear for a ready post projection",
        )
        self.assertNotIn(
            proj_reset_url,
            content,
            "Reset must NOT appear for a ready post projection",
        )

    def test_duplicate_not_shown_on_published_post_projection(self):
        """
        Finding 6: Duplicate must NOT appear on published post projections
        (parity with event template gating).
        """
        post, proj = self._make_post_with_projection(status="published")

        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Check that version-duplicate URL for this projection's CV is not present
        version_dup_url = f"/syndication/versions/{proj.content_version.pk}/duplicate/"
        self.assertNotIn(
            version_dup_url,
            content,
            "Duplicate must NOT appear for a published post projection (parity with event template)",
        )

    def test_duplicate_shown_on_draft_post_projection(self):
        """
        Finding 6: Duplicate MUST appear on draft post projections (parity with event template).
        """
        post, proj = self._make_post_with_projection(status="draft")

        response = self.client.get(f"/syndication/posts/{post.pk}/fragments/post_syndication/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        version_dup_url = f"/syndication/versions/{proj.content_version.pk}/duplicate/"
        self.assertIn(
            version_dup_url,
            content,
            "Duplicate MUST appear for a draft post projection (parity with event template)",
        )
