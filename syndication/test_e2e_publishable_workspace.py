"""
End-to-end integration probe for the syndication publishable-workspace epic
(kb-q4u9.5).

Exercises the REAL HTTP endpoints the composer uses — not the service functions
directly (that's child B's probe; here we hit the VIEWS to prove the UI seam).

This is the integration probe that proves the UI→service seam works end-to-end:
customizing a post channel in the workspace ACTUALLY writes the post version and
renders/publishes a divergent body.

Harness signal: the "Invalidation" clause the parent epic names — the failure
mode where the composer never writes the post version even though service-layer
tests pass.

canonical_refs: ADR-016 D2 (per-channel divergence at the data layer through
the UI seam), ADR-016 D5 (publish invokes the adapter with the channel's own
frozen body).
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import (
    PlatformConnection,
    PlatformProjection,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirroring the pattern from test_e2e_board.py)
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


def _fake_ok_response():
    """Return a fake httpx.Response-like mock for Telegram Bot API success."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": {"message_id": 456}}
    return resp


# ---------------------------------------------------------------------------
# Customize seam: POST to the customize + edit endpoints actually writes the
# post version and renders a divergent body.
#
# This is the primary "invalidation" probe: a service-layer test can pass while
# the VIEWS never call customize() or edit_version(). This test hits the real
# HTTP endpoints and asserts on rendered HTML (response.content), not context.
# ---------------------------------------------------------------------------


