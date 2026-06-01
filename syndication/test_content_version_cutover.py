"""
TDD tests for kb-wz8m.2: ContentVersion cutover.

Acceptance assertions:
  (a) event-create seeds exactly ONE canonical ContentVersion that all eager
      projections FK to.
  (b) editing the canonical ContentVersion changes a DRAFT projection's
      render_projection output.
  (c) a ready/published projection's frozen_content is byte-stable across a
      later version edit.
  (d) override_data and projection-level provenance/generated_by/
      last_generated_at fields are gone from PlatformProjection.

canonical_refs: ADR-016 D2/D3/D4, ADR-008 D1/D3, ADR-003.
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import (
    ContentVersion,
    PlatformConnection,
    PlatformProjection,
    Post,
)

from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name="CV Organizer", slug="cv-organizer", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(**kwargs):
    defaults = {
        "title": "CV Test Party",
        "slug": "cv-test-party",
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_connection(profile, platform="fetlife", destination_id="fl-cv-001", kinds=None):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        enabled=True,
        kinds=kinds or ["listing"],
    )


# ---------------------------------------------------------------------------
# (a) A1 seed: create_event auto-seeds ONE canonical ContentVersion
# ---------------------------------------------------------------------------


class CanonicalVersionSeedTest(TestCase):
    """
    create_event must auto-seed exactly ONE canonical ContentVersion per Event,
    and all eager projections must FK to that version.
    """

    def setUp(self):
        self.user = _make_user(
            username="seed_user", email="seed@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="Seed Org", slug="seed-org", user=self.user
        )
        self.conn = _make_connection(self.profile, destination_id="fl-seed-001")

    def test_create_event_seeds_exactly_one_canonical_version(self):
        """
        After create_event, the event must have exactly one ContentVersion
        named 'canonical' with empty editorial fields (track-live).
        """
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Seeded Event",
            slug="seeded-event",
            start=timezone.now(),
        )

        versions = ContentVersion.objects.filter(event=event)
        self.assertEqual(
            versions.count(),
            1,
            "create_event must seed exactly ONE canonical ContentVersion",
        )
        cv = versions.first()
        self.assertEqual(cv.name, "canonical")
        # All editorial fields must be null/empty (track-live semantics)
        self.assertIsNone(cv.headline)
        self.assertIsNone(cv.body)
        self.assertIsNone(cv.imagery)
        self.assertIsNone(cv.cta)
        self.assertIsNone(cv.voice)

    def test_eager_projections_fk_to_canonical_version(self):
        """
        All eager listing projections created by create_event must have their
        content_version FK pointing to the canonical ContentVersion.
        """
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="FK Seeded Event",
            slug="fk-seeded-event",
            start=timezone.now(),
        )

        canonical_cv = ContentVersion.objects.get(event=event, name="canonical")
        projections = PlatformProjection.objects.filter(source_event=event)
        self.assertGreater(
            projections.count(), 0, "create_event must produce eager projections"
        )
        for proj in projections:
            self.assertEqual(
                proj.content_version_id,
                canonical_cv.pk,
                f"Projection {proj.pk} must FK to the canonical ContentVersion",
            )

    def test_create_event_with_multiple_connections_shares_one_canonical_version(self):
        """
        Multiple connections → multiple projections, all FK to ONE canonical version.
        """
        from syndication.services import create_event

        conn2 = _make_connection(
            self.profile, platform="switch", destination_id="switch-own-page", kinds=["listing"]
        )

        event = create_event(
            user=self.user,
            title="Multi-Conn Event",
            slug="multi-conn-event",
            start=timezone.now(),
        )

        versions = ContentVersion.objects.filter(event=event, name="canonical")
        self.assertEqual(versions.count(), 1)

        canonical_cv = versions.first()
        projections = PlatformProjection.objects.filter(source_event=event)
        self.assertEqual(projections.count(), 2)  # one per connection
        for proj in projections:
            self.assertEqual(proj.content_version_id, canonical_cv.pk)

    def test_create_post_seeds_canonical_version_for_promotion_projections(self):
        """
        create_post seeds a canonical ContentVersion for the POST (not the Event)
        and points eager promotion projections FK at it.

        ADR-016 D2 (kb-q4u9.2): promotion projections FK the post's canonical
        (ContentVersion.post set, ContentVersion.event null), not the event's.
        """
        from syndication.services import create_post

        # Set up a promotion-capable connection
        promo_conn = _make_connection(
            self.profile, platform="telegram", destination_id="tg-chan-1", kinds=["promotion"]
        )
        event = _make_event(slug="post-seed-event")
        EventOrganizer.objects.create(event=event, profile=self.profile, is_primary=True)

        post = create_post(
            user=self.user,
            event=event,
            headline="Save the date",
            body="Big party coming up",
        )

        # The canonical must be POST-owned (post FK set, event FK null)
        post_canonical_cv = ContentVersion.objects.filter(post=post, name="canonical").first()
        self.assertIsNotNone(
            post_canonical_cv,
            "create_post must seed a canonical ContentVersion for the POST (post FK set)",
        )
        self.assertIsNone(
            post_canonical_cv.event_id,
            "Post's canonical CV must have event=None (post-owned, not event-owned)",
        )

        projections = PlatformProjection.objects.filter(source_post=post)
        self.assertGreater(projections.count(), 0)
        for proj in projections:
            self.assertEqual(
                proj.content_version_id,
                post_canonical_cv.pk,
                f"Promotion projection {proj.pk} must FK to the POST's canonical ContentVersion",
            )


# ---------------------------------------------------------------------------
# (b) Editing canonical ContentVersion changes DRAFT render output
# ---------------------------------------------------------------------------


class DraftTrackingVersionEditTest(TestCase):
    """
    Editing a ContentVersion field (setting an explicit value) must change
    the render_projection output for DRAFT projections sharing that version.

    NULL field = derive from live canonical Event at render time.
    Non-NULL field = override; used in place of canonical.
    """

    def setUp(self):
        self.user = _make_user(
            username="draft_track_user", email="drafttrack@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="DraftTrack Org", slug="drafttrack-org", user=self.user
        )
        self.conn = _make_connection(self.profile, destination_id="fl-drafttrack-001")

    def test_null_content_version_fields_derive_from_live_canonical(self):
        """
        When ContentVersion has null fields, render_projection derives from
        the live canonical Event — same behavior as the old override_data-absent path.
        """
        from syndication.engine import render_projection
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Live Canonical Event",
            slug="live-canonical-event",
            start=timezone.now(),
        )

        proj = PlatformProjection.objects.filter(source_event=event).first()
        self.assertIsNotNone(proj)
        self.assertEqual(proj.status, "draft")

        body = render_projection(proj)
        self.assertIn("Live Canonical Event", body)

    def test_editing_version_body_changes_draft_render(self):
        """
        Setting ContentVersion.body to an explicit value overrides the derived
        body in render_projection for DRAFT projections.
        """
        from syndication.engine import render_projection
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Version Edit Event",
            slug="version-edit-event",
            start=timezone.now(),
        )

        proj = PlatformProjection.objects.filter(source_event=event).first()
        cv = proj.content_version

        # Set explicit body on the ContentVersion
        cv.body = "Explicit version body that overrides derived"
        cv.save()

        body = render_projection(proj)
        self.assertIn("Explicit version body that overrides derived", body)

    def test_editing_live_canonical_event_changes_null_field_draft_render(self):
        """
        When ContentVersion.body is null (derive-from-canonical), editing the
        Event.title must change the draft render output (live tracking preserved).
        """
        from syndication.engine import render_projection
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Original Live Title",
            slug="original-live-title-event",
            start=timezone.now(),
        )

        proj = PlatformProjection.objects.filter(source_event=event).first()
        cv = proj.content_version

        # Confirm body is null (will derive from canonical)
        self.assertIsNone(cv.body)

        # Edit the canonical event title
        event.title = "Edited Live Title"
        event.save()

        body = render_projection(proj)
        self.assertIn("Edited Live Title", body)
        self.assertNotIn("Original Live Title", body)

    def test_shared_version_edit_propagates_to_all_draft_projections(self):
        """
        When multiple projections share one ContentVersion, editing the version
        propagates to all of them.
        """
        from syndication.engine import render_projection
        from syndication.services import create_event

        conn2 = _make_connection(
            self.profile, platform="switch", destination_id="switch-shared", kinds=["listing"]
        )

        event = create_event(
            user=self.user,
            title="Shared Version Event",
            slug="shared-version-event",
            start=timezone.now(),
        )

        projections = list(PlatformProjection.objects.filter(source_event=event))
        self.assertEqual(len(projections), 2)

        cv = projections[0].content_version
        cv.body = "Shared version body override"
        cv.save()

        for proj in projections:
            body = render_projection(proj)
            self.assertIn("Shared version body override", body)


# ---------------------------------------------------------------------------
# (c) Ready/published frozen_content is byte-stable across later version edits
# ---------------------------------------------------------------------------


class FrozenContentStabilityTest(TestCase):
    """
    A ready/published projection's frozen_content is materialized at draft→ready
    and must NOT change when the ContentVersion is later edited.
    """

    def setUp(self):
        self.user = _make_user(
            username="frozen_stab_user", email="frozen@test.com", password="pw"
        )
        self.profile = _make_profile(
            name="FrozenStab Org", slug="frozenstab-org", user=self.user
        )
        self.conn = _make_connection(self.profile, destination_id="fl-frozen-001")

    def test_frozen_content_byte_stable_after_version_body_edit(self):
        """
        After draft→ready (freeze), editing ContentVersion.body must NOT
        change the frozen_content or render_projection output.
        """
        from syndication.engine import render_projection, transition_status
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Freeze Stable Event",
            slug="freeze-stable-event",
            start=timezone.now(),
        )

        proj = PlatformProjection.objects.filter(source_event=event).first()
        transition_status(proj, "ready")
        proj.refresh_from_db()

        frozen_body_before = proj.frozen_content["body"]

        # Edit ContentVersion AFTER freeze
        cv = proj.content_version
        cv.body = "Post-freeze version edit — must not propagate"
        cv.save()

        proj.refresh_from_db()
        self.assertEqual(
            proj.frozen_content["body"],
            frozen_body_before,
            "frozen_content must be byte-stable after version edit",
        )

        rendered = render_projection(proj)
        self.assertNotIn("Post-freeze version edit", rendered)

    def test_published_projection_frozen_content_stable_across_version_edit(self):
        """
        A published projection's frozen_content is also stable after version edit.
        """
        from syndication.engine import render_projection, transition_status
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Published Stable Event",
            slug="published-stable-event",
            start=timezone.now(),
        )

        proj = PlatformProjection.objects.filter(source_event=event).first()
        transition_status(proj, "ready")
        transition_status(proj, "published")
        proj.refresh_from_db()

        frozen_body_before = proj.frozen_content["body"]

        cv = proj.content_version
        cv.body = "Post-publish edit — must not appear in frozen"
        cv.save()

        proj.refresh_from_db()
        self.assertEqual(proj.frozen_content["body"], frozen_body_before)
        self.assertNotIn("Post-publish edit", render_projection(proj))


# ---------------------------------------------------------------------------
# (d) override_data and projection-level provenance fields are gone
# ---------------------------------------------------------------------------


class FieldsRemovedTest(TestCase):
    """
    override_data and the projection-level provenance/generated_by/
    last_generated_at fields must be removed from PlatformProjection (ADR-008 D1).
    """

    def test_override_data_field_removed_from_platform_projection(self):
        """
        PlatformProjection must NOT have an override_data field.
        """
        pp = PlatformProjection()
        self.assertFalse(
            hasattr(pp, "override_data"),
            "PlatformProjection must NOT have override_data (removed in kb-wz8m.2)",
        )

    def test_provenance_field_removed_from_platform_projection(self):
        """
        PlatformProjection must NOT have a provenance field
        (provenance lives on ContentVersion now).
        """
        pp = PlatformProjection()
        self.assertFalse(
            hasattr(pp, "provenance"),
            "PlatformProjection must NOT have provenance (moved to ContentVersion in kb-wz8m.2)",
        )

    def test_generated_by_field_removed_from_platform_projection(self):
        """
        PlatformProjection must NOT have a generated_by field
        (lives on ContentVersion now).
        """
        pp = PlatformProjection()
        self.assertFalse(
            hasattr(pp, "generated_by"),
            "PlatformProjection must NOT have generated_by (moved to ContentVersion in kb-wz8m.2)",
        )

    def test_last_generated_at_field_removed_from_platform_projection(self):
        """
        PlatformProjection must NOT have a last_generated_at field
        (lives on ContentVersion now).
        """
        pp = PlatformProjection()
        self.assertFalse(
            hasattr(pp, "last_generated_at"),
            "PlatformProjection must NOT have last_generated_at (moved to ContentVersion in kb-wz8m.2)",
        )

    def test_content_version_fk_non_null_after_create_event(self):
        """
        content_version FK on a projection created via create_event must be
        non-null (the FK is mandatory after the A1 seed + migration backfill).
        """
        from syndication.services import create_event
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = _make_user(username="nonnull_user", email="nonnull@test.com", password="pw")
        profile = _make_profile(name="NonNull Org", slug="nonnull-org", user=user)
        _make_connection(profile, destination_id="fl-nonnull-001")

        event = create_event(
            user=user,
            title="NonNull Version Event",
            slug="nonnull-version-event",
            start=timezone.now(),
        )

        for proj in PlatformProjection.objects.filter(source_event=event):
            self.assertIsNotNone(
                proj.content_version_id,
                "content_version FK must be non-null after A1 seed",
            )


# ---------------------------------------------------------------------------
# generate_projection sets provenance on ContentVersion, not projection
# ---------------------------------------------------------------------------


class GenerateProjectionProvenanceOnVersionTest(TestCase):
    """
    generate_projection must set provenance on the ContentVersion,
    not on the (now-removed) projection.provenance field.
    """

    def setUp(self):
        self.profile = Profile.objects.create(name="GP Prov Org", slug="gp-prov-org")
        self.conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-gp-prov",
        )
        self.event = _make_event(slug="gp-prov-event")

    def test_generate_projection_rule_based_sets_cv_provenance_rule_template(self):
        """
        generate_projection with mode=rule_based must result in the projection's
        ContentVersion having provenance=rule_template.
        """
        from syndication.engine import generate_projection

        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        self.assertIsNotNone(proj.content_version)
        self.assertEqual(proj.content_version.provenance, "rule_template")

    def test_generate_projection_agent_assisted_sets_cv_provenance_agent_supplied(self):
        """
        generate_projection with mode=agent_assisted must result in the projection's
        ContentVersion having provenance=agent_supplied.
        """
        from syndication.engine import generate_projection

        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="agent_assisted",
            body="Agent-supplied body",
        )
        self.assertIsNotNone(proj.content_version)
        self.assertEqual(proj.content_version.provenance, "agent_supplied")


# ---------------------------------------------------------------------------
# F6: agent_assisted must NOT mutate the shared canonical ContentVersion
# ---------------------------------------------------------------------------


class AgentAssistedDedicatedVersionTest(TestCase):
    """
    F6 (adversarial review): generate_projection(agent_assisted) must create/attach
    a DEDICATED ContentVersion for the one projection, never clobbering the shared
    canonical version that sibling projections point at.

    Invariant: agent-supplied copy for one target is divergence — its body must
    live on a separate ContentVersion row; the canonical track-live version must
    remain untouched (body=None) so sibling projections can continue deriving
    from the live canonical Event.
    """

    def setUp(self):
        self.profile = Profile.objects.create(name="F6 Org", slug="f6-org")
        self.conn_a = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-f6-a",
        )
        self.conn_b = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="sw-f6-b",
        )
        self.event = _make_event(slug="f6-agent-event")

    def test_agent_assisted_does_not_mutate_canonical_version_body(self):
        """
        After generate_projection(agent_assisted), the canonical ContentVersion
        (name='canonical') must still have body=None (track-live).

        The agent-supplied body must live on the projection's OWN ContentVersion,
        not the shared canonical.
        """
        from syndication.engine import generate_projection

        # First: create a rule_based projection — establishes the canonical CV.
        rule_proj = generate_projection(
            kind="listing",
            connection=self.conn_a,
            source_event=self.event,
            mode="rule_based",
        )
        canonical_cv = rule_proj.content_version
        self.assertIsNone(canonical_cv.body)

        # Now create an agent_assisted projection for the SAME event (different conn).
        agent_proj = generate_projection(
            kind="listing",
            connection=self.conn_b,
            source_event=self.event,
            mode="agent_assisted",
            body="Agent-supplied body for conn B only",
        )

        # The agent projection must have a DIFFERENT ContentVersion from the canonical.
        self.assertNotEqual(
            agent_proj.content_version_id,
            canonical_cv.pk,
            "agent_assisted must attach a DEDICATED ContentVersion, not the shared canonical",
        )

        # The canonical version body must still be None.
        canonical_cv.refresh_from_db()
        self.assertIsNone(
            canonical_cv.body,
            "agent_assisted must NOT mutate the canonical ContentVersion body",
        )

        # The agent projection's ContentVersion must carry the supplied body.
        self.assertEqual(agent_proj.content_version.body, "Agent-supplied body for conn B only")
        self.assertEqual(agent_proj.content_version.provenance, "agent_supplied")

    def test_agent_assisted_siblings_unaffected_render(self):
        """
        A rule_based projection sharing the canonical CV must render from the
        live canonical Event AFTER an agent_assisted projection is created for
        the same event — the agent body must not bleed into the sibling's render.
        """
        from syndication.engine import generate_projection, render_projection

        # Establish a rule_based sibling projection first.
        rule_proj = generate_projection(
            kind="listing",
            connection=self.conn_a,
            source_event=self.event,
            mode="rule_based",
        )

        # Now add an agent_assisted projection for the same event.
        agent_proj = generate_projection(
            kind="listing",
            connection=self.conn_b,
            source_event=self.event,
            mode="agent_assisted",
            body="Exclusive agent body — must not appear in sibling",
        )

        # Sibling must render from the live canonical event (contains event title).
        sibling_body = render_projection(rule_proj)
        self.assertIn(self.event.title, sibling_body)
        self.assertNotIn(
            "Exclusive agent body",
            sibling_body,
            "Agent body must not bleed into sibling rule_based projection",
        )


# ---------------------------------------------------------------------------
# kb-q4u9.2 Probe 2: Migration 0007 backfill
#
# Tests that migration 0007 correctly backfills existing dogfood data:
# - Mints a canonical ContentVersion per existing Post
# - Repoints each promotion PlatformProjection.content_version from the
#   event's canonical to the post's new canonical.
#
# Uses MigrationLoader + RunPython.code() pattern from
# tests/test_organizer_lia_migration.py.
# ---------------------------------------------------------------------------


def _get_0007_migration_forward():
    """Return the forward RunPython function from migration 0007."""
    from django.db import connections
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(connections["default"])
    migration = loader.get_migration("syndication", "0007_backfill_post_canonical_content_versions")
    for operation in migration.operations:
        if hasattr(operation, "code"):
            return operation.code, operation.reverse_code
    raise ValueError("No RunPython found in syndication migration 0007")


class Migration0007BackfillTest(TestCase):
    """
    Probe 2: Migration 0007 backfill correctness.

    Seed a pre-generalization state: Posts whose promotion projections FK the
    event's canonical ContentVersion. Run the 0007 forward function. Assert:
    - Each Post has its own canonical ContentVersion row (post FK set, event null).
    - Every promotion projection that belonged to a Post now FKs the Post's
      canonical (not the event's canonical).
    - Two different Posts each have a DISTINCT canonical row.

    Assert raw-ORM, independent of the service path.
    """

    def setUp(self):
        self.profile = _make_profile(name="Mig0007 Org", slug="mig0007-org")
        self.event = _make_event(slug="mig0007-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)

    def _seed_pre_generalization_state(self):
        """
        Create a post and promotion projections that FK the EVENT's canonical
        (the pre-0007 state that the migration must fix).
        """
        # Event canonical (the old state — projections pointed here)
        event_canonical, _ = ContentVersion.objects.get_or_create(
            event=self.event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )

        # A Post on the event
        post = Post.objects.create(event=self.event, headline="Pre-gen Post", body="Body")

        # Promotion connection
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-mig007-001",
            kinds=["promotion"],
            enabled=True,
        )

        # Promotion projection pointing at EVENT's canonical (pre-0007 state)
        proj = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            connection=conn,
            source_post=post,
            content_version=event_canonical,
        )
        return post, proj, event_canonical

    def test_migration_creates_post_canonical_per_post(self):
        """
        After running migration 0007, each Post must have exactly one
        canonical ContentVersion with post FK set and event FK null.
        """
        post, proj, event_canonical = self._seed_pre_generalization_state()

        forward_fn, _ = _get_0007_migration_forward()
        from django.apps import apps
        from django.db import connection

        with connection.schema_editor() as schema_editor:
            forward_fn(apps, schema_editor)

        post_cvs = ContentVersion.objects.filter(post=post, name="canonical")
        self.assertEqual(post_cvs.count(), 1, "Migration must create exactly one post-canonical CV per Post")
        cv = post_cvs.first()
        self.assertIsNone(cv.event_id, "Post's canonical CV must have event=None")
        self.assertEqual(cv.post_id, post.pk)

    def test_migration_repoints_promotion_projections_to_post_canonical(self):
        """
        After migration 0007, every promotion projection that had source_post set
        must FK the POST's canonical ContentVersion (not the event's).
        """
        post, proj, event_canonical = self._seed_pre_generalization_state()

        forward_fn, _ = _get_0007_migration_forward()
        from django.apps import apps
        from django.db import connection

        with connection.schema_editor() as schema_editor:
            forward_fn(apps, schema_editor)

        proj.refresh_from_db()
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")

        self.assertEqual(
            proj.content_version_id,
            post_canonical.pk,
            "Promotion projection must be repointed to the POST's canonical after migration",
        )
        self.assertNotEqual(
            proj.content_version_id,
            event_canonical.pk,
            "Promotion projection must NOT still point at the event's canonical after migration",
        )

    def test_migration_two_posts_get_distinct_canonicals(self):
        """
        Two Posts on the same Event must each get their own distinct canonical
        ContentVersion after migration 0007 runs.
        """
        # Seed first post + projection
        event_canonical, _ = ContentVersion.objects.get_or_create(
            event=self.event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
        post1 = Post.objects.create(event=self.event, headline="Post 1", body="Body 1")
        post2 = Post.objects.create(event=self.event, headline="Post 2", body="Body 2")

        conn1 = PlatformConnection.objects.create(
            organizer=self.profile, platform="telegram", destination_id="tg-mig007-p1",
            kinds=["promotion"], enabled=True,
        )
        conn2 = PlatformConnection.objects.create(
            organizer=self.profile, platform="fetlife", destination_id="fl-mig007-p2",
            kinds=["promotion"], enabled=True,
        )
        PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION, status=PlatformProjection.Status.DRAFT,
            connection=conn1, source_post=post1, content_version=event_canonical,
        )
        PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.PROMOTION, status=PlatformProjection.Status.DRAFT,
            connection=conn2, source_post=post2, content_version=event_canonical,
        )

        forward_fn, _ = _get_0007_migration_forward()
        from django.apps import apps
        from django.db import connection

        with connection.schema_editor() as schema_editor:
            forward_fn(apps, schema_editor)

        cv1 = ContentVersion.objects.get(post=post1, name="canonical")
        cv2 = ContentVersion.objects.get(post=post2, name="canonical")
        self.assertNotEqual(cv1.pk, cv2.pk, "Two posts must have distinct canonical CVs after migration")

    def test_migration_idempotent(self):
        """
        Running migration 0007 twice must not double-create canonical rows or
        produce inconsistent state (idempotent forward function).
        """
        post, proj, event_canonical = self._seed_pre_generalization_state()

        forward_fn, _ = _get_0007_migration_forward()
        from django.apps import apps
        from django.db import connection

        # First run
        with connection.schema_editor() as schema_editor:
            forward_fn(apps, schema_editor)

        cv_count_after_first = ContentVersion.objects.filter(post=post, name="canonical").count()

        # Second run — idempotent
        with connection.schema_editor() as schema_editor:
            forward_fn(apps, schema_editor)

        cv_count_after_second = ContentVersion.objects.filter(post=post, name="canonical").count()
        self.assertEqual(
            cv_count_after_first,
            cv_count_after_second,
            "Migration 0007 must be idempotent (running twice must not create extra canonical rows)",
        )

    def test_migration_event_canonical_retained_not_deleted(self):
        """
        The event's canonical ContentVersion must be RETAINED after migration
        (on_delete=PROTECT means we can't cascade — the event canonical stays).
        """
        post, proj, event_canonical = self._seed_pre_generalization_state()

        forward_fn, _ = _get_0007_migration_forward()
        from django.apps import apps
        from django.db import connection

        with connection.schema_editor() as schema_editor:
            forward_fn(apps, schema_editor)

        # Event canonical must still exist
        self.assertTrue(
            ContentVersion.objects.filter(pk=event_canonical.pk).exists(),
            "Event's canonical ContentVersion must be retained after migration (on_delete=PROTECT)",
        )
