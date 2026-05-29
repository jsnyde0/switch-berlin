"""
End-to-end integration test: start-shared → customize → publish (kb-wz8m.8).

Harness target Signal for the kb-wz8m parent epic.

Walks the REAL v0 path using the live service layer. Unit tests pass even when
the wiring is broken; this test walks the actual cross-component path (kb-jgda
lesson).

Data path only — no UI/template rendering. The "live on" visual render is
kb-wz8m.5's browser loop, explicitly out of scope here.

canonical_refs: ADR-008 D3/D4, ADR-016 D5.

Design notes on the routing-swap assertion (steps 3 + combined):
  The test customises proj_1 to body="CUSTOM-BODY-PROJ1" while proj_2 is left
  on the canonical version. Both projections FK to telegram connections. When
  publish_projection(proj_1) is called, the REAL publish_telegram_promotion
  adapter runs — only httpx.post is mocked at the transport boundary, returning
  a fake {"ok": true, "result": {"message_id": 123}} response.

  The routing assertion (3a) inspects the actual call to httpx.post:
    call_args.kwargs["json"]["text"] == "CUSTOM-BODY-PROJ1"

  A deliberate routing swap — where publish_projection passes proj_2 (or the
  canonical version's content) to the adapter while the caller meant proj_1 —
  would result in the Telegram payload containing proj_2's body (the composed
  canonical body, NOT "CUSTOM-BODY-PROJ1"). The assertion FAILS, catching the
  swap.

  The transition assertion (3b) checks that proj_1.status == PUBLISHED and
  proj_1.frozen_content is populated. This passes ONLY if the real adapter ran
  and called transition_status — a spy-based test that never fires the real
  adapter would leave proj_1 in READY, failing 3b.
"""

from unittest.mock import MagicMock, patch

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


def _make_connection(profile, platform, destination_id, kinds, enabled=True, credentials=None):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=enabled,
        credentials=credentials or {},
    )


# ---------------------------------------------------------------------------
# Fake httpx response helper (reused across tests)
# ---------------------------------------------------------------------------

