"""
TDD tests for the HTTP API skeleton (kb-a4u.2).

Tests assert:
- /api/docs serves the OpenAPI schema (200).
- Unauthenticated request to a protected endpoint → 401.
- agents/register endpoint returns a Bearer API key (displayed once, long-lived).
- identity-token-exchange: valid Bearer key → short-lived identity token.
- Identity token is REUSABLE within its TTL (multi-call case).
- Protected endpoint with valid identity token → 200.
- verify-identity endpoint exists but is stubbed (200 with stub body).
- Actor-marker recorded on writes (session vs Bearer provenance).
- Bearer key is LONG-LIVED and can be exchanged multiple times (F1/F3).
- Expired identity token is rejected (F8).
- Non-vouched authenticated user is rejected on protected endpoint (F2/F7 + F8).
- Malformed/tampered token rejected (F8).

Per harness target (kb-a4u.2): pytest on auth-rejection/acceptance +
Django test-client GET asserting OpenAPI schema response.
"""

import json
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

User = get_user_model()


def _make_vouched_user(**kwargs):
    """Create a user with status='vouched' (required for protected endpoints)."""
    return User.objects.create_user(status="vouched", **kwargs)


def _make_open_user(**kwargs):
    """Create a user with default status='open' (not vouched)."""
    return User.objects.create_user(**kwargs)


class OpenAPIDocsTest(TestCase):
    """OpenAPI/JSON-schema docs served at /api/docs."""

    def test_openapi_docs_returns_200(self):
        """GET /api/docs should return 200 with OpenAPI schema content."""
        client = Client()
        response = client.get("/api/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_schema_json_returns_200(self):
        """GET /api/openapi.json should return a JSON schema with openapi key."""
        client = Client()
        response = client.get("/api/openapi.json")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("openapi", data)
        self.assertIn("paths", data)


class UnauthenticatedRejectionTest(TestCase):
    """Unauthenticated request to a protected endpoint → 401."""

    def test_protected_endpoint_rejects_unauthenticated(self):
        """GET /api/events/ without any auth token → 401."""
        client = Client()
        response = client.get("/api/events/")
        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_rejects_invalid_identity_token(self):
        """GET /api/events/ with an invalid/expired identity token → 401."""
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        self.assertEqual(response.status_code, 401)


class AgentRegisterTest(TestCase):
    """agents/register: returns a Bearer API key (long-lived, displayed once)."""

    def setUp(self):
        # register endpoint uses NinjaSessionAuth directly (no vouching gate here)
        self.user = _make_vouched_user(
            username="agent_user",
            email="agent@example.com",
            password="testpass123",
        )

    def test_register_returns_api_key(self):
        """POST /api/agents/register (authenticated user) → returns api_key."""
        client = Client()
        client.force_login(self.user)
        response = client.post("/api/agents/register")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("api_key", data)
        self.assertTrue(len(data["api_key"]) > 20)

    def test_register_unauthenticated_rejected(self):
        """POST /api/agents/register without session auth → 401."""
        client = Client()
        response = client.post("/api/agents/register")
        self.assertEqual(response.status_code, 401)

    def test_register_creates_agent_credential(self):
        """Registering creates an AgentCredential record in DB."""
        from syndication.models import AgentCredential

        client = Client()
        client.force_login(self.user)
        client.post("/api/agents/register")
        self.assertEqual(AgentCredential.objects.filter(user=self.user).count(), 1)

    def test_bearer_key_can_be_exchanged_multiple_times(self):
        """
        F1/F3: The Bearer API key is LONG-LIVED and reusable for many exchanges.
        'One-time' means displayed-once-on-register (raw key), NOT single-use semantics.
        """
        client = Client()
        client.force_login(self.user)
        reg_response = client.post("/api/agents/register")
        api_key = json.loads(reg_response.content)["api_key"]

        # Exchange first time — should work
        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        self.assertEqual(ex_response.status_code, 200, "First exchange should succeed")

        # Exchange again — MUST also work (long-lived key)
        ex_response2 = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        self.assertEqual(ex_response2.status_code, 200, "Second exchange must also succeed (long-lived key)")

    def test_third_exchange_also_succeeds(self):
        """
        F1: Bearer key is long-lived — three exchanges all succeed (belt-and-suspenders).
        """
        client = Client()
        client.force_login(self.user)
        reg_response = client.post("/api/agents/register")
        api_key = json.loads(reg_response.content)["api_key"]

        for i in range(3):
            ex_response = client.post(
                "/api/agents/token",
                data=json.dumps({"api_key": api_key}),
                content_type="application/json",
            )
            self.assertEqual(ex_response.status_code, 200, f"Exchange {i+1} must succeed")


class IdentityTokenExchangeTest(TestCase):
    """Bearer API key → short-lived identity token exchange."""

    def setUp(self):
        self.user = _make_vouched_user(
            username="exchange_user",
            email="exchange@example.com",
            password="testpass123",
        )

    def _register_and_get_api_key(self):
        client = Client()
        client.force_login(self.user)
        reg_response = client.post("/api/agents/register")
        return json.loads(reg_response.content)["api_key"]

    def test_valid_api_key_returns_identity_token(self):
        """POST /api/agents/token with valid api_key → identity_token."""
        api_key = self._register_and_get_api_key()
        client = Client()
        response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("identity_token", data)
        self.assertIn("expires_at", data)

    def test_invalid_api_key_rejected(self):
        """POST /api/agents/token with invalid api_key → 401."""
        client = Client()
        response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": "not-a-real-key"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_identity_token_grants_access_to_protected_endpoint(self):
        """After exchange, identity token allows access to a protected endpoint."""
        api_key = self._register_and_get_api_key()
        client = Client()

        # Exchange for identity token
        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        identity_token = json.loads(ex_response.content)["identity_token"]

        # Use identity token on protected endpoint
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {identity_token}",
        )
        self.assertEqual(response.status_code, 200)

    def test_identity_token_is_reusable_within_ttl(self):
        """
        F3: The SAME identity token is valid on a SECOND call within its TTL.
        A 1h TTL is meaningless if the token dies after one request.
        """
        api_key = self._register_and_get_api_key()
        client = Client()

        # Get identity token
        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        identity_token = json.loads(ex_response.content)["identity_token"]

        # Use it once
        response1 = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {identity_token}",
        )
        self.assertEqual(response1.status_code, 200, "First use should succeed")

        # Use the SAME token again — must still work within TTL
        response2 = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {identity_token}",
        )
        self.assertEqual(response2.status_code, 200, "Second use of same token within TTL must succeed")

    def test_identity_token_reusable_for_multiple_endpoints(self):
        """
        F3: Same identity token can be used across different endpoints within TTL.
        """
        api_key = self._register_and_get_api_key()
        client = Client()

        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        identity_token = json.loads(ex_response.content)["identity_token"]

        for endpoint in ["/api/events/", "/api/posts/", "/api/projections/"]:
            response = client.get(
                endpoint,
                HTTP_AUTHORIZATION=f"Bearer {identity_token}",
            )
            self.assertEqual(response.status_code, 200, f"{endpoint} should accept token")


