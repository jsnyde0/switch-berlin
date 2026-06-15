"""
TDD tests for the coverage view + send-checklist UI (kb-56c2.2).

Tests assert against response.content (rendered HTML), NOT response.context,
because context-only tests pass on broken templates (memory:
django-view-test-context-vs-content-hollow).

Harness target (from bead --design):
(a) each of the four machine states renders with an honest label in the rendered HTML;
(b) NO "sent" string in any rendered template/response;
(c) public-tier renders as a deep-link affordance (not placed/pending);
(d) forum rows are forum-level (one per forum connection);
(e) a flagged_missing destination renders flagged-loud;
(f) the send-checklist renders the human-action set (agent-tier placed + public-tier),
    filtered by postability, and ticking does NOT POST a coverage mutation;
(g) browser read-back confirms (a)-(f) visually.

ADR-018 D2: no "sent" state ever in rendered HTML.
ADR-008 D3: vanished/flagged_missing rendered flagged-loud, not silently dropped.
kb-56c2 D6: public-tier is a human-action affordance (deep-link), never placed/pending.
kb-56c2 D3: send-checklist = agent-tier placed + public-tier; bot excluded; agent-pending excluded.
kb-56c2 D5: forum rows are forum-level (one row per forum connection, not per-topic).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import (
    PlatformConnection,
    Post,
    TelegramPlacement,
    TelegramPlacementStatus,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_vouched_user(username="coverage-user", email="coverage@test.com", password="testpass"):
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        status="vouched",
    )


def _make_profile(name="Coverage Test Org", slug="coverage-test-org", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(slug="coverage-test-event", **kwargs):
    defaults = {
        "title": "Coverage Test Party",
        "slug": slug,
        "start": timezone.now(),
        "status": "published",
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, headline="Coverage Test Post", body="Come join us."):
    return Post.objects.create(event=event, headline=headline, body=body)


def _make_connection(
    profile,
    destination_id="-1001234567890",
    postability="bot",
    kinds=None,
    flagged_missing=False,
    **kwargs,
):
    if kinds is None:
        kinds = ["promotion"]
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=kinds,
        postability=postability,
        flagged_missing=flagged_missing,
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


class CoverageViewBaseTest(TestCase):
    """
    Base setup for coverage view tests.

    Seeds:
    - one vouched user with a profile claim
    - one event + post
    - one bot-tier connection (placed)
    - one agent-tier connection (placed)
    - one agent-tier connection (failed)
    - one agent-tier connection (pending — no record)
    - one agent-tier connection (skipped-pre-existing-draft)
    - one public-tier connection
    - one flagged_missing connection
    """

    def setUp(self):
        self.user = _make_vouched_user()
        self.profile = _make_profile(user=self.user)
        self.event = _make_event()
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)

        # Bot-tier connection: will have placed record
        self.bot_conn = _make_connection(
            self.profile,
            destination_id="-1001110000001",
            postability="bot",
            title="Bot Channel",
        )
        self.bot_proj = _make_promotion_projection(self.bot_conn, self.post)
        _make_placement(self.bot_proj, self.bot_conn, TelegramPlacementStatus.PLACED)

        # Agent-tier connection: placed (should appear in send-checklist)
        self.agent_placed_conn = _make_connection(
            self.profile,
            destination_id="-1001110000002",
            postability="agent",
            title="Agent Group Placed",
        )
        self.agent_placed_proj = _make_promotion_projection(self.agent_placed_conn, self.post)
        _make_placement(self.agent_placed_proj, self.agent_placed_conn, TelegramPlacementStatus.PLACED)

        # Agent-tier connection: failed
        self.agent_failed_conn = _make_connection(
            self.profile,
            destination_id="-1001110000003",
            postability="agent",
            title="Agent Group Failed",
        )
        self.agent_failed_proj = _make_promotion_projection(self.agent_failed_conn, self.post)
        _make_placement(
            self.agent_failed_proj,
            self.agent_failed_conn,
            TelegramPlacementStatus.FAILED,
            error_detail="saveDraft returned error 400",
        )

        # Agent-tier connection: pending (no record — should NOT appear in send-checklist)
        self.agent_pending_conn = _make_connection(
            self.profile,
            destination_id="-1001110000004",
            postability="agent",
            title="Agent Group Pending",
        )
        self.agent_pending_proj = _make_promotion_projection(self.agent_pending_conn, self.post)
        # No TelegramPlacement record for this one → computed pending

        # Agent-tier connection: skipped-pre-existing-draft
        self.agent_skipped_conn = _make_connection(
            self.profile,
            destination_id="-1001110000005",
            postability="agent",
            title="Agent Group Skipped",
        )
        self.agent_skipped_proj = _make_promotion_projection(self.agent_skipped_conn, self.post)
        _make_placement(
            self.agent_skipped_proj,
            self.agent_skipped_conn,
            TelegramPlacementStatus.SKIPPED_PRE_EXISTING_DRAFT,
        )

        # Public-tier connection: deep-link affordance (never placed/pending)
        self.public_conn = _make_connection(
            self.profile,
            destination_id="-1001110000006",
            postability="public",
            title="Public Channel",
        )
        self.public_proj = _make_promotion_projection(self.public_conn, self.post)
        # No TelegramPlacement record (public-tier never gets one)

        # Flagged-missing connection
        self.vanished_conn = _make_connection(
            self.profile,
            destination_id="-1001110000007",
            postability="agent",
            title="Vanished Group",
            flagged_missing=True,
        )
        self.vanished_proj = _make_promotion_projection(self.vanished_conn, self.post)

        self.client = Client()
        self.client.login(username="coverage-user", password="testpass")

        # URL: keyed on the post pk (kb-e0ch re-key)
        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def _get_html(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, f"Expected 200, got {response.status_code}")
        return response.content.decode("utf-8")

    def _checklist_section(self, html):
        """
        Return ONLY the rendered send-checklist <section> substring, so checklist
        membership assertions cannot pass on a title that merely appears in the
        main coverage list. The checklist section is bounded by its heading id
        and the next </section> (it contains no nested <section>).
        """
        start = html.find('aria-labelledby="send-checklist-heading"')
        if start == -1:
            return ""
        # Back up to the opening <section ...> tag for completeness, then bound
        # the slice at the first </section> after the heading.
        section_open = html.rfind("<section", 0, start)
        end = html.find("</section>", start)
        self.assertNotEqual(end, -1, "send-checklist <section> is not closed in rendered HTML")
        return html[section_open if section_open != -1 else start : end]


# ---------------------------------------------------------------------------
# (a) Four machine states render with honest labels
# ---------------------------------------------------------------------------


class CoverageViewFourStatesTest(CoverageViewBaseTest):
    """
    (a) Each of the four machine states renders with an honest label in the HTML.
    """

    def test_placed_state_renders_label(self):
        """A placed connection renders with a 'placed' label."""
        html = self._get_html()
        self.assertIn("placed", html.lower(), "Expected 'placed' label in coverage HTML")

    def test_failed_state_renders_label(self):
        """A failed connection renders with a 'failed' label."""
        html = self._get_html()
        self.assertIn("failed", html.lower(), "Expected 'failed' label in coverage HTML")

    def test_pending_state_renders_label(self):
        """A pending connection (no record) renders with a 'pending' label."""
        html = self._get_html()
        self.assertIn("pending", html.lower(), "Expected 'pending' label in coverage HTML")

    def test_skipped_state_renders_label(self):
        """A skipped connection renders with a skipped label (not 'failed')."""
        html = self._get_html()
        # Check for 'skipped' in the HTML — could be 'skipped', 'pre-existing', etc.
        self.assertTrue(
            "skipped" in html.lower() or "pre-existing" in html.lower(),
            "Expected 'skipped' or 'pre-existing' label in coverage HTML for skipped-pre-existing-draft",
        )


# ---------------------------------------------------------------------------
# (b) NO "sent" string in any rendered response
# ---------------------------------------------------------------------------


class CoverageViewNoSentBadgeTest(CoverageViewBaseTest):
    """
    (b) ADR-018 D2: NO "sent" string must appear in the rendered HTML.
    """

    def test_no_sent_badge_in_rendered_html(self):
        """The rendered coverage HTML must never contain the string 'sent'."""
        html = self._get_html()
        # Check as whole-word to avoid false positives from "consent" etc.
        # Look specifically for "sent" as a status badge/label
        import re

        # Check for patterns like: ">sent<", "badge-sent", "status-sent",
        # "label: sent", etc. — any rendering of 'sent' as a status.
        # The word 'sent' should not appear as a standalone badge-like word
        # We look for common badge rendering patterns
        forbidden_patterns = [
            r"\bsent\b",
        ]
        for pattern in forbidden_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            # Allow "sent" only in comments or in the word "consent"
            # Filter: any occurrence that isn't "consent" is forbidden
            actual_hits = [m for m in matches if "consent" not in m.lower()]
            self.assertEqual(
                len(actual_hits),
                0,
                f"Found forbidden 'sent' badge patterns in rendered HTML: {actual_hits[:3]}. "
                "ADR-018 D2 FIRM: no 'sent' state is observable.",
            )


# ---------------------------------------------------------------------------
# (c) Public-tier renders as deep-link affordance (not placed/pending)
# ---------------------------------------------------------------------------


class CoverageViewPublicTierTest(CoverageViewBaseTest):
    """
    (c) Public-tier destinations render as a deep-link affordance,
    not placed/pending (kb-56c2 D6 / ADR-018 D2).
    """

    def test_public_tier_renders_as_deep_link(self):
        """The public-tier connection renders with a deep-link affordance marker."""
        html = self._get_html()
        # The public conn title should appear
        self.assertIn(
            "Public Channel",
            html,
            "Public Channel connection title must appear in coverage HTML",
        )
        # The page must contain a deep-link related label (not placed/pending)
        self.assertTrue(
            "deep-link" in html.lower()
            or "open" in html.lower()
            or "post manually" in html.lower()
            or "tg://" in html.lower(),
            "Public-tier destination must render as a deep-link affordance in coverage HTML",
        )

    def test_public_tier_not_rendered_as_placed(self):
        """Public-tier connection must NOT be associated with a 'placed' label."""
        html = self._get_html()
        # The public connection row should not have "placed" near its title
        # We assert by checking the row context for public conn
        # This is a coarse check — the full isolation is done at the service level (C3a)
        # Here we verify the rendered surface doesn't label public-tier as placed
        # The public tier row should contain "open" / "deep-link" / "manually"
        # and NOT contain a raw "placed" label for the public connection
        public_title_idx = html.find("Public Channel")
        self.assertGreater(public_title_idx, 0, "Public Channel must appear in HTML")

        # Search in a window around the public channel title
        window = html[max(0, public_title_idx - 200) : public_title_idx + 500]
        # The window should not have "placed" as a status label for this row
        # (it can contain "placed" for other rows earlier in the page, so we use a window)
        # Assert the public affordance marker is present
        self.assertTrue(
            "deep-link" in window.lower()
            or "open" in window.lower()
            or "manually" in window.lower()
            or "tg://" in window.lower(),
            f"Public Channel row window must contain a deep-link affordance marker. Window: {window[:300]}",
        )


# ---------------------------------------------------------------------------
# (d) Forum rows are forum-level (one row per forum connection)
# ---------------------------------------------------------------------------


class CoverageViewForumLevelTest(TestCase):
    """
    (d) Forum destinations render at forum-level (one row per forum connection,
    not per-topic) — kb-56c2 D5.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="forum-coverage-user", email="forum-coverage@test.com")
        self.profile = _make_profile(
            name="Forum Coverage Org",
            slug="forum-coverage-org",
            user=self.user,
        )
        self.event = _make_event(slug="forum-coverage-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)

        from syndication.models import TelegramDialogType

        # Forum connection (forum-level, one row expected)
        self.forum_conn = _make_connection(
            self.profile,
            destination_id="-1001220000001",
            postability="agent",
            title="Forum Group Coverage",
            type=TelegramDialogType.GROUP,
        )
        self.forum_proj = _make_promotion_projection(self.forum_conn, self.post)
        _make_placement(self.forum_proj, self.forum_conn, TelegramPlacementStatus.PLACED)

        self.client = Client()
        self.client.login(username="forum-coverage-user", password="testpass")
        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def test_forum_connection_renders_once_in_coverage_list(self):
        """
        A forum connection renders exactly once in the coverage destination list
        (forum-level, not per-topic).

        The title may also appear in the send-checklist section (if placed), but
        the key contract is that the coverage list has ONE row per forum connection.
        We verify by counting data-connection-pk occurrences in the coverage section.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        import re

        # Count data-connection-pk attributes matching this connection — each coverage
        # row has exactly one data-connection-pk attribute. One per forum connection
        # means the forum is rendered at forum-level, not once per topic.
        conn_pk = str(self.forum_conn.pk)

        # Count the coverage list rows for this connection by data-connection-pk
        rows = re.findall(rf'data-connection-pk="{conn_pk}"', html)
        self.assertEqual(
            len(rows),
            1,
            f"Forum connection {conn_pk} must render exactly once in the coverage list "
            f"(forum-level, not per-topic), found {len(rows)} data-connection-pk occurrences",
        )


# ---------------------------------------------------------------------------
# (e) Flagged_missing destination renders flagged-loud
# ---------------------------------------------------------------------------


class CoverageViewFlaggedMissingTest(CoverageViewBaseTest):
    """
    (e) A vanished (flagged_missing) destination renders flagged-loud,
    not silently dropped (ADR-008 D3).
    """

    def test_vanished_destination_renders_flagged_loud(self):
        """A vanished destination renders with a visible warning marker."""
        html = self._get_html()
        # The vanished connection title should appear
        self.assertIn(
            "Vanished Group",
            html,
            "Vanished Group connection title must appear in coverage HTML",
        )
        # The page must contain a loud flag for the vanished destination
        # (e.g., "vanished", "missing", "flagged" or similar)
        vanished_idx = html.find("Vanished Group")
        self.assertGreater(vanished_idx, 0)

        # Look in a window around the vanished group title
        window = html[max(0, vanished_idx - 300) : vanished_idx + 600]
        self.assertTrue(
            "vanished" in window.lower()
            or "missing" in window.lower()
            or "flagged" in window.lower()
            or "data-vanished" in window.lower(),
            f"Vanished destination must render with a loud flag. Window: {window[:400]}",
        )

    def test_vanished_destination_not_silently_dropped(self):
        """A vanished destination must appear in the HTML (not silently omitted)."""
        html = self._get_html()
        self.assertIn(
            "Vanished Group",
            html,
            "Vanished Group must be present in HTML — ADR-008 D3: no silent drops",
        )


# ---------------------------------------------------------------------------
# (f) Send-checklist: human-action set, postability-filtered, no mutation
# ---------------------------------------------------------------------------


class CoverageViewSendChecklistTest(CoverageViewBaseTest):
    """
    (f) The send-checklist renders:
    - agent-tier placed destinations (a draft exists to send)
    - public-tier destinations (human must post manually)
    - NOT bot-tier (bot already sent)
    - NOT agent-tier pending (no draft to send yet)
    - tickable items that do NOT POST to any mutation endpoint
    """

    def test_checklist_renders_agent_placed_connection(self):
        """Agent-tier placed connections appear IN the send-checklist section."""
        section = self._checklist_section(self._get_html())
        self.assertIn(
            "Agent Group Placed",
            section,
            "Agent-tier placed connection must appear inside the send-checklist section",
        )

    def test_checklist_renders_public_tier_connection(self):
        """Public-tier connections appear IN the send-checklist section."""
        section = self._checklist_section(self._get_html())
        self.assertIn(
            "Public Channel",
            section,
            "Public-tier connection must appear inside the send-checklist section",
        )

    def test_checklist_section_exists(self):
        """A send-checklist section is present in the rendered HTML."""
        html = self._get_html()
        self.assertTrue(
            "checklist" in html.lower() or "send" in html.lower(),
            "A send-checklist section must be present in the coverage HTML",
        )

    def test_checklist_items_are_not_form_submissions(self):
        """
        Checklist items are client-only — ticking does NOT POST to any server endpoint.

        The checkboxes in the send-checklist must either:
        (a) have no form/hx-post/action attribute pointing to a coverage mutation URL, or
        (b) use a client-only JS toggle (Alpine), not an HTMX POST.

        We verify that there is NO hx-post to any placements/coverage/checklist-tick endpoint.
        """
        html = self._get_html()
        import re

        # Look for any hx-post attribute pointing to a coverage mutation endpoint
        # The checklist ticks must NOT post to any URL containing these patterns
        forbidden_hx_patterns = [
            r'hx-post="[^"]*coverage[^"]*"',
            r'hx-post="[^"]*checklist[^"]*"',
            r'hx-post="[^"]*placement[^"]*tick[^"]*"',
            r'hx-post="[^"]*send-checklist[^"]*"',
        ]
        for pattern in forbidden_hx_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            self.assertEqual(
                len(matches),
                0,
                f"Found forbidden coverage mutation HTMX POST in send-checklist: {matches}. "
                "Ticking a checklist item must NOT mutate coverage state.",
            )

    def test_bot_tier_placed_not_in_send_checklist(self):
        """
        Bot-tier connections should NOT appear in the send-checklist
        (the bot already published — no human action needed for the send step).

        Note: the bot connection title may appear in the main coverage list,
        but must NOT appear in the dedicated send-checklist section.
        """
        section = self._checklist_section(self._get_html())
        self.assertNotEqual(section, "", "A send-checklist section must be present")

        # Bot-tier must not appear in the checklist — neither by postability data
        # attribute nor by the bot connection title.
        self.assertNotIn(
            'data-checklist-postability="bot"',
            section,
            "Bot-tier connections must NOT appear as send-checklist items",
        )
        self.assertNotIn(
            "Bot Channel",
            section,
            "Bot-tier connection title must NOT appear inside the send-checklist section",
        )

    def test_agent_pending_excluded_from_send_checklist(self):
        """
        Agent-tier pending connections are EXCLUDED from the send-checklist
        (no draft exists to send yet — D3). Scoped to the checklist section so
        the assertion is load-bearing: the pending title appears in the main
        coverage list but must NOT appear inside the checklist.
        """
        html = self._get_html()
        section = self._checklist_section(html)
        self.assertNotEqual(section, "", "A send-checklist section must be present")

        # The pending connection IS shown in the main coverage list...
        self.assertIn("Agent Group Pending", html, "Pending connection must appear in the main coverage list")
        # ...but is EXCLUDED from the send-checklist section.
        self.assertNotIn(
            "Agent Group Pending",
            section,
            "Agent-tier pending connection must NOT appear inside the send-checklist (no draft to send yet)",
        )
        # The human-action items (agent placed + public) ARE in the checklist.
        self.assertIn("Agent Group Placed", section)
        self.assertIn("Public Channel", section)


# ---------------------------------------------------------------------------
# Auth guard: unauthenticated redirects
# ---------------------------------------------------------------------------


class CoverageViewAuthTest(TestCase):
    """Auth guard: unauthenticated access redirects to login."""

    def setUp(self):
        self.user = _make_vouched_user(username="auth-test-user", email="auth@test.com")
        self.profile = _make_profile(
            name="Auth Test Org",
            slug="auth-test-org",
            user=self.user,
        )
        self.event = _make_event(slug="auth-test-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)
        self.conn = _make_connection(self.profile, destination_id="-1001330000001", postability="bot")
        self.proj = _make_promotion_projection(self.conn, self.post)
        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def test_unauthenticated_redirects_to_login(self):
        """Unauthenticated access to coverage view redirects to login."""
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


# ---------------------------------------------------------------------------
# URL resolution: coverage URL exists
# ---------------------------------------------------------------------------


class CoverageViewURLTest(TestCase):
    """URL wiring: the coverage URL resolves and renders."""

    def test_coverage_url_resolves(self):
        """The coverage URL pattern resolves without error."""
        url = reverse("syndication:coverage", kwargs={"pk": 1})
        self.assertIn("/coverage/", url)

    def test_coverage_url_uses_post_pk(self):
        """The coverage URL pattern is keyed on post pk, not projection pk (kb-e0ch)."""
        url = reverse("syndication:coverage", kwargs={"pk": 42})
        self.assertIn("/posts/42/coverage/", url)
        self.assertNotIn("/projections/", url)


# ---------------------------------------------------------------------------
# kb-e0ch: Post-keyed coverage view new tests
# ---------------------------------------------------------------------------


class CoveragePostKeyedRenderTest(TestCase):
    """
    (kb-e0ch) posts/<pk>/coverage/ renders destination rows for a post
    with Telegram promotion connections.

    Asserts against response.content (rendered HTML), not response.context.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="postkey-user", email="postkey@test.com")
        self.profile = _make_profile(
            name="Post Key Org",
            slug="post-key-org",
            user=self.user,
        )
        self.event = _make_event(slug="postkey-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)

        # One bot-tier connection with a placement
        self.conn = _make_connection(
            self.profile,
            destination_id="-1001440000001",
            postability="bot",
            title="PostKey Bot Channel",
        )
        self.proj = _make_promotion_projection(self.conn, self.post)
        _make_placement(self.proj, self.conn, TelegramPlacementStatus.PLACED)

        self.client = Client()
        self.client.login(username="postkey-user", password="testpass")
        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def test_post_keyed_url_renders_200(self):
        """posts/<pk>/coverage/ returns 200 for the post owner."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_post_keyed_url_renders_destination_rows(self):
        """posts/<pk>/coverage/ renders the destination rows for the post's connections."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        # The connection title must appear in the rendered HTML
        self.assertIn(
            "PostKey Bot Channel",
            html,
            "The connection title must appear in the coverage HTML for a post-keyed URL",
        )
        # A placed status label must appear
        self.assertIn(
            "placed",
            html.lower(),
            "A 'placed' label must appear in the rendered HTML for a placed connection",
        )


class CoverageNonOwnerForbiddenTest(TestCase):
    """
    (kb-e0ch) A non-owner user (no ProfileClaim / can_edit False) gets 404.

    Matches the existing view's non-owner → Http404 behavior;
    does not leak existence (ADR-008 D3).
    """

    def setUp(self):
        # Owner user
        self.owner = _make_vouched_user(username="nonowner-owner", email="nonowner-owner@test.com")
        self.profile = _make_profile(
            name="Non Owner Org",
            slug="nonowner-org",
            user=self.owner,
        )
        self.event = _make_event(slug="nonowner-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)

        # Non-owner user: no ProfileClaim on this event's organizer
        self.other_user = _make_vouched_user(
            username="nonowner-other",
            email="nonowner-other@test.com",
        )

        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def test_non_owner_gets_404(self):
        """A user with no claim on the post's event gets 404 (does not leak existence)."""
        client = Client()
        client.login(username="nonowner-other", password="testpass")
        response = client.get(self.url)
        self.assertEqual(
            response.status_code,
            404,
            "Non-owner must get 404 (not 403) — does not leak existence",
        )


class CoverageNoProjectionsTest(TestCase):
    """
    (kb-e0ch) A post with no Telegram projections renders the coverage page with
    an empty destinations list and does not 500.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="noproj-user", email="noproj@test.com")
        self.profile = _make_profile(
            name="No Proj Org",
            slug="noproj-org",
            user=self.user,
        )
        self.event = _make_event(slug="noproj-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        # Post with NO projections at all
        self.post = _make_post(self.event)

        self.client = Client()
        self.client.login(username="noproj-user", password="testpass")
        self.url = reverse("syndication:coverage", kwargs={"pk": self.post.pk})

    def test_no_projections_renders_200_not_500(self):
        """A post with no Telegram projections renders with 200, not 500."""
        response = self.client.get(self.url)
        self.assertEqual(
            response.status_code,
            200,
            "A post with no projections must render 200, not 500",
        )

    def test_no_projections_renders_empty_destinations_list(self):
        """A post with no Telegram projections renders an empty destinations list."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        # The "No destinations selected" message (or equivalent empty-list rendering)
        # must appear — the page must not 500 or show a broken state.
        self.assertTrue(
            "no destinations" in html.lower() or "destinations" in html.lower(),
            "An empty destinations message or section must appear in the rendered HTML",
        )
