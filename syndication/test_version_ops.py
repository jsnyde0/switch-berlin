"""
TDD tests for kb-wz8m.3: snapshot-semantic version operations.

Acceptance assertions:
- customize: isolates — editing the customized row leaves a canonical-sharing
  sibling's render UNAFFECTED.
- reset_to_canonical: repoints FK back at canonical with NO new row created.
- copy_to: mints N independent rows for N targets.
- edit_version on a shared row propagates to all consumers.
- consumers(version) returns correct set of projections.
- content_version_consumers_map(event) returns correct mapping.
- non-claimant raises PermissionError for all gated ops.
- save_projection_override is gone from syndication.services.

canonical_refs: ADR-016 D2, ADR-017 D2, ADR-008 D2/D3.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings as _override_settings
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


def _make_profile(name="VO Organizer", slug="vo-organizer", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(slug="vo-event", **kwargs):
    defaults = {
        "title": "Version Ops Test Event",
        "slug": slug,
        "start": timezone.now(),
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_connection(profile, platform="fetlife", destination_id="fl-vo-001", kinds=None, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds or ["listing"],
        enabled=enabled,
    )


def _make_canonical_cv(event, **kwargs):
    """Get-or-create the canonical ContentVersion for event."""
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


def _make_projection(connection, event, cv=None, status="draft"):
    """Create a listing projection."""
    if cv is None:
        cv = _make_canonical_cv(event)
    return PlatformProjection.objects.create(
        kind=PlatformProjection.Kind.LISTING,
        status=status,
        connection=connection,
        source_event=event,
        content_version=cv,
    )


def _make_ready_projection(user, connection, event, cv=None):
    """Create a listing projection in ready/frozen state."""
    from syndication.services import approve_projection

    proj = _make_projection(connection, event, cv=cv)
    approve_projection(user=user, projection=proj)
    proj.refresh_from_db()
    return proj


# ---------------------------------------------------------------------------
# consumers(version)
# ---------------------------------------------------------------------------


class ConsumersTest(TestCase):
    """
    consumers(version) returns the set of PlatformProjections whose
    content_version FK points at this version.
    """

    def setUp(self):
        self.user = _make_user(username="cons_user", email="cons@test.com", password="pw")
        self.profile = _make_profile(name="Cons Org", slug="cons-org", user=self.user)
        self.event = _make_event(slug="cons-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-cons-001")

    def test_consumers_returns_projections_pointing_at_version(self):
        """consumers(version) returns projections that share the given ContentVersion."""
        from syndication.services import consumers

        cv = _make_canonical_cv(self.event)
        proj1 = _make_projection(self.conn, self.event, cv=cv)
        conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-cons-002", kinds=["listing"])
        proj2 = _make_projection(conn2, self.event, cv=cv)

        result = set(consumers(cv))
        self.assertIn(proj1, result)
        self.assertIn(proj2, result)
        self.assertEqual(len(result), 2)

    def test_consumers_excludes_projections_on_other_versions(self):
        """consumers(version) does not include projections on a different ContentVersion."""
        from syndication.services import consumers

        cv_a = _make_canonical_cv(self.event)
        proj_a = _make_projection(self.conn, self.event, cv=cv_a)

        cv_b = ContentVersion.objects.create(
            event=self.event,
            name="variant-b",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-cons-excl", kinds=["listing"])
        proj_b = _make_projection(conn2, self.event, cv=cv_b)

        result_a = set(consumers(cv_a))
        self.assertIn(proj_a, result_a)
        self.assertNotIn(proj_b, result_a)

        result_b = set(consumers(cv_b))
        self.assertIn(proj_b, result_b)
        self.assertNotIn(proj_a, result_b)

    def test_consumers_returns_empty_when_no_projections(self):
        """consumers(version) returns empty when no projections point at version."""
        from syndication.services import consumers

        cv = ContentVersion.objects.create(
            event=self.event,
            name="orphan",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        result = list(consumers(cv))
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# content_version_consumers_map(event)
# ---------------------------------------------------------------------------


class ContentVersionConsumersMapTest(TestCase):
    """
    content_version_consumers_map(event) returns a mapping from each
    ContentVersion for that event to its consumer projections.

    Chosen shape: dict {version: [projection, ...]}
    """

    def setUp(self):
        self.user = _make_user(username="cvmap_user", email="cvmap@test.com", password="pw")
        self.profile = _make_profile(name="CVMap Org", slug="cvmap-org", user=self.user)
        self.event = _make_event(slug="cvmap-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-cvmap-001")

    def test_map_returns_dict_keyed_by_version(self):
        """content_version_consumers_map returns a dict with ContentVersion keys."""
        from syndication.services import content_version_consumers_map

        cv = _make_canonical_cv(self.event)
        _proj = _make_projection(self.conn, self.event, cv=cv)

        mapping = content_version_consumers_map(self.event)
        self.assertIsInstance(mapping, dict)
        self.assertIn(cv, mapping)

    def test_map_projections_list_contains_consumers(self):
        """The value for each version in the map contains the projections using it."""
        from syndication.services import content_version_consumers_map

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=cv)

        mapping = content_version_consumers_map(self.event)
        self.assertIn(proj, mapping[cv])

    def test_map_multiple_versions_separated(self):
        """Different versions appear as separate keys in the map."""
        from syndication.services import content_version_consumers_map

        cv_a = _make_canonical_cv(self.event)
        conn2 = _make_connection(self.profile, platform="switch", destination_id="sw-cvmap-002", kinds=["listing"])
        cv_b = ContentVersion.objects.create(
            event=self.event,
            name="variant-b",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        proj_a = _make_projection(self.conn, self.event, cv=cv_a)
        proj_b = _make_projection(conn2, self.event, cv=cv_b)

        mapping = content_version_consumers_map(self.event)
        self.assertIn(cv_a, mapping)
        self.assertIn(cv_b, mapping)
        self.assertIn(proj_a, mapping[cv_a])
        self.assertIn(proj_b, mapping[cv_b])
        self.assertNotIn(proj_b, mapping[cv_a])

    def test_map_excludes_versions_from_other_events(self):
        """Versions from other events are not included in the map."""
        from syndication.services import content_version_consumers_map

        cv = _make_canonical_cv(self.event)
        _make_projection(self.conn, self.event, cv=cv)

        # Other event
        other_event = _make_event(slug="cvmap-other-event")
        cv_other = _make_canonical_cv(other_event)

        mapping = content_version_consumers_map(self.event)
        self.assertNotIn(cv_other, mapping)

    def test_map_empty_for_event_with_no_versions(self):
        """content_version_consumers_map returns empty dict for event with no ContentVersions."""
        from syndication.services import content_version_consumers_map

        # Fresh event, no versions seeded
        empty_event = _make_event(slug="cvmap-empty-event")
        mapping = content_version_consumers_map(empty_event)
        self.assertIsInstance(mapping, dict)
        self.assertEqual(len(mapping), 0)


# ---------------------------------------------------------------------------
# duplicate(version)
# ---------------------------------------------------------------------------


class DuplicateVersionTest(TestCase):
    """
    duplicate(version) creates a NEW independent ContentVersion seeded from an
    existing one (same Event, copied editorial fields, fresh row).
    """

    def setUp(self):
        self.user = _make_user(username="dup_user", email="dup@test.com", password="pw")
        self.profile = _make_profile(name="Dup Org", slug="dup-org", user=self.user)
        self.event = _make_event(slug="dup-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-dup-001")

    def test_duplicate_creates_new_row(self):
        """duplicate(version) returns a new ContentVersion with a different PK."""
        from syndication.services import duplicate

        proj = _make_projection(self.conn, self.event)
        cv = proj.content_version
        new_cv = duplicate(self.user, cv)

        self.assertNotEqual(new_cv.pk, cv.pk)
        self.assertIsNotNone(new_cv.pk)

    def test_duplicate_copies_editorial_fields(self):
        """duplicate copies headline, body, imagery, cta, voice to the new row."""
        from syndication.services import duplicate

        cv = _make_canonical_cv(self.event)
        cv.headline = "Test Headline"
        cv.body = "Test Body"
        cv.cta = "Buy tickets"
        cv.voice = "playful"
        cv.save()

        _proj = _make_projection(self.conn, self.event, cv=cv)
        new_cv = duplicate(self.user, cv)

        self.assertEqual(new_cv.headline, "Test Headline")
        self.assertEqual(new_cv.body, "Test Body")
        self.assertEqual(new_cv.cta, "Buy tickets")
        self.assertEqual(new_cv.voice, "playful")

    def test_duplicate_same_event(self):
        """duplicate creates new version for the same event."""
        from syndication.services import duplicate

        cv = _make_canonical_cv(self.event)
        _proj = _make_projection(self.conn, self.event, cv=cv)
        new_cv = duplicate(self.user, cv)

        self.assertEqual(new_cv.event_id, self.event.pk)

    def test_duplicate_does_not_repoint_original_projections(self):
        """
        duplicate does NOT repoint any existing projections — it just creates
        a fresh row. The original projections still point at the original version.
        """
        from syndication.services import duplicate

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=cv)
        original_cv_pk = cv.pk

        _new_cv = duplicate(self.user, cv)

        proj.refresh_from_db()
        self.assertEqual(proj.content_version_id, original_cv_pk)

    def test_duplicate_non_claimant_raises_permission_error(self):
        """Non-claimant cannot duplicate a version."""
        from syndication.services import duplicate

        other_user = _make_user(username="dup_other", email="dupother@test.com", password="pw")
        cv = _make_canonical_cv(self.event)
        _make_projection(self.conn, self.event, cv=cv)

        with self.assertRaises(PermissionError):
            duplicate(other_user, cv)


# ---------------------------------------------------------------------------
# customize(projection)
# ---------------------------------------------------------------------------


class CustomizeTest(TestCase):
    """
    customize(projection) duplicates the projection's CURRENT version into a
    new row and repoints the projection's FK at the new row (opt-in divergence).

    Key invariant: editing the customized row leaves a canonical-sharing sibling's
    render UNAFFECTED.
    """

    def setUp(self):
        self.user = _make_user(username="cust_user", email="cust@test.com", password="pw")
        self.profile = _make_profile(name="Cust Org", slug="cust-org", user=self.user)
        self.event = _make_event(slug="cust-event", title="Cust Event Title")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_a = _make_connection(self.profile, platform="fetlife", destination_id="fl-cust-a")
        self.conn_b = _make_connection(self.profile, platform="switch", destination_id="sw-cust-b", kinds=["listing"])

    def test_customize_repoints_projection_to_new_version(self):
        """
        customize(projection) makes the projection point at a NEW ContentVersion,
        not the shared canonical.
        """
        from syndication.services import customize

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn_a, self.event, cv=cv)
        original_cv_pk = cv.pk

        new_cv = customize(self.user, proj)
        proj.refresh_from_db()

        self.assertNotEqual(proj.content_version_id, original_cv_pk)
        self.assertEqual(proj.content_version_id, new_cv.pk)

    def test_customize_returns_new_version(self):
        """customize returns the new ContentVersion."""
        from syndication.services import customize

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn_a, self.event, cv=cv)
        new_cv = customize(self.user, proj)

        self.assertIsNotNone(new_cv.pk)
        self.assertNotEqual(new_cv.pk, cv.pk)

    def test_customize_isolates_from_sibling(self):
        """
        Editing the customized row leaves a canonical-sharing sibling's
        render UNAFFECTED.
        """
        from syndication.engine import render_projection
        from syndication.services import customize

        cv = _make_canonical_cv(self.event)
        proj_a = _make_projection(self.conn_a, self.event, cv=cv)  # gets customized
        proj_b = _make_projection(self.conn_b, self.event, cv=cv)  # stays on canonical

        # Customize proj_a — it gets its own version row
        new_cv = customize(self.user, proj_a)

        # Edit the customized version's body
        new_cv.body = "CUSTOM BODY — must not appear in sibling"
        new_cv.save()

        # proj_b still shares the original canonical — its render must use
        # the live canonical event (not the custom body)
        proj_b_body = render_projection(proj_b)
        self.assertNotIn("CUSTOM BODY — must not appear in sibling", proj_b_body)
        self.assertIn("Cust Event Title", proj_b_body)

    def test_customize_non_claimant_raises_permission_error(self):
        """Non-claimant cannot customize a projection."""
        from syndication.services import customize

        other_user = _make_user(username="cust_other", email="custother@test.com", password="pw")
        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn_a, self.event, cv=cv)

        with self.assertRaises(PermissionError):
            customize(other_user, proj)


# ---------------------------------------------------------------------------
# copy_from(projection, source_version)
# ---------------------------------------------------------------------------


class CopyFromTest(TestCase):
    """
    copy_from(projection, source_version) repoints the projection at a NEW
    independent copy taken from source_version (mint a new row, FK the projection
    to it).
    """

    def setUp(self):
        self.user = _make_user(username="cpfrom_user", email="cpfrom@test.com", password="pw")
        self.profile = _make_profile(name="CpFrom Org", slug="cpfrom-org", user=self.user)
        self.event = _make_event(slug="cpfrom-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_a = _make_connection(self.profile, platform="fetlife", destination_id="fl-cpfrom-a")
        self.conn_b = _make_connection(self.profile, platform="switch", destination_id="sw-cpfrom-b", kinds=["listing"])

    def test_copy_from_repoints_projection_to_new_version(self):
        """copy_from repoints the projection to a fresh ContentVersion copy."""
        from syndication.services import copy_from

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-variant",
            body="Source body to copy",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        target_proj = _make_projection(self.conn_a, self.event)
        original_cv_pk = target_proj.content_version_id

        new_cv = copy_from(self.user, target_proj, source_cv)
        target_proj.refresh_from_db()

        self.assertNotEqual(target_proj.content_version_id, original_cv_pk)
        self.assertNotEqual(target_proj.content_version_id, source_cv.pk)
        self.assertEqual(target_proj.content_version_id, new_cv.pk)

    def test_copy_from_copies_editorial_fields(self):
        """copy_from copies editorial fields from source_version to the new row."""
        from syndication.services import copy_from

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-content",
            body="Source body",
            headline="Source Headline",
            cta="Source CTA",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        target_proj = _make_projection(self.conn_a, self.event)

        new_cv = copy_from(self.user, target_proj, source_cv)

        self.assertEqual(new_cv.body, "Source body")
        self.assertEqual(new_cv.headline, "Source Headline")
        self.assertEqual(new_cv.cta, "Source CTA")

    def test_copy_from_source_unchanged(self):
        """copy_from does NOT modify the source version."""
        from syndication.services import copy_from

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-unchanged",
            body="Original source body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        target_proj = _make_projection(self.conn_a, self.event)

        copy_from(self.user, target_proj, source_cv)
        source_cv.refresh_from_db()
        self.assertEqual(source_cv.body, "Original source body")

    def test_copy_from_non_claimant_raises(self):
        """Non-claimant cannot copy_from."""
        from syndication.services import copy_from

        other_user = _make_user(username="cpfrom_other", email="cpfromoth@test.com", password="pw")
        source_cv = _make_canonical_cv(self.event)
        target_proj = _make_projection(self.conn_a, self.event)

        with self.assertRaises(PermissionError):
            copy_from(other_user, target_proj, source_cv)

    def test_copy_from_cross_event_source_raises(self):
        """
        copy_from raises ValueError if source_version belongs to a DIFFERENT
        event than the target projection's event (ADR-008 D3: fail loud on
        cross-event data-integrity violation).

        The projection's content_version must be unchanged — no DB mutation
        must have occurred before the raise.
        """
        from syndication.services import copy_from

        # Foreign event + source version from that foreign event
        other_profile = _make_profile(name="Other Org CF", slug="other-org-cf")
        other_event = _make_event(slug="cpfrom-other-event-cf")
        EventOrganizer.objects.create(event=other_event, profile=other_profile, is_primary=True)
        foreign_source_cv = _make_canonical_cv(other_event)

        # Target projection belongs to self.event (different from other_event)
        target_proj = _make_projection(self.conn_a, self.event)
        original_cv_pk = target_proj.content_version_id

        with self.assertRaises(ValueError):
            copy_from(self.user, target_proj, foreign_source_cv)

        # No repointing — projection must still point at its original version
        target_proj.refresh_from_db()
        self.assertEqual(target_proj.content_version_id, original_cv_pk)


# ---------------------------------------------------------------------------
# copy_to(source_version, target_projections)
# ---------------------------------------------------------------------------


class CopyToTest(TestCase):
    """
    copy_to(source_version, target_projections) mints N independent new
    ContentVersions (one per target projection) and repoints each projection's
    FK at its own copy.
    """

    def setUp(self):
        self.user = _make_user(username="cpto_user", email="cpto@test.com", password="pw")
        self.profile = _make_profile(name="CpTo Org", slug="cpto-org", user=self.user)
        self.event = _make_event(slug="cpto-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_a = _make_connection(self.profile, platform="fetlife", destination_id="fl-cpto-a")
        self.conn_b = _make_connection(self.profile, platform="switch", destination_id="sw-cpto-b", kinds=["listing"])
        self.conn_c = _make_connection(self.profile, platform="telegram", destination_id="tg-cpto-c", kinds=["listing"])

    def test_copy_to_mints_n_independent_rows(self):
        """copy_to creates exactly N new ContentVersion rows for N target projections."""
        from syndication.services import copy_to

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-for-copy-to",
            body="Pushed body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        proj_b = _make_projection(self.conn_b, self.event)
        proj_c = _make_projection(self.conn_c, self.event)

        cv_count_before = ContentVersion.objects.filter(event=self.event).count()

        new_versions = copy_to(self.user, source_cv, [proj_b, proj_c])

        cv_count_after = ContentVersion.objects.filter(event=self.event).count()
        self.assertEqual(cv_count_after - cv_count_before, 2)  # 2 new rows
        self.assertEqual(len(new_versions), 2)

        # All new versions must have distinct PKs from each other and from source
        pks = {v.pk for v in new_versions}
        self.assertNotIn(source_cv.pk, pks)
        self.assertEqual(len(pks), 2)  # all distinct

    def test_copy_to_each_projection_gets_own_independent_row(self):
        """
        Each target projection is repointed at its OWN new row — not shared.
        Editing one new row must not affect the other.
        """
        from syndication.services import copy_to

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-independent",
            body="Shared source body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        proj_b = _make_projection(self.conn_b, self.event)
        proj_c = _make_projection(self.conn_c, self.event)

        copy_to(self.user, source_cv, [proj_b, proj_c])
        proj_b.refresh_from_db()
        proj_c.refresh_from_db()

        # They must point at DIFFERENT ContentVersions
        self.assertNotEqual(proj_b.content_version_id, proj_c.content_version_id)

    def test_copy_to_projections_repointed(self):
        """Each target projection's content_version FK is updated to a new row."""
        from syndication.services import copy_to

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-repoint",
            body="Repoint body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        proj_b = _make_projection(self.conn_b, self.event)
        proj_c = _make_projection(self.conn_c, self.event)
        original_b_cv = proj_b.content_version_id
        original_c_cv = proj_c.content_version_id

        _new_versions = copy_to(self.user, source_cv, [proj_b, proj_c])
        proj_b.refresh_from_db()
        proj_c.refresh_from_db()

        self.assertNotEqual(proj_b.content_version_id, original_b_cv)
        self.assertNotEqual(proj_c.content_version_id, original_c_cv)

    def test_copy_to_copies_editorial_fields(self):
        """Each new row has editorial fields copied from source_version."""
        from syndication.services import copy_to

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-fields",
            body="Fields body",
            headline="Fields Headline",
            cta="Fields CTA",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        proj_b = _make_projection(self.conn_b, self.event)

        new_versions = copy_to(self.user, source_cv, [proj_b])
        new_cv = new_versions[0]

        self.assertEqual(new_cv.body, "Fields body")
        self.assertEqual(new_cv.headline, "Fields Headline")
        self.assertEqual(new_cv.cta, "Fields CTA")

    def test_copy_to_non_claimant_raises(self):
        """Non-claimant cannot copy_to."""
        from syndication.services import copy_to

        other_user = _make_user(username="cpto_other", email="cptoother@test.com", password="pw")
        source_cv = _make_canonical_cv(self.event)
        proj_b = _make_projection(self.conn_b, self.event)

        with self.assertRaises(PermissionError):
            copy_to(other_user, source_cv, [proj_b])

    def test_copy_to_empty_target_list_no_rows(self):
        """copy_to with no targets creates no rows and returns empty list."""
        from syndication.services import copy_to

        source_cv = _make_canonical_cv(self.event)
        _make_projection(self.conn_a, self.event, cv=source_cv)

        cv_count_before = ContentVersion.objects.filter(event=self.event).count()
        new_versions = copy_to(self.user, source_cv, [])
        cv_count_after = ContentVersion.objects.filter(event=self.event).count()

        self.assertEqual(cv_count_after, cv_count_before)
        self.assertEqual(new_versions, [])

    def test_copy_to_cross_event_target_raises_before_repointing(self):
        """
        copy_to raises ValueError if any target projection belongs to a DIFFERENT
        event than source_version (ADR-008 D3: fail loud on data-integrity violation).

        No repointing must have occurred for ANY target — all-or-nothing.
        """
        from syndication.services import copy_to

        # Foreign event + projection
        other_profile = _make_profile(name="Other Org F4", slug="other-org-f4")
        other_event = _make_event(slug="cpto-other-event-f4")
        EventOrganizer.objects.create(event=other_event, profile=other_profile, is_primary=True)
        other_conn = _make_connection(other_profile, platform="fetlife", destination_id="fl-f4-other")
        other_cv = _make_canonical_cv(other_event)
        foreign_proj = _make_projection(other_conn, other_event, cv=other_cv)
        original_foreign_cv_pk = foreign_proj.content_version_id

        source_cv = _make_canonical_cv(self.event)

        with self.assertRaises(ValueError):
            copy_to(self.user, source_cv, [foreign_proj])

        # No repointing — foreign_proj must still point at its original version
        foreign_proj.refresh_from_db()
        self.assertEqual(foreign_proj.content_version_id, original_foreign_cv_pk)

    def test_copy_to_each_projection_gets_truly_independent_row(self):
        """
        After copy_to to two targets, editing one target's version must NOT
        affect the other target's render (true independence, not just distinct FKs).
        """
        from syndication.engine import render_projection
        from syndication.services import copy_to, edit_version

        source_cv = ContentVersion.objects.create(
            event=self.event,
            name="source-true-independence",
            body="Shared source body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        proj_b = _make_projection(self.conn_b, self.event)
        proj_c = _make_projection(self.conn_c, self.event)

        copy_to(self.user, source_cv, [proj_b, proj_c])
        proj_b.refresh_from_db()
        proj_c.refresh_from_db()

        # Edit proj_b's new version — proj_c's render must be unaffected
        cv_b = proj_b.content_version
        edit_version(self.user, cv_b, body="PROJ_B ONLY — must not appear in C")

        render_c = render_projection(proj_c)
        self.assertNotIn("PROJ_B ONLY — must not appear in C", render_c)


# ---------------------------------------------------------------------------
# reset_to_canonical(projection)
# ---------------------------------------------------------------------------


class ResetToCanonicalTest(TestCase):
    """
    reset_to_canonical(projection) repoints the projection's FK back at the
    Event's canonical ContentVersion (pure FK reassignment, NO new row).
    """

    def setUp(self):
        self.user = _make_user(username="reset_user", email="reset@test.com", password="pw")
        self.profile = _make_profile(name="Reset Org", slug="reset-org", user=self.user)
        self.event = _make_event(slug="reset-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_connection(self.profile, destination_id="fl-reset-001")

    def test_reset_repoints_to_canonical(self):
        """reset_to_canonical repoints projection to the canonical ContentVersion."""
        from syndication.services import customize, reset_to_canonical

        canonical_cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=canonical_cv)

        # First customize to diverge from canonical
        custom_cv = customize(self.user, proj)
        proj.refresh_from_db()
        self.assertEqual(proj.content_version_id, custom_cv.pk)

        # Now reset
        reset_to_canonical(self.user, proj)
        proj.refresh_from_db()
        self.assertEqual(proj.content_version_id, canonical_cv.pk)

    def test_reset_creates_no_new_row(self):
        """reset_to_canonical does NOT create a new ContentVersion row."""
        from syndication.services import customize, reset_to_canonical

        canonical_cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=canonical_cv)
        customize(self.user, proj)  # creates custom row

        cv_count_before = ContentVersion.objects.filter(event=self.event).count()
        reset_to_canonical(self.user, proj)
        cv_count_after = ContentVersion.objects.filter(event=self.event).count()

        self.assertEqual(cv_count_after, cv_count_before)

    def test_reset_non_claimant_raises(self):
        """Non-claimant cannot reset_to_canonical."""
        from syndication.services import reset_to_canonical

        other_user = _make_user(username="reset_other", email="resetoth@test.com", password="pw")
        proj = _make_projection(self.conn, self.event)

        with self.assertRaises(PermissionError):
            reset_to_canonical(other_user, proj)

    def test_reset_idempotent_when_already_on_canonical(self):
        """
        reset_to_canonical on a projection already pointing at canonical is
        idempotent — no new rows, same FK.
        """
        from syndication.services import reset_to_canonical

        canonical_cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=canonical_cv)

        cv_count_before = ContentVersion.objects.filter(event=self.event).count()
        reset_to_canonical(self.user, proj)
        cv_count_after = ContentVersion.objects.filter(event=self.event).count()

        proj.refresh_from_db()
        self.assertEqual(proj.content_version_id, canonical_cv.pk)
        self.assertEqual(cv_count_after, cv_count_before)

    def test_reset_creates_no_new_row_on_normally_seeded_event(self):
        """
        reset_to_canonical is a pure FK assignment — it NEVER creates a new row.
        The count of ContentVersions must be the same before and after.

        This locks the contract: reset is NOT get_or_create; it is fetch-or-raise.
        """
        from syndication.services import customize, reset_to_canonical

        canonical_cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=canonical_cv)
        customize(self.user, proj)  # diverge so reset is non-trivial

        cv_count_before = ContentVersion.objects.count()
        reset_to_canonical(self.user, proj)
        cv_count_after = ContentVersion.objects.count()

        self.assertEqual(cv_count_after, cv_count_before)

    def test_reset_raises_if_no_canonical_exists(self):
        """
        reset_to_canonical raises ValueError (fail loud, ADR-008 D3) when the
        event has no canonical ContentVersion.

        A missing canonical is a violated A1 invariant — a data bug, never a
        normal condition. The correct response is fail loud, NOT silent creation.
        """
        from syndication.services import reset_to_canonical

        # Event with self.profile as organizer (so can_edit passes) but no
        # canonical CV — bypasses normal seeding to simulate data bug.
        bare_event = _make_event(slug="reset-bare-event-f5")
        EventOrganizer.objects.create(event=bare_event, profile=self.profile, is_primary=True)
        other_conn = _make_connection(
            self.profile, platform="telegram", destination_id="tg-reset-bare-f5", kinds=["listing"]
        )
        # Create a non-canonical version so we have something to point the projection at
        non_canonical_cv = ContentVersion.objects.create(
            event=bare_event,
            name="not-canonical",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        bare_proj = _make_projection(other_conn, bare_event, cv=non_canonical_cv)

        # No canonical row exists for bare_event — must raise, not create
        with self.assertRaises(ValueError):
            reset_to_canonical(self.user, bare_proj)


# ---------------------------------------------------------------------------
# customize → reset_to_canonical round-trip reflected in consumers_map (kb-wz8m.10)
# ---------------------------------------------------------------------------


class CustomizeResetConsumersMapRoundTripTest(TestCase):
    """
    Gap 1 integration test (kb-wz8m.10):

    customize → reset_to_canonical round-trip reflected in consumers_map.

    Verifies that:
    1. Two projections on the shared canonical are BOTH listed under canonical
       in content_version_consumers_map.
    2. After customize(proj_a), consumers_map shows canonical → [proj_b only]
       and a new version → [proj_a].  proj_a LEFT the shared set.
    3. After reset_to_canonical(proj_a), proj_a REJOINS: consumers_map again
       groups BOTH projections under the canonical version, and
       consumers(canonical_cv) includes the reset projection.

    This is the "live-on cue correctness after reset" clause.
    """

    def setUp(self):
        self.user = _make_user(username="crmap_user", email="crmap@test.com", password="pw")
        self.profile = _make_profile(name="CRMap Org", slug="crmap-org", user=self.user)
        self.event = _make_event(slug="crmap-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_a = _make_connection(self.profile, platform="fetlife", destination_id="fl-crmap-a")
        self.conn_b = _make_connection(self.profile, platform="switch", destination_id="sw-crmap-b", kinds=["listing"])

    def test_customize_reset_round_trip_reflected_in_consumers_map(self):
        """
        After customize(proj_a): proj_a leaves the shared set; consumers_map shows
        canonical → [proj_b] and new_cv → [proj_a].

        After reset_to_canonical(proj_a): proj_a rejoins; consumers_map again shows
        canonical → [proj_a, proj_b] (both), and consumers(canonical_cv) includes
        proj_a.
        """
        from syndication.services import (
            consumers,
            content_version_consumers_map,
            customize,
            reset_to_canonical,
        )

        canonical_cv = _make_canonical_cv(self.event)
        proj_a = _make_projection(self.conn_a, self.event, cv=canonical_cv)
        proj_b = _make_projection(self.conn_b, self.event, cv=canonical_cv)

        # --- Step 1: both projections start on canonical ---
        cv_map = content_version_consumers_map(self.event)
        self.assertIn(canonical_cv, cv_map, "canonical_cv must appear in map initially")
        initial_consumer_pks = {p.pk for p in cv_map[canonical_cv]}
        self.assertIn(proj_a.pk, initial_consumer_pks, "proj_a must be in canonical consumers initially")
        self.assertIn(proj_b.pk, initial_consumer_pks, "proj_b must be in canonical consumers initially")
        self.assertEqual(len(initial_consumer_pks), 2, "Exactly 2 projections under canonical initially")

        # --- Step 2: customize proj_a --- mints its own row, leaves canonical set ---
        new_cv = customize(self.user, proj_a)
        proj_a.refresh_from_db()

        cv_map_after_customize = content_version_consumers_map(self.event)

        # canonical_cv must now show ONLY proj_b
        self.assertIn(canonical_cv, cv_map_after_customize)
        canonical_consumers_after = {p.pk for p in cv_map_after_customize[canonical_cv]}
        self.assertNotIn(
            proj_a.pk,
            canonical_consumers_after,
            "proj_a must have LEFT the canonical consumers set after customize",
        )
        self.assertIn(
            proj_b.pk,
            canonical_consumers_after,
            "proj_b must still be under canonical after customize(proj_a)",
        )
        self.assertEqual(len(canonical_consumers_after), 1, "Only proj_b remains under canonical")

        # new_cv must show proj_a (the customized projection)
        self.assertIn(new_cv, cv_map_after_customize, "new_cv must appear in map after customize")
        customized_consumers = {p.pk for p in cv_map_after_customize[new_cv]}
        self.assertIn(
            proj_a.pk,
            customized_consumers,
            "proj_a must appear under new_cv (its own customized version) after customize",
        )
        self.assertEqual(len(customized_consumers), 1, "Only proj_a under new_cv after customize")

        # --- Step 3: reset proj_a back to canonical --- it REJOINS canonical set ---
        reset_to_canonical(self.user, proj_a)
        proj_a.refresh_from_db()

        cv_map_after_reset = content_version_consumers_map(self.event)

        # canonical_cv must now show BOTH proj_a and proj_b again
        self.assertIn(canonical_cv, cv_map_after_reset)
        canonical_consumers_after_reset = {p.pk for p in cv_map_after_reset[canonical_cv]}
        self.assertIn(
            proj_a.pk,
            canonical_consumers_after_reset,
            "proj_a must REJOIN the canonical consumers set after reset_to_canonical",
        )
        self.assertIn(
            proj_b.pk,
            canonical_consumers_after_reset,
            "proj_b must still be under canonical after reset",
        )
        self.assertEqual(
            len(canonical_consumers_after_reset),
            2,
            "Both proj_a and proj_b must be under canonical after reset (full rejoin)",
        )

        # consumers(canonical_cv) must also include the reset projection
        canonical_consumer_qs = set(consumers(canonical_cv).values_list("pk", flat=True))
        self.assertIn(
            proj_a.pk,
            canonical_consumer_qs,
            "consumers(canonical_cv) must include proj_a after reset_to_canonical",
        )
        self.assertIn(
            proj_b.pk,
            canonical_consumer_qs,
            "consumers(canonical_cv) must include proj_b after reset",
        )

        # Verify proj_a FK is back on canonical
        self.assertEqual(
            proj_a.content_version_id,
            canonical_cv.pk,
            "proj_a.content_version must point at canonical_cv after reset",
        )


# ---------------------------------------------------------------------------
# edit_version(version, **fields)
# ---------------------------------------------------------------------------


class EditVersionTest(TestCase):
    """
    edit_version(version, **fields) mutates a version's editorial fields and
    sets provenance=manual on human edit.

    Propagates to ALL draft projections sharing the row.
    Frozen projections (ready/published/failed) are fully isolated — they
    return frozen_content["body"] and are unaffected by version edits (A2
    freeze per engine.py render_projection).
    Guard: cannot edit a version when ALL consumer projections are frozen
    (every consumer is non-draft: ready/published/failed).  At least one
    draft consumer makes edit always permitted.
    """

    def setUp(self):
        self.user = _make_user(username="editv_user", email="editv@test.com", password="pw")
        self.profile = _make_profile(name="EditV Org", slug="editv-org", user=self.user)
        self.event = _make_event(slug="editv-event", title="EditV Event Title")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_a = _make_connection(self.profile, platform="fetlife", destination_id="fl-editv-a")
        self.conn_b = _make_connection(self.profile, platform="switch", destination_id="sw-editv-b", kinds=["listing"])

    def test_edit_version_mutates_fields(self):
        """edit_version updates the editorial fields on the ContentVersion."""
        from syndication.services import edit_version

        cv = _make_canonical_cv(self.event)
        _make_projection(self.conn_a, self.event, cv=cv)

        edit_version(self.user, cv, body="New body via edit", headline="New Headline")
        cv.refresh_from_db()

        self.assertEqual(cv.body, "New body via edit")
        self.assertEqual(cv.headline, "New Headline")

    def test_edit_version_flips_provenance_to_manual(self):
        """edit_version sets provenance=manual on the ContentVersion."""
        from syndication.services import edit_version

        cv = _make_canonical_cv(self.event)
        _make_projection(self.conn_a, self.event, cv=cv)

        edit_version(self.user, cv, body="Human edit sets provenance")
        cv.refresh_from_db()

        self.assertEqual(cv.provenance, ContentVersion.Provenance.MANUAL)

    def test_edit_version_propagates_to_all_consumers(self):
        """
        Editing a shared version propagates to all projections using it,
        as they all share the same ContentVersion row.
        """
        from syndication.engine import render_projection
        from syndication.services import edit_version

        cv = _make_canonical_cv(self.event)
        proj_a = _make_projection(self.conn_a, self.event, cv=cv)
        proj_b = _make_projection(self.conn_b, self.event, cv=cv)

        edit_version(self.user, cv, body="Shared edit propagates everywhere")

        body_a = render_projection(proj_a)
        body_b = render_projection(proj_b)

        self.assertIn("Shared edit propagates everywhere", body_a)
        self.assertIn("Shared edit propagates everywhere", body_b)

    def test_edit_version_non_claimant_raises(self):
        """Non-claimant cannot edit a version."""
        from syndication.services import edit_version

        other_user = _make_user(username="editv_other", email="editvoth@test.com", password="pw")
        cv = _make_canonical_cv(self.event)
        _make_projection(self.conn_a, self.event, cv=cv)

        with self.assertRaises(PermissionError):
            edit_version(other_user, cv, body="Not allowed")

    def test_edit_version_raises_if_all_consumers_are_published(self):
        """
        edit_version raises ValueError if ALL consumer projections are published
        (ADR-008 D3: fail loud — every consumer is frozen, no live readers).
        """
        from syndication.services import approve_projection, edit_version

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn_a, self.event, cv=cv)
        # Advance to published
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()
        from syndication.engine import transition_status

        transition_status(proj, "published")
        proj.refresh_from_db()

        with self.assertRaises(ValueError):
            edit_version(self.user, cv, body="Cannot edit frozen content")

    def test_edit_version_raises_if_all_consumers_are_ready(self):
        """
        edit_version raises ValueError if ALL consumers are ready.
        Every consumer has frozen_content; no draft consumer reads the live row.
        """
        from syndication.services import approve_projection, edit_version

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn_a, self.event, cv=cv)
        approve_projection(user=self.user, projection=proj)
        proj.refresh_from_db()

        with self.assertRaises(ValueError):
            edit_version(self.user, cv, body="Cannot edit when frozen")

    def test_edit_version_allowed_when_mixed_draft_and_published(self):
        """
        edit_version succeeds when the version is shared by both a draft and a
        published projection (the MIXED case).

        - The DRAFT projection re-renders live and sees the updated body.
        - The PUBLISHED projection returns frozen_content["body"] and is UNCHANGED.

        This is the key isolation invariant: A2 freeze means non-draft projections
        never read the live ContentVersion, so editing it cannot corrupt them.
        """
        from syndication.engine import render_projection, transition_status
        from syndication.services import approve_projection, edit_version

        cv = _make_canonical_cv(self.event)
        proj_draft = _make_projection(self.conn_a, self.event, cv=cv)
        proj_published = _make_projection(self.conn_b, self.event, cv=cv)

        # Capture the frozen render BEFORE the edit (the "original" published body)
        approve_projection(user=self.user, projection=proj_published)
        proj_published.refresh_from_db()
        transition_status(proj_published, "published")
        proj_published.refresh_from_db()
        frozen_body_before_edit = render_projection(proj_published)

        # Mixed state: proj_draft is draft, proj_published is published
        # edit_version must SUCCEED (at least one draft consumer)
        edit_version(self.user, cv, body="UPDATED AFTER FREEZE")
        cv.refresh_from_db()

        # Draft projection re-renders live — sees the updated body
        draft_render = render_projection(proj_draft)
        self.assertIn("UPDATED AFTER FREEZE", draft_render)

        # Published projection returns its frozen snapshot — UNCHANGED
        proj_published.refresh_from_db()
        published_render = render_projection(proj_published)
        self.assertEqual(published_render, frozen_body_before_edit)
        self.assertNotIn("UPDATED AFTER FREEZE", published_render)

    def test_edit_version_allowed_when_all_consumers_are_draft(self):
        """edit_version succeeds when all consumers are draft."""
        from syndication.services import edit_version

        cv = _make_canonical_cv(self.event)
        _proj_a = _make_projection(self.conn_a, self.event, cv=cv)
        _proj_b = _make_projection(self.conn_b, self.event, cv=cv)

        # Both draft — edit should succeed
        edit_version(self.user, cv, body="Draft edit is OK")
        cv.refresh_from_db()
        self.assertEqual(cv.body, "Draft edit is OK")

    def test_edit_version_only_unknown_fields_skipped(self):
        """edit_version ignores fields not in the CV editorial set."""
        from syndication.services import edit_version

        cv = _make_canonical_cv(self.event)
        _make_projection(self.conn_a, self.event, cv=cv)

        # Should not raise even with unknown kwargs — they are silently ignored.
        edit_version(self.user, cv, body="Known field", nonexistent_field="ignored")
        cv.refresh_from_db()
        self.assertEqual(cv.body, "Known field")