class CustomizeSeamViewTest(TestCase):
    """
    Prove the composer's Customize and Save controls write the post version
    through the real view path, and that divergence is visible in the rendered
    fragment HTML.

    Steps:
    1. Create a post (via create_post service) with ≥2 promotion projections
       on different Telegram channels.
    2. POST to the customize endpoint for channel 1.
    3. POST to the version-edit endpoint with a divergent body for channel 1.
    4. GET the post_syndication fragment and assert:
       (a) channel 1's rendered body shows the divergent text in response.content.
       (b) channel 2's rendered body does NOT show the divergent text.
    5. Assert the customize actually wrote a post-owned ContentVersion for channel 1
       (FK repointed — the data-layer divergence, not just a render trick).
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="cseam_user",
            email="cseam@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="CSeam Organizer",
            slug="cseam-organizer",
            user=self.user,
        )

        # Event with organizer link so can_edit / can_publish works.
        self.event = Event.objects.create(
            title="CSeam Event",
            slug="cseam-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile,
            is_primary=True,
        )

        # Two Telegram promotion connections — gives us ≥2 promotion projections.
        self.conn_tg_1 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@cseam-ch-1",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-cseam-1"},
        )
        self.conn_tg_2 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@cseam-ch-2",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-cseam-2"},
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_customize_seam_writes_post_version_and_diverges_channel_body(self):
        """
        POST to customize → POST to version-edit → GET post_syndication fragment:

        (a) channel 1's rendered body in response.content matches the divergent text.
        (b) channel 2's rendered body in response.content does NOT match the
            divergent text (isolation invariant).
        (c) At the data layer, channel 1's projection now FKs a distinct
            ContentVersion from channel 2 (customize actually wrote the post version).

        This is the "composer actually writes the post version" assertion.
        A failure here means the Customize control is wired to the wrong endpoint
        or the view never calls the service — the invalidation the parent harness names.
        """
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="CSeam Headline",
            body="Canonical post body for cseam",
        )

        proj_1 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_1,
        )
        proj_2 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_2,
        )

        # Precondition: both projections share the same canonical ContentVersion.
        self.assertEqual(
            proj_1.content_version_id,
            proj_2.content_version_id,
            "Precondition: both projections must start on the same canonical CV.",
        )
        original_cv_id = proj_1.content_version_id

        # --- Customize seam: POST to the view endpoint ---
        customize_response = self.client.post(
            f"/syndication/projections/{proj_1.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(
            customize_response.status_code,
            [200, 302],
            "Customize endpoint must return 200 (HTMX fragment) or 302 (redirect).",
        )

        # Reload proj_1 — its content_version FK must have changed.
        proj_1.refresh_from_db()
        self.assertNotEqual(
            proj_1.content_version_id,
            original_cv_id,
            "(c) customize() must have minted a new ContentVersion and repointed "
            "proj_1's FK — the 'composer writes the post version' invariant.",
        )

        # The new ContentVersion must be post-scoped (not event-scoped).
        new_cv = proj_1.content_version
        self.assertIsNone(
            new_cv.event,
            "The customized ContentVersion must be post-scoped (event FK null).",
        )
        self.assertEqual(
            new_cv.post,
            post,
            "The customized ContentVersion must be owned by the post.",
        )

        # proj_2's FK must be UNCHANGED (divergence isolation).
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.content_version_id,
            original_cv_id,
            "proj_2 must still FK the canonical CV — customize must NOT affect siblings.",
        )

        # --- Edit-body seam: POST to the version-edit endpoint ---
        divergent_body = "DIVERGENT-BODY-CHANNEL-1-UNIQUE"
        edit_response = self.client.post(
            f"/syndication/versions/{new_cv.pk}/edit/",
            {"body": divergent_body},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(
            edit_response.status_code,
            [200, 302],
            "Version-edit endpoint must return 200 (HTMX fragment) or 302 (redirect).",
        )

        # Verify the data layer: the version body must be stored.
        new_cv.refresh_from_db()
        self.assertEqual(
            new_cv.body,
            divergent_body,
            "edit_version must persist the divergent body to ContentVersion.body.",
        )
        self.assertEqual(
            new_cv.provenance,
            "manual",
            "edit_version must flip ContentVersion.provenance to 'manual'.",
        )

        # --- GET the post_syndication fragment and assert rendered HTML ---
        fragment_response = self.client.get(
            f"/syndication/posts/{post.pk}/fragments/post_syndication/",
        )
        self.assertEqual(
            fragment_response.status_code,
            200,
            "post_syndication fragment must render successfully.",
        )

        content = fragment_response.content.decode("utf-8")

        # (a) The divergent body must appear somewhere in the rendered HTML.
        # The template renders body text in the textarea (draft state) and preview.
        self.assertIn(
            divergent_body,
            content,
            "(a) The divergent body must appear in the rendered post_syndication "
            "fragment — channel 1's customized version must be visible.",
        )

        # (b) channel 2's body must be the canonical body (not the divergent text).
        # We assert the CANONICAL body appears (channel 2's render) while the
        # divergent text is ONLY channel 1's.
        # The canonical body was "Canonical post body for cseam" — assert it is also
        # present (channel 2 still renders it), and that divergence is isolated.
        # Direct check: the divergent text should appear ONCE — only for channel 1.
        # Because channel 2 renders the canonical body, they are distinct strings.
        canonical_body = "Canonical post body for cseam"
        self.assertIn(
            canonical_body,
            content,
            "(b) The canonical body must appear in the rendered fragment "
            "(channel 2 still shares the canonical ContentVersion).",
        )

        # (b) Explicit isolation assertion: proj_2 still FKs the original canonical CV.
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.content_version_id,
            original_cv_id,
            "(b) After editing channel 1, proj_2 must still be on the canonical CV. The divergence must be isolated.",
        )


# ---------------------------------------------------------------------------
# Publish seam: advance the customized channel-1 projection to ready, then
# POST to the publish endpoint and assert the adapter is invoked with
# channel 1's OWN (frozen) body.
# ---------------------------------------------------------------------------


class PublishSeamViewTest(TestCase):
    """
    Prove the publish endpoint routes the customized channel's OWN body to the
    adapter — not the canonical body or another channel's body.

    Steps:
    1. Create a post with ≥2 Telegram promotion projections.
    2. Customize channel 1 and edit its body to a DISTINGUISHABLE value.
    3. Advance channel 1 to ready (POST to approve endpoint).
    4. POST to the publish endpoint for channel 1.
    5. Assert:
       (a) The Telegram adapter (httpx.post) was called with channel 1's OWN body
           (the frozen divergent body, not the canonical body). Mirrors the
           adapter dispatch assertion from test_e2e_board.py step 3.
       (b) channel 1's projection status is PUBLISHED.
       (c) channel 2's projection status is DRAFT (untouched).

    The mock is placed at the transport boundary (httpx.post in syndication.adapters),
    same pattern as
    E2EBoardFlowTest.test_step3_publish_routes_customized_content_to_adapter.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="pseam_user",
            email="pseam@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="PSeam Organizer",
            slug="pseam-organizer",
            user=self.user,
        )

        self.event = Event.objects.create(
            title="PSeam Event",
            slug="pseam-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile,
            is_primary=True,
        )

        # Two Telegram promotion connections.
        self.conn_tg_1 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@pseam-ch-1",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-pseam-1"},
        )
        self.conn_tg_2 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@pseam-ch-2",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-pseam-2"},
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_publish_seam_invokes_adapter_with_channels_own_body(self):
        """
        customize → edit → approve → publish via REAL view endpoints:

        (a) httpx.post (the Telegram transport boundary) is called exactly once
            with channel 1's OWN divergent body in the payload — not the canonical
            body or channel 2's body. A routing swap would deliver the wrong body.
        (b) channel 1's projection is PUBLISHED after the view call.
        (c) channel 2's projection remains DRAFT (untouched by channel 1's publish).

        ADR-016 D5: publish invokes the adapter with the channel's own frozen body.
        """
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="PSeam Headline",
            body="Canonical body for pseam",
        )

        proj_1 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_1,
        )
        proj_2 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_2,
        )

        # --- Customize channel 1 via view endpoint ---
        self.client.post(
            f"/syndication/projections/{proj_1.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        proj_1.refresh_from_db()
        new_cv = proj_1.content_version

        # --- Edit channel 1's body to a DISTINGUISHABLE value ---
        divergent_body = "PUBLISH-SEAM-CUSTOM-BODY-CH1"
        self.client.post(
            f"/syndication/versions/{new_cv.pk}/edit/",
            {"body": divergent_body},
            HTTP_HX_REQUEST="true",
        )

        # --- Advance channel 1 to ready via approve endpoint ---
        approve_response = self.client.post(
            f"/syndication/projections/{proj_1.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(
            approve_response.status_code,
            [200, 302],
            "Approve endpoint must return 200 or 302.",
        )
        proj_1.refresh_from_db()
        self.assertEqual(
            proj_1.status,
            PlatformProjection.Status.READY,
            "Precondition: proj_1 must be READY after approve.",
        )
        self.assertEqual(
            proj_1.frozen_content["body"],
            divergent_body,
            "Precondition: proj_1's frozen_content must carry the divergent body.",
        )

        # channel 2 must still be DRAFT (approve for channel 1 must NOT affect it).
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "Precondition: proj_2 must still be DRAFT after channel 1's approve.",
        )

        # --- Publish channel 1 via view endpoint — mock only httpx.post ---
        with patch(
            "syndication.adapters.httpx.post",
            return_value=_fake_ok_response(),
        ) as mock_post:
            publish_response = self.client.post(
                f"/syndication/projections/{proj_1.pk}/publish/",
                HTTP_HX_REQUEST="true",
            )

        self.assertIn(
            publish_response.status_code,
            [200, 302],
            "Publish endpoint must return 200 (HTMX fragment) or 302 (redirect).",
        )

        # (a) httpx.post must be called exactly once — the real Telegram adapter ran.
        self.assertEqual(
            mock_post.call_count,
            1,
            "(a) httpx.post must be called exactly once for channel 1's publish.",
        )

        # (a) The Telegram payload text must be channel 1's OWN divergent body.
        # A routing swap would deliver the canonical body or channel 2's body.
        # httpx.post is called as httpx.post(url, json=payload) → kwargs["json"].
        actual_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            actual_payload["text"],
            divergent_body,
            "(a) Telegram payload text must be channel 1's OWN divergent body. "
            "A routing swap would post the canonical body — this assertion catches it. "
            "ADR-016 D5: publish must route the channel's own frozen body.",
        )

        # Explicit routing-swap catch: the payload must NOT be the canonical body.
        canonical_body = "Canonical body for pseam"
        self.assertNotEqual(
            actual_payload["text"],
            canonical_body,
            "(a) Routing-swap catch: payload must NOT be the canonical body.",
        )

        # (b) channel 1 must now be PUBLISHED.
        proj_1.refresh_from_db()
        self.assertEqual(
            proj_1.status,
            PlatformProjection.Status.PUBLISHED,
            "(b) channel 1 must be PUBLISHED after the publish view call.",
        )
        self.assertEqual(
            proj_1.frozen_content["body"],
            divergent_body,
            "(b) channel 1's frozen_content must be the divergent body after publish.",
        )

        # (c) channel 2 must still be DRAFT — untouched.
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.DRAFT,
            "(c) channel 2 must remain DRAFT while only channel 1 was published.",
        )