class VerifyIdentityStubTest(TestCase):
    """verify-identity endpoint: present but stubbed (ADR-008 D2)."""

    def test_verify_identity_endpoint_exists(self):
        """GET /api/agents/verify returns 200 with stub body (no consumer at v0)."""
        client = Client()
        response = client.post("/api/agents/verify", content_type="application/json")
        # Stub: present, not 404. Body is minimal.
        self.assertNotEqual(response.status_code, 404)

    def test_verify_identity_stub_body(self):
        """verify-identity stub response includes a 'stub' indicator."""
        client = Client()
        response = client.post("/api/agents/verify", content_type="application/json")
        data = json.loads(response.content)
        self.assertIn("stub", data)


class ActorMarkerTest(TestCase):
    """Actor-marker: write requests carry provenance (session vs Bearer)."""

    def setUp(self):
        self.user = _make_vouched_user(
            username="marker_user",
            email="marker@example.com",
            password="testpass123",
        )

    def _get_identity_token(self):
        client = Client()
        client.force_login(self.user)
        reg_response = client.post("/api/agents/register")
        api_key = json.loads(reg_response.content)["api_key"]
        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        return json.loads(ex_response.content)["identity_token"]

    def test_bearer_auth_sets_actor_marker_bearer(self):
        """A request authenticated via identity token carries actor='agent_bearer'."""
        identity_token = self._get_identity_token()
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {identity_token}",
        )
        self.assertEqual(response.status_code, 200)
        # Actor marker is embedded in the response (X-Actor-Marker header)
        self.assertEqual(response.get("X-Actor-Marker"), "agent_bearer")

    def test_session_auth_sets_actor_marker_session(self):
        """A request authenticated via Django session carries actor='web_session'."""
        client = Client()
        client.force_login(self.user)
        response = client.get("/api/events/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get("X-Actor-Marker"), "web_session")


class StubEndpointSurfaceTest(TestCase):
    """Event, Post, Projection endpoint routes exist (bodies stubbed for C3/C4)."""

    def setUp(self):
        self.user = _make_vouched_user(
            username="stub_user",
            email="stub@example.com",
            password="testpass123",
        )

    def _get_identity_token(self):
        client = Client()
        client.force_login(self.user)
        reg_response = client.post("/api/agents/register")
        api_key = json.loads(reg_response.content)["api_key"]
        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        return json.loads(ex_response.content)["identity_token"]

    def test_events_list_stub_endpoint_exists(self):
        """GET /api/events/ returns 200 (stubbed body) with valid identity token."""
        token = self._get_identity_token()
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertNotEqual(response.status_code, 404)

    def test_posts_list_stub_endpoint_exists(self):
        """GET /api/posts/ returns non-404 (stubbed body) with valid identity token."""
        token = self._get_identity_token()
        client = Client()
        response = client.get(
            "/api/posts/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertNotEqual(response.status_code, 404)

    def test_projections_list_stub_endpoint_exists(self):
        """GET /api/projections/ returns non-404 (stubbed body) with valid identity token."""
        token = self._get_identity_token()
        client = Client()
        response = client.get(
            "/api/projections/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertNotEqual(response.status_code, 404)

    def test_stub_endpoints_return_schema_with_stub_field(self):
        """
        F4: Stub endpoints return a declared Ninja response schema (stub + detail fields).
        The OpenAPI contract must be stable for downstream beads.
        """
        token = self._get_identity_token()
        client = Client()
        for endpoint in ["/api/events/", "/api/posts/", "/api/projections/"]:
            response = client.get(
                endpoint,
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
            self.assertEqual(response.status_code, 200, f"{endpoint} should return 200")
            data = json.loads(response.content)
            self.assertIn("stub", data, f"{endpoint} response must have 'stub' field")
            self.assertIn("detail", data, f"{endpoint} response must have 'detail' field")


class TokenNegativeTests(TestCase):
    """
    F8: Negative tests for token lifecycle.
    - Expired identity token is rejected.
    - Non-vouched authenticated user is rejected on protected endpoint.
    - Malformed/tampered token rejected.
    """

    def setUp(self):
        self.vouched_user = _make_vouched_user(
            username="neg_vouched_user",
            email="neg_vouched@example.com",
            password="testpass123",
        )
        self.open_user = _make_open_user(
            username="neg_open_user",
            email="neg_open@example.com",
            password="testpass123",
        )

    def _get_api_key(self, user):
        """Register and return an API key for a given user (session auth)."""
        client = Client()
        client.force_login(user)
        reg_response = client.post("/api/agents/register")
        return json.loads(reg_response.content)["api_key"]

    def test_expired_identity_token_rejected(self):
        """
        F8: An identity token past its expires_at timestamp is rejected (401).
        """
        from syndication.models import IdentityToken

        # Issue a token that is already expired
        expired_token = IdentityToken.objects.create(
            user=self.vouched_user,
            expires_at=timezone.now() - timezone.timedelta(seconds=1),
        )
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {expired_token.token}",
        )
        self.assertEqual(response.status_code, 401, "Expired identity token must be rejected")

    def test_malformed_token_rejected(self):
        """
        F8: A malformed (non-UUID) Bearer token is rejected (401).
        """
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION="Bearer not-a-valid-uuid-at-all",
        )
        self.assertEqual(response.status_code, 401, "Malformed token must be rejected")

    def test_tampered_uuid_token_rejected(self):
        """
        F8: A syntactically valid UUID that doesn't match any token is rejected (401).
        """
        client = Client()
        fake_token = str(uuid.uuid4())
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {fake_token}",
        )
        self.assertEqual(response.status_code, 401, "Tampered/nonexistent token must be rejected")

    def test_non_vouched_user_rejected_on_bearer_protected_endpoint(self):
        """
        F2/F7/F8: A non-vouched (status='open') user whose token is otherwise valid
        is rejected (401) on a protected endpoint. The vouching invariant must be
        enforced by the auth callable, not just the middleware (since /api/ is in
        ALWAYS_PUBLIC_PREFIXES and bypasses LoginWallMiddleware's vouching gate).
        """
        from syndication.models import IdentityToken

        # Issue a fresh, unexpired identity token for a non-vouched user
        valid_token = IdentityToken.objects.create(
            user=self.open_user,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {valid_token.token}",
        )
        self.assertEqual(
            response.status_code,
            401,
            "Non-vouched user must be rejected even with a valid (unexpired) identity token",
        )

    def test_non_vouched_user_rejected_on_session_protected_endpoint(self):
        """
        F2/F7/F8: A non-vouched (status='open') user authenticated via session is
        rejected (401) on a protected endpoint. SessionMarkerAuth must enforce vouching.
        """
        client = Client()
        client.force_login(self.open_user)
        response = client.get("/api/events/")
        self.assertEqual(
            response.status_code,
            401,
            "Non-vouched session user must be rejected on protected endpoint",
        )

    def test_vouched_user_accepted_on_protected_endpoint(self):
        """Positive control: vouched user with valid token IS accepted."""
        from syndication.models import IdentityToken

        valid_token = IdentityToken.objects.create(
            user=self.vouched_user,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {valid_token.token}",
        )
        self.assertEqual(response.status_code, 200, "Vouched user must be accepted")
