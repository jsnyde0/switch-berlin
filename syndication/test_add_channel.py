"""
TDD tests for kb-96tn.4: add_projection / reconcile_projections service verbs
and the add-channel / remove-channel view endpoints.

Harness signal:
(a) Unit tests: add_projection(event, conn) creates exactly one draft when none
    exists; idempotent on re-call; raises ValueError on wrong-kind mismatch;
    remove-channel POST on a published projection returns HTTP 400 with a
    non-empty reason string.
(b) View tests: POST add-channel returns 200 with the new channel's platform
    in the content.

ADR-016 D4 (post-hoc projection reconciliation); ADR-008 D3 (fail loud);
ADR-017 D1 (can_edit gate).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers (mirror test_authoring.py helpers)
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


def _make_connection(profile, platform="fetlife", destination_id="fl-user", kinds=None, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds if kinds is not None else ["listing"],
        enabled=enabled,
    )


def _make_event(profile, title="Test Event", slug="test-event"):
    event = Event.objects.create(title=title, slug=slug, start=timezone.now())
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    # Create canonical ContentVersion (required by A1 invariant)
    from syndication.services import _ensure_canonical_content_version

    _ensure_canonical_content_version(event=event)
    return event


def _make_post(event, profile):
    from syndication.models import Post as _Post
    from syndication.services import _ensure_canonical_content_version

    post = _Post.objects.create(event=event, headline="Test Post", body="Test body")
    _ensure_canonical_content_version(post=post)
    return post


# ---------------------------------------------------------------------------
# 1. add_projection service verb — unit tests (TDD RED first)
# ---------------------------------------------------------------------------


class AddProjectionServiceTest(TestCase):
    """
    syndication.services.add_projection(publishable, connection):
    - Creates exactly one draft PlatformProjection for Event x connection if none exists.
    - Idempotent: re-call returns the existing projection without creating a duplicate.
    - Raises ValueError if connection.kinds does not include the applicable kind.
    - NEVER touches a published projection.
    ADR-016 D4; ADR-008 D3.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="add_proj_user", email="add_proj@test.com", password="x")
        self.profile = _make_profile(name="Add Proj Profile", slug="add-proj-profile", user=self.user)
        self.event = _make_event(self.profile)
        self.listing_conn = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )

    def test_add_projection_creates_one_draft_when_none_exists(self):
        """add_projection creates exactly one draft projection for event x connection."""
        from syndication.services import add_projection

        proj = add_projection(self.event, self.listing_conn)

        self.assertIsNotNone(proj.pk)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)
        self.assertEqual(proj.kind, PlatformProjection.Kind.LISTING)
        self.assertEqual(proj.source_event, self.event)
        self.assertEqual(proj.connection, self.listing_conn)
        # Exactly one projection exists for this pair
        count = PlatformProjection.objects.filter(source_event=self.event, connection=self.listing_conn).count()
        self.assertEqual(count, 1)

    def test_add_projection_idempotent_returns_existing(self):
        """Re-calling add_projection returns the existing projection, never duplicates."""
        from syndication.services import add_projection

        proj1 = add_projection(self.event, self.listing_conn)
        proj2 = add_projection(self.event, self.listing_conn)

        # Same object — same pk
        self.assertEqual(proj1.pk, proj2.pk)
        # Count remains 1
        count = PlatformProjection.objects.filter(source_event=self.event, connection=self.listing_conn).count()
        self.assertEqual(count, 1)

    def test_add_projection_raises_value_error_on_wrong_kind_for_event(self):
        """
        add_projection raises ValueError when connection.kinds does not include
        'listing' (the applicable kind for an Event publishable).
        ADR-008 D3: fail loud — wrong-kind is a data-integrity error, not a silent no-op.
        """
        from syndication.services import add_projection

        promo_only_conn = _make_connection(
            self.profile, platform="telegram", destination_id="tg-channel", kinds=["promotion"]
        )

        with self.assertRaises(ValueError):
            add_projection(self.event, promo_only_conn)

    def test_add_projection_raises_value_error_on_wrong_kind_for_post(self):
        """
        add_projection raises ValueError when connection.kinds does not include
        'promotion' (the applicable kind for a Post publishable).
        """
        from syndication.services import add_projection

        listing_only_conn = _make_connection(
            self.profile, platform="switch", destination_id="own-page", kinds=["listing"]
        )
        post = _make_post(self.event, self.profile)

        with self.assertRaises(ValueError):
            add_projection(post, listing_only_conn)

    def test_add_projection_never_touches_published_projection(self):
        """
        If the existing projection is published, add_projection returns it WITHOUT
        modifying it (idempotent — never deletes or overwrites a published one).
        """
        from syndication.engine import transition_status
        from syndication.services import add_projection

        proj = add_projection(self.event, self.listing_conn)
        # Force to published by going through draft→ready→published
        cv = proj.content_version
        cv.body = "Some content"
        cv.save(update_fields=["body"])
        transition_status(proj, "ready")
        transition_status(proj, "published")

        # Re-calling add_projection should return the same published projection
        proj_again = add_projection(self.event, self.listing_conn)
        self.assertEqual(proj.pk, proj_again.pk)
        self.assertEqual(proj_again.status, PlatformProjection.Status.PUBLISHED)

    def test_add_projection_fks_to_canonical_content_version(self):
        """add_projection wires the new projection to the canonical content_version."""
        from syndication.models import ContentVersion
        from syndication.services import add_projection

        proj = add_projection(self.event, self.listing_conn)

        canonical_cv = ContentVersion.objects.get(event=self.event, name="canonical")
        self.assertEqual(proj.content_version, canonical_cv)

    def test_add_projection_for_post_creates_promotion_kind(self):
        """add_projection on a Post x promotion-capable connection creates a PROMOTION projection."""
        from syndication.services import add_projection

        promo_conn = _make_connection(
            self.profile, platform="telegram", destination_id="tg-channel", kinds=["promotion"]
        )
        post = _make_post(self.event, self.profile)

        proj = add_projection(post, promo_conn)

        self.assertEqual(proj.kind, PlatformProjection.Kind.PROMOTION)
        self.assertEqual(proj.source_post, post)
        self.assertEqual(proj.status, PlatformProjection.Status.DRAFT)


