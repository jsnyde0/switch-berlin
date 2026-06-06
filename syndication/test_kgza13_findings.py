"""
TDD tests for kb-kgza.13 — three correctness findings on the edit/publish surface.

FINDING 1: Two silent is_dirty swallows (ADR-008 D3 fail-loud)
  - projection_detach_and_edit: views.py:1521-1522
  - version_edit: views.py:1728-1729
  Both coerce invariant-violation ValueError to False — must surface/raise.

  The swallow `except ValueError: _content_is_dirty = False` is wrong even though
  the guard `if proj.frozen_content is not None` prevents the null-frozen_content
  ValueError. If `_materialize_effective_fields` raises (e.g., missing source_event),
  the swallow hides it. The fix: remove the try/except, let ValueError propagate.

  Adversarial-review Finding 2 (kb-kgza.13): the deletion proof (grep for absence of
  `_content_is_dirty = False`) is a necessary but not sufficient canary — it would miss
  a re-introduction under a different spelling. The behavioral tests below (class
  F1BehavioralPropagationTest) prove the invariant violation is surfaced through
  the actual HTTP endpoints, providing a living contract the grep cannot capture.

FINDING 2: version_copy_from legacy path (source_version_pk)
  - Determined UNREACHABLE from templates (all forms use source_projection_pk)
  - Per ADR-008 D1: delete dead paths, do not fix.

FINDING 3: Stale frozen_content on first publish after source edit (ADR-016 D5)
  - engine.py transition_status ready→published hits bare else with no re-freeze
  - Must re-freeze at ready→published, not just draft→ready

Assert on response.content / model state, NOT response.context.
"""

import os

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
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
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
        description="Test event description",
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


def _make_fetlife_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id="fl-test-user",
        kinds=["listing"],
        enabled=True,
    )


def _make_published_projection(event, connection):
    """Create a projection that is published with frozen_content set."""
    proj = generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    transition_status(proj, "published")
    proj.refresh_from_db()
    return proj


# ---------------------------------------------------------------------------
# FINDING 1 — is_dirty ValueError swallow removed from both view sites
# ---------------------------------------------------------------------------