# ---------------------------------------------------------------------------
# save_projection_override is GONE
# ---------------------------------------------------------------------------


class SaveProjectionOverrideGoneTest(TestCase):
    """
    save_projection_override must be removed from syndication.services.
    kb-wz8m.3 owns its removal.
    """

    def test_save_projection_override_not_in_services(self):
        """save_projection_override must NOT exist in syndication.services."""
        import syndication.services as services_mod

        self.assertFalse(
            hasattr(services_mod, "save_projection_override"),
            "save_projection_override must be removed from syndication.services in kb-wz8m.3",
        )

    def test_save_projection_override_not_imported_in_views(self):
        """views.py must NOT import save_projection_override."""
        import syndication.views as views_mod

        self.assertFalse(
            hasattr(views_mod, "save_projection_override"),
            "views.py must not import save_projection_override after kb-wz8m.3",
        )

    def test_save_projection_override_not_imported_in_api(self):
        """api.py must NOT import save_projection_override."""
        import syndication.api as api_mod

        self.assertFalse(
            hasattr(api_mod, "save_projection_override"),
            "api.py must not import save_projection_override after kb-wz8m.3",
        )


# ---------------------------------------------------------------------------
# kb-q4u9.2 Probe 1: Post-owned ContentVersion paths
#
# ADR-016 D2: promotion projections FK the post's canonical, not the event's.
# ADR-008 D3: post-owned version resolving to its event must RAISE.
# ---------------------------------------------------------------------------


