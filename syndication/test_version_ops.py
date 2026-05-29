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

from django.contrib.auth import get_user_model
from django.test import TestCase
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
        conn2 = _make_connection(
            self.profile, platform="switch", destination_id="sw-cons-002", kinds=["listing"]
        )
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
        conn2 = _make_connection(
            self.profile, platform="switch", destination_id="sw-cons-excl", kinds=["listing"]
        )
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
        proj = _make_projection(self.conn, self.event, cv=cv)

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
        conn2 = _make_connection(
            self.profile, platform="switch", destination_id="sw-cvmap-002", kinds=["listing"]
        )
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

        proj = _make_projection(self.conn, self.event, cv=cv)
        new_cv = duplicate(self.user, cv)

        self.assertEqual(new_cv.headline, "Test Headline")
        self.assertEqual(new_cv.body, "Test Body")
        self.assertEqual(new_cv.cta, "Buy tickets")
        self.assertEqual(new_cv.voice, "playful")

    def test_duplicate_same_event(self):
        """duplicate creates new version for the same event."""
        from syndication.services import duplicate

        cv = _make_canonical_cv(self.event)
        proj = _make_projection(self.conn, self.event, cv=cv)
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

        new_cv = duplicate(self.user, cv)

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
        self.conn_b = _make_connection(
            self.profile, platform="switch", destination_id="sw-cust-b", kinds=["listing"]
        )

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
        self.conn_b = _make_connection(
            self.profile, platform="switch", destination_id="sw-cpfrom-b", kinds=["listing"]
        )

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
        self.conn_b = _make_connection(
            self.profile, platform="switch", destination_id="sw-cpto-b", kinds=["listing"]
        )
        self.conn_c = _make_connection(
            self.profile, platform="telegram", destination_id="tg-cpto-c", kinds=["listing"]
        )

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

        new_versions = copy_to(self.user, source_cv, [proj_b, proj_c])
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
        from syndication.services import reset_to_canonical, customize

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
        from syndication.services import reset_to_canonical, customize

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
        from syndication.services import reset_to_canonical, customize

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
        self.conn_b = _make_connection(
            self.profile, platform="switch", destination_id="sw-editv-b", kinds=["listing"]
        )

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
        from syndication.services import edit_version, approve_projection

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
        from syndication.services import edit_version, approve_projection

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
        from syndication.services import edit_version, approve_projection

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
        proj_a = _make_projection(self.conn_a, self.event, cv=cv)
        proj_b = _make_projection(self.conn_b, self.event, cv=cv)

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
