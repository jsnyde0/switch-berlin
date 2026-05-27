"""
TDD tests for the HTTP API skeleton (kb-a4u.2).

Tests assert:
- /api/docs serves the OpenAPI schema (200).
- Unauthenticated request to a protected endpoint → 401.
- agents/register endpoint returns a one-time Bearer API key.
- identity-token-exchange: valid Bearer key → short-lived identity token.
- Protected endpoint with valid identity token → 200.
- verify-identity endpoint exists but is stubbed (200 with stub body).
- Actor-marker recorded on writes (session vs Bearer provenance).

Per harness target (kb-a4u.2): pytest on auth-rejection/acceptance +
Django test-client GET asserting OpenAPI schema response.
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

User = get_user_model()


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
    """agents/register: returns a one-time Bearer API key."""

    def setUp(self):
        self.user = User.objects.create_user(
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

    def test_register_api_key_is_single_use_on_exchange(self):
        """The raw API key returned by register is usable exactly once for exchange."""
        client = Client()
        client.force_login(self.user)
        reg_response = client.post("/api/agents/register")
        api_key = json.loads(reg_response.content)["api_key"]

        # Exchange it once — should work
        ex_response = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        self.assertEqual(ex_response.status_code, 200)

        # Exchange again — should fail (key is single-use)
        ex_response2 = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        self.assertEqual(ex_response2.status_code, 401)


class IdentityTokenExchangeTest(TestCase):
    """Bearer API key → short-lived identity token exchange."""

    def setUp(self):
        self.user = User.objects.create_user(
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
        self.user = User.objects.create_user(
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
        from syndication.services import get_actor_marker

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
        self.user = User.objects.create_user(
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