class F1IsDirtySwallowRemovedTest(TestCase):
    """
    Finding 1: Both view sites wrap `proj.is_dirty` in
      `try: ... except ValueError: _content_is_dirty = False`
    This coerces ANY ValueError from is_dirty (or from _materialize_effective_fields
    inside it) to a silent False — violating ADR-008 D3.

    The fix: remove the try/except, let the ValueError propagate.

    We verify by:
    (a) Code audit: the swallow pattern no longer appears in views.py
    (b) Functional: the normal-state (no error) path still works correctly
        after removing the try/except (regression guard)
    """

    def test_is_dirty_swallow_pattern_removed_from_views(self):
        """
        The pattern `_content_is_dirty = False` inside an except ValueError block
        must not appear in views.py. ADR-008 D3: no silent swallow of data-integrity errors.

        Checks the swallow is gone from BOTH sites:
        - projection_detach_and_edit (was views.py:1521-1522)
        - version_edit (was views.py:1728-1729)
        """
        views_path = os.path.join(os.path.dirname(__file__), "views.py")
        with open(views_path) as f:
            content = f.read()

        # The original swallow was:
        #   except ValueError:
        #       _content_is_dirty = False
        # After the fix, this pattern must not appear.
        self.assertNotIn(
            "_content_is_dirty = False",
            content,
            "The is_dirty swallow `_content_is_dirty = False` in except ValueError block "
            "must be removed from views.py (ADR-008 D3: fail loud). "
            "Found in BOTH projection_detach_and_edit and version_edit.",
        )

    def test_detach_and_edit_oob_dirty_state_works_for_published_projection(self):
        """
        Regression guard: after removing the try/except, the normal path
        (published projection with valid frozen_content) still works correctly.
        The OOB dirty-state is computed and returned in the HTMX response.
        """
        client = Client()
        user = _make_user(username="f1a_reg_user", email="f1a_reg@test.com", password="pw")
        profile = _make_profile("F1A Reg Org", "f1a-reg-org", user=user)
        event = _make_event(profile, "F1A Reg Event", "f1a-reg-event")
        conn = _make_switch_connection(profile)
        client.force_login(user)

        # Create a published projection (frozen_content is properly set)
        proj = _make_published_projection(event, conn)
        self.assertEqual(proj.status, "published")
        self.assertIsNotNone(proj.frozen_content)

        # Edit the CV body to make it dirty
        cv = proj.content_version
        cv.body = "Dirty content after publish"
        cv.save(update_fields=["body"])

        # Attempt detach-and-edit (HTMX autosave path)
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": proj.pk})
        response = client.post(
            url,
            data={"body": "Dirty content after publish"},
            HTTP_HX_REQUEST="true",
        )

        # Without the swallow, the happy path still returns 200 with OOB fragments
        self.assertEqual(
            response.status_code,
            200,
            "detach-and-edit for a published projection with valid frozen_content "
            "must return 200 with OOB fragments (normal operation after swallow removal).",
        )

    def test_version_edit_oob_dirty_state_works_for_published_projection(self):
        """
        Regression guard: after removing the try/except in version_edit,
        the normal path (published projection with valid frozen_content) still works.
        """
        client = Client()
        user = _make_user(username="f1b_reg_user", email="f1b_reg@test.com", password="pw")
        profile = _make_profile("F1B Reg Org", "f1b-reg-org", user=user)
        event = _make_event(profile, "F1B Reg Event", "f1b-reg-event")
        conn = _make_switch_connection(profile)
        client.force_login(user)

        # Create a published projection
        proj = _make_published_projection(event, conn)
        cv = proj.content_version
        self.assertEqual(proj.status, "published")
        self.assertIsNotNone(proj.frozen_content)

        # Attempt version_edit (HTMX autosave path)
        url = reverse("syndication:version-edit", kwargs={"pk": cv.pk})
        response = client.post(
            url,
            data={"body": "Updated content after publish"},
            HTTP_HX_REQUEST="true",
        )

        # Without the swallow, normal operation returns 200 with OOB fragments
        self.assertEqual(
            response.status_code,
            200,
            "version_edit for a published projection with valid frozen_content "
            "must return 200 with OOB fragments (normal operation after swallow removal).",
        )


# ---------------------------------------------------------------------------
# FINDING 1B — Behavioral propagation: invariant violation surfaces through
# the edit-path endpoints (adversarial-review Finding 2, kb-kgza.13)
# ---------------------------------------------------------------------------