# ---------------------------------------------------------------------------
# 2. reconcile_projections service verb — unit tests
# ---------------------------------------------------------------------------


class ReconcileProjectionsServiceTest(TestCase):
    """
    syndication.services.reconcile_projections(publishable):
    - For every enabled connection on the organizer that supports the kind,
      calls add_projection; returns the list of newly-created projections.
    - Existing projections are not duplicated (idempotency via add_projection).
    ADR-016 D4.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="reconcile_user", email="reconcile@test.com", password="x")
        self.profile = _make_profile(name="Reconcile Profile", slug="reconcile-profile", user=self.user)
        self.event = _make_event(self.profile)

    def test_reconcile_creates_projections_for_enabled_connections(self):
        """reconcile_projections creates new projections for enabled connections with no existing projection."""
        from syndication.services import reconcile_projections

        conn1 = _make_connection(self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"])
        conn2 = _make_connection(
            self.profile, platform="tickettailor", destination_id="tt-acc", kinds=["listing"]
        )

        created = reconcile_projections(self.event)

        self.assertEqual(len(created), 2)
        conn_ids = {p.connection_id for p in created}
        self.assertIn(conn1.pk, conn_ids)
        self.assertIn(conn2.pk, conn_ids)

    def test_reconcile_does_not_duplicate_existing_projections(self):
        """reconcile_projections skips connections that already have a projection."""
        from syndication.services import add_projection, reconcile_projections

        conn = _make_connection(self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"])
        # Pre-create the projection
        add_projection(self.event, conn)

        created = reconcile_projections(self.event)

        # Nothing newly created
        self.assertEqual(created, [])
        # Still exactly one projection
        self.assertEqual(PlatformProjection.objects.filter(source_event=self.event, connection=conn).count(), 1)

    def test_reconcile_returns_only_newly_created(self):
        """reconcile_projections returns ONLY the newly-created projections (not existing ones)."""
        from syndication.services import add_projection, reconcile_projections

        conn_existing = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )
        conn_new = _make_connection(
            self.profile, platform="tickettailor", destination_id="tt-acc", kinds=["listing"]
        )

        # Pre-create one
        add_projection(self.event, conn_existing)

        created = reconcile_projections(self.event)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].connection, conn_new)

    def test_reconcile_skips_disabled_connections(self):
        """reconcile_projections skips disabled connections."""
        from syndication.services import reconcile_projections

        _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"], enabled=False
        )

        created = reconcile_projections(self.event)

        self.assertEqual(created, [])

    def test_reconcile_skips_wrong_kind_connections(self):
        """reconcile_projections skips connections whose kinds don't include 'listing' for an Event."""
        from syndication.services import reconcile_projections

        _make_connection(
            self.profile, platform="telegram", destination_id="tg-channel", kinds=["promotion"], enabled=True
        )

        created = reconcile_projections(self.event)

        self.assertEqual(created, [])


# ---------------------------------------------------------------------------
# 3. add-channel view endpoint — POST tests
# ---------------------------------------------------------------------------


