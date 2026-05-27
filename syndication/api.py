"""
HTTP API skeleton for Switch syndication (kb-a4u.2).

Django Ninja API per ADR-016 D6 (in-process handlers → JSON API + HTMX views
share ONE auth + service layer).

Auth chain (ADR-016 D3):
  Leg 1: POST /api/agents/register  (session auth)     → one-time Bearer API key
  Leg 2: POST /api/agents/token     (no auth required) → short-lived identity token
  Leg 3: POST /api/agents/verify    (STUBBED — ADR-008 D2)

Protected endpoints use IdentityTokenAuth (HttpBearer subclass):
  Authorization: Bearer <identity_token_uuid>

Actor-marker (ADR-017 D1): both session and Bearer paths resolve to the same
User with identical authority. The auth callables stamp request._actor_marker
for audit-only provenance in service-layer writes.

Event/Post/Projection endpoint bodies are STUBBED here (filled by C3/C4).
"""

import json as _json

from django.http import HttpResponse
from ninja import NinjaAPI, Schema, Status
from ninja.security import HttpBearer
from ninja.security import SessionAuth as NinjaSessionAuth

from syndication.models import AgentCredential, IdentityToken
from syndication.services import (
    ACTOR_BEARER,
    ACTOR_SESSION,
    exchange_api_key_for_identity_token,
    register_agent_credential,
)

# ---------------------------------------------------------------------------
# Auth callables
# ---------------------------------------------------------------------------

class IdentityTokenAuth(HttpBearer):
    """
    Ninja auth callable for Bearer identity-token auth on protected endpoints
    (ADR-016 D3 leg 2).

    Validates the Bearer token as an IdentityToken UUID.
    On success: stamps request._actor_marker = ACTOR_BEARER and returns user.
    On failure: returns None → Ninja tries next auth or returns 401.
    """

    def authenticate(self, request, token: str):
        try:
            _it, user = IdentityToken.consume(token)
            request._actor_marker = ACTOR_BEARER
            return user
        except (IdentityToken.DoesNotExist, ValueError):
            return None


class SessionMarkerAuth(NinjaSessionAuth):
    """
    Ninja auth callable for session auth on co-equal API endpoints (ADR-016 D6).

    The HTMX views authenticate via Django session and hit the same API
    handlers as agent clients (Bearer). Stamps request._actor_marker =
    ACTOR_SESSION so service-layer writes can record provenance.

    ADR-017 D1: identical authority — same User, same permissions.
    """

    def authenticate(self, request, key):
        user = super().authenticate(request, key)
        if user:
            request._actor_marker = ACTOR_SESSION
        return user


# Combined auth: identity token (agent path) OR session (HTMX/web path).
# Ninja tries each in order; first success wins.
_RESOURCE_AUTH = [IdentityTokenAuth(), SessionMarkerAuth()]


# ---------------------------------------------------------------------------
# API instantiation
# The API itself has no global auth — individual endpoints declare their own.
# /api/docs serves OpenAPI at the root (Django Ninja default).
# ---------------------------------------------------------------------------