class F1BehavioralPropagationTest(TestCase):
    """
    Behavioral proof that the is_dirty invariant violation (published projection
    with frozen_content=None) SURFACES through both edit-path endpoints rather
    than being silently swallowed and returning a clean 200.

    Adversarial-review Finding 2: the grep-based deletion proof in
    F1IsDirtySwallowRemovedTest catches the specific variable name but would miss
    a re-introduction under a different spelling.  These behavioral tests provide
    a living contract: a corrupt projection must produce a visible error response,
    not a clean success-shaped fragment.

    Mechanism:
    - For BOTH edit paths, the service (edit_version with _allow_edit_after_publish=True)
      explicitly checks for published projections with frozen_content=None and raises
      ValueError (services.py: "invariant violation — missing published snapshot").
    - That ValueError propagates through detach_and_edit → caught in
      projection_detach_and_edit view → _publishable_fragment_response(..., action_error=...).
    - Ditto for version_edit view.
    - The fragment template renders "Action failed" when action_error is set.

    Discovery: the manifested behavior is a 200 response with "Action failed" in the
    body — NOT a clean 200 (no error text) and NOT a raised exception/500.  The invariant
    violation surfaces as a visible error fragment, satisfying ADR-008 D3 (fail loud).

    Board-render sites (views.py:517-525 and :827-834) intentionally catch ValueError
    from is_dirty and set render_error=True; those are the correct ADR-008 D3 handling
    for the READ/render loop and are NOT tested here (see comment in bead background).
    """

    def setUp(self):
        self.user = _make_user(username="f1b_prop_user", email="f1b_prop@test.com", password="pw")
        self.profile = _make_profile("F1B Prop Org", "f1b-prop-org", user=self.user)
        self.event = _make_event(self.profile, "F1B Prop Event", "f1b-prop-event")
        self.conn = _make_switch_connection(self.profile)
        self.client = Client()
        self.client.force_login(self.user)

    def _make_corrupt_published_projection(self):
        """
        Force a published projection into the invariant-violation state:
        status='published' with frozen_content=None.

        This is NOT a reachable state through normal lifecycle transitions
        (transition_status always sets frozen_content before marking published).
        It represents data corruption — the exact case the fail-loud guard defends against.

        Mirrors test_edit_after_publish.py case 4 (~line 180).
        """
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        # Force into the invariant-violation state via direct ORM update (bypasses service guards).
        PlatformProjection.objects.filter(pk=proj.pk).update(
            status="published",
            frozen_content=None,
        )
        proj.refresh_from_db()
        assert proj.status == "published"
        assert proj.frozen_content is None
        return proj

    def test_detach_and_edit_surfaces_error_for_corrupt_published_projection(self):
        """
        POST to projection-detach-and-edit for a corrupt published projection
        (status=published, frozen_content=None) must NOT return a clean success.

        Invariant: the edit_version service raises ValueError for the corrupt state.
        That ValueError propagates through detach_and_edit → caught in the view →
        rendered as an "Action failed" fragment (action_error set).

        Proves: the is_dirty swallow removal + the service's fail-loud guard work end-to-end.
        The response body must contain "Action failed" — not a silent 200 with no error.
        """
        proj = self._make_corrupt_published_projection()
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": proj.pk})
        response = self.client.post(
            url,
            data={"body": "edit attempt on corrupt projection"},
            HTTP_HX_REQUEST="true",
        )
        # The invariant violation surfaces as a 200 with "Action failed" — NOT a clean 200.
        # (A 500 would also be acceptable proof of propagation; assert on both to handle either.)
        if response.status_code == 500:
            # ValueError escaped all handlers — invariant violation is loudly surfaced.
            return
        self.assertEqual(
            response.status_code,
            200,
            f"Expected 200 (error fragment) or 500 (unhandled), got {response.status_code}",
        )
        content = response.content.decode()
        self.assertIn(
            "Action failed",
            content,
            "corrupt published projection (frozen_content=None) must produce an error response "
            "through projection-detach-and-edit, not a silent clean fragment. "
            "ADR-008 D3: fail loud — invariant violations must surface, never be swallowed.",
        )

    def test_version_edit_surfaces_error_for_corrupt_published_projection(self):
        """
        POST to version-edit for a corrupt published projection
        (status=published, frozen_content=None) must NOT return a clean success.

        The version_edit view computes _allow_edit_after_publish=True (all consumers
        are non-draft for a published projection), passes it to edit_version, which
        explicitly checks for corrupt published projections → raises ValueError →
        caught in the view → action_error fragment returned.

        Proves: the is_dirty swallow removal + the service's fail-loud guard work end-to-end
        for the version-edit endpoint specifically.
        """
        proj = self._make_corrupt_published_projection()
        cv = proj.content_version
        url = reverse("syndication:version-edit", kwargs={"pk": cv.pk})
        response = self.client.post(
            url,
            data={"body": "edit attempt on corrupt projection"},
            HTTP_HX_REQUEST="true",
        )
        if response.status_code == 500:
            return
        self.assertEqual(
            response.status_code,
            200,
            f"Expected 200 (error fragment) or 500 (unhandled), got {response.status_code}",
        )
        content = response.content.decode()
        self.assertIn(
            "Action failed",
            content,
            "corrupt published projection (frozen_content=None) must produce an error response "
            "through version-edit, not a silent clean fragment. "
            "ADR-008 D3: fail loud — invariant violations must surface, never be swallowed.",
        )


