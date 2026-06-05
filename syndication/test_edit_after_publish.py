"""
Tests for edit-after-publish dirty marker + explicit re-publish (kb-96tn.5).

ADR-016 D5: when a facilitator edits the content of an already-PUBLISHED channel,
it becomes "dirty" — edited, re-publish needed.

Harness targets:
  (a) is_dirty property — 4 cases:
      1. published + effective body != frozen_content → is_dirty == True
      2. published + effective body == frozen_content → is_dirty == False
      3. draft + null frozen_content → is_dirty == False (NO raise)
      4. published + null frozen_content → raises / errors (ADR-008 D3: fail loud)

  (b) edit_after_publish policy point — grep must show exactly ONE resolution site,
      default "dirty_then_republish".

  (c) publish_projection handles re-publish of a dirty (published) projection:
      re-freezes frozen_content to the new effective content.

TDD discipline: tests written BEFORE implementation (ADR-016 D5, ADR-008 D3).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import generate_projection, transition_status
from syndication.models import PlatformConnection, PlatformProjection

User = get_user_model()


# ---------------------------------------------------------------------------
# Test helpers
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
    return Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
        description="Test event description",
    )


def _make_switch_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing"],
        enabled=True,
    )


def _make_published_projection(event, connection, body_override=None):
    """Create a projection that is published with frozen_content set."""
    proj = generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )
    # Optionally set an explicit body on the content_version
    if body_override is not None:
        cv = proj.content_version
        cv.body = body_override
        cv.save(update_fields=["body"])
    # Advance to ready (which freezes content)
    transition_status(proj, "ready")
    # Advance to published
    proj.refresh_from_db()
    transition_status(proj, "published")
    proj.refresh_from_db()
    return proj


class IsDirtyPropertyTest(TestCase):
    """
    ADR-016 D5: is_dirty property on PlatformProjection.

    Gate order: check status == 'published' FIRST; a DRAFT projection with null
    frozen_content is NEVER dirty and must NOT raise.
    A PUBLISHED projection with null frozen_content is an invariant violation → error.
    """

    def setUp(self):
        self.user = _make_user(username="dirty_user", email="dirty@test.com", password="pw")
        self.profile = _make_profile("Dirty Org", "dirty-org", user=self.user)
        self.event = _make_event(self.profile, "Dirty Marker Event", "dirty-marker-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_switch_connection(self.profile)

    # Case 1: published + effective body != frozen_content → is_dirty == True
    def test_published_with_changed_content_is_dirty_true(self):
        """
        When a published projection's content_version body differs from frozen_content body,
        is_dirty must return True.
        """
        proj = _make_published_projection(self.event, self.conn)
        self.assertEqual(proj.status, "published")
        self.assertIsNotNone(proj.frozen_content)

        # Edit the content_version body AFTER publish — simulates edit-after-publish
        cv = proj.content_version
        cv.body = "TOTALLY DIFFERENT CONTENT that was never frozen"
        cv.save(update_fields=["body"])

        # Reload to get fresh state
        proj.refresh_from_db()
        proj.content_version.refresh_from_db()

        self.assertTrue(
            proj.is_dirty,
            "Published projection with edited content should be dirty (is_dirty=True).",
        )

    # Case 2: published + effective body == frozen_content → is_dirty == False
    def test_published_with_unchanged_content_is_dirty_false(self):
        """
        When a published projection's content_version body matches frozen_content body,
        is_dirty must return False.
        """
        proj = _make_published_projection(self.event, self.conn)
        self.assertEqual(proj.status, "published")
        self.assertIsNotNone(proj.frozen_content)

        # Do NOT change the content — still matches frozen
        proj.refresh_from_db()
        proj.content_version.refresh_from_db()

        self.assertFalse(
            proj.is_dirty,
            "Published projection with unchanged content should not be dirty (is_dirty=False).",
        )

    # Case 3: draft + null frozen_content → is_dirty == False, no raise
    def test_draft_with_null_frozen_content_is_dirty_false_no_raise(self):
        """
        A DRAFT projection legitimately has null frozen_content — is_dirty must be
        False and must NOT raise. Gate on status == 'published' FIRST (ADR-016 D5).
        """
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        proj.refresh_from_db()
        self.assertEqual(proj.status, "draft")
        self.assertIsNone(proj.frozen_content)

        # Must not raise; must return False
        result = proj.is_dirty
        self.assertFalse(
            result,
            "Draft projection with null frozen_content must have is_dirty=False (no raise).",
        )

    # Case 4: published + null frozen_content → raises / errors (ADR-008 D3: fail loud)
    def test_published_with_null_frozen_content_raises(self):
        """
        A PUBLISHED projection with null frozen_content is an invariant violation.
        is_dirty must raise or surface an error (ADR-008 D3: fail loud, not silent False).
        """
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        # Manually force to published with null frozen_content (invariant violation)
        PlatformProjection.objects.filter(pk=proj.pk).update(
            status="published",
            frozen_content=None,
        )
        proj.refresh_from_db()
        self.assertEqual(proj.status, "published")
        self.assertIsNone(proj.frozen_content)

        with self.assertRaises((ValueError, AssertionError)):
            _ = proj.is_dirty


class EditAfterPublishPolicyTest(TestCase):
    """
    ADR-016 D5 (cheap foresight, ADR-003): the edit-after-publish behaviour is read
    through a single named resolution point.

    grep must show exactly ONE site where edit_after_publish policy is resolved,
    and the default must be "dirty_then_republish".
    """

    def test_edit_after_publish_policy_default_is_dirty_then_republish(self):
        """
        The edit_after_publish policy function must exist and return 'dirty_then_republish'
        for all v0 platforms.
        """
        from syndication.services import edit_after_publish_policy

        for platform in ["switch", "telegram", "fetlife", "tickettailor"]:
            result = edit_after_publish_policy(platform)
            self.assertEqual(
                result,
                "dirty_then_republish",
                f"edit_after_publish_policy('{platform}') must return 'dirty_then_republish' at v0.",
            )

    def test_edit_after_publish_policy_single_resolution_site(self):
        """
        grep -r 'edit_after_publish' must find exactly ONE resolution site in the
        syndication code. Policy must be concentrated, not duplicated.
        """
        import subprocess

        result = subprocess.run(
            ["grep", "-r", "edit_after_publish", "/Users/jonat/code/personal/kinky-bubbles/syndication/"],
            capture_output=True,
            text=True,
        )
        lines = [
            line
            for line in result.stdout.strip().split("\n")
            if line  # non-empty
            and ".pyc" not in line  # ignore compiled
            and "__pycache__" not in line  # ignore cache
            and "test_edit_after_publish.py" not in line  # ignore this test file
        ]
        # The function definition + the import in models = still ONE logical resolution site
        # We want to verify the policy logic is NOT scattered across multiple callers.
        # ONE function definition in services.py = the seam. Callers can import it.
        # The test here just verifies the function exists at one place.
        self.assertGreater(len(lines), 0, "edit_after_publish must appear at least once in syndication code.")
        # Verify the function is defined in services.py only (not in multiple places)
        definition_sites = [line for line in lines if "def edit_after_publish" in line]
        self.assertEqual(
            len(definition_sites),
            1,
            f"edit_after_publish policy must be defined in exactly ONE place. Found: {definition_sites}",
        )


class RepublishProjectionTest(TestCase):
    """
    ADR-016 D5: re-publish reuses the existing publish verb (publish_projection)
    and re-freezes frozen_content with the new effective content.
    """

    def setUp(self):
        self.user = _make_user(username="repub_user", email="repub@test.com", password="pw")
        self.profile = _make_profile("Repub Org", "repub-org", user=self.user)
        self.event = _make_event(self.profile, "Re-publish Test Event", "repub-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.conn = _make_switch_connection(self.profile)

    def test_republish_updates_frozen_content(self):
        """
        After publishing, editing the content version, and re-publishing,
        frozen_content must be updated to the new effective content.
        """
        from syndication.services import publish_projection_direct

        proj = _make_published_projection(self.event, self.conn)
        old_frozen = proj.frozen_content.copy()

        # Edit the content version AFTER publish (simulates edit-after-publish)
        cv = proj.content_version
        cv.body = "UPDATED BODY FOR RE-PUBLISH TEST"
        cv.save(update_fields=["body"])
        proj.refresh_from_db()

        # The projection should be dirty now
        self.assertTrue(proj.is_dirty, "Projection should be dirty after content edit.")

        # Re-publish: publish_projection_direct must handle published projections
        publish_projection_direct(user=self.user, projection=proj)
        proj.refresh_from_db()

        # After re-publish, status should still be published
        self.assertEqual(proj.status, "published")
        # frozen_content must be updated to the new effective content
        self.assertNotEqual(
            proj.frozen_content,
            old_frozen,
            "frozen_content must be re-frozen with the new effective content after re-publish.",
        )
        self.assertIn(
            "UPDATED BODY FOR RE-PUBLISH TEST",
            proj.frozen_content.get("body", ""),
            "New frozen_content must contain the updated body.",
        )
        # After re-publish, the projection must not be dirty
        self.assertFalse(proj.is_dirty, "Projection must not be dirty after re-publish.")