class AddChannelViewTest(TestCase):
    """
    POST /syndication/events/<pk>/add-channel/
    - requires can_edit (ADR-017)
    - calls add_projection service
    - returns HTMX swap of the syndication fragment (status 200)
    - response contains the new channel's platform name
    """

    def setUp(self):
        self.user = _make_vouched_user(username="add_ch_user", email="add_ch@test.com", password="x")
        self.profile = _make_profile(name="Add Ch Profile", slug="add-ch-profile", user=self.user)
        self.event = _make_event(self.profile)
        self.conn = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_add_channel_creates_projection_and_returns_200(self):
        """POST add-channel creates a projection and returns 200."""
        url = f"/syndication/events/{self.event.pk}/add-channel/"
        response = self.client.post(
            url,
            data={"connection_pk": self.conn.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        # Projection was created
        self.assertTrue(
            PlatformProjection.objects.filter(source_event=self.event, connection=self.conn).exists()
        )

    def test_add_channel_response_contains_platform_name(self):
        """HTMX response contains the new channel's platform name (fetlife)."""
        url = f"/syndication/events/{self.event.pk}/add-channel/"
        response = self.client.post(
            url,
            data={"connection_pk": self.conn.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fetlife")

    def test_add_channel_requires_login(self):
        """add-channel requires authentication."""
        anon_client = Client()
        url = f"/syndication/events/{self.event.pk}/add-channel/"
        response = anon_client.post(url, data={"connection_pk": self.conn.pk})
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])

    def test_add_channel_non_editor_gets_403(self):
        """A non-editor user gets 403."""
        stranger = _make_vouched_user(username="stranger_ch", email="stranger_ch@test.com", password="x")
        stranger_client = Client()
        stranger_client.force_login(stranger)
        url = f"/syndication/events/{self.event.pk}/add-channel/"
        response = stranger_client.post(url, data={"connection_pk": self.conn.pk})
        self.assertEqual(response.status_code, 403)

    def test_add_channel_idempotent_returns_200(self):
        """Re-POSTing add-channel for the same connection returns 200 (idempotent)."""
        url = f"/syndication/events/{self.event.pk}/add-channel/"
        self.client.post(url, data={"connection_pk": self.conn.pk}, HTTP_HX_REQUEST="true")
        response = self.client.post(url, data={"connection_pk": self.conn.pk}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        # Still exactly one projection
        self.assertEqual(
            PlatformProjection.objects.filter(source_event=self.event, connection=self.conn).count(), 1
        )


# ---------------------------------------------------------------------------
# 4. remove-channel view endpoint — POST / DELETE tests
# ---------------------------------------------------------------------------


class RemoveChannelViewTest(TestCase):
    """
    POST /syndication/projections/<pk>/remove-channel/
    - Removes/disables an UNPUBLISHED projection (200 + refreshed fragment).
    - Returns HTTP 400 with a VISIBLE non-empty reason when called on a PUBLISHED
      projection (ADR-008 D3: fail loud, never silent 200).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="rm_ch_user", email="rm_ch@test.com", password="x")
        self.profile = _make_profile(name="Rm Ch Profile", slug="rm-ch-profile", user=self.user)
        self.event = _make_event(self.profile)
        self.conn = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )
        # Create a draft projection to remove
        from syndication.services import add_projection

        self.projection = add_projection(self.event, self.conn)
        self.client = Client()
        self.client.force_login(self.user)

    def test_remove_channel_deletes_draft_projection_returns_200(self):
        """Removing an unpublished (draft) projection returns 200 and deletes it."""
        url = f"/syndication/projections/{self.projection.pk}/remove-channel/"
        response = self.client.post(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        # Projection should be deleted
        self.assertFalse(PlatformProjection.objects.filter(pk=self.projection.pk).exists())

    def test_remove_channel_published_returns_400_with_reason(self):
        """
        Removing a PUBLISHED projection returns HTTP 400 with a non-empty reason
        in the response body. ADR-008 D3: fail loud, visible error state.
        """
        from syndication.engine import transition_status

        # Advance to published
        cv = self.projection.content_version
        cv.body = "Some content"
        cv.save(update_fields=["body"])
        transition_status(self.projection, "ready")
        transition_status(self.projection, "published")

        url = f"/syndication/projections/{self.projection.pk}/remove-channel/"
        response = self.client.post(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 400)
        # Response body must contain a non-empty reason (ADR-008 D3: visible error)
        content = response.content.decode()
        self.assertTrue(len(content.strip()) > 0, "Response body must not be empty (ADR-008 D3)")
        # The reason should reference "published" or similar indicator
        self.assertTrue(
            "published" in content.lower() or "cannot" in content.lower() or "remove" in content.lower(),
            f"Response body should contain a visible reason, got: {content[:200]}",
        )

    def test_remove_channel_requires_login(self):
        """remove-channel requires authentication."""
        anon_client = Client()
        url = f"/syndication/projections/{self.projection.pk}/remove-channel/"
        response = anon_client.post(url)
        self.assertIn(response.status_code, [302, 403])

    def test_remove_channel_non_editor_gets_403(self):
        """A non-editor user gets 403."""
        stranger = _make_vouched_user(username="stranger_rm", email="stranger_rm@test.com", password="x")
        stranger_client = Client()
        stranger_client.force_login(stranger)
        url = f"/syndication/projections/{self.projection.pk}/remove-channel/"
        response = stranger_client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_remove_channel_ready_projection_also_returns_200(self):
        """
        Removing a 'ready' (not yet published) projection returns 200 and deletes it.
        'Ready' is unpublished — it has not reached an external platform yet.
        """
        from syndication.engine import transition_status

        cv = self.projection.content_version
        cv.body = "Some content"
        cv.save(update_fields=["body"])
        transition_status(self.projection, "ready")

        url = f"/syndication/projections/{self.projection.pk}/remove-channel/"
        response = self.client.post(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PlatformProjection.objects.filter(pk=self.projection.pk).exists())


# ---------------------------------------------------------------------------
# 5. "…" dropdown context — available connections in view context
# ---------------------------------------------------------------------------


class AddChannelDropdownContextTest(TestCase):
    """
    The event_syndication fragment context includes 'available_connections' —
    the list of enabled connections that support 'listing' but have no projection
    yet for this event. This powers the "…" toggle dropdown in the UI.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="dropdown_user", email="dropdown@test.com", password="x")
        self.profile = _make_profile(name="Dropdown Profile", slug="dropdown-profile", user=self.user)
        self.event = _make_event(self.profile)
        self.client = Client()
        self.client.force_login(self.user)

    def test_fragment_context_contains_available_connections(self):
        """
        fragment_event_syndication view includes 'available_connections' in context
        — enabled connections without a projection yet.
        """
        conn = _make_connection(self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"])
        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # available_connections should contain the fetlife connection
        self.assertIn("available_connections", response.context)
        available_pks = [c.pk for c in response.context["available_connections"]]
        self.assertIn(conn.pk, available_pks)

    def test_fragment_available_connections_excludes_projected_connections(self):
        """
        Connections that already have a projection for this event are excluded
        from available_connections (they are already projected — no need to add).
        """
        from syndication.services import add_projection

        conn_projected = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )
        conn_not_projected = _make_connection(
            self.profile, platform="tickettailor", destination_id="tt-acc", kinds=["listing"]
        )

        # Pre-create a projection for conn_projected
        add_projection(self.event, conn_projected)

        url = f"/syndication/events/{self.event.pk}/fragments/event_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        available_pks = [c.pk for c in response.context["available_connections"]]
        # conn_projected is already projected — should NOT be in available_connections
        self.assertNotIn(conn_projected.pk, available_pks)
        # conn_not_projected has no projection — SHOULD be in available_connections
        self.assertIn(conn_not_projected.pk, available_pks)


# ---------------------------------------------------------------------------
# 6. add_channel_post view endpoint — POST tests (kb-96tn.4 parity)
# ---------------------------------------------------------------------------


class AddChannelPostViewTest(TestCase):
    """
    POST /syndication/posts/<pk>/add-channel/
    - requires can_edit (ADR-017)
    - calls add_projection service (promotion kind for Post)
    - returns HTMX swap of the post_syndication fragment (status 200)
    - response contains the new channel's platform name
    Mirror of AddChannelViewTest for events, but scoped to Posts.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="add_ch_post_user", email="add_ch_post@test.com", password="x")
        self.profile = _make_profile(name="Add Ch Post Profile", slug="add-ch-post-profile", user=self.user)
        self.event = _make_event(self.profile)
        self.post = _make_post(self.event, self.profile)
        self.conn = _make_connection(
            self.profile, platform="telegram", destination_id="tg-channel", kinds=["promotion"]
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_add_channel_post_creates_projection_and_returns_200(self):
        """POST add-channel for a post creates a promotion projection and returns 200."""
        url = f"/syndication/posts/{self.post.pk}/add-channel/"
        response = self.client.post(
            url,
            data={"connection_pk": self.conn.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            PlatformProjection.objects.filter(source_post=self.post, connection=self.conn).exists()
        )

    def test_add_channel_post_response_contains_platform_name(self):
        """HTMX response for add_channel_post contains the new channel's platform name (telegram)."""
        url = f"/syndication/posts/{self.post.pk}/add-channel/"
        response = self.client.post(
            url,
            data={"connection_pk": self.conn.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "telegram")

    def test_add_channel_post_requires_login(self):
        """add_channel_post requires authentication."""
        anon_client = Client()
        url = f"/syndication/posts/{self.post.pk}/add-channel/"
        response = anon_client.post(url, data={"connection_pk": self.conn.pk})
        self.assertIn(response.status_code, [302, 403])

    def test_add_channel_post_non_editor_gets_403(self):
        """A non-editor user gets 403 on add_channel_post."""
        stranger = _make_vouched_user(username="stranger_post_ch", email="stranger_post_ch@test.com", password="x")
        stranger_client = Client()
        stranger_client.force_login(stranger)
        url = f"/syndication/posts/{self.post.pk}/add-channel/"
        response = stranger_client.post(url, data={"connection_pk": self.conn.pk})
        self.assertEqual(response.status_code, 403)

    def test_add_channel_post_idempotent_returns_200(self):
        """Re-POSTing add_channel_post for the same connection returns 200 (idempotent)."""
        url = f"/syndication/posts/{self.post.pk}/add-channel/"
        self.client.post(url, data={"connection_pk": self.conn.pk}, HTTP_HX_REQUEST="true")
        response = self.client.post(url, data={"connection_pk": self.conn.pk}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            PlatformProjection.objects.filter(source_post=self.post, connection=self.conn).count(), 1
        )

    def test_add_channel_post_creates_promotion_kind_projection(self):
        """add_channel_post creates a PROMOTION-kind projection (not listing)."""
        url = f"/syndication/posts/{self.post.pk}/add-channel/"
        self.client.post(
            url,
            data={"connection_pk": self.conn.pk},
            HTTP_HX_REQUEST="true",
        )
        proj = PlatformProjection.objects.get(source_post=self.post, connection=self.conn)
        self.assertEqual(proj.kind, PlatformProjection.Kind.PROMOTION)


# ---------------------------------------------------------------------------
# 7. "…" dropdown context — available_connections in post_syndication fragment
# ---------------------------------------------------------------------------


class PostSyndicationAvailableConnectionsTest(TestCase):
    """
    The post_syndication fragment context includes 'available_connections' —
    the list of enabled connections that support 'promotion' but have no
    projection yet for this post. This powers the "…" toggle dropdown in the UI.
    Mirror of AddChannelDropdownContextTest but for Posts.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="post_dropdown_user", email="post_dropdown@test.com", password="x")
        self.profile = _make_profile(name="Post Dropdown Profile", slug="post-dropdown-profile", user=self.user)
        self.event = _make_event(self.profile)
        self.post = _make_post(self.event, self.profile)
        self.client = Client()
        self.client.force_login(self.user)

    def test_post_fragment_context_contains_available_connections(self):
        """
        fragment_post_syndication view includes 'available_connections' in context
        — enabled promotion connections without a projection yet for this post.
        """
        conn = _make_connection(
            self.profile, platform="telegram", destination_id="tg-channel", kinds=["promotion"]
        )
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("available_connections", response.context)
        available_pks = [c.pk for c in response.context["available_connections"]]
        self.assertIn(conn.pk, available_pks)

    def test_post_fragment_available_connections_excludes_projected(self):
        """
        Connections that already have a projection for this post are excluded
        from available_connections.
        """
        from syndication.services import add_projection

        conn_projected = _make_connection(
            self.profile, platform="telegram", destination_id="tg-channel", kinds=["promotion"]
        )
        # Use fetlife (promotion-capable) — switch is excluded by _supports_post_promotion.
        conn_not_projected = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-post", kinds=["listing", "promotion"]
        )

        add_projection(self.post, conn_projected)

        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        available_pks = [c.pk for c in response.context["available_connections"]]
        self.assertNotIn(conn_projected.pk, available_pks)
        self.assertIn(conn_not_projected.pk, available_pks)

    def test_post_fragment_available_connections_excludes_listing_only(self):
        """
        Listing-only connections (kinds=['listing']) are excluded from
        available_connections in the post fragment (posts only show promotion channels).
        """
        listing_conn = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing"]
        )
        url = f"/syndication/posts/{self.post.pk}/fragments/post_syndication/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        available_pks = [c.pk for c in response.context["available_connections"]]
        # listing-only conn should NOT appear in the post's available_connections
        self.assertNotIn(listing_conn.pk, available_pks)