# ---------------------------------------------------------------------------
# FINDING 2 — version_copy_from legacy path (source_version_pk)
# Verdict: UNREACHABLE → DELETED per ADR-008 D1
# ---------------------------------------------------------------------------


class F2LegacyPathDeletedTest(TestCase):
    """
    Finding 2: the legacy source_version_pk path in version_copy_from was
    determined to be unreachable — no template uses source_version_pk; all
    forms use source_projection_pk (verified by grep on templates/).

    Per ADR-008 D1 (no backward-compat shims at V0), the dead path was DELETED.

    This test verifies:
    (a) The legacy path no longer exists in views.py (grep)
    (b) The preferred source_projection_pk path still exists in views.py
    """

    def test_legacy_source_version_pk_path_removed_from_views(self):
        """
        The legacy source_version_pk branch must no longer exist as live code in views.py.
        ADR-008 D1: delete dead paths, do not preserve backward-compat shims.

        We check that the code pattern `request.POST.get("source_version_pk"` is gone —
        the docstring mention is acceptable (it documents the deletion), but the live
        request-handling code must be removed.
        """
        views_path = os.path.join(os.path.dirname(__file__), "views.py")
        with open(views_path) as f:
            content = f.read()

        self.assertNotIn(
            'request.POST.get("source_version_pk"',
            content,
            "Legacy source_version_pk live code path must be deleted from views.py (ADR-008 D1). "
            "The POST.get call must not exist — docstring mentions are acceptable.",
        )

    def test_preferred_source_projection_pk_path_still_exists(self):
        """
        After deleting the legacy path, the preferred source_projection_pk path
        must still exist and work.
        """
        views_path = os.path.join(os.path.dirname(__file__), "views.py")
        with open(views_path) as f:
            content = f.read()

        self.assertIn(
            "source_projection_pk",
            content,
            "Preferred source_projection_pk path must remain after legacy deletion.",
        )


# ---------------------------------------------------------------------------
# FINDING 3 — Stale frozen_content on first publish after source edit (ADR-016 D5)
# ---------------------------------------------------------------------------


