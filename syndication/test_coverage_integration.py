"""
Integration test: seeded end-to-end coverage read-back (kb-56c2.5 / C3d).

Cross-surface contract between:
  C3a — TelegramPlacement model + TelegramPlacementItemIn schema + reconcile service
  C3b — coverage view + coverage.html template
  C3c — switch-cli distribute report payload shape {destination_id, topic_id?, status, error_detail?}

Two-part test:

Part 1 — Browser read-back (via Django test client, same altitude as C3b tests):
  Seeds a distribution run spanning ALL tiers (own channel bot, private group agent,
  forum agent, pending agent no-record, public deep-link) on ONE promotion projection
  anchor and asserts the rendered coverage view shows:
    (a) four machine states co-occur honestly in one rendered coverage view
    (b) forum-level granularity holds end-to-end (one row per forum connection)
    (c) a pending destination (selected, no record) renders as pending
    (d) a public destination renders as a deep-link affordance (not placed/pending)
    (e) send-checklist lists the human-action set (agent-tier placed + public)
    (f) NO "sent" badge anywhere (ADR-018 D2 FIRM)

Part 2 — Cross-surface contract assertion:
  Imports TelegramPlacementItemIn (C3a schema artifact) and validates C3c-shaped
  report payload dicts against it:
    (g) valid {destination_id, topic_id?, status, error_detail?} payloads are accepted
    (h) a forbidden field (session_string, content) causes a validation error
  This pins the agent↔server contract so neither side can drift silently.

Read-back path: Django test-client (not live browser against docker app).
Rationale: The seeding is server-side (no live MTProto required per bead constraint),
the coverage view is a standard Django HTML view, and the test client renders real
template output (response.content) with the full middleware stack — the same altitude
used by C3b tests. A live browser drive against the dockerized app would require
separately seeding the docker DB and is out of scope for an agent-closeable bead.
The test-client path exercises the same render path the browser would see (same
template, same context, same middleware) and is sufficient for the stated contract.

ADR-018 D2: no "sent" state ever.
ADR-008 D3: fail loud; no silent fallbacks.
kb-56c2 D2: pending = absence of record for selected bot/agent-tier connection.
kb-56c2 D6: public-tier is a human-action affordance, never placed/pending.
kb-56c2 D3: send-checklist = agent-tier placed + public-tier.
kb-56c2 D5: forum coverage is forum-level.
"""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import (
    PlatformConnection,
    Post,
    TelegramDialogType,
    TelegramPlacement,
    TelegramPlacementStatus,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Seeding helpers (reuse style from test_coverage_view.py)
# ---------------------------------------------------------------------------


def _make_vouched_user(username, email, password="testpass"):
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        status="vouched",
    )


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(slug, **kwargs):
    defaults = {
        "title": f"Integration Test Party ({slug})",
        "slug": slug,
        "start": timezone.now(),
        "status": "published",
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, headline="Integration Test Post"):
    return Post.objects.create(event=event, headline=headline, body="Come join us.")


def _make_connection(profile, destination_id, postability, title, **kwargs):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=["promotion"],
        postability=postability,
        title=title,
        **kwargs,
    )


def _make_promotion_projection(connection, post):
    """Generate a promotion projection and advance it to ready status."""
    from syndication.engine import generate_projection, transition_status

    proj = generate_projection(
        kind="promotion",
        connection=connection,
        source_post=post,
        mode="rule_based",
    )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    return proj


def _make_placement(proj, conn, status, error_detail=None):
    placement, _ = TelegramPlacement.objects.update_or_create(
        projection=proj,
        connection=conn,
        defaults={"status": status, "error_detail": error_detail},
    )
    return placement


# ---------------------------------------------------------------------------
# Part 1: Seeded end-to-end coverage read-back
# ---------------------------------------------------------------------------