def _make_post(event, headline="Save the Date", body="Big party coming up"):
    """Create a Post for an event."""
    return Post.objects.create(event=event, headline=headline, body=body)


def _make_promo_connection(profile, platform="telegram", destination_id="tg-promo-001"):
    """Create a promotion-capable PlatformConnection."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=["promotion"],
        enabled=True,
    )


def _make_canonical_cv_for_post(post, **kwargs):
    """Get-or-create the canonical ContentVersion for a post."""
    cv, _ = ContentVersion.objects.get_or_create(
        post=post,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


class PostOwnedCanonicalSeedTest(TestCase):
    """
    create_post must seed a canonical ContentVersion for the POST
    (ContentVersion.post set, ContentVersion.event null), not the event.

    All eager promotion projections must FK to the post's canonical, not the event's.
    ADR-016 D2, ADR-008 D3.
    """

    def setUp(self):
        self.user = _make_user(username="postseed_user", email="postseed@test.com", password="pw")
        self.profile = _make_profile(name="PostSeed Org", slug="postseed-org", user=self.user)
        self.event = _make_event(slug="postseed-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_tg = _make_promo_connection(self.profile, destination_id="tg-postseed-001")
        self.conn_fl = _make_promo_connection(self.profile, platform="fetlife", destination_id="fl-postseed-002")

    def test_create_post_seeds_post_canonical_not_event_canonical(self):
        """
        create_post must seed a canonical ContentVersion with post FK set
        and event FK null (post-owned, not event-owned).
        """
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="Test Post",
            body="Test body",
        )

        # Must be a ContentVersion with post=post, event=null
        post_cvs = ContentVersion.objects.filter(post=post, name="canonical")
        self.assertEqual(post_cvs.count(), 1, "create_post must seed exactly one post-owned canonical CV")
        cv = post_cvs.first()
        self.assertIsNone(cv.event_id, "Post's canonical CV must have event=None (post-owned)")
        self.assertEqual(cv.post_id, post.pk, "Post's canonical CV must have post FK set")

    def test_create_post_promotion_projections_fk_post_canonical(self):
        """
        All eager promotion projections created by create_post must FK to the
        POST's canonical ContentVersion, not the event's canonical.
        """
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="FK Test Post",
            body="FK test body",
        )

        post_canonical = ContentVersion.objects.get(post=post, name="canonical")
        projections = PlatformProjection.objects.filter(source_post=post)
        self.assertGreater(projections.count(), 0, "create_post must produce eager projections")
        for proj in projections:
            self.assertEqual(
                proj.content_version_id,
                post_canonical.pk,
                f"Projection {proj.pk} must FK to the POST's canonical, not the event's",
            )
            # Verify the FK'd CV is post-owned (event=None)
            self.assertIsNone(
                proj.content_version.event_id,
                f"Projection {proj.pk}'s content_version must be post-owned (event=None)",
            )

    def test_two_posts_each_get_own_canonical(self):
        """
        Two Posts on the same Event each get their own canonical ContentVersion.
        The event's canonical (if any) is distinct from both post canonicals.
        """
        from syndication.services import create_post

        post1 = create_post(user=self.user, event=self.event, headline="Post 1", body="Body 1")
        post2 = create_post(user=self.user, event=self.event, headline="Post 2", body="Body 2")

        cv1 = ContentVersion.objects.get(post=post1, name="canonical")
        cv2 = ContentVersion.objects.get(post=post2, name="canonical")
        self.assertNotEqual(cv1.pk, cv2.pk, "Two posts must have separate canonical ContentVersions")


class PostPromotionCustomizeResetTest(TestCase):
    """
    customize + reset_to_canonical round-trip for post-owned promotion projections.

    ADR-016 D2: reset_to_canonical for a promotion projection must resolve the
    POST's canonical, not the event's. The consumers_map must also work for post-owned CVs.
    """

    def setUp(self):
        self.user = _make_user(username="postctrl_user", email="postctrl@test.com", password="pw")
        self.profile = _make_profile(name="PostCtrl Org", slug="postctrl-org", user=self.user)
        self.event = _make_event(slug="postctrl-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn_tg = _make_promo_connection(self.profile, destination_id="tg-postctrl-001")
        self.conn_fl = _make_promo_connection(self.profile, platform="fetlife", destination_id="fl-postctrl-002")

    def test_customize_on_post_promotion_creates_post_owned_version(self):
        """
        customize(projection) on a post-owned promotion projection must create
        a new ContentVersion with post FK set (not event FK).
        """
        from syndication.services import create_post, customize

        post = create_post(user=self.user, event=self.event, headline="Promo Post", body="Body")
        proj = PlatformProjection.objects.filter(source_post=post).first()
        self.assertIsNotNone(proj)

        new_cv = customize(self.user, proj)
        # The customized CV must be post-owned, not event-owned
        self.assertEqual(new_cv.post_id, post.pk)
        self.assertIsNone(new_cv.event_id)

    def test_customize_isolates_post_channels(self):
        """
        Customizing one promotion channel must not affect the other still-synced channel.
        """
        from syndication.engine import render_projection
        from syndication.services import create_post, customize, edit_version

        post = create_post(user=self.user, event=self.event, headline="Isolation Post", body="Original body")
        projs = list(PlatformProjection.objects.filter(source_post=post))
        self.assertGreaterEqual(len(projs), 2, "Need ≥2 promotion projections")

        proj_a, proj_b = projs[0], projs[1]

        # Customize proj_a
        new_cv = customize(self.user, proj_a)
        proj_a.refresh_from_db()

        # Edit customized version's body
        edit_version(self.user, new_cv, body="CUSTOM BODY CHAN A")

        # proj_b still shares the post canonical → render uses post body
        body_b = render_projection(proj_b)
        self.assertNotIn("CUSTOM BODY CHAN A", body_b)

    def test_reset_to_canonical_for_post_promotion_uses_post_canonical(self):
        """
        reset_to_canonical for a post-owned promotion projection must re-point
        at the POST's canonical, not the event's canonical.
        """
        from syndication.services import create_post, customize, reset_to_canonical

        post = create_post(user=self.user, event=self.event, headline="Reset Post", body="Body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")

        proj = PlatformProjection.objects.filter(source_post=post).first()
        # Customize to diverge
        customize(self.user, proj)
        proj.refresh_from_db()
        self.assertNotEqual(proj.content_version_id, post_canonical.pk)

        # Reset — must re-point at POST's canonical, not event's
        reset_to_canonical(self.user, proj)
        proj.refresh_from_db()
        self.assertEqual(
            proj.content_version_id,
            post_canonical.pk,
            "reset_to_canonical for a promotion projection must point at the POST's canonical",
        )

    def test_content_version_consumers_map_for_post(self):
        """
        content_version_consumers_map must support post-scoped queries.
        Both synced promotion channels must be listed under the post's canonical.
        """
        from syndication.services import content_version_consumers_map, create_post

        post = create_post(user=self.user, event=self.event, headline="Map Post", body="Body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")
        projs = list(PlatformProjection.objects.filter(source_post=post))
        self.assertGreaterEqual(len(projs), 2)

        mapping = content_version_consumers_map(post=post)
        self.assertIn(post_canonical, mapping)
        consumer_pks = {p.pk for p in mapping[post_canonical]}
        for proj in projs:
            self.assertIn(proj.pk, consumer_pks)

    def test_edit_post_canonical_propagates_to_draft_not_frozen(self):
        """
        Editing the post's shared canonical propagates to still-synced draft channels
        but NOT to a channel already ready/published (freeze, ADR-016 D2).
        """
        from syndication.engine import render_projection
        from syndication.services import approve_projection, create_post, edit_version

        post = create_post(user=self.user, event=self.event, headline="Freeze Post", body="Original")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")
        projs = list(PlatformProjection.objects.filter(source_post=post))
        self.assertGreaterEqual(len(projs), 2)

        proj_draft, proj_ready = projs[0], projs[1]

        # Advance proj_ready to ready (frozen)
        approve_projection(user=self.user, projection=proj_ready)
        proj_ready.refresh_from_db()
        frozen_body = render_projection(proj_ready)

        # Edit the shared canonical
        edit_version(self.user, post_canonical, body="UPDATED CANONICAL")

        # Draft channel sees the update
        draft_render = render_projection(proj_draft)
        self.assertIn("UPDATED CANONICAL", draft_render)

        # Ready channel is frozen — unchanged
        proj_ready.refresh_from_db()
        ready_render = render_projection(proj_ready)
        self.assertEqual(ready_render, frozen_body)
        self.assertNotIn("UPDATED CANONICAL", ready_render)


class PostOwnedVersionResolveEventRaisesTest(TestCase):
    """
    ADR-008 D3: Any service resolving a post-owned ContentVersion to its event
    must RAISE rather than silently fall back.

    _gate_can_edit_for_cv is the specific guard that must fail loud when
    content_version.event is None.
    """

    def setUp(self):
        self.user = _make_user(username="postguard_user", email="postguard@test.com", password="pw")
        self.profile = _make_profile(name="PostGuard Org", slug="postguard-org", user=self.user)
        self.event = _make_event(slug="postguard-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_promo_connection(self.profile, destination_id="tg-postguard-001")
        # Second promotion connection so tests that need ≥2 projections work
        self.conn2 = _make_promo_connection(self.profile, platform="fetlife", destination_id="fl-postguard-002")

    def test_gate_can_edit_for_cv_resolves_event_via_post_not_none(self):
        """
        _gate_can_edit_for_cv on a post-owned ContentVersion must resolve
        the event via post.event (not raise or pass None to can_edit).

        A user who IS the organizer of the event must be allowed to edit.
        (Regression guard: previously would fail with can_edit(user, None).)
        """
        from syndication.services import create_post, edit_version

        post = create_post(user=self.user, event=self.event, headline="Guard Post", body="Body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")

        # If _gate_can_edit_for_cv incorrectly passes None to can_edit, this raises.
        # The correct behavior is: can_edit resolves event via post.event → succeeds.
        _proj = PlatformProjection.objects.filter(source_post=post).first()
        # edit_version goes through _gate_can_edit_for_cv
        edit_version(self.user, post_canonical, body="Edited via post-owned CV")
        post_canonical.refresh_from_db()
        self.assertEqual(post_canonical.body, "Edited via post-owned CV")

    def test_copy_from_on_post_source_creates_post_owned_version(self):
        """
        copy_from when source_version is post-owned must create a new ContentVersion
        with post FK set (not event=source.event, which would violate check constraint
        since source.event=None → CV with both null → raises DB constraint).
        """
        from syndication.services import copy_from, create_post

        post = create_post(user=self.user, event=self.event, headline="CopyFrom Post", body="Body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")
        proj = PlatformProjection.objects.filter(source_post=post).first()

        # copy_from with a post-owned source must produce a post-owned new CV
        new_cv = copy_from(self.user, proj, post_canonical)
        self.assertEqual(new_cv.post_id, post.pk)
        self.assertIsNone(new_cv.event_id)

    def test_duplicate_on_post_owned_cv_creates_post_owned_version(self):
        """
        duplicate on a post-owned ContentVersion must produce a new CV with
        post FK set, not event FK (which is None on the source → would violate constraint).
        """
        from syndication.services import create_post, duplicate

        post = create_post(user=self.user, event=self.event, headline="Dup Post", body="Body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")

        new_cv = duplicate(self.user, post_canonical)
        self.assertEqual(new_cv.post_id, post.pk)
        self.assertIsNone(new_cv.event_id)

    def test_copy_to_on_post_source_creates_post_owned_versions(self):
        """
        copy_to when source_version is post-owned must create new CVs with
        post FK set for each target projection.
        """
        from syndication.services import copy_to, create_post

        post = create_post(user=self.user, event=self.event, headline="CopyTo Post", body="Body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")
        projs = list(PlatformProjection.objects.filter(source_post=post))
        self.assertGreaterEqual(len(projs), 2)

        new_versions = copy_to(self.user, post_canonical, [projs[1]])
        new_cv = new_versions[0]
        self.assertEqual(new_cv.post_id, post.pk)

    def test_copy_to_post_source_n2_independence(self):
        """
        copy_to on a post-owned source with TWO targets must produce TWO
        truly independent ContentVersion rows: different PKs, both post-owned,
        and edits to one must not affect the other.

        Mirrors the event-path test
        test_copy_to_each_projection_gets_truly_independent_row.
        """
        from syndication.engine import render_projection
        from syndication.services import copy_to, create_post, edit_version

        post = create_post(user=self.user, event=self.event, headline="N2 Independence Post", body="Shared body")
        post_canonical = ContentVersion.objects.get(post=post, name="canonical")
        projs = list(PlatformProjection.objects.filter(source_post=post))
        self.assertGreaterEqual(len(projs), 2, "Need ≥2 promotion projections for N=2 test")

        proj_a, proj_b = projs[0], projs[1]

        # copy_to both targets from the same source
        new_versions = copy_to(self.user, post_canonical, [proj_a, proj_b])
        self.assertEqual(len(new_versions), 2, "copy_to must return 2 new CVs for 2 targets")

        cv_a, cv_b = new_versions[0], new_versions[1]

        # (a) Distinct rows — not the same object
        self.assertNotEqual(cv_a.pk, cv_b.pk, "Two copy_to targets must get distinct CV PKs")

        # (b) Both post-owned
        self.assertEqual(cv_a.post_id, post.pk)
        self.assertIsNone(cv_a.event_id)
        self.assertEqual(cv_b.post_id, post.pk)
        self.assertIsNone(cv_b.event_id)

        # (c) Independence: editing cv_a must not affect cv_b's render
        proj_a.refresh_from_db()
        proj_b.refresh_from_db()
        edit_version(self.user, cv_a, body="EXCLUSIVE BODY A")
        body_b = render_projection(proj_b)
        self.assertNotIn(
            "EXCLUSIVE BODY A",
            body_b,
            "Editing cv_a must not bleed into proj_b's render (true row independence)",
        )


# ---------------------------------------------------------------------------
# kb-q4u9.2 Probe: publish path for post-owned promotion projections
#
# Acceptance: per-channel publish AND publish-all-ready over the post projections
# each invoke the adapter with its OWN channel body (frozen at ready), not the
# canonical's or the other channel's body.
# ---------------------------------------------------------------------------


def _make_publish_ok_response():
    """Return a fake httpx.Response-like mock for Telegram Bot API success."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": {"message_id": 555}}
    return resp