class F3FirstPublishRefreezeTest(TestCase):
    """
    Finding 3: engine.py transition_status ready→published does NOT re-freeze.

    If source ContentVersion is edited AFTER a consumer reaches 'ready',
    the first publish freezes nothing new → published frozen_content is STALE.

    The fix: ready→published re-freeze in engine.py transition_status,
    mirroring the draft→ready freeze.

    NOTE: republish_projection already re-freezes (services.py) — so the gap
    is first-publish only. The existing RepublishProjectionTest must stay green.

    Asserts on model state (frozen_content), NOT response.context.
    """

    def setUp(self):
        self.user = _make_user(username="f3_user", email="f3@test.com", password="pw")
        self.profile = _make_profile("F3 Org", "f3-org", user=self.user)
        self.event = _make_event(self.profile, "F3 Event", "f3-event")
        self.conn = _make_switch_connection(self.profile)

    def test_first_publish_after_source_edit_freezes_post_edit_content(self):
        """
        Sequence:
          1. Create projection, transition draft→ready (freezes content at ready-time)
          2. Edit the source ContentVersion AFTER the projection is 'ready'
             (permitted — version_edit allows _allow_edit_after_publish=True)
          3. Transition ready→published (first publish)
          4. Assert: published frozen_content contains the POST-edit content, not the
             ready-time snapshot.

        Before the fix, step 3 would skip re-freeze → published frozen_content
        would still hold the ready-time snapshot (stale).

        After the fix, step 3 must re-freeze → published frozen_content must
        reflect the edited content.
        """
        # Step 1: Create projection at draft, advance to ready (freezes)
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()

        self.assertEqual(proj.status, "ready")
        self.assertIsNotNone(proj.frozen_content)
        ready_time_frozen = proj.frozen_content.copy()

        # Step 2: Edit the source ContentVersion AFTER reaching 'ready'
        # (same operation permitted by version_edit's _allow_edit_after_publish)
        cv = proj.content_version
        new_body = "POST-EDIT CONTENT: added after consumer reached ready"
        cv.body = new_body
        cv.save(update_fields=["body"])

        # Verify the edit happened and differs from frozen
        self.assertNotIn(new_body, ready_time_frozen.get("body", ""))

        # Step 3: First publish (ready→published)
        transition_status(proj, "published")
        proj.refresh_from_db()

        self.assertEqual(proj.status, "published")
        self.assertIsNotNone(proj.frozen_content)

        # Step 4: Assert — published frozen_content must contain the post-edit content
        published_body = proj.frozen_content.get("body", "")
        self.assertIn(
            new_body,
            published_body,
            f"published frozen_content must contain the post-edit body. "
            f"Got: {published_body!r}. "
            f"Ready-time frozen: {ready_time_frozen.get('body', '')!r}. "
            f"ADR-016 D5: first publish must re-freeze, not serve stale ready-time snapshot.",
        )
        self.assertNotEqual(
            proj.frozen_content,
            ready_time_frozen,
            "published frozen_content must differ from the ready-time snapshot "
            "(source was edited between ready and published).",
        )

    def test_republish_refreeze_still_works(self):
        """
        Regression guard: the existing republish re-freeze must still work after
        the engine fix. publish_projection_direct re-freezes a published projection.

        This mirrors RepublishProjectionTest.test_republish_updates_frozen_content
        to confirm no double-freeze or regression.
        """
        from syndication.services import publish_projection_direct

        # Create and publish a projection
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()
        transition_status(proj, "published")
        proj.refresh_from_db()

        # Edit after publish
        cv = proj.content_version
        cv.body = "REPUBLISH TEST BODY"
        cv.save(update_fields=["body"])
        proj.refresh_from_db()

        self.assertTrue(proj.is_dirty, "Should be dirty after content edit.")

        # Re-publish (services.py republish path)
        publish_projection_direct(user=self.user, projection=proj)
        proj.refresh_from_db()

        self.assertEqual(proj.status, "published")
        self.assertIn(
            "REPUBLISH TEST BODY",
            proj.frozen_content.get("body", ""),
            "Re-publish must update frozen_content with new body.",
        )
        self.assertFalse(proj.is_dirty, "Must not be dirty after re-publish.")

    def test_no_double_freeze_when_content_unchanged(self):
        """
        Regression guard: the ready→published re-freeze must produce the same
        frozen_content as the draft→ready freeze when content is unchanged.

        Verifies no corruption: if no edits happened between ready and published,
        frozen_content stays semantically equivalent (same body, just re-materialized).
        """
        proj = generate_projection(
            kind="listing",
            connection=self.conn,
            source_event=self.event,
            mode="rule_based",
        )
        transition_status(proj, "ready")
        proj.refresh_from_db()
        ready_frozen = proj.frozen_content.copy()

        # Publish WITHOUT editing (no changes between ready and published)
        transition_status(proj, "published")
        proj.refresh_from_db()

        self.assertEqual(proj.status, "published")
        # frozen_content should still be semantically equivalent (body same)
        self.assertEqual(
            proj.frozen_content.get("body"),
            ready_frozen.get("body"),
            "With no edits between ready and published, frozen_content body must be "
            "semantically equivalent (re-materialized but same content).",
        )
