"""
TDD tests for kb-k2ds.3: enable-promotion service verb + co-equal REST surface
(enable-promotion action, connections discoverability) and the fan-out proof
that create_post only mints a promotion projection AFTER a connection is
enabled.

Harness signal (kb-k2ds.3 ## Harness target, suite (b)):
- enable_promotion adds 'promotion' to kinds + enabled=True.
- Idempotent: re-calling on an already-enabled connection is a success no-op
  (no duplicate kinds append).
- Raises ValueError on a connection whose platform cannot support promotion
  (_supports_post_promotion gate, e.g. 'switch').
- Raises ValueError on a non-selectable connection (flagged_missing,
  agent-tier locked) — same fail-loud gate as the web destination_select view.
- Never creates a connection.
- POST /api/connections/{id}/enable-promotion/ mirrors the service behavior;
  GET /api/connections/ gives an agent the id to target (discoverability).
- create_post's eager fan-out creates a draft promotion projection for a
  connection ONLY after it has been enabled; before enabling, none.

ADR-016 D1/D4/D6 (co-equal REST + eager projection fan-out);
ADR-008 D3 (fail loud); ADR-010 D1 (platform-capability gate).
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection, TelegramPostability

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers (mirror test_add_channel.py / test_api.py helpers)
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name="Test Organizer", slug="test-organizer", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_connection(profile, platform="telegram", destination_id="tg-channel", kinds=None, enabled=False, **kwargs):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds if kinds is not None else [],
        enabled=enabled,
        **kwargs,
    )


def _make_event(profile, title="Test Event", slug="test-event"):
    event = Event.objects.create(title=title, slug=slug, start=timezone.now())
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    from syndication.services import _ensure_canonical_content_version

    _ensure_canonical_content_version(event=event)
    return event


def _register_and_get_api_key(user):
    client = Client()
    client.force_login(user)
    reg_response = client.post("/api/agents/register")
    assert reg_response.status_code == 200, f"register failed: {reg_response.content}"
    pairing_token = json.loads(reg_response.content)["pairing_token"]
    redeem_response = client.post(
        "/api/agents/redeem",
        data=json.dumps({"pairing_token": pairing_token}),
        content_type="application/json",
    )
    assert redeem_response.status_code == 200, f"redeem failed: {redeem_response.content}"
    return json.loads(redeem_response.content)["api_key"]


def _get_identity_token_for_user(user):
    api_key = _register_and_get_api_key(user)
    client = Client()
    ex = client.post(
        "/api/agents/token",
        data=json.dumps({"api_key": api_key}),
        content_type="application/json",
    )
    assert ex.status_code == 200, f"token exchange failed: {ex.content}"
    return json.loads(ex.content)["identity_token"]


# ---------------------------------------------------------------------------
# 1. enable_promotion service verb — unit tests (TDD RED first)
# ---------------------------------------------------------------------------


class EnablePromotionServiceTest(TestCase):
    """
    syndication.services.enable_promotion(user, connection):
    - Adds 'promotion' to kinds (additive) + sets enabled=True.
    - Idempotent: re-call is a success no-op, never a duplicate append.
    - Raises ValueError on a promotion-incapable platform (e.g. 'switch').
    - Raises ValueError on a non-selectable connection (flagged_missing,
      agent-tier locked) — same gate as the web destination_select view.
    - Never creates a connection.
    ADR-016 D4; ADR-008 D3; ADR-010 D1.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="enable_promo_user", email="enable_promo@test.com", password="x")
        self.profile = _make_profile(name="Enable Promo Profile", slug="enable-promo-profile", user=self.user)

    def test_enable_promotion_adds_promotion_kind_and_enables(self):
        from syndication.services import enable_promotion

        conn = _make_connection(self.profile, kinds=[], enabled=False)

        enable_promotion(user=self.user, connection=conn)

        conn.refresh_from_db()
        self.assertIn("promotion", conn.kinds)
        self.assertTrue(conn.enabled)

    def test_enable_promotion_preserves_existing_kinds(self):
        """Enabling promotion on a connection that already has 'listing' keeps 'listing' (additive)."""
        from syndication.services import enable_promotion

        conn = _make_connection(self.profile, platform="fetlife", kinds=["listing"], enabled=True)

        enable_promotion(user=self.user, connection=conn)

        conn.refresh_from_db()
        self.assertIn("listing", conn.kinds)
        self.assertIn("promotion", conn.kinds)

    def test_enable_promotion_idempotent_no_duplicate_append(self):
        """Re-calling enable_promotion on an already-enabled connection does not duplicate 'promotion'."""
        from syndication.services import enable_promotion

        conn = _make_connection(self.profile, kinds=[], enabled=False)

        enable_promotion(user=self.user, connection=conn)
        enable_promotion(user=self.user, connection=conn)

        conn.refresh_from_db()
        self.assertEqual(conn.kinds.count("promotion"), 1)
        self.assertTrue(conn.enabled)

    def test_enable_promotion_raises_on_promotion_incapable_platform(self):
        """A 'switch' connection cannot be enabled for promotion (_supports_post_promotion gate, ADR-010 D1)."""
        from syndication.services import enable_promotion

        conn = _make_connection(self.profile, platform="switch", destination_id="own-page", kinds=[], enabled=True)

        with self.assertRaises(ValueError):
            enable_promotion(user=self.user, connection=conn)

        conn.refresh_from_db()
        self.assertNotIn("promotion", conn.kinds or [])

    def test_enable_promotion_raises_on_flagged_missing_connection(self):
        """A flagged_missing (vanished) connection cannot be enabled (ADR-008 D3 fail loud)."""
        from syndication.services import enable_promotion

        conn = _make_connection(self.profile, kinds=[], enabled=False, flagged_missing=True)

        with self.assertRaises(ValueError):
            enable_promotion(user=self.user, connection=conn)

        conn.refresh_from_db()
        self.assertNotIn("promotion", conn.kinds or [])
        self.assertFalse(conn.enabled)

    def test_enable_promotion_raises_on_agent_tier_locked_connection(self):
        """An agent-tier connection with no active AgentCredential for the user cannot be enabled."""
        from syndication.services import enable_promotion

        conn = _make_connection(
            self.profile, kinds=[], enabled=False, postability=TelegramPostability.AGENT
        )

        with self.assertRaises(ValueError):
            enable_promotion(user=self.user, connection=conn)

        conn.refresh_from_db()
        self.assertNotIn("promotion", conn.kinds or [])

    def test_enable_promotion_never_creates_a_connection(self):
        """enable_promotion never creates a new PlatformConnection row — only mutates the given one."""
        from syndication.services import enable_promotion

        conn = _make_connection(self.profile, kinds=[], enabled=False)
        count_before = PlatformConnection.objects.count()

        enable_promotion(user=self.user, connection=conn)

        self.assertEqual(PlatformConnection.objects.count(), count_before)


