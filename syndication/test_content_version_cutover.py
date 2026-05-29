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
        create_post seeds a canonical ContentVersion for the Event (if absent)
        and points eager promotion projections FK at it.
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

        canonical_cv = ContentVersion.objects.filter(event=event, name="canonical").first()
        self.assertIsNotNone(canonical_cv, "create_post must ensure a canonical ContentVersion exists")

        projections = PlatformProjection.objects.filter(source_post=post)
        self.assertGreater(projections.count(), 0)
        for proj in projections:
            self.assertEqual(
                proj.content_version_id,
                canonical_cv.pk,
                f"Promotion projection {proj.pk} must FK to the canonical ContentVersion",
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