@_override_settings(TELEGRAM_BOT_TOKEN="test-dummy-token")
class PostOwnedProjectionPublishProbeTest(TestCase):
    """
    Probe: per-channel publish AND publish-all-ready for post-owned promotion
    projections each invoke the Telegram adapter with THAT channel's own frozen
    body — not the canonical's or the other channel's.

    Uses the REAL adapter path (only httpx.post is mocked at the transport
    boundary), mirroring the style in test_e2e_board.py step 3/step 4.
    """

    def setUp(self):
        self.user = _make_user(username="pubprobe_user", email="pubprobe@test.com", password="pw")
        self.profile = _make_profile(name="PubProbe Org", slug="pubprobe-org", user=self.user)
        self.event = _make_event(slug="pubprobe-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        # Two telegram promotion connections so each post gets ≥2 projections
        self.conn_tg_a = _make_promo_connection(self.profile, destination_id="tg-pubprobe-001")
        self.conn_tg_b = _make_promo_connection(self.profile, destination_id="tg-pubprobe-002")

    def test_per_channel_publish_uses_own_frozen_body(self):
        """
        (a) Per-channel publish: customize one projection, advance both to ready,
        publish the customized one — the Telegram adapter receives THAT channel's
        own customized body, NOT the canonical's or the other channel's.
        """
        from syndication.services import (
            approve_projection,
            create_post,
            customize,
            edit_version,
            publish_projection,
        )

        post = create_post(
            user=self.user,
            event=self.event,
            headline="Publish Probe Post",
            body="Shared canonical body",
        )
        projs = list(PlatformProjection.objects.filter(source_post=post).order_by("pk"))
        self.assertGreaterEqual(len(projs), 2, "Need ≥2 promotion projections")

        proj_a, proj_b = projs[0], projs[1]

        # Customize proj_a with a distinguishable body
        new_cv_a = customize(self.user, proj_a)
        proj_a.refresh_from_db()
        edit_version(self.user, new_cv_a, body="PUBLISH-BODY-CHAN-A")

        # Advance proj_a to ready (freeze)
        approve_projection(user=self.user, projection=proj_a)
        proj_a.refresh_from_db()
        self.assertEqual(proj_a.status, PlatformProjection.Status.READY)
        self.assertTrue(
            proj_a.frozen_content["body"].startswith("PUBLISH-BODY-CHAN-A"),
            "Precondition: proj_a must have its custom body frozen. "
            f"Got body={proj_a.frozen_content['body']!r}",
        )

        # proj_b stays draft (unaffected)
        proj_b.refresh_from_db()
        self.assertEqual(proj_b.status, PlatformProjection.Status.DRAFT)

        # Publish proj_a — only httpx.post is mocked
        with patch(
            "syndication.adapters.httpx.post",
            return_value=_make_publish_ok_response(),
        ) as mock_post:
            publish_projection(self.user, proj_a)

        # httpx.post called exactly once
        self.assertEqual(mock_post.call_count, 1)

        # The payload text must be proj_a's OWN customized body
        actual_payload = mock_post.call_args.kwargs["json"]
        self.assertTrue(
            actual_payload["text"].startswith("PUBLISH-BODY-CHAN-A"),
            "Per-channel publish must deliver proj_a's OWN frozen body to the adapter. "
            "A routing swap would post proj_b's/canonical body — this assertion catches it. "
            f"Got text={actual_payload['text']!r}",
        )

        # proj_a must now be PUBLISHED
        proj_a.refresh_from_db()
        self.assertEqual(proj_a.status, PlatformProjection.Status.PUBLISHED)
        self.assertTrue(proj_a.frozen_content["body"].startswith("PUBLISH-BODY-CHAN-A"))

        # proj_b must still be draft
        proj_b.refresh_from_db()
        self.assertEqual(proj_b.status, PlatformProjection.Status.DRAFT)

    def test_publish_all_ready_uses_own_frozen_body_per_projection(self):
        """
        (b) publish-all-ready: customize BOTH projections with divergent bodies,
        advance both to ready, call publish_all_ready_projections — the adapter
        is invoked for EACH projection with THAT channel's own frozen body.

        Two httpx.post calls: one with "BODY-CHAN-A", one with "BODY-CHAN-B".
        A routing swap or shared-body bug would cause both calls to carry the
        same text — this assertion catches it.
        """
        from syndication.services import (
            approve_projection,
            create_post,
            customize,
            edit_version,
            publish_all_ready_projections,
        )

        post = create_post(
            user=self.user,
            event=self.event,
            headline="PublishAll Probe Post",
            body="Canonical body for publish-all",
        )
        projs = list(PlatformProjection.objects.filter(source_post=post).order_by("pk"))
        self.assertGreaterEqual(len(projs), 2, "Need ≥2 promotion projections")

        proj_a, proj_b = projs[0], projs[1]

        # Customize both with divergent bodies
        cv_a = customize(self.user, proj_a)
        proj_a.refresh_from_db()
        edit_version(self.user, cv_a, body="BODY-CHAN-A")

        cv_b = customize(self.user, proj_b)
        proj_b.refresh_from_db()
        edit_version(self.user, cv_b, body="BODY-CHAN-B")

        # Advance both to ready
        approve_projection(user=self.user, projection=proj_a)
        approve_projection(user=self.user, projection=proj_b)
        proj_a.refresh_from_db()
        proj_b.refresh_from_db()
        self.assertEqual(proj_a.status, PlatformProjection.Status.READY)
        self.assertEqual(proj_b.status, PlatformProjection.Status.READY)
        self.assertTrue(proj_a.frozen_content["body"].startswith("BODY-CHAN-A"))
        self.assertTrue(proj_b.frozen_content["body"].startswith("BODY-CHAN-B"))

        # Capture payloads from httpx.post calls
        captured_payloads = []

        def capture_post(url, **kwargs):
            captured_payloads.append(kwargs.get("json", {}))
            return _make_publish_ok_response()

        with patch("syndication.adapters.httpx.post", side_effect=capture_post):
            published_batch, failures = publish_all_ready_projections(self.user, self.event)

        # No failures
        self.assertEqual(failures, [], f"Expected no failures, got: {failures}")

        # Both projections published
        self.assertEqual(len(published_batch), 2)
        published_pks = {p.pk for p in published_batch}
        self.assertIn(proj_a.pk, published_pks)
        self.assertIn(proj_b.pk, published_pks)

        # httpx.post called exactly twice (once per projection)
        self.assertEqual(
            len(captured_payloads),
            2,
            "httpx.post must be called exactly twice — once per ready promotion projection",
        )

        # Each call must carry the channel's OWN body (URL suffix appended after).
        captured_texts = [p["text"] for p in captured_payloads]
        self.assertTrue(
            any(t.startswith("BODY-CHAN-A") for t in captured_texts),
            "publish-all-ready must deliver proj_a's OWN body to the adapter. "
            f"Got captured_texts={captured_texts!r}",
        )
        self.assertTrue(
            any(t.startswith("BODY-CHAN-B") for t in captured_texts),
            "publish-all-ready must deliver proj_b's OWN body to the adapter. "
            f"Got captured_texts={captured_texts!r}",
        )

        # Both projections must be PUBLISHED
        proj_a.refresh_from_db()
        proj_b.refresh_from_db()
        self.assertEqual(proj_a.status, PlatformProjection.Status.PUBLISHED)
        self.assertTrue(proj_a.frozen_content["body"].startswith("BODY-CHAN-A"))
        self.assertEqual(proj_b.status, PlatformProjection.Status.PUBLISHED)
        self.assertTrue(proj_b.frozen_content["body"].startswith("BODY-CHAN-B"))