# ---------------------------------------------------------------------------
# 2. GET /api/connections/ + POST /api/connections/{id}/enable-promotion/
# ---------------------------------------------------------------------------


class ConnectionsApiTest(TestCase):
    """
    Co-equal REST surface for discoverability (kb-k2ds.3 acceptance (2)) and
    enable-promotion (acceptance (1)/(4)).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="conn_api_user", email="conn_api_user@test.com", password="x")
        self.profile = _make_profile(name="Conn Api Profile", slug="conn-api-profile", user=self.user)
        self.conn = _make_connection(self.profile, kinds=[], enabled=False, title="My Telegram Channel")
        self.token = _get_identity_token_for_user(self.user)

    def _get(self, path):
        client = Client()
        return client.get(path, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _post(self, path):
        client = Client()
        return client.post(path, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_list_connections_returns_caller_rows(self):
        """GET /api/connections/ returns the caller's own connection with id/platform/kinds/enabled."""
        response = self._get("/api/connections/")
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertEqual(row["id"], self.conn.pk)
        self.assertEqual(row["platform"], "telegram")
        self.assertEqual(row["destination_id"], "tg-channel")
        self.assertEqual(row["title"], "My Telegram Channel")
        self.assertEqual(row["kinds"], [])
        self.assertFalse(row["enabled"])

    def test_list_connections_excludes_other_users_connections(self):
        """A second organizer's connection never leaks into this caller's list (no cross-tenant leak)."""
        other_user = _make_vouched_user(
            username="other_conn_user", email="other_conn_user@test.com", password="x"
        )
        other_profile = _make_profile(name="Other Conn Profile", slug="other-conn-profile", user=other_user)
        _make_connection(other_profile, destination_id="other-tg-channel")

        response = self._get("/api/connections/")
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], self.conn.pk)

    def test_list_connections_unauthenticated_401(self):
        """GET /api/connections/ without any auth token → 401."""
        client = Client()
        response = client.get("/api/connections/")
        self.assertEqual(response.status_code, 401)

    def test_enable_promotion_endpoint_adds_kind_and_enables(self):
        """POST /api/connections/{id}/enable-promotion/ adds 'promotion' + enabled=True, returns 200."""
        response = self._post(f"/api/connections/{self.conn.pk}/enable-promotion/")
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertIn("promotion", data["kinds"])
        self.assertTrue(data["enabled"])

        self.conn.refresh_from_db()
        self.assertIn("promotion", self.conn.kinds)
        self.assertTrue(self.conn.enabled)

    def test_enable_promotion_endpoint_idempotent(self):
        """Re-POSTing enable-promotion for the same connection returns 200 without duplicating kinds."""
        self._post(f"/api/connections/{self.conn.pk}/enable-promotion/")
        response = self._post(f"/api/connections/{self.conn.pk}/enable-promotion/")

        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertEqual(data["kinds"].count("promotion"), 1)

    def test_enable_promotion_endpoint_unknown_connection_404s(self):
        """POST enable-promotion on an unknown connection id fails loud with 404 (ADR-008 D3)."""
        response = self._post("/api/connections/999999/enable-promotion/")
        self.assertEqual(response.status_code, 404)

    def test_enable_promotion_endpoint_other_users_connection_404s(self):
        """POST enable-promotion on another organizer's connection 404s (no cross-tenant mutation)."""
        other_user = _make_vouched_user(
            username="other_enable_user", email="other_enable_user@test.com", password="x"
        )
        other_profile = _make_profile(name="Other Enable Profile", slug="other-enable-profile", user=other_user)
        other_conn = _make_connection(other_profile, destination_id="other-tg-2")

        response = self._post(f"/api/connections/{other_conn.pk}/enable-promotion/")
        self.assertEqual(response.status_code, 404)

        other_conn.refresh_from_db()
        self.assertNotIn("promotion", other_conn.kinds or [])

    def test_enable_promotion_endpoint_incapable_platform_400s(self):
        """POST enable-promotion on a 'switch' connection fails loud with 400 (platform-capability gate)."""
        switch_conn = _make_connection(self.profile, platform="switch", destination_id="own-page", enabled=True)

        response = self._post(f"/api/connections/{switch_conn.pk}/enable-promotion/")
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertTrue(len(data.get("detail", "")) > 0, "response must carry a non-empty reason (ADR-008 D3)")

        switch_conn.refresh_from_db()
        self.assertNotIn("promotion", switch_conn.kinds or [])

    def test_enable_promotion_endpoint_flagged_missing_400s(self):
        """POST enable-promotion on a flagged_missing connection fails loud with 400."""
        vanished = _make_connection(self.profile, destination_id="vanished-tg", flagged_missing=True)

        response = self._post(f"/api/connections/{vanished.pk}/enable-promotion/")
        self.assertEqual(response.status_code, 400)

        vanished.refresh_from_db()
        self.assertNotIn("promotion", vanished.kinds or [])

    def test_enable_promotion_endpoint_unauthenticated_401(self):
        """POST /api/connections/{id}/enable-promotion/ without any auth token → 401."""
        client = Client()
        response = client.post(f"/api/connections/{self.conn.pk}/enable-promotion/")
        self.assertEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# 3. Fan-out proof: create_post only mints a promotion projection AFTER enable