def _fake_ok_response():
    """Return a fake httpx.Response-like mock for Telegram Bot API success."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": {"message_id": 123}}
    return resp


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
      - publish_projection() routes to the CORRECT per-projection adapter with the
        CORRECT content (transport boundary mocked; real adapter body runs).
      - publish_all_ready_projections() fans out exactly once per ready projection.

    Platform choice for steps 3 + combined:
      Telegram is a push-API promotion platform whose adapter calls httpx.post
      internally (syndication.adapters). By mocking only httpx.post at the
      transport boundary (patch "syndication.adapters.httpx.post"), the REAL
      publish_telegram_promotion function runs end-to-end, including the call to
      transition_status(projection, "published"). This means:
        (3a) We can inspect the actual Telegram payload text for routing correctness.
        (3b) proj_1 transitions to PUBLISHED with frozen_content populated — the
             real adapter path asserts both routing AND the lifecycle transition.

    SetUp creates two Telegram promotion connections with bot tokens, so that
    create_post produces ≥2 eager promotion projections on the shared canonical CV.
    Projections are selected deterministically by connection pk, not by pk ordering,
    so the test is stable across Postgres and SQLite.
    """

    def setUp(self):
        # Organizer: one user, one profile, two platform connections.
        #
        # We use TWO Telegram promotion connections (tg_1 + tg_2) so that
        # create_post produces ≥2 eager promotion projections sharing a canonical
        # ContentVersion. The Telegram adapter uses httpx.post — mocking that
        # boundary lets the real adapter run without network I/O.
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
        # eager listing projections on create_event. Used ONLY for steps 1 + 2
        # (shared canonical + customize isolation). No network I/O for these.
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

        # Two Telegram promotion connections with bot tokens — used for steps
        # 3 + combined (real Telegram adapter + httpx.post mock).
        self.conn_tg_1 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@channel-1",
            kinds=["promotion"],
            credentials={"bot_token": "fake-bot-token-1"},
        )
        self.conn_tg_2 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@channel-2",
            kinds=["promotion"],
            credentials={"bot_token": "fake-bot-token-2"},
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
    # Step 2: Divergence isolation — customize proj_1, assert proj_2 unaffected.
    # Uses listing projections (switch + fetlife) — no network I/O needed.
    # -------------------------------------------------------------------------

    def test_step2_customize_diverges_without_affecting_sibling(self):
        """
        customize(proj_1) gives proj_1 its own ContentVersion row.
        Editing proj_1's new version (edit_version) does NOT affect proj_2's
        effective/rendered content (proj_2 still points at canonical).

        proj_1 and proj_2 are selected by their connection platform, not by pk
        order, so the test is stable across Postgres and SQLite.
        """
        from syndication.services import create_event, customize, edit_version
        from syndication.engine import render_projection

        event = create_event(
            user=self.user,
            title="E2E Divergence Event",
            slug="e2e-divergence-event",
            start=timezone.now(),
        )

        # Select deterministically by platform, not by pk ordering.
        proj_1 = PlatformProjection.objects.get(
            source_event=event,
            connection=self.conn_switch,
        )
        proj_2 = PlatformProjection.objects.get(
            source_event=event,
            connection=self.conn_fetlife,
        )

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
    # Step 3: Publish routing — real Telegram adapter with httpx.post mocked.
    #
    # REAL adapter path: only httpx.post (in syndication.adapters) is patched.
    # publish_telegram_promotion runs end-to-end, calling transition_status
    # internally — so BOTH the routing assertion AND the lifecycle transition
    # assertion are meaningful.
    #
    # Routing-swap catch argument:
    #   A swap would cause publish_projection to pass proj_2 (or proj_2's
    #   canonical content) to the adapter. The adapter would then render
    #   proj_2's body (the composed canonical listing body, NOT "CUSTOM-BODY-PROJ1")
    #   and POST that text to Telegram. The assertion
    #       mock_post.call_args.kwargs["json"]["text"] == "CUSTOM-BODY-PROJ1"
    #   would FAIL because the payload text is proj_2's body, not proj_1's.
    # -------------------------------------------------------------------------

    def test_step3_publish_routes_customized_content_to_adapter(self):
        """
        Uses the REAL publish_telegram_promotion adapter (not a spy on the adapter
        function itself) — only httpx.post is mocked at the transport boundary.

        Assertions:
        (3a) httpx.post was called exactly once with payload text == "CUSTOM-BODY-PROJ1"
             (NOT proj_2's/canonical content). This catches a routing swap.
        (3b) proj_1.status == PUBLISHED and proj_1.frozen_content["body"] ==
             "CUSTOM-BODY-PROJ1" (real transition fired by the real adapter).
             proj_2.status == DRAFT (unaffected).
        """
        from syndication.services import (
            create_event,
            create_post,
            customize,
            edit_version,
            approve_projection,
            publish_projection,
        )

        event = create_event(
            user=self.user,
            title="E2E Publish Event",
            slug="e2e-publish-event",
            start=timezone.now(),
        )

        # create_post eager-creates promotion projections on the two Telegram connections.
        post = create_post(
            user=self.user,
            event=event,
            headline="Test Headline",
            body="Canonical post body",
        )

        # Select deterministically by connection, not by pk order.
        proj_1 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_1,
        )
        proj_2 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_2,
        )

        self.assertEqual(proj_1.connection.platform, "telegram")
        self.assertEqual(proj_2.connection.platform, "telegram")

        # Both start on the same canonical CV (precondition).
        self.assertEqual(
            proj_1.content_version_id,
            proj_2.content_version_id,
            "Precondition: both projections start on the same canonical CV.",
        )

        # Customize proj_1 and set a DISTINGUISHABLE body.
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

        # Publish proj_1 via the REAL adapter — only httpx.post is mocked.
        # The real publish_telegram_promotion runs, calls transition_status,
        # and stamps external_id.
        with patch("syndication.adapters.httpx.post", return_value=_fake_ok_response()) as mock_post:
            publish_projection(self.user, proj_1)

        # (3a) httpx.post must have been called exactly once.
        self.assertEqual(
            mock_post.call_count,
            1,
            "httpx.post must be called exactly once for proj_1's Telegram publish.",
        )

        # (3a) Non-trivial routing assertion: the payload text must be proj_1's
        # CUSTOMIZED body, NOT proj_2's/canonical body.
        # A routing swap would deliver proj_2's body ("Test Headline\n\nCanonical post body"
        # or similar canonical composition) — NOT "CUSTOM-BODY-PROJ1". This assertion
        # would FAIL, surfacing the routing bug.
        # httpx.post is called as httpx.post(url, json=payload) → kwargs["json"].
        actual_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            actual_payload["text"],
            "CUSTOM-BODY-PROJ1",
            "(3a) Telegram payload text must be proj_1's CUSTOMIZED body. "
            "A routing swap would post proj_2's body — this assertion catches it.",
        )

        # Verify the payload is NOT proj_2's canonical body (explicit routing-swap catch).
        from syndication.engine import render_projection
        proj_2_canonical_body = render_projection(proj_2)
        self.assertNotEqual(
            actual_payload["text"],
            proj_2_canonical_body,
            "(3a) Routing-swap catch: the Telegram payload must differ from proj_2's body.",
        )

        # (3b) proj_1 must now be PUBLISHED (the REAL adapter ran transition_status).
        proj_1.refresh_from_db()
        self.assertEqual(
            proj_1.status,
            PlatformProjection.Status.PUBLISHED,
            "(3b) proj_1 must be PUBLISHED — the real adapter must call transition_status.",
        )

        # (3b) frozen_content must be populated with the CUSTOMIZED body.
        self.assertEqual(
            proj_1.frozen_content["body"],
            "CUSTOM-BODY-PROJ1",
            "(3b) proj_1.frozen_content['body'] must be the customized body after publish.",
        )

        # (3b) external_id must be set (stamped by the real adapter from the mock response).
        self.assertEqual(
            proj_1.external_id,
            "123",
            "(3b) external_id must be set to the message_id from the Bot API response.",
        )

        # (3b) proj_2 must still be draft — untouched by proj_1's publish.
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "(3b) proj_2 must remain draft while only proj_1 was published.",
        )

    # -------------------------------------------------------------------------
    # Step 4: Publish-all fan-out — each ready projection's adapter invoked once.
    # Uses listing projections (switch + fetlife).
    # switch: real adapter, but no external call (resolves URL, no httpx.post).
    # fetlife: attestation path (no adapter call, transition_status direct).
    # -------------------------------------------------------------------------

    def test_step4_publish_all_ready_fanout(self):
        """
        Advance all listing projections to ready, then call publish_all_ready_projections.

        switch: real publish_switch_own_page runs (URL resolution, no external I/O).
        fetlife: attestation path — transition_status called directly in publish_projection.

        Assert: each projection transitions to PUBLISHED, publish count matches.
        Selected deterministically by connection, not pk order.
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

        # Select deterministically by connection platform.
        proj_switch = PlatformProjection.objects.get(
            source_event=event,
            connection=self.conn_switch,
        )
        proj_fetlife = PlatformProjection.objects.get(
            source_event=event,
            connection=self.conn_fetlife,
        )

        projs = [proj_switch, proj_fetlife]

        # Advance all to ready.
        for proj in projs:
            approve_projection(self.user, proj)
            proj.refresh_from_db()
            self.assertEqual(proj.status, PlatformProjection.Status.READY)

        # Run publish-all. switch: real adapter (URL resolution, no httpx).
        # fetlife: attestation path in publish_projection.
        published_batch, failures = publish_all_ready_projections(self.user, event)

        self.assertEqual(failures, [], f"Expected no failures, got: {failures}")
        self.assertEqual(
            len(published_batch),
            len(projs),
            "All ready projections must appear in the published list.",
        )

        # Both projections must have transitioned to PUBLISHED via real paths.
        proj_switch.refresh_from_db()
        self.assertEqual(
            proj_switch.status,
            PlatformProjection.Status.PUBLISHED,
            "switch projection must be PUBLISHED after publish_all_ready_projections.",
        )

        proj_fetlife.refresh_from_db()
        self.assertEqual(
            proj_fetlife.status,
            PlatformProjection.Status.PUBLISHED,
            "fetlife projection must be PUBLISHED after publish_all_ready_projections.",
        )

    # -------------------------------------------------------------------------
    # Combined flow: create → customize → freeze → publish proj_1 → publish-all
    # (the full v0 path in one test, using Telegram for the publish steps)
    # -------------------------------------------------------------------------

    def test_full_v0_path_start_shared_customize_publish(self):
        """
        Combined end-to-end flow using Telegram promotion projections:
          1. create_post → ≥2 promotion projections on canonical CV.
          2. customize(proj_1) + edit_version → diverge.
          3. approve(proj_1) → freeze customized body.
          4. publish_projection(proj_1) with httpx.post mocked →
             (4a) Telegram payload text == "COMBINED-CUSTOM-PROJ1" (routing assertion).
             (4b) proj_1.status == PUBLISHED (real transition).
          5. approve(proj_2) → freeze canonical body.
          6. publish_all_ready_projections → each ready projection transitions to PUBLISHED.

        Routing-swap catch for step 4a: a swap delivers proj_2's canonical body to
        the Telegram payload. That body is NOT "COMBINED-CUSTOM-PROJ1", so the
        payload["text"] assertion FAILS, surfacing the routing bug.
        """
        from syndication.services import (
            create_event,
            create_post,
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

        post = create_post(
            user=self.user,
            event=event,
            headline="Combined Headline",
            body="Canonical post body",
        )

        # Select deterministically by connection, not by pk order.
        proj_1 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_1,
        )
        proj_2 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_2,
        )

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

        # --- Step 4: publish proj_1 via real Telegram adapter (httpx.post mocked) ---
        with patch("syndication.adapters.httpx.post", return_value=_fake_ok_response()) as mock_post_step4:
            publish_projection(self.user, proj_1)

        # (4a) Non-trivial routing assertion: the Telegram payload text must be
        # proj_1's CUSTOMIZED body, NOT proj_2's canonical-derived body.
        # A routing swap (delivering proj_2's content) would fail this assertion.
        # httpx.post is called as httpx.post(url, json=payload) → kwargs["json"].
        actual_payload = mock_post_step4.call_args.kwargs["json"]
        self.assertEqual(
            actual_payload["text"],
            "COMBINED-CUSTOM-PROJ1",
            "(4a) Telegram payload text must be proj_1's CUSTOMIZED body. "
            "A routing swap would post proj_2's body — this assertion catches it.",
        )
        self.assertNotEqual(
            actual_payload["text"],
            render_projection(proj_2),
            "(4a) Routing-swap catch: customized content must differ from proj_2's canonical body.",
        )

        # (4b) proj_1 must now be PUBLISHED (real transition fired by real adapter).
        proj_1.refresh_from_db()
        self.assertEqual(
            proj_1.status,
            PlatformProjection.Status.PUBLISHED,
            "(4b) proj_1 must be PUBLISHED after real Telegram adapter publish.",
        )
        self.assertEqual(
            proj_1.frozen_content["body"],
            "COMBINED-CUSTOM-PROJ1",
            "(4b) frozen_content must be the customized body after publish.",
        )

        # (4b) proj_2 must still be draft
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "(4b) proj_2 must remain draft while only proj_1 was published.",
        )

        # --- Step 5: approve proj_2 ---
        approve_projection(self.user, proj_2)
        proj_2.refresh_from_db()
        self.assertEqual(proj_2.status, PlatformProjection.Status.READY)

        # --- Step 6: publish_all_ready_projections fans out ---
        # After step 4, proj_1 is PUBLISHED. Only proj_2 is ready.
        # publish_all_ready_projections must publish each ready projection exactly once.
        ready_projs = PlatformProjection.objects.filter(
            source_post=post,
            status=PlatformProjection.Status.READY,
        )
        ready_count = ready_projs.count()
        self.assertGreaterEqual(ready_count, 1, "Expected at least proj_2 in ready state")

        # Mock httpx.post for the fan-out publish of proj_2 (real Telegram adapter).
        with patch("syndication.adapters.httpx.post", return_value=_fake_ok_response()) as mock_post_fanout:
            published_batch, failures = publish_all_ready_projections(self.user, event)

        self.assertEqual(failures, [], f"Expected no failures in fan-out: {failures}")
        self.assertEqual(
            len(published_batch),
            ready_count,
            f"publish_all_ready_projections must publish all {ready_count} ready projections.",
        )

        # httpx.post must be called once per ready Telegram projection in the fan-out.
        self.assertEqual(
            mock_post_fanout.call_count,
            ready_count,
            "httpx.post must be called once per ready Telegram projection in fan-out.",
        )

        # proj_2 must now be PUBLISHED.
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.PUBLISHED,
            "proj_2 must be PUBLISHED after publish_all_ready_projections fan-out.",
        )