api = NinjaAPI(
    title="Switch Syndication API",
    description=(
        "Switch v0 HTTP API — agent credential auth, Event/Post/Projection "
        "management. See ADR-016 D3 for the auth chain shape."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterResponse(Schema):
    api_key: str


class TokenRequest(Schema):
    api_key: str


class TokenResponse(Schema):
    identity_token: str
    expires_at: str


class VerifyRequest(Schema):
    token: str = ""


class VerifyResponse(Schema):
    stub: bool
    detail: str


# ---------------------------------------------------------------------------
# Agent auth endpoints
# ---------------------------------------------------------------------------

@api.post(
    "/agents/register",
    auth=NinjaSessionAuth(),
    response=RegisterResponse,
    summary="Register agent — issue one-time Bearer API key",
    description=(
        "Authenticated (session) user registers an agent credential. "
        "Returns a one-time Bearer API key. Exchange it at /agents/token. "
        "C6/kb-a4u.6 owns the full browser pairing flow (ProfileClaim binding)."
    ),
)
def agents_register(request):
    """
    Leg 1 of the auth chain (ADR-016 D3).

    Issue a one-time Bearer API key bound to the authenticated user.
    The raw key is returned once and never stored — store it securely.
    Actor-marker is web_session (user authenticated via Django session).
    """
    request._actor_marker = ACTOR_SESSION
    _credential, raw_key = register_agent_credential(request.auth)
    return {"api_key": raw_key}


@api.post(
    "/agents/token",
    auth=None,  # Public — API key is the credential
    response={200: TokenResponse, 401: dict},
    summary="Exchange API key for a short-lived identity token",
    description=(
        "Leg 2: consume the one-time Bearer API key and receive a "
        "short-lived (~1h), single-use identity token. Pass this token as "
        "'Authorization: Bearer <identity_token>' on protected endpoints."
    ),
)
def agents_token(request, body: TokenRequest):
    """
    Leg 2 of the auth chain (ADR-016 D3).

    Consumes the one-time API key (single-use; fails loud on re-use per
    ADR-008 D3). Returns a short-lived identity token (~1h, single-use).
    """
    try:
        identity_token, _user = exchange_api_key_for_identity_token(body.api_key)
    except (AgentCredential.DoesNotExist, ValueError):
        return Status(401, {"detail": "Invalid or already-consumed API key."})

    return {
        "identity_token": str(identity_token.token),
        "expires_at": identity_token.expires_at.isoformat(),
    }


@api.post(
    "/agents/verify",
    auth=None,
    response=VerifyResponse,
    summary="Verify identity token — STUBBED (ADR-008 D2)",
    description=(
        "Leg 3: third-party validation of a Switch identity token. "
        "v0 has no external consumer — stubbed per ADR-008 D2. "
        "The endpoint surface is named now; implementation ships when "
        "an external consumer exists."
    ),
)
def agents_verify(request, body: VerifyRequest):
    """
    Leg 3 stub (ADR-016 D3 + ADR-008 D2).

    No v0 consumer — facilitator's own agent calls Switch directly;
    Switch verifies its own tokens. Stub returns deterministically.
    """
    return {
        "stub": True,
        "detail": (
            "verify-identity is stubbed at v0 (ADR-008 D2). No external consumer yet."
        ),
    }


# ---------------------------------------------------------------------------
# Protected resource stubs (bodies filled by C3/C4 — kb-a4u.3/.4)
# ---------------------------------------------------------------------------
# These endpoints define the OpenAPI surface so downstream beads have a
# stable route to implement against. Auth is enforced; bodies are minimal stubs.
# The service-layer seam (syndication.services) is where persistence logic
# will live — do not add persistence directly to handlers here.

class StubListResponse(Schema):
    stub: bool
    detail: str


def _stub_response_with_marker(request, detail: str) -> HttpResponse:
    """
    Build a JSON stub response and attach X-Actor-Marker header (audit-only).

    Returns an HttpResponse directly — Ninja passes through HttpResponse objects
    unchanged, so the header survives routing.
    """
    marker = getattr(request, "_actor_marker", ACTOR_SESSION)
    body = _json.dumps({"stub": True, "detail": detail})
    response = HttpResponse(body, content_type="application/json", status=200)
    response["X-Actor-Marker"] = marker
    return response


@api.get(
    "/events/",
    auth=_RESOURCE_AUTH,
    summary="List events — STUBBED (C3/kb-a4u.3)",
)
def events_list(request):
    """Stub — body implemented by C3/kb-a4u.3.

    Returns HttpResponse directly so X-Actor-Marker header is preserved.
    """
    return _stub_response_with_marker(
        request,
        "Event list not yet implemented (C3/kb-a4u.3).",
    )


@api.get(
    "/posts/",
    auth=_RESOURCE_AUTH,
    summary="List posts — STUBBED (C3/kb-a4u.3)",
)
def posts_list(request):
    """Stub — body implemented by C3/kb-a4u.3."""
    return _stub_response_with_marker(
        request,
        "Post list not yet implemented (C3/kb-a4u.3).",
    )


@api.get(
    "/projections/",
    auth=_RESOURCE_AUTH,
    summary="List projections — STUBBED (C4/kb-a4u.4)",
)
def projections_list(request):
    """Stub — body implemented by C4/kb-a4u.4."""
    return _stub_response_with_marker(
        request,
        "Projection list not yet implemented (C4/kb-a4u.4).",
    )