#    (kb-k2ds.3 acceptance (3) — closes the services.py:744-746 silent no-op)
# ---------------------------------------------------------------------------


class FanOutAfterEnableTest(TestCase):
    """
    Before enabling a connection for promotion, create_post's eager fan-out
    creates NO projection for it. After enabling (service or REST), it does.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="fanout_user", email="fanout_user@test.com", password="x")
        self.profile = _make_profile(name="Fanout Profile", slug="fanout-profile", user=self.user)
        self.event = _make_event(self.profile)
        # Synced-but-not-yet-enabled Telegram connection: kinds=[] (the real
        # ru55.2 seam — synced rows land with kinds=[], promotion off).
        self.conn = _make_connection(self.profile, kinds=[], enabled=True, title="My Telegram Channel")

    def test_create_post_creates_no_projection_before_enable(self):
        from syndication.services import create_post

        post = create_post(user=self.user, event=self.event, headline="H", body="B")

        self.assertFalse(PlatformProjection.objects.filter(source_post=post, connection=self.conn).exists())

    def test_create_post_creates_projection_after_enable(self):
        from syndication.services import create_post, enable_promotion

        enable_promotion(user=self.user, connection=self.conn)

        post = create_post(user=self.user, event=self.event, headline="H", body="B")

        projection = PlatformProjection.objects.get(source_post=post, connection=self.conn)
        self.assertEqual(projection.kind, PlatformProjection.Kind.PROMOTION)
        self.assertEqual(projection.status, PlatformProjection.Status.DRAFT)

    def test_create_post_creates_projection_after_enable_via_rest_endpoint(self):
        """The REST enable-promotion action (not just the service call) unlocks fan-out."""
        from syndication.services import create_post

        token = _get_identity_token_for_user(self.user)
        client = Client()
        response = client.post(
            f"/api/connections/{self.conn.pk}/enable-promotion/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200, response.content)

        post = create_post(user=self.user, event=self.event, headline="H", body="B")

        self.assertTrue(PlatformProjection.objects.filter(source_post=post, connection=self.conn).exists())