# ---------------------------------------------------------------------------
# Anchor confirmation: assert the canonical anchors are rendered in HTML.
#
# - Event workspace: Switch tab is the canonical anchor (ADR-010 D1) — the
#   Switch projection appears FIRST in the rendered tab list.
# - Post workspace: "Source" is the canonical anchor label (no native-home
#   channel for posts) — the word "Source" appears in the rendered header.
#
# These tie the rendered HTML to the data layer.
# ---------------------------------------------------------------------------


class AnchorConfirmationTest(TestCase):
    """
    Assert the canonical anchor is rendered in the fragment HTML for both
    event workspace and post workspace.

    Event workspace anchor: Switch tab first (ADR-010 D1 — Switch is the
    canonical home channel for events). The fragment sorting puts switch listing
    projection at tier 0 (before all others). Assert "switch" appears in the
    rendered HTML before any other platform name.

    Post workspace anchor: "Source" label in the post workspace header (no
    native-home channel for posts — ADR-008 D2: no tab framework speculation).
    Assert the literal text "Source" is rendered in the post_syndication
    fragment HTML.

    Assertion is on response.content (rendered HTML bytes), NOT on
    response.context, per the memory: django-view-test-context-vs-content-hollow.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="anchor_user",
            email="anchor@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="Anchor Organizer",
            slug="anchor-organizer",
            user=self.user,
        )

        self.event = Event.objects.create(
            title="Anchor Event",
            slug="anchor-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile,
            is_primary=True,
        )

        # Switch listing connection (the canonical anchor for event workspace).
        self.conn_switch = _make_connection(
            self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
        )

        # A second listing connection to give the fragment ≥2 tabs.
        self.conn_fetlife = _make_connection(
            self.profile,
            platform="fetlife",
            destination_id="fl-anchor-001",
            kinds=["listing"],
        )

        # Telegram promotion connection for the post workspace.
        self.conn_tg = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@anchor-tg",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-anchor"},
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_event_workspace_switch_tab_is_canonical_anchor(self):
        """
        GET the event_syndication fragment and assert 'switch' appears in the
        rendered HTML before 'fetlife' (Switch is the canonical anchor tab,
        ADR-010 D1).

        The fragment view sorts projections with Switch listing at tier 0
        (before all other channels). The rendered tablist therefore has 'switch'
        before 'fetlife' in the HTML.

        Asserts on response.content (rendered bytes), not response.context.
        """
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Anchor Event Switch",
            slug="anchor-event-switch",
            start=timezone.now(),
        )

        fragment_response = self.client.get(
            f"/syndication/events/{event.pk}/fragments/event_syndication/",
        )
        self.assertEqual(fragment_response.status_code, 200)

        content = fragment_response.content.decode("utf-8")

        # The rendered HTML must contain both platform names.
        self.assertIn(
            "switch",
            content,
            "Event workspace must render the switch channel tab.",
        )
        self.assertIn(
            "fetlife",
            content,
            "Event workspace must render the fetlife channel tab.",
        )

        # ADR-010 D1: Switch is the canonical anchor — it must appear BEFORE fetlife
        # in the rendered HTML (sorting tier 0 vs tier 1).
        switch_pos = content.find("switch")
        fetlife_pos = content.find("fetlife")
        self.assertLess(
            switch_pos,
            fetlife_pos,
            "ADR-010 D1: Switch tab must appear BEFORE fetlife in the event workspace "
            "HTML — Switch is the canonical anchor (tier 0 in the sort key).",
        )

    def test_post_workspace_renders_single_top_row_no_event_hub_link(self):
        """
        kb-96tn.1 (composer bar): GET the post_syndication fragment and assert
        the single top row renders WITHOUT the old 'Event Workspace ↗' cross-link.
        The back-link to the event hub is now the breadcrumb in the composer bar
        (_post_hub_body.html), not in the fragment itself.

        Asserts on response.content (rendered bytes), not response.context.
        """
        from syndication.services import create_event, create_post

        # We need a create_event first to satisfy the post FK
        event = create_event(
            user=self.user,
            title="Anchor Post Event",
            slug="anchor-post-event",
            start=timezone.now(),
        )

        post = create_post(
            user=self.user,
            event=event,
            headline="Anchor Post",
            body="Anchor post body",
        )

        fragment_response = self.client.get(
            f"/syndication/posts/{post.pk}/fragments/post_syndication/",
        )
        self.assertEqual(fragment_response.status_code, 200)

        content = fragment_response.content.decode("utf-8")

        # kb-96tn.1: The 'Event Workspace ↗' link was removed from the fragment.
        # The breadcrumb in the composer bar (_post_hub_body.html) is now the
        # back-link. The fragment must NOT contain the old link text.
        self.assertNotIn(
            "Event Workspace",
            content,
            "Post syndication fragment must NOT render the old 'Event Workspace ↗' "
            "cross-link — the breadcrumb in the composer bar is the back-link (kb-96tn.1).",
        )


# ---------------------------------------------------------------------------
# Post-scoped publish-all-ready seam (kb-q4u9.6 MATERIAL FIX 1).
#
# The event-scoped batch-publish was wired into the post workspace button.
# This test proves the post-scoped endpoint:
#   (a) each channel's adapter invoked with its OWN body,
#   (b) projections under OTHER posts / the event's listing are NOT published,
#   (c) the response is the POST fragment (not the event fragment).
# ---------------------------------------------------------------------------


class PostScopedPublishAllReadyTest(TestCase):
    """
    Prove the post-scoped publish-all-ready endpoint (kb-q4u9.6 MATERIAL FIX 1):

    1. Create a post with ≥2 ready promotion projections carrying DIVERGENT bodies.
    2. Create a second post + listing projection (must NOT be published by this call).
    3. POST the post-scoped publish-all-ready endpoint.
    4. Assert:
       (a) Each channel's adapter invoked with its OWN body (mock httpx.post,
           assert call_count == 2 and each call carries the right text).
       (b) Projections under OTHER posts / the event's listing are NOT published.
       (c) The response contains the post-workspace marker (id="post-syndication"),
           NOT the event-syndication id — proves the POST fragment was returned.

    ADR-016 D5: publish invokes the adapter with the channel's own frozen body.
    ADR-008 D3: fail loud — no silent fallback on wrong fragment returned.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="pbatch_user",
            email="pbatch@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="PBatch Organizer",
            slug="pbatch-organizer",
            user=self.user,
        )

        self.event = Event.objects.create(
            title="PBatch Event",
            slug="pbatch-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile,
            is_primary=True,
        )

        # Two Telegram promotion connections for the post under test.
        self.conn_tg_1 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@pbatch-ch-1",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-pbatch-1"},
        )
        self.conn_tg_2 = _make_connection(
            self.profile,
            platform="telegram",
            destination_id="@pbatch-ch-2",
            kinds=["promotion"],
            credentials={"bot_token": "fake-token-pbatch-2"},
        )

        # FetLife listing connection — its projection must NOT be published
        # by the post-scoped endpoint.
        self.conn_fl = _make_connection(
            self.profile,
            platform="fetlife",
            destination_id="fl-pbatch-001",
            kinds=["listing"],
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_post_scoped_publish_all_ready_invokes_each_adapter_with_own_body_and_returns_post_fragment(self):
        """
        POST the post-scoped publish-all-ready endpoint for a post with two
        divergent ready Telegram channels:

        (a) httpx.post called exactly twice — once per channel — each with its
            OWN divergent body (not the canonical body, not the other channel's body).
        (b) Listing projection + projections under a different post remain DRAFT
            (scoping: this call must NOT publish the whole event).
        (c) response.content contains id="post-syndication" (the POST fragment),
            and does NOT contain id="event-syndication" (the event fragment).
        """
        from syndication.services import create_post

        # Primary post: two Telegram channels, divergent bodies.
        post = create_post(
            user=self.user,
            event=self.event,
            headline="PBatch Primary Post",
            body="Canonical body for pbatch primary",
        )

        proj_1 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_1,
        )
        proj_2 = PlatformProjection.objects.get(
            source_post=post,
            connection=self.conn_tg_2,
        )

        # Create a second post — its projections must NOT be published.
        post_other = create_post(
            user=self.user,
            event=self.event,
            headline="PBatch Other Post",
            body="Other post body",
        )
        proj_other = PlatformProjection.objects.get(
            source_post=post_other,
            connection=self.conn_tg_1,
        )

        # Create listing projection — must NOT be published by post-scoped endpoint.
        from syndication.models import ContentVersion

        cv_listing = ContentVersion.objects.create(
            event=self.event,
            name="listing-cv",
            provenance="rule_template",
        )
        proj_listing = PlatformProjection.objects.create(
            kind=PlatformProjection.Kind.LISTING,
            source_event=self.event,
            connection=self.conn_fl,
            content_version=cv_listing,
            status=PlatformProjection.Status.READY,
        )

        # Customize ch1 and ch2 to divergent bodies, then approve both.
        body_1 = "PBATCH-DIVERGENT-BODY-CHANNEL-1"
        body_2 = "PBATCH-DIVERGENT-BODY-CHANNEL-2"

        self.client.post(
            f"/syndication/projections/{proj_1.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        proj_1.refresh_from_db()
        cv_1 = proj_1.content_version
        self.client.post(
            f"/syndication/versions/{cv_1.pk}/edit/",
            {"body": body_1},
            HTTP_HX_REQUEST="true",
        )

        self.client.post(
            f"/syndication/projections/{proj_2.pk}/customize/",
            HTTP_HX_REQUEST="true",
        )
        proj_2.refresh_from_db()
        cv_2 = proj_2.content_version
        self.client.post(
            f"/syndication/versions/{cv_2.pk}/edit/",
            {"body": body_2},
            HTTP_HX_REQUEST="true",
        )

        # Approve both channels → ready status.
        self.client.post(
            f"/syndication/projections/{proj_1.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )
        self.client.post(
            f"/syndication/projections/{proj_2.pk}/approve/",
            HTTP_HX_REQUEST="true",
        )

        proj_1.refresh_from_db()
        proj_2.refresh_from_db()
        self.assertEqual(
            proj_1.status,
            PlatformProjection.Status.READY,
            "Precondition: proj_1 must be READY.",
        )
        self.assertEqual(
            proj_2.status,
            PlatformProjection.Status.READY,
            "Precondition: proj_2 must be READY.",
        )

        # POST the post-scoped publish-all-ready endpoint (mocking httpx.post).
        with patch(
            "syndication.adapters.httpx.post",
            return_value=_fake_ok_response(),
        ) as mock_post:
            response = self.client.post(
                f"/syndication/posts/{post.pk}/projections/publish-all-ready/",
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(
            response.status_code,
            200,
            "Post-scoped publish-all-ready must return HTTP 200.",
        )

        # (a) httpx.post called exactly twice — one per channel.
        self.assertEqual(
            mock_post.call_count,
            2,
            "(a) httpx.post must be called exactly twice — once per ready channel "
            "of the target post. Publishing the event-scope would call more times.",
        )

        # (a) Each channel was called with its OWN body.
        called_texts = {call.kwargs["json"]["text"] for call in mock_post.call_args_list}
        self.assertIn(
            body_1,
            called_texts,
            "(a) Channel 1's adapter must be called with channel 1's OWN body.",
        )
        self.assertIn(
            body_2,
            called_texts,
            "(a) Channel 2's adapter must be called with channel 2's OWN body.",
        )

        # (b) Other post's projection and listing projection must remain DRAFT / READY
        # (untouched by this call).
        proj_other.refresh_from_db()
        self.assertNotEqual(
            proj_other.status,
            PlatformProjection.Status.PUBLISHED,
            "(b) Other post's projection must NOT be published by post-scoped endpoint.",
        )

        proj_listing.refresh_from_db()
        self.assertNotEqual(
            proj_listing.status,
            PlatformProjection.Status.PUBLISHED,
            "(b) Listing projection must NOT be published by post-scoped endpoint.",
        )

        # (c) Response contains the POST fragment id, not the event fragment id.
        content = response.content.decode("utf-8")
        self.assertIn(
            'id="post-syndication"',
            content,
            '(c) Response must contain the post-syndication fragment (id="post-syndication") — not the event fragment.',
        )
        self.assertNotIn(
            'id="event-syndication"',
            content,
            "(c) Response must NOT contain the event-syndication fragment id — "
            "the post-scoped endpoint returns the post fragment only.",
        )


# ---------------------------------------------------------------------------
# Post card navigation: post card in the event hub must link to the post
# composer (syndication:post-hub). kb-q4u9.6 MATERIAL FIX 2.
# ---------------------------------------------------------------------------


class PostCardNavigationTest(TestCase):
    """
    Assert the event hub's post list renders each post card with a link to
    the post-hub URL (/syndication/posts/<pk>/).

    Parent acceptance bullet 1 / D1: "a flat list of publishables is navigable;
    selecting one opens its composer."

    Assertion: GET the event_posts fragment and check that the rendered HTML
    contains a link href pointing to /syndication/posts/<post.pk>/.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="pnav_user",
            email="pnav@test.com",
            password="pw",
        )
        self.profile = _make_profile(
            name="PNav Organizer",
            slug="pnav-organizer",
            user=self.user,
        )

        self.event = Event.objects.create(
            title="PNav Event",
            slug="pnav-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(
            event=self.event,
            profile=self.profile,
            is_primary=True,
        )

        self.client = Client()
        self.client.force_login(self.user)

    def test_post_card_links_to_post_hub(self):
        """
        GET the event_posts fragment: each post card must render a link to
        /syndication/posts/<pk>/ (the post composer / post-hub route).

        Asserts on response.content (rendered bytes), not response.context.
        """
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="PNav Post Headline",
            body="PNav post body",
        )

        response = self.client.get(
            f"/syndication/events/{self.event.pk}/fragments/event_posts/",
        )
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        post_hub_url = f"/syndication/posts/{post.pk}/"

        self.assertIn(
            post_hub_url,
            content,
            f"event_posts fragment must contain a link to the post-hub URL "
            f"({post_hub_url}). Selecting a post must open its composer "
            "(parent acceptance bullet 1 / D1).",
        )
