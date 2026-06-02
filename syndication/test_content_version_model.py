"""
TDD tests for ContentVersion model (bead kb-wz8m.1, updated kb-q4u9.1).

Additive-only step: introduces ContentVersion and a nullable content_version FK
on PlatformProjection. No behavior change — override_data still exists and no
code reads content_version yet.

Acceptance: ContentVersion model exists with correct fields; nullable
content_version FK exists on PlatformProjection; migrations are clean (checked
separately via makemigrations --check --dry-run).

kb-q4u9.1 additions: ContentVersion generalized to publishable-scoped.
- event FK nullable, post FK added (nullable), CheckConstraint enforces exactly-one-of.
- (event,name) unique split into two partial constraints (one per FK).

canonical_refs: ADR-016 D2 (content-version evolution, revised 2026-05-29),
ADR-008 D1 (no back-compat shims), ADR-008 D2 (no Publishable base model),
ADR-008 D3 (fail loud on integrity violation), ADR-003 (cheap foresight on data shape).
"""

from django.test import TestCase
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from syndication.models import (
    ContentVersion,
    PlatformConnection,
    PlatformProjection,
    Post,
)


def _make_event(**kwargs):
    """Create a minimal Event for test setup."""
    from django.utils import timezone as tz

    defaults = {
        "title": "Test Event",
        "slug": "test-event",
        "start": tz.now(),
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_profile(**kwargs):
    """Create a minimal Profile for test setup."""
    import uuid

    defaults = {
        "name": f"Test Organizer {uuid.uuid4().hex[:6]}",
        "slug": f"test-org-{uuid.uuid4().hex[:6]}",
    }
    defaults.update(kwargs)
    return Profile.objects.create(**defaults)


def _make_post(event, **kwargs):
    """Create a minimal Post for test setup."""
    import uuid

    defaults = {
        "event": event,
        "headline": f"Post {uuid.uuid4().hex[:6]}",
        "body": "Test body content.",
    }
    defaults.update(kwargs)
    return Post.objects.create(**defaults)


def _make_connection(profile, **kwargs):
    """Create a minimal PlatformConnection for test setup."""
    defaults = {
        "organizer": profile,
        "platform": "switch",
        "destination_id": "own-page",
        "kinds": ["listing"],
    }
    defaults.update(kwargs)
    return PlatformConnection.objects.create(**defaults)


class ContentVersionModelExistsTest(TestCase):
    """ContentVersion model must exist with the correct field set (ADR-016 D2)."""

    def test_content_version_model_importable(self):
        """ContentVersion must be importable from syndication.models."""
        # noqa: F401 — importability check only
        from syndication.models import ContentVersion  # noqa: F401

    def test_content_version_can_be_created_for_event(self):
        """ContentVersion is per-Event: it must accept an event FK."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertEqual(cv.event, event)
        self.assertEqual(cv.name, "v1")

    def test_content_version_has_name_field(self):
        """ContentVersion must carry a name field (named editorial copy variant)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="canonical")
        self.assertEqual(cv.name, "canonical")

    def test_content_version_has_headline_field(self):
        """ContentVersion carries headline (nullable/blank)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", headline="Join us!")
        self.assertEqual(cv.headline, "Join us!")

    def test_content_version_headline_optional(self):
        """
        ContentVersion.headline must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical' (null-means-derive semantics).
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.headline)

    def test_content_version_has_body_field(self):
        """ContentVersion carries body text field."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", body="Come party.")
        self.assertEqual(cv.body, "Come party.")

    def test_content_version_body_optional(self):
        """
        ContentVersion.body must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical' (null-means-derive semantics).
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.body)

    def test_content_version_has_imagery_field(self):
        """ContentVersion carries imagery (JSON, nullable)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", imagery=["img1.jpg"])
        self.assertEqual(cv.imagery, ["img1.jpg"])

    def test_content_version_imagery_optional(self):
        """ContentVersion.imagery must be optional (null default)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.imagery)

    def test_content_version_has_cta_field(self):
        """ContentVersion carries cta (call to action)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", cta="https://example.com")
        self.assertEqual(cv.cta, "https://example.com")

    def test_content_version_cta_optional(self):
        """
        ContentVersion.cta must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical'.
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.cta)

    def test_content_version_has_voice_field(self):
        """ContentVersion carries voice/tone field."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1", voice="playful")
        self.assertEqual(cv.voice, "playful")

    def test_content_version_voice_optional(self):
        """
        ContentVersion.voice must be optional (nullable).
        kb-wz8m.2: null means 'derive from canonical'.
        """
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.voice)


class ContentVersionProvenanceFieldsTest(TestCase):
    """ContentVersion carries content-authorship signals (ADR-016 D2)."""

    def test_content_version_has_provenance_field(self):
        """ContentVersion must carry provenance ∈ {rule_template, agent_supplied, manual}."""  # noqa: E501
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.assertEqual(cv.provenance, "rule_template")

    def test_content_version_provenance_defaults_to_rule_template(self):
        """ContentVersion.provenance default is rule_template."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertEqual(cv.provenance, ContentVersion.Provenance.RULE_TEMPLATE)

    def test_content_version_provenance_agent_supplied(self):
        """ContentVersion.provenance accepts agent_supplied."""
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            provenance=ContentVersion.Provenance.AGENT_SUPPLIED,
        )
        self.assertEqual(cv.provenance, "agent_supplied")

    def test_content_version_provenance_manual(self):
        """ContentVersion.provenance accepts manual."""
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        self.assertEqual(cv.provenance, "manual")

    def test_content_version_has_generated_by_field(self):
        """ContentVersion carries generated_by (nullable agent identity)."""
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            generated_by="claude-code-agent",
        )
        self.assertEqual(cv.generated_by, "claude-code-agent")

    def test_content_version_generated_by_nullable(self):
        """ContentVersion.generated_by must be nullable (null default)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.generated_by)

    def test_content_version_has_last_generated_at_field(self):
        """ContentVersion carries last_generated_at (nullable datetime)."""
        now = timezone.now()
        event = _make_event()
        cv = ContentVersion.objects.create(
            event=event,
            name="v1",
            last_generated_at=now,
        )
        self.assertEqual(cv.last_generated_at, now)

    def test_content_version_last_generated_at_nullable(self):
        """ContentVersion.last_generated_at must be nullable (null default)."""
        event = _make_event()
        cv = ContentVersion.objects.create(event=event, name="v1")
        self.assertIsNone(cv.last_generated_at)


class ContentVersionUniquenessTest(TestCase):
    """
    ContentVersion (event, name) pair must be unique within an event.

    Same name on DIFFERENT events is allowed (uniqueness is scoped per-event).
    Duplicate (event, name) must raise IntegrityError (ADR-016 D2 revised
    2026-05-29; kb-wz8m.2 seeds exactly one 'canonical' version per event and
    must not create duplicates).
    """

    def test_duplicate_name_on_same_event_raises_integrity_error(self):
        """Two ContentVersions with the same name on the same event must fail."""
        from django.db import IntegrityError

        event = _make_event(slug="unique-test-event")
        ContentVersion.objects.create(event=event, name="canonical")
        with self.assertRaises(IntegrityError):
            ContentVersion.objects.create(event=event, name="canonical")

    def test_same_name_on_different_events_is_allowed(self):
        """The uniqueness constraint is scoped per-event; cross-event reuse is fine."""
        event_a = _make_event(slug="event-a-uniq")
        event_b = _make_event(slug="event-b-uniq")
        cv_a = ContentVersion.objects.create(event=event_a, name="canonical")
        cv_b = ContentVersion.objects.create(event=event_b, name="canonical")
        self.assertEqual(cv_a.name, cv_b.name)
        self.assertNotEqual(cv_a.event_id, cv_b.event_id)


class ContentVersionStrTest(TestCase):
    """ContentVersion.__str__ should be human-readable."""

    def test_content_version_str_includes_name(self):
        """__str__ of ContentVersion includes the name field."""
        event = _make_event(title="My Event")
        cv = ContentVersion.objects.create(event=event, name="campaign-v1")
        self.assertIn("campaign-v1", str(cv))


class PlatformProjectionContentVersionFKTest(TestCase):
    """
    PlatformProjection.content_version FK (ADR-016 D2).

    kb-wz8m.1 added the nullable FK (additive step).
    kb-wz8m.2 made it non-null (A1 invariant: every projection always has a version).
    """

    def test_platform_projection_has_content_version_field(self):
        """PlatformProjection.content_version field must exist on the model."""
        # Check via _meta.get_field — hasattr on an unsaved instance is unreliable
        # for non-null FKs (no default, descriptor raises before __get__ returns).
        try:
            field = PlatformProjection._meta.get_field("content_version")
            self.assertIsNotNone(field)
        except Exception as exc:
            self.fail(f"PlatformProjection must have a content_version field: {exc}")

    def test_platform_projection_content_version_non_null_after_cutover(self):
        """
        kb-wz8m.2 cutover: content_version FK is non-null (A1 invariant).
        Every projection must be created with a content_version.
        """
        event = _make_event()
        profile = _make_profile()
        conn = _make_connection(profile)
        cv = ContentVersion.objects.create(event=event, name="canonical")
        pp = PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        self.assertIsNotNone(pp.content_version)
        self.assertEqual(pp.content_version, cv)

    def test_platform_projection_content_version_can_be_set(self):
        """content_version FK can be set to a ContentVersion instance."""
        event = _make_event()
        profile = _make_profile()
        conn = _make_connection(profile)
        cv = ContentVersion.objects.create(event=event, name="v1")
        pp = PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        self.assertEqual(pp.content_version, cv)

    def test_platform_projection_override_data_removed(self):
        """
        kb-wz8m.2 cutover: override_data must NOT be present on PlatformProjection.
        Content fields now live on ContentVersion (ADR-016 D2, ADR-008 D1).
        """
        event = _make_event()
        profile = _make_profile()
        conn = _make_connection(profile)
        cv = ContentVersion.objects.create(event=event, name="canonical")
        pp = PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        self.assertFalse(
            hasattr(pp, "override_data"),
            "PlatformProjection must NOT have override_data after kb-wz8m.2 cutover",
        )

    def test_multiple_projections_can_share_one_content_version(self):
        """
        Multiple projections may point at one ContentVersion
        (single-row sharing — ADR-016 D2 content-version evolution).
        """
        event = _make_event()
        profile = _make_profile()
        conn1 = _make_connection(profile, destination_id="own-page", kinds=["listing"])
        conn2 = _make_connection(profile, platform="fetlife", destination_id="user123", kinds=["listing"])
        cv = ContentVersion.objects.create(event=event, name="shared")
        pp1 = PlatformProjection.objects.create(
            connection=conn1,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        pp2 = PlatformProjection.objects.create(
            connection=conn2,
            kind=PlatformProjection.Kind.LISTING,
            source_event=event,
            content_version=cv,
        )
        self.assertEqual(pp1.content_version, cv)
        self.assertEqual(pp2.content_version, cv)
        self.assertEqual(pp1.content_version_id, pp2.content_version_id)


# ---------------------------------------------------------------------------
# kb-q4u9.1: ContentVersion publishable-scoped schema tests
# ---------------------------------------------------------------------------


class ContentVersionPublishableScopeCheckConstraintTest(TestCase):
    """
    ContentVersion exactly-one-of check constraint (ADR-008 D3 — fail loud).

    Exactly one of (event, post) must be non-null. Both set OR neither set
    must raise IntegrityError at write-time.
    """

    def test_content_version_with_event_only_succeeds(self):
        """ContentVersion with event=<E>, post=None must succeed."""
        event = _make_event(slug="cv-event-only")
        cv = ContentVersion.objects.create(event=event, post=None, name="canonical")
        self.assertIsNotNone(cv.pk)
        self.assertEqual(cv.event, event)
        self.assertIsNone(cv.post)

    def test_content_version_with_post_only_succeeds(self):
        """ContentVersion with event=None, post=<P> must succeed."""
        event = _make_event(slug="cv-post-only-event")
        post = _make_post(event)
        cv = ContentVersion.objects.create(event=None, post=post, name="canonical")
        self.assertIsNotNone(cv.pk)
        self.assertIsNone(cv.event)
        self.assertEqual(cv.post, post)

    def test_content_version_with_both_event_and_post_raises(self):
        """Both event+post set must raise IntegrityError (ADR-008 D3)."""
        from django.db import IntegrityError

        event = _make_event(slug="cv-both-set-event")
        post = _make_post(event)
        with self.assertRaises(IntegrityError):
            ContentVersion.objects.create(event=event, post=post, name="canonical")

    def test_content_version_with_neither_event_nor_post_raises(self):
        """ContentVersion with neither event nor post must raise IntegrityError (D3)."""
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            ContentVersion.objects.create(event=None, post=None, name="canonical")

    def test_check_constraint_exists_in_meta(self):
        """CheckConstraint for exactly-one-of must be in ContentVersion.Meta."""
        from django.db.models import CheckConstraint

        constraint_names = [c.name for c in ContentVersion._meta.constraints]
        check_constraints = [c for c in ContentVersion._meta.constraints if isinstance(c, CheckConstraint)]
        self.assertTrue(
            len(check_constraints) >= 1,
            f"Expected at least one CheckConstraint in ContentVersion.Meta.constraints; found: {constraint_names}",
        )


class ContentVersionPostFKFieldTest(TestCase):
    """ContentVersion.post FK: exists, nullable, CASCADE on_delete."""

    def test_content_version_has_post_field(self):
        """ContentVersion must have a post field."""
        try:
            field = ContentVersion._meta.get_field("post")
            self.assertIsNotNone(field)
        except Exception as exc:
            self.fail(f"ContentVersion must have a post field: {exc}")

    def test_content_version_post_field_is_nullable(self):
        """ContentVersion.post FK must be nullable."""
        field = ContentVersion._meta.get_field("post")
        self.assertTrue(field.null, "ContentVersion.post must be nullable")

    def test_content_version_event_field_is_nullable(self):
        """ContentVersion.event FK must be nullable (generalized from event-only)."""
        field = ContentVersion._meta.get_field("event")
        self.assertTrue(field.null, "ContentVersion.event must be nullable (kb-q4u9.1)")

    def test_content_version_can_be_created_for_post(self):
        """ContentVersion can be created attached to a Post (post=<P>, event=None)."""
        event = _make_event(slug="cv-post-fk-event")
        post = _make_post(event)
        cv = ContentVersion.objects.create(post=post, name="canonical")
        cv.refresh_from_db()
        self.assertEqual(cv.post, post)
        self.assertIsNone(cv.event)


class ContentVersionPartialUniqueConstraintTest(TestCase):
    """
    (event,name) and (post,name) partial unique constraints (kb-q4u9.1).

    The original single (event,name) unique is split into two partial constraints
    so that two different posts can independently hold a name='canonical' row,
    and an event + a post can each independently hold name='canonical'.
    """

    def test_two_posts_can_each_hold_canonical_name(self):
        """Two separate Posts can each have a ContentVersion named 'canonical'."""
        event = _make_event(slug="cv-two-posts-event")
        post_a = _make_post(event)
        post_b = _make_post(event)
        cv_a = ContentVersion.objects.create(post=post_a, name="canonical")
        cv_b = ContentVersion.objects.create(post=post_b, name="canonical")
        self.assertNotEqual(cv_a.pk, cv_b.pk)
        self.assertEqual(cv_a.name, cv_b.name)

    def test_event_and_post_can_each_independently_hold_canonical_name(self):
        """Event-owned and post-owned CVs can both be named 'canonical'."""
        event = _make_event(slug="cv-event-post-indep-event")
        post = _make_post(event)
        cv_event = ContentVersion.objects.create(event=event, name="canonical")
        cv_post = ContentVersion.objects.create(post=post, name="canonical")
        self.assertNotEqual(cv_event.pk, cv_post.pk)
        self.assertEqual(cv_event.name, cv_post.name)

    def test_duplicate_post_name_raises(self):
        """Two CVs on the same Post with the same name must raise IntegrityError."""
        from django.db import IntegrityError

        event = _make_event(slug="cv-dup-post-event")
        post = _make_post(event)
        ContentVersion.objects.create(post=post, name="canonical")
        with self.assertRaises(IntegrityError):
            ContentVersion.objects.create(post=post, name="canonical")

    def test_event_partial_unique_constraint_present(self):
        """(event,name) partial unique must be in ContentVersion.Meta."""
        from django.db.models import UniqueConstraint

        partial_uniq = [
            c for c in ContentVersion._meta.constraints if isinstance(c, UniqueConstraint) and c.condition is not None
        ]
        event_constraint = next(
            (c for c in partial_uniq if "event" in c.fields),
            None,
        )
        self.assertIsNotNone(
            event_constraint,
            "Expected partial UniqueConstraint on (event, name) in ContentVersion.Meta.constraints",
        )

    def test_post_partial_unique_constraint_present(self):
        """(post,name) partial unique must be in ContentVersion.Meta."""
        from django.db.models import UniqueConstraint

        partial_uniq = [
            c for c in ContentVersion._meta.constraints if isinstance(c, UniqueConstraint) and c.condition is not None
        ]
        post_constraint = next(
            (c for c in partial_uniq if "post" in c.fields),
            None,
        )
        self.assertIsNotNone(
            post_constraint,
            "Expected partial UniqueConstraint on (post, name) in ContentVersion.Meta.constraints",
        )


class ContentVersionStrUpdatedTest(TestCase):
    """
    ContentVersion.__str__ must not assume event-only (kb-q4u9.1).
    Both event-owned and post-owned versions must produce readable strings.
    """

    def test_str_includes_name_for_event_owned_version(self):
        """__str__ includes the name for an event-owned ContentVersion."""
        event = _make_event(slug="cv-str-event")
        cv = ContentVersion.objects.create(event=event, name="campaign-v1")
        self.assertIn("campaign-v1", str(cv))

    def test_str_includes_name_for_post_owned_version(self):
        """__str__ includes the name for a post-owned ContentVersion."""
        event = _make_event(slug="cv-str-post-event")
        post = _make_post(event)
        cv = ContentVersion.objects.create(post=post, name="campaign-v1")
        self.assertIn("campaign-v1", str(cv))
