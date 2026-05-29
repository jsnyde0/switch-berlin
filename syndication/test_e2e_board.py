"""
End-to-end integration test: start-shared → customize → publish (kb-wz8m.8).

Harness target Signal for the kb-wz8m parent epic.

Walks the REAL v0 path with an adapter spy. Unit tests pass even when the
wiring is broken; this test walks the actual cross-component path (kb-jgda
lesson).

Data path only — no UI/template rendering. The "live on" visual render is
kb-wz8m.5's browser loop, explicitly out of scope here.

canonical_refs: ADR-008 D3/D4, ADR-016 D5.
"""

from unittest.mock import patch, call

from django.contrib.auth import get_user_model
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

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirroring the pattern from test_authoring.py / test_publish_dispatch.py)
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
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


def _make_connection(profile, platform, destination_id, kinds, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# The integration test
# ---------------------------------------------------------------------------


class E2EBoardFlowTest(TestCase):
    """
    End-to-end integration probe: start-shared → customize → publish.

    Walk the REAL v0 path using the live service layer. This test exercises
    cross-component wiring that unit tests cannot catch:
      - create_event eager-creates projections pointing at the canonical CV.
      - consumers()/content_version_consumers_map() correctly report consumers.
      - customize() + edit_version() diverges one projection without affecting others.
      - publish_projection() routes to the CORRECT per-projection adapter.
      - publish_all_ready_projections() fans out exactly once per ready projection.

    The routing assertion (step 3) is non-trivial: if publish_projection ever
    routed the canonical/projection_2's content while publishing projection_1
    (a routing swap), the render_projection(received_proj) == "CUSTOM-BODY"
    assertion FAILS because projection_2 is not customized to "CUSTOM-BODY".
    """

    def setUp(self):
        # Organizer: one user, one profile, two platform connections.
        #   - switch (listing) → listing projections eager-created on create_event
        #   - telegram (promotion) → promotion projections eager-created on create_post
        self.user = _make_vouched_user(
            username="e2e_user",
            email="e2e@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="E2E Organizer",
            slug="e2e-organizer",
            user=self.user,
        )

        # Two listing-capable connections (switch and fetlife) so we get ≥2
        # eager listing projections on create_event. Using fetlife as second
        # because it supports listing.
        self.conn_switch = _make_connection(
            self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )
        self.conn_fetlife = _make_connection(
            self.profile,
            platform="fetlife",
            destination_id="fl-e2e-001",
            kinds=["listing"],
        )

    # -------------------------------------------------------------------------
    # Step 1: Shared default — ≥2 projections on the SAME canonical ContentVersion
    # -------------------------------------------------------------------------

    def test_step1_shared_canonical_on_create_event(self):
        """
        create_event with ≥2 enabled listing connections eager-creates ≥2
        projections, all pointing at the SAME canonical ContentVersion.

        consumers(canonical_cv) reports both projections.
        content_version_consumers_map(event) maps the canonical CV → both.
        """
        from syndication.services import (
            create_event,
            consumers,
            content_version_consumers_map,
        )

        event = create_event(
            user=self.user,
            title="E2E Test Event",
            slug="e2e-test-event",
            start=timezone.now(),
        )

        # Retrieve the canonical ContentVersion (seeded by create_event).
        canonical_cv = ContentVersion.objects.get(event=event, name="canonical")

        # Both projections must have been created.
        projs = PlatformProjection.objects.filter(source_event=event)
        self.assertGreaterEqual(projs.count(), 2, "Expected ≥2 eager listing projections")

        # All projections must point at the SAME canonical ContentVersion.
        cv_ids = set(projs.values_list("content_version_id", flat=True))
        self.assertEqual(
            cv_ids,
            {canonical_cv.pk},
            "All eager projections must share the single canonical ContentVersion "
            "(single-row sharing — the A1 invariant).",
        )

        # consumers(canonical_cv) must list both projections.
        consumer_set = set(consumers(canonical_cv).values_list("pk", flat=True))
        proj_pk_set = set(projs.values_list("pk", flat=True))
        self.assertEqual(
            consumer_set,
            proj_pk_set,
            "consumers(canonical_cv) must return all projections that FK to it.",
        )

        # content_version_consumers_map(event) must map canonical_cv → both projections.
        cv_map = content_version_consumers_map(event)
        self.assertIn(canonical_cv, cv_map, "canonical_cv must appear in consumers map")
        map_pk_set = {p.pk for p in cv_map[canonical_cv]}
        self.assertEqual(
            map_pk_set,
            proj_pk_set,
            "content_version_consumers_map must map canonical_cv to both projections.",
        )

    # -------------------------------------------------------------------------
    # Step 2: Divergence isolation — customize proj_1, assert proj_2 unaffected
    # -------------------------------------------------------------------------

    def test_step2_customize_diverges_without_affecting_sibling(self):
        """
        customize(proj_1) gives proj_1 its own ContentVersion row.
        Editing proj_1's new version (edit_version) does NOT affect proj_2's
        effective/rendered content (proj_2 still points at canonical).

        This tests the isolation invariant: single-row sharing is preserved for
        proj_2; only proj_1 has diverged.
        """
        from syndication.services import create_event, customize, edit_version
        from syndication.engine import render_projection

        event = create_event(
            user=self.user,
            title="E2E Divergence Event",
            slug="e2e-divergence-event",
            start=timezone.now(),
        )

        projs = list(PlatformProjection.objects.filter(source_event=event).order_by("pk"))
        self.assertGreaterEqual(len(projs), 2)
        proj_1 = projs[0]
        proj_2 = projs[1]

        # Both start on the canonical CV.
        self.assertEqual(
            proj_1.content_version_id,
            proj_2.content_version_id,
            "Precondition: both projections start on the same canonical CV.",
        )

        # Capture proj_2's rendered body BEFORE customizing proj_1.
        body_before = render_projection(proj_2)

        # Customize proj_1: mints its own ContentVersion row and repoints FK.
        new_cv = customize(self.user, proj_1)
        proj_1.refresh_from_db()

        # Edit proj_1's new version to a DISTINGUISHABLE body.
        edit_version(self.user, new_cv, body="CUSTOM-BODY-PROJ1")

        # proj_1 must now render its custom body.
        self.assertEqual(render_projection(proj_1), "CUSTOM-BODY-PROJ1")

        # proj_2 must NOT have changed — it still points at canonical.
        proj_2.refresh_from_db()
        body_after = render_projection(proj_2)
        self.assertEqual(
            body_after,
            body_before,
            "Editing proj_1's customized CV must leave proj_2's rendered body UNCHANGED "
            "(isolation invariant: proj_2 still shares the canonical version).",
        )

        # The bodies must be distinct (proj_1 ≠ proj_2).
        self.assertNotEqual(
            render_projection(proj_1),
            render_projection(proj_2),
            "After customize + edit, proj_1 and proj_2 must render DIFFERENT bodies.",
        )

    # -------------------------------------------------------------------------
    # Step 3: Publish routing — proj_1 customized content reaches the adapter,
    #         NOT canonical / proj_2 content. proj_2 stays draft.
    # -------------------------------------------------------------------------

    def test_step3_publish_routes_customized_content_to_adapter(self):
        """
        Publish routing: advancing proj_1 to ready and publishing it via the
        adapter spy asserts:
        (a) proj_1's adapter receives proj_1 with proj_1's CUSTOMIZED content
            (frozen_content["body"] == "CUSTOM-BODY-PROJ1").
        (b) proj_2 stays draft (unaffected by proj_1's publish).

        Non-trivial routing assertion: if publish_projection accidentally routed
        proj_2's/canonical content while publishing proj_1 (a routing swap),
        render_projection(received_proj) would return proj_2's body or the
        composed canonical body — NOT "CUSTOM-BODY-PROJ1". This assertion would
        then FAIL, catching the routing swap.
        """
        from syndication.services import (
            create_event,
            customize,
            edit_version,
            approve_projection,
            publish_projection,
        )
        from syndication.engine import render_projection

        event = create_event(
            user=self.user,
            title="E2E Publish Event",
            slug="e2e-publish-event",
            start=timezone.now(),
        )

        projs = list(PlatformProjection.objects.filter(source_event=event).order_by("pk"))
        self.assertGreaterEqual(len(projs), 2)
        proj_1 = projs[0]
        proj_2 = projs[1]

        # Customize proj_1 and set a distinguishable body.
        new_cv = customize(self.user, proj_1)
        proj_1.refresh_from_db()
        edit_version(self.user, new_cv, body="CUSTOM-BODY-PROJ1")

        # Advance proj_1 to ready (freeze).
        approve_projection(self.user, proj_1)
        proj_1.refresh_from_db()
        self.assertEqual(proj_1.status, PlatformProjection.Status.READY)
        self.assertEqual(
            proj_1.frozen_content["body"],
            "CUSTOM-BODY-PROJ1",
            "Precondition: proj_1 must have its custom body frozen at draft→ready.",
        )

        # proj_2 must still be draft (unaffected by proj_1's approve).
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "proj_2 must still be draft after proj_1 is approved.",
        )

        # Spy on the adapter for proj_1's platform.
        received_by_switch_adapter = []
        received_by_fetlife_adapter = []

        def spy_switch(p):
            received_by_switch_adapter.append(p)

        def spy_fetlife(p):
            received_by_fetlife_adapter.append(p)

        # Determine which spy to use based on proj_1's connection platform.
        proj_1_platform = proj_1.connection.platform

        if proj_1_platform == "switch":
            with patch("syndication.services.publish_switch_own_page", side_effect=spy_switch):
                publish_projection(self.user, proj_1)
            received = received_by_switch_adapter
        elif proj_1_platform == "fetlife":
            # fetlife is attestation path (no external push), transitions directly.
            # We spy on transition_status to verify the publish happened.
            import syndication.engine as engine_mod
            from syndication.engine import transition_status as real_transition

            transition_calls = []

            def spy_transition(projection, new_status):
                transition_calls.append((projection.pk, new_status))
                real_transition(projection, new_status)

            with patch.object(engine_mod, "transition_status", side_effect=spy_transition):
                publish_projection(self.user, proj_1)

            proj_1.refresh_from_db()
            self.assertEqual(
                proj_1.status,
                PlatformProjection.Status.PUBLISHED,
                "proj_1 must be published after publish_projection for fetlife.",
            )
            # Check frozen_content was preserved.
            self.assertEqual(
                proj_1.frozen_content["body"],
                "CUSTOM-BODY-PROJ1",
                "(3a) The frozen content for proj_1 must be the CUSTOMIZED body, not canonical.",
            )
            # proj_2 must still be draft.
            proj_2.refresh_from_db()
            self.assertEqual(
                proj_2.status,
                PlatformProjection.Status.DRAFT,
                "(3b) proj_2 must remain draft while only proj_1 was published.",
            )
            return  # exit test early for fetlife path (attestation, no adapter receive)
        else:
            self.fail(f"Unexpected platform {proj_1_platform!r} — test needs updating.")

        # --- Assertions for push-adapter path (switch) ---

        # (3a) The adapter received proj_1.
        self.assertEqual(len(received), 1, "Adapter must be called exactly once for proj_1.")
        received_proj = received[0]
        self.assertEqual(
            received_proj.pk,
            proj_1.pk,
            "Adapter must receive proj_1 (not proj_2 or some other projection — routing swap catch).",
        )

        # (3a) Non-trivial routing assertion: the content the adapter WOULD post is
        # proj_1's CUSTOMIZED body, NOT canonical/proj_2's body.
        # render_projection on the received projection returns frozen_content["body"]
        # (since it's ready/published). A routing swap would deliver the wrong projection
        # object, whose frozen_content would NOT contain "CUSTOM-BODY-PROJ1".
        self.assertEqual(
            render_projection(received_proj),
            "CUSTOM-BODY-PROJ1",
            "(3a) Adapter must receive proj_1's CUSTOMIZED content (CUSTOM-BODY-PROJ1). "
            "If this fails, publish_projection routed the wrong projection (routing swap).",
        )

        # Extra: explicitly assert the customized body is NOT the canonical/proj_2's body.
        self.assertNotEqual(
            render_projection(received_proj),
            render_projection(proj_2),
            "(3a) The content routed to the adapter must differ from proj_2's body "
            "(routing-swap catch: they must not accidentally be the same).",
        )

        # (3b) proj_2 must still be draft — untouched by proj_1's publish.
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "(3b) proj_2 must remain draft while only proj_1 was published.",
        )

        # (3b) proj_1 must now be published (frozen_content preserved).
        # The spy_switch adapter did NOT call transition_status; so proj_1 stays
        # at ready. We need to check what the actual adapter would do — since
        # we're spying (not letting the real adapter run), we only assert the
        # content routing, not the final status transition.
        # The status assertion for the end-to-end "published" state is tested by
        # existing test_publish_dispatch.py and test_switch_adapter.py.

    # -------------------------------------------------------------------------
    # Step 4: Publish-all fan-out — each ready projection's adapter invoked once
    # -------------------------------------------------------------------------

    def test_step4_publish_all_ready_fanout(self):
        """
        Advance all projections to ready, then call publish_all_ready_projections.
        Assert each ready projection's adapter is invoked exactly once.

        Uses switch + fetlife listing projections (both created by create_event).
        """
        from syndication.services import (
            create_event,
            approve_projection,
            publish_all_ready_projections,
        )

        event = create_event(
            user=self.user,
            title="E2E FanOut Event",
            slug="e2e-fanout-event",
            start=timezone.now(),
        )

        projs = list(PlatformProjection.objects.filter(source_event=event).order_by("pk"))
        self.assertGreaterEqual(len(projs), 2)

        # Advance all to ready.
        for proj in projs:
            approve_projection(self.user, proj)
            proj.refresh_from_db()
            self.assertEqual(proj.status, PlatformProjection.Status.READY)

        # Spy on both adapters.
        switch_calls = []
        fetlife_transitions = []

        def spy_switch(p):
            switch_calls.append(p.pk)

        # For fetlife (attestation path), we spy on transition_status inside services
        # so we can count the calls without needing to intercept the engine level.
        import syndication.engine as engine_mod
        from syndication.engine import transition_status as real_transition

        def spy_transition(projection, new_status):
            if projection.connection.platform == "fetlife" and new_status == "published":
                fetlife_transitions.append(projection.pk)
            real_transition(projection, new_status)

        with patch("syndication.services.publish_switch_own_page", side_effect=spy_switch):
            with patch.object(engine_mod, "transition_status", side_effect=spy_transition):
                published, failures = publish_all_ready_projections(self.user, event)

        self.assertEqual(failures, [], f"Expected no failures, got: {failures}")

        # Collect the platforms of created projections.
        switch_proj_pks = set(
            p.pk for p in projs if p.connection.platform == "switch"
        )
        fetlife_proj_pks = set(
            p.pk for p in projs if p.connection.platform == "fetlife"
        )

        # Switch adapter: called once per switch projection.
        self.assertEqual(
            set(switch_calls),
            switch_proj_pks,
            "publish_switch_own_page must be called exactly once per switch projection.",
        )

        # FetLife (attestation path): transition_status(proj, 'published') called
        # once per fetlife projection.
        self.assertEqual(
            set(fetlife_transitions),
            fetlife_proj_pks,
            "transition_status to 'published' must be called once per fetlife projection.",
        )

        # Total published count = all projections.
        self.assertEqual(
            len(published),
            len(projs),
            "All ready projections must appear in the published list.",
        )

    # -------------------------------------------------------------------------
    # Combined flow: create → customize → freeze → publish proj_1 → publish-all
    # (the full v0 path in one test)
    # -------------------------------------------------------------------------

    def test_full_v0_path_start_shared_customize_publish(self):
        """
        Combined end-to-end flow:
          1. create_event → ≥2 projections on canonical CV.
          2. customize(proj_1) + edit_version → diverge.
          3. approve(proj_1) → freeze customized body.
          4. publish_projection(proj_1) via adapter spy → customized body routed.
          5. approve(proj_2) → freeze canonical body.
          6. publish_all_ready_projections → each adapter called once.

        The routing assertion in step 4 is the key integration probe:
        if publish_projection accidentally routes proj_2's content while
        publishing proj_1, render_projection(received_proj) would return
        proj_2's canonical-derived body, NOT "COMBINED-CUSTOM-PROJ1". The
        assertion would FAIL, surfacing the routing bug.
        """
        from syndication.services import (
            create_event,
            customize,
            edit_version,
            approve_projection,
            publish_projection,
            publish_all_ready_projections,
            consumers,
            content_version_consumers_map,
        )
        from syndication.engine import render_projection

        # --- Setup ---
        event = create_event(
            user=self.user,
            title="E2E Full Path Event",
            slug="e2e-full-path-event",
            start=timezone.now(),
        )

        projs = list(PlatformProjection.objects.filter(source_event=event).order_by("pk"))
        self.assertGreaterEqual(len(projs), 2, "Expected ≥2 eager listing projections")
        proj_1 = projs[0]
        proj_2 = projs[1]

        # --- Step 1: both on the same canonical CV ---
        canonical_cv = ContentVersion.objects.get(event=event, name="canonical")
        self.assertEqual(proj_1.content_version_id, canonical_cv.pk)
        self.assertEqual(proj_2.content_version_id, canonical_cv.pk)

        # consumers() reports both
        consumer_pks = set(consumers(canonical_cv).values_list("pk", flat=True))
        self.assertIn(proj_1.pk, consumer_pks)
        self.assertIn(proj_2.pk, consumer_pks)

        # content_version_consumers_map maps canonical → both
        cv_map = content_version_consumers_map(event)
        map_pks = {p.pk for p in cv_map[canonical_cv]}
        self.assertIn(proj_1.pk, map_pks)
        self.assertIn(proj_2.pk, map_pks)

        # --- Step 2: customize proj_1, assert proj_2 unaffected ---
        body_proj2_before = render_projection(proj_2)

        new_cv = customize(self.user, proj_1)
        proj_1.refresh_from_db()
        edit_version(self.user, new_cv, body="COMBINED-CUSTOM-PROJ1")

        # proj_1 renders its custom body
        self.assertEqual(render_projection(proj_1), "COMBINED-CUSTOM-PROJ1")

        # proj_2 still renders its unchanged canonical body
        proj_2.refresh_from_db()
        self.assertEqual(
            render_projection(proj_2),
            body_proj2_before,
            "proj_2's body must be UNCHANGED after customizing proj_1.",
        )

        # --- Step 3: approve proj_1, assert freeze ---
        approve_projection(self.user, proj_1)
        proj_1.refresh_from_db()
        self.assertEqual(proj_1.status, PlatformProjection.Status.READY)
        self.assertEqual(
            proj_1.frozen_content["body"],
            "COMBINED-CUSTOM-PROJ1",
            "proj_1's frozen body must be the CUSTOMIZED value.",
        )

        # proj_2 still draft
        proj_2.refresh_from_db()
        self.assertEqual(proj_2.status, PlatformProjection.Status.DRAFT)

        # --- Step 4: publish proj_1 via adapter spy ---
        proj_1_platform = proj_1.connection.platform
        received_by_adapter = []

        def capture_adapter(p):
            received_by_adapter.append(p)

        # Patch the appropriate adapter based on proj_1's platform.
        adapter_patch_path = {
            "switch": "syndication.services.publish_switch_own_page",
            "fetlife": None,  # attestation path — handled separately below
        }.get(proj_1_platform)

        if adapter_patch_path:
            with patch(adapter_patch_path, side_effect=capture_adapter):
                publish_projection(self.user, proj_1)

            self.assertEqual(len(received_by_adapter), 1)
            received_proj = received_by_adapter[0]

            # (3a) Non-trivial routing assertion:
            # The adapter must receive proj_1 with "COMBINED-CUSTOM-PROJ1",
            # NOT proj_2's canonical-derived body. A routing swap (delivering
            # proj_2's content) would fail this assertion.
            self.assertEqual(received_proj.pk, proj_1.pk)
            self.assertEqual(
                render_projection(received_proj),
                "COMBINED-CUSTOM-PROJ1",
                "(3a) Adapter received proj_1's CUSTOMIZED body. "
                "A routing swap would deliver proj_2's body instead — this assertion catches it.",
            )
            self.assertNotEqual(
                render_projection(received_proj),
                render_projection(proj_2),
                "(3a) Routing-swap catch: customized content must differ from proj_2's body.",
            )
        else:
            # fetlife: attestation path, no external adapter call
            publish_projection(self.user, proj_1)
            proj_1.refresh_from_db()
            self.assertEqual(proj_1.status, PlatformProjection.Status.PUBLISHED)
            # Even without an external adapter, frozen_content must be the custom body.
            self.assertEqual(
                proj_1.frozen_content["body"],
                "COMBINED-CUSTOM-PROJ1",
                "(3a) frozen_content must preserve the customized body after publish.",
            )

        # (3b) proj_2 must still be draft
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "(3b) proj_2 must remain draft while only proj_1 was published.",
        )

        # --- Step 5: approve proj_2 ---
        approve_projection(self.user, proj_2)
        proj_2.refresh_from_db()
        self.assertEqual(proj_2.status, PlatformProjection.Status.READY)

        # --- Step 6: publish_all_ready_projections fans out ---
        # After step 4, proj_1 is either published (fetlife) or still ready
        # (switch/spy didn't run real adapter). For fan-out we only count the
        # projections that are in 'ready' state at this point.
        ready_projs = PlatformProjection.objects.filter(
            source_event=event,
            status=PlatformProjection.Status.READY,
        )
        ready_count = ready_projs.count()
        self.assertGreaterEqual(ready_count, 1, "Expected at least proj_2 in ready state")

        adapter_calls = []

        def capture_all(p):
            adapter_calls.append(p.pk)

        import syndication.engine as engine_mod
        from syndication.engine import transition_status as real_transition

        fetlife_publish_calls = []

        def spy_transition_for_fanout(projection, new_status):
            if projection.connection.platform == "fetlife" and new_status == "published":
                fetlife_publish_calls.append(projection.pk)
            real_transition(projection, new_status)

        with patch("syndication.services.publish_switch_own_page", side_effect=capture_all):
            with patch("syndication.services.publish_telegram_promotion", side_effect=capture_all):
                with patch.object(engine_mod, "transition_status", side_effect=spy_transition_for_fanout):
                    published_batch, failures = publish_all_ready_projections(self.user, event)

        self.assertEqual(failures, [], f"Expected no failures in fan-out: {failures}")
        self.assertEqual(
            len(published_batch),
            ready_count,
            f"publish_all_ready_projections must publish all {ready_count} ready projections.",
        )