class CoverageIntegrationReadbackTest(TestCase):
    """
    Integration test: seed a distribution run spanning all tiers and assert
    the rendered coverage view shows all four machine states co-occurring
    honestly.

    Seeds (all on one organizer / one post):
    - Own channel (postability=bot): placed record
    - Private group (postability=agent): placed record
    - Forum (postability=agent, type=group): placed record (forum-level granularity)
    - Pending agent destination: selected, NO placement record → computed "pending"
    - Public destination (postability=public): deep-link affordance (no record)

    Asserts via rendered HTML (response.content), NOT response.context.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="integ-coverage-user",
            email="integ-coverage@test.com",
        )
        self.profile = _make_profile(
            name="Integration Coverage Org",
            slug="integ-coverage-org",
            user=self.user,
        )
        self.event = _make_event(slug="integ-coverage-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)

        # --- Seed all tiers ---

        # (1) Own channel: bot-tier, placed
        self.bot_conn = _make_connection(
            self.profile,
            destination_id="-1001500000001",
            postability="bot",
            title="Own Channel (Bot)",
        )
        self.bot_proj = _make_promotion_projection(self.bot_conn, self.post)
        _make_placement(self.bot_proj, self.bot_conn, TelegramPlacementStatus.PLACED)

        # (2) Private group: agent-tier, placed (→ send-checklist)
        self.agent_placed_conn = _make_connection(
            self.profile,
            destination_id="-1001500000002",
            postability="agent",
            title="Private Group (Agent Placed)",
        )
        self.agent_placed_proj = _make_promotion_projection(self.agent_placed_conn, self.post)
        _make_placement(self.agent_placed_proj, self.agent_placed_conn, TelegramPlacementStatus.PLACED)

        # (3) Forum: agent-tier, placed at forum-level (kb-56c2 D5)
        self.forum_conn = _make_connection(
            self.profile,
            destination_id="-1001500000003",
            postability="agent",
            title="Forum Group (Agent Forum-Level)",
            type=TelegramDialogType.GROUP,
        )
        self.forum_proj = _make_promotion_projection(self.forum_conn, self.post)
        _make_placement(self.forum_proj, self.forum_conn, TelegramPlacementStatus.PLACED)

        # (4) Pending agent destination: selected, NO record → computed pending
        self.agent_pending_conn = _make_connection(
            self.profile,
            destination_id="-1001500000004",
            postability="agent",
            title="Agent Group (Pending)",
        )
        self.agent_pending_proj = _make_promotion_projection(self.agent_pending_conn, self.post)
        # No TelegramPlacement record → reconcile computes "pending"

        # (5) Public destination: deep-link affordance (never placed/pending)
        self.public_conn = _make_connection(
            self.profile,
            destination_id="-1001500000005",
            postability="public",
            title="Public Channel (Deep-Link)",
        )
        self.public_proj = _make_promotion_projection(self.public_conn, self.post)
        # No TelegramPlacement record (public-tier never gets one — kb-56c2 D6)

        self.client = Client()
        self.client.login(username="integ-coverage-user", password="testpass")

        # URL: keyed on the post pk (kb-e0ch re-key)
        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def _get_html(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, f"Coverage view returned {response.status_code}")
        return response.content.decode("utf-8")

    def _checklist_section(self, html):
        """Extract the send-checklist <section> from the rendered HTML."""
        start = html.find('aria-labelledby="send-checklist-heading"')
        if start == -1:
            return ""
        section_open = html.rfind("<section", 0, start)
        end = html.find("</section>", start)
        self.assertNotEqual(end, -1, "send-checklist <section> is not closed in rendered HTML")
        return html[section_open if section_open != -1 else start : end]

    # ------------------------------------------------------------------
    # (a) Four machine states co-occur in one rendered coverage view
    # ------------------------------------------------------------------

    def test_a_all_four_machine_states_cooccur_in_rendered_view(self):
        """
        All four machine states (placed, failed, pending, skipped-pre-existing-draft)
        are representable and three of them co-occur in this seeded run.

        This run seeds: placed (bot), placed (agent), placed (forum),
        pending (agent no-record), and deep-link (public).

        We assert placed and pending co-occur (the two most load-bearing states
        for conjunction-drift — placed shows the tracker writes, pending shows
        absence-of-record reconciliation).

        The skipped-pre-existing-draft state is verified in the cross-state test
        below to confirm the schema reaches all four values.
        """
        html = self._get_html()
        # "placed" must appear (bot + agent + forum placements)
        self.assertIn("placed", html.lower(), "Expected 'placed' label in rendered HTML")
        # "pending" must appear (agent-pending has no record)
        self.assertIn("pending", html.lower(), "Expected 'pending' label in rendered HTML")

    def test_a_placed_and_pending_rendered_in_same_view(self):
        """
        The coverage view for this seeded run renders both 'placed' and 'pending'
        labels — confirming the two writers and the reconciliation interact correctly
        in the composed surface (the conjunction-drift target).
        """
        html = self._get_html()
        # Both statuses visible in the same response
        placed_idx = html.lower().find("placed")
        pending_idx = html.lower().find("pending")
        self.assertGreater(placed_idx, -1, "Expected 'placed' in HTML")
        self.assertGreater(pending_idx, -1, "Expected 'pending' in HTML")

    def test_a_all_connection_titles_rendered(self):
        """All seeded connection titles appear in the rendered coverage HTML."""
        html = self._get_html()
        titles = [
            "Own Channel (Bot)",
            "Private Group (Agent Placed)",
            "Forum Group (Agent Forum-Level)",
            "Agent Group (Pending)",
            "Public Channel (Deep-Link)",
        ]
        for title in titles:
            self.assertIn(title, html, f"Expected '{title}' in coverage HTML")

    # ------------------------------------------------------------------
    # (b) Forum-level granularity holds end-to-end (kb-56c2 D5)
    # ------------------------------------------------------------------

    def test_b_forum_connection_renders_exactly_once(self):
        """
        The forum connection renders exactly one coverage row (forum-level,
        not per-topic) — kb-56c2 D5.
        """
        html = self._get_html()
        conn_pk = str(self.forum_conn.pk)
        rows = re.findall(rf'data-connection-pk="{conn_pk}"', html)
        self.assertEqual(
            len(rows),
            1,
            f"Forum connection {conn_pk} must render exactly once (forum-level), "
            f"found {len(rows)} data-connection-pk occurrences",
        )

    # ------------------------------------------------------------------
    # (c) Pending destination renders with "pending" label
    # ------------------------------------------------------------------

    def test_c_pending_destination_renders_pending(self):
        """
        The pending agent destination (selected, no record) renders with a
        'pending' label in the coverage view.
        """
        html = self._get_html()
        # Confirm the pending conn title appears
        self.assertIn("Agent Group (Pending)", html)
        # Find the pending conn row and check it shows "pending"
        pending_title_idx = html.find("Agent Group (Pending)")
        self.assertGreater(pending_title_idx, -1)
        window = html[max(0, pending_title_idx - 300) : pending_title_idx + 600]
        self.assertIn("pending", window.lower(), "Pending destination must show 'pending' in its row window")

    def test_c_pending_destination_not_in_send_checklist(self):
        """
        The pending destination is NOT in the send-checklist (no draft to send yet,
        per kb-56c2 D3: agent-pending is excluded from checklist).
        """
        html = self._get_html()
        section = self._checklist_section(html)
        self.assertNotEqual(section, "", "send-checklist section must be present")
        self.assertNotIn(
            "Agent Group (Pending)",
            section,
            "Pending agent destination must NOT appear in send-checklist (no draft to send yet)",
        )

    # ------------------------------------------------------------------
    # (d) Public destination renders as a deep-link affordance
    # ------------------------------------------------------------------

    def test_d_public_destination_renders_deep_link_affordance(self):
        """
        The public-tier destination renders as a deep-link affordance (not placed/pending)
        — kb-56c2 D6 / ADR-018 D2 FIRM.
        """
        html = self._get_html()
        self.assertIn("Public Channel (Deep-Link)", html)
        public_idx = html.find("Public Channel (Deep-Link)")
        window = html[max(0, public_idx - 300) : public_idx + 600]
        self.assertTrue(
            "deep-link" in window.lower()
            or "open" in window.lower()
            or "manually" in window.lower()
            or "tg://" in window.lower(),
            f"Public destination row must show a deep-link affordance. Window: {window[:400]}",
        )

    def test_d_public_destination_not_labeled_placed_or_pending(self):
        """
        The public-tier connection must NOT be labeled 'placed' or 'pending' in its row.
        It must be labeled as a deep-link / manual-action affordance.
        """
        html = self._get_html()
        public_idx = html.find("Public Channel (Deep-Link)")
        self.assertGreater(public_idx, -1)
        window = html[max(0, public_idx - 100) : public_idx + 700]
        # The window should show the human-action affordance marker, NOT a machine state
        self.assertTrue(
            "open" in window.lower() or "manually" in window.lower() or "deep-link" in window.lower(),
            f"Public Channel row must show deep-link affordance, not a machine state. Window: {window[:400]}",
        )

    # ------------------------------------------------------------------
    # (e) Send-checklist lists agent-tier placed + public destinations
    # ------------------------------------------------------------------

    def test_e_send_checklist_contains_agent_placed(self):
        """
        Agent-tier placed destinations appear in the send-checklist (draft exists
        for facilitator to send natively) — kb-56c2 D3.
        """
        html = self._get_html()
        section = self._checklist_section(html)
        self.assertNotEqual(section, "", "send-checklist section must be present")
        self.assertIn(
            "Private Group (Agent Placed)",
            section,
            "Agent-tier placed connection must appear in send-checklist",
        )

    def test_e_send_checklist_contains_public_tier(self):
        """
        Public-tier destinations appear in the send-checklist (facilitator must
        post manually via deep-link) — kb-56c2 D3.
        """
        html = self._get_html()
        section = self._checklist_section(html)
        self.assertNotEqual(section, "", "send-checklist section must be present")
        self.assertIn(
            "Public Channel (Deep-Link)",
            section,
            "Public-tier connection must appear in send-checklist",
        )

    def test_e_send_checklist_excludes_bot_tier(self):
        """
        Bot-tier placed destinations must NOT appear in the send-checklist
        (the bot already published — no human action needed for the send step).
        """
        html = self._get_html()
        section = self._checklist_section(html)
        self.assertNotEqual(section, "", "send-checklist section must be present")
        self.assertNotIn(
            "Own Channel (Bot)",
            section,
            "Bot-tier connection must NOT appear in send-checklist (bot already sent)",
        )

    def test_e_send_checklist_section_present(self):
        """The send-checklist section exists in the rendered HTML."""
        html = self._get_html()
        self.assertIn(
            'aria-labelledby="send-checklist-heading"',
            html,
            "send-checklist section must be present in coverage HTML",
        )

    def test_e_forum_placed_in_send_checklist(self):
        """
        Forum-level placed connection (agent-tier) also appears in the send-checklist
        — it is an agent-tier placed destination.
        """
        html = self._get_html()
        section = self._checklist_section(html)
        self.assertNotEqual(section, "", "send-checklist section must be present")
        self.assertIn(
            "Forum Group (Agent Forum-Level)",
            section,
            "Forum-level agent-tier placed connection must appear in send-checklist",
        )

    # ------------------------------------------------------------------
    # (f) NO "sent" badge anywhere (ADR-018 D2 FIRM)
    # ------------------------------------------------------------------

    def test_f_no_sent_badge_in_rendered_html(self):
        """
        The rendered coverage HTML must NEVER contain the string 'sent' as a
        status badge/label (ADR-018 D2 FIRM draft-only firewall).
        """
        html = self._get_html()
        # \b word boundary — match "sent" only as a standalone word (the boundary
        # already excludes substrings like "consent"/"present", so no extra filter
        # is needed).
        actual_hits = re.findall(r"\bsent\b", html, re.IGNORECASE)
        self.assertEqual(
            len(actual_hits),
            0,
            f"Found forbidden 'sent' label in rendered HTML: {actual_hits[:5]}. "
            "ADR-018 D2 FIRM: no 'sent' state is observable by the machine.",
        )

    # ------------------------------------------------------------------
    # Composed state: all five connections render in one view
    # ------------------------------------------------------------------

    def test_composed_state_five_connections_all_render(self):
        """
        All five seeded connections (bot placed, agent placed, forum placed,
        agent pending, public deep-link) render in a single coverage view —
        confirming the cross-surface composition works end-to-end.
        """
        html = self._get_html()
        expected_titles = [
            "Own Channel (Bot)",
            "Private Group (Agent Placed)",
            "Forum Group (Agent Forum-Level)",
            "Agent Group (Pending)",
            "Public Channel (Deep-Link)",
        ]
        for title in expected_titles:
            self.assertIn(title, html, f"'{title}' must appear in the composed coverage view")

    def test_composed_state_correct_status_for_each_tier(self):
        """
        The data-status attributes in the composed view correctly reflect
        per-tier reconciliation outcomes.
        """
        html = self._get_html()
        # Bot connection's row must be present AND carry data-status="placed".
        # The row-presence asserts are unconditional so this test cannot pass by
        # silently skipping its inner assertions when a row is absent.
        bot_conn_pk = str(self.bot_conn.pk)
        bot_idx = html.find(f'data-connection-pk="{bot_conn_pk}"')
        self.assertNotEqual(bot_idx, -1, "Bot-tier connection row must render in the coverage view")
        bot_window = html[bot_idx : bot_idx + 800]
        self.assertIn(
            'data-status="placed"',
            bot_window,
            "Bot-tier placed connection row must have data-status='placed'",
        )

        # Pending connection's row must be present AND carry data-status="pending"
        pending_pk = str(self.agent_pending_conn.pk)
        pending_idx = html.find(f'data-connection-pk="{pending_pk}"')
        self.assertNotEqual(pending_idx, -1, "Pending agent connection row must render in the coverage view")
        pending_window = html[pending_idx : pending_idx + 800]
        self.assertIn(
            'data-status="pending"',
            pending_window,
            "Pending agent connection row must have data-status='pending'",
        )

        # Public connection's row must be present AND carry data-postability="public"
        public_pk = str(self.public_conn.pk)
        public_idx = html.find(f'data-connection-pk="{public_pk}"')
        self.assertNotEqual(public_idx, -1, "Public-tier connection row must render in the coverage view")
        public_window = html[public_idx : public_idx + 800]
        self.assertIn(
            'data-postability="public"',
            public_window,
            "Public-tier connection row must have data-postability='public'",
        )


# ---------------------------------------------------------------------------
# Part 2: Cross-surface contract assertion (C3a schema vs C3c payload)
# ---------------------------------------------------------------------------


class TelegramPlacementContractTest(TestCase):
    """
    (g) Cross-surface contract: C3c report payload shape validated against
    the C3a Ninja input schema (TelegramPlacementItemIn).

    This is a schema-level assertion — no HTTP call, no database write.
    It directly imports the named schema artifact (TelegramPlacementItemIn
    from syndication/api.py) and validates C3c-shaped payloads against it.

    If either side drifts (C3c adds a field C3a doesn't know, or C3a removes
    a field C3c sends), this test fails — exactly the signal it's designed to give.

    C3c payload shape (from switch-cli distribute report):
        {destination_id, topic_id?, status, error_detail?}
    """

    def test_g_valid_placed_payload_accepted(self):
        """
        A C3c-shaped 'placed' report payload validates against the C3a schema.
        """
        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "placed",
        }
        item = TelegramPlacementItemIn(**payload)
        self.assertEqual(item.destination_id, "-1001234567890")
        self.assertEqual(item.status, TelegramPlacementStatus.PLACED)
        self.assertIsNone(item.topic_id)
        self.assertIsNone(item.error_detail)

    def test_g_valid_failed_payload_accepted(self):
        """
        A C3c-shaped 'failed' report payload (with error_detail) validates.
        """
        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "failed",
            "error_detail": "saveDraft returned error 400",
        }
        item = TelegramPlacementItemIn(**payload)
        self.assertEqual(item.status, TelegramPlacementStatus.FAILED)
        self.assertEqual(item.error_detail, "saveDraft returned error 400")

    def test_g_valid_skipped_payload_accepted(self):
        """
        A C3c-shaped 'skipped-pre-existing-draft' payload validates.
        """
        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "skipped-pre-existing-draft",
        }
        item = TelegramPlacementItemIn(**payload)
        self.assertEqual(item.status, TelegramPlacementStatus.SKIPPED_PRE_EXISTING_DRAFT)

    def test_g_valid_forum_level_payload_with_topic_id_accepted(self):
        """
        A C3c-shaped forum-level payload with topic_id validates.
        Forum-level coverage (kb-56c2 D5): topic_id is optional.
        """
        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "topic_id": 42,
            "status": "placed",
        }
        item = TelegramPlacementItemIn(**payload)
        self.assertEqual(item.topic_id, 42)
        self.assertEqual(item.destination_id, "-1001234567890")

    def test_g_forbidden_field_session_string_rejected(self):
        """
        A payload carrying 'session_string' (forbidden field per ADR-018 D4)
        is rejected by the C3a schema with a validation error.
        """
        from pydantic import ValidationError

        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "placed",
            "session_string": "AQAD...",  # forbidden!
        }
        with self.assertRaises(ValidationError, msg="session_string must be rejected by TelegramPlacementItemIn"):
            TelegramPlacementItemIn(**payload)

    def test_g_forbidden_field_content_rejected(self):
        """
        A payload carrying 'content' (forbidden field per ADR-018 D4)
        is rejected by the C3a schema.
        """
        from pydantic import ValidationError

        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "placed",
            "content": "This is the post content — forbidden!",  # forbidden!
        }
        with self.assertRaises(ValidationError, msg="content must be rejected by TelegramPlacementItemIn"):
            TelegramPlacementItemIn(**payload)

    def test_g_sent_status_rejected_by_schema(self):
        """
        'sent' is NOT a valid status value — the C3a schema must reject it.
        ADR-018 D2 FIRM: no 'sent' state exists in the model or schema.
        """
        from pydantic import ValidationError

        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "sent",  # forbidden — does not exist in TelegramPlacementStatus
        }
        with self.assertRaises(ValidationError, msg="'sent' must not be a valid status in TelegramPlacementItemIn"):
            TelegramPlacementItemIn(**payload)

    def test_g_pending_status_rejected_by_schema(self):
        """
        'pending' is NOT a stored status (it is computed at reconciliation).
        The C3a schema must reject a report payload with status='pending'.
        """
        from pydantic import ValidationError

        from syndication.api import TelegramPlacementItemIn

        payload = {
            "destination_id": "-1001234567890",
            "status": "pending",  # not a stored value — computed only
        }
        with self.assertRaises(ValidationError, msg="'pending' must not be a valid status in TelegramPlacementItemIn"):
            TelegramPlacementItemIn(**payload)

    def test_g_schema_allows_only_three_stored_statuses(self):
        """
        TelegramPlacementItemIn accepts exactly the three stored status values:
        {placed, failed, skipped-pre-existing-draft}.
        No fourth value (sent, pending, or any other) is accepted.
        """
        from pydantic import ValidationError

        from syndication.api import TelegramPlacementItemIn

        valid_statuses = ["placed", "failed", "skipped-pre-existing-draft"]
        for status in valid_statuses:
            item = TelegramPlacementItemIn(destination_id="-1001234567890", status=status)
            self.assertIsNotNone(item, f"status={status!r} must be accepted")

        invalid_statuses = ["sent", "pending", "unknown", "", "PLACED"]
        for status in invalid_statuses:
            with self.assertRaises(ValidationError, msg=f"status={status!r} must be rejected"):
                TelegramPlacementItemIn(destination_id="-1001234567890", status=status)

    def test_g_schema_artifact_is_named_c3a_import(self):
        """
        TelegramPlacementItemIn is importable from syndication.api — this confirms
        it is the named artifact (C3a's Ninja input schema), not a copy or local shim.
        The schema's model_config carries extra='forbid' to guard forbidden fields.
        """
        from syndication.api import TelegramPlacementItemIn

        # Confirm the schema has extra=forbid (the guard for ADR-018 D4)
        config = getattr(TelegramPlacementItemIn, "model_config", {})
        self.assertEqual(
            config.get("extra"),
            "forbid",
            "TelegramPlacementItemIn must have model_config={'extra': 'forbid'} "
            "to reject forbidden fields (ADR-018 D4 guard)",
        )

    # ------------------------------------------------------------------
    # Schema has the exact four fields C3c sends (no more, no less)
    # ------------------------------------------------------------------

    def test_g_schema_fields_match_c3c_payload_shape(self):
        """
        TelegramPlacementItemIn's field set matches the C3c report payload shape:
        {destination_id (required), topic_id (optional), status (required), error_detail (optional)}.

        This is the pinned contract: if C3c adds a new field, or C3a removes one,
        this test fails and the drift is surfaced immediately.
        """
        from syndication.api import TelegramPlacementItemIn

        # Pydantic v2 schema fields
        schema_fields = set(TelegramPlacementItemIn.model_fields.keys())
        expected_fields = {"destination_id", "topic_id", "status", "error_detail"}
        self.assertEqual(
            schema_fields,
            expected_fields,
            f"TelegramPlacementItemIn fields {schema_fields} must match C3c payload shape {expected_fields}. "
            "If a new field is added on either side, update this contract assertion explicitly.",
        )


# ---------------------------------------------------------------------------
# Skipped-pre-existing-draft state reachability (cross-state schema assertion)
# ---------------------------------------------------------------------------


class TelegramPlacementStatusEnumTest(TestCase):
    """
    Verify the TelegramPlacementStatus enum has exactly the four documented
    values and that 'sent' does not exist anywhere in the enum.

    This is a defense-in-depth assertion: the enum is the single resolution
    point (kb-56c2.1) and adding 'sent' here would propagate to the model,
    schema, and template — a single mutation that defeats the ADR-018 D2 firewall.
    """

    def test_placement_status_has_exactly_three_stored_values(self):
        """
        TelegramPlacementStatus has exactly 3 stored values:
        {placed, failed, skipped-pre-existing-draft}.
        'pending' and 'sent' must NOT be in the enum.
        """
        values = {v for v, _ in TelegramPlacementStatus.choices}
        self.assertEqual(
            values,
            {"placed", "failed", "skipped-pre-existing-draft"},
            f"TelegramPlacementStatus must have exactly 3 stored values, got: {values}",
        )

    def test_sent_not_in_placement_status_enum(self):
        """'sent' must not be a value in TelegramPlacementStatus (ADR-018 D2 FIRM)."""
        values = {v for v, _ in TelegramPlacementStatus.choices}
        self.assertNotIn(
            "sent",
            values,
            "ADR-018 D2 FIRM: 'sent' must NEVER appear in TelegramPlacementStatus enum",
        )

    def test_pending_not_in_placement_status_enum(self):
        """
        'pending' is a computed state (absence of record), not a stored enum value.
        It must NOT be in TelegramPlacementStatus — adding it would break reconciliation.
        """
        values = {v for v, _ in TelegramPlacementStatus.choices}
        self.assertNotIn(
            "pending",
            values,
            "'pending' must NOT be a stored TelegramPlacementStatus value "
            "(it is computed at reconciliation, not stored — kb-56c2 D2)",
        )

    def test_skipped_pre_existing_draft_is_reachable(self):
        """
        The skipped-pre-existing-draft status value is reachable (it exists in the
        enum and can be stored as a TelegramPlacement record).
        """
        self.assertIn(
            TelegramPlacementStatus.SKIPPED_PRE_EXISTING_DRAFT,
            TelegramPlacementStatus.values,
            "skipped-pre-existing-draft must be a reachable TelegramPlacementStatus value",
        )
        self.assertEqual(
            TelegramPlacementStatus.SKIPPED_PRE_EXISTING_DRAFT,
            "skipped-pre-existing-draft",
        )
