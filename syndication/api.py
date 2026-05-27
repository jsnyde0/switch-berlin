"""
HTTP API skeleton for Switch syndication (kb-a4u.2).

Django Ninja API per ADR-016 D6 (in-process handlers → JSON API + HTMX views
share ONE auth + service layer).

Auth chain (ADR-016 D3):
  Leg 1: POST /api/agents/register  (session auth)     → long-lived Bearer API key
  Leg 2: POST /api/agents/token     (no auth required) → short-lived (~1h) identity token
  Leg 3: POST /api/agents/verify    (STUBBED — ADR-008 D2)

Token lifecycle (kb-a4u.2 fix):
  - Bearer API key (AgentCredential) is LONG-LIVED + reusable for many exchanges.
    "Displayed once" = raw key shown once at registration, stored hashed. Revoke
    via enabled=False.
  - Identity token is ~1h TTL + REUSABLE within that window. Expiry enforced;
    no per-request consumption.

Protected endpoints use IdentityTokenAuth (HttpBearer subclass):
  Authorization: Bearer <identity_token_uuid>

Vouching gate (F2/F7): /api/ is in ALWAYS_PUBLIC_PREFIXES so LoginWallMiddleware
skips its vouching check. IdentityTokenAuth + SessionMarkerAuth enforce the same
invariant (vouched or staff) to avoid silent bypass (ADR-008 D3).

Actor-marker (ADR-017 D1): both session and Bearer paths resolve to the same
User with identical authority. The auth callables stamp request._actor_marker
for audit-only provenance in service-layer writes.

Event/Post/Projection endpoint bodies are STUBBED here (filled by C3/C4).
OpenAPI response schemas declared for stable contract (F4).
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

def _is_vouched(user) -> bool:
    """
    Return True if the user passes the vouching invariant.

    Mirrors LoginWallMiddleware's gate (user.status == 'vouched' or is_staff).
    This must be re-enforced in the Ninja auth callables because /api/ is in
    ALWAYS_PUBLIC_PREFIXES — the middleware skips its vouching check for /api/
    paths so that API clients get JSON 401s instead of HTML 302 redirects.
    Not enforcing it here would silently drop the invariant (ADR-008 D3).
    """
    return user.is_staff or getattr(user, "status", None) == "vouched"


class IdentityTokenAuth(HttpBearer):
    """
    Ninja auth callable for Bearer identity-token auth on protected endpoints
    (ADR-016 D3 leg 2).

    Validates the Bearer token as an IdentityToken UUID.
    Token is REUSABLE within its TTL — expiry is enforced, not single-use.

    On success (valid token + vouched user): stamps request._actor_marker =
    ACTOR_BEARER and returns user.
    On failure (invalid/expired token OR non-vouched user): returns None →
    Ninja tries next auth or returns 401.

    Vouching is enforced here (not just in middleware) because /api/ is in
    ALWAYS_PUBLIC_PREFIXES — see _is_vouched() (ADR-008 D3, F2/F7).
    """

    def authenticate(self, request, token: str):
        try:
            _it, user = IdentityToken.validate(token)
        except (IdentityToken.DoesNotExist, ValueError):
            return None
        if not _is_vouched(user):
            return None
        request._actor_marker = ACTOR_BEARER
        return user


class SessionMarkerAuth(NinjaSessionAuth):
    """
    Ninja auth callable for session auth on co-equal API endpoints (ADR-016 D6).

    The HTMX views authenticate via Django session and hit the same API
    handlers as agent clients (Bearer). Stamps request._actor_marker =
    ACTOR_SESSION so service-layer writes can record provenance.

    ADR-017 D1: identical authority — same User, same permissions.

    Vouching is enforced here (not just in middleware) because /api/ is in
    ALWAYS_PUBLIC_PREFIXES — see _is_vouched() (ADR-008 D3, F2/F7).
    """

    def authenticate(self, request, key):
        user = super().authenticate(request, key)
        if not user:
            return None
        if not _is_vouched(user):
            return None
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
    auth=SessionMarkerAuth(),
    response=RegisterResponse,
    summary="Register agent — issue one-time Bearer API key",
    description=(
        "Vouched (session) user registers an agent credential. "
        "Returns a one-time Bearer API key. Exchange it at /agents/token. "
        "C6/kb-a4u.6 owns the full browser pairing flow (ProfileClaim binding). "
        "Non-vouched users are rejected — ADR-017 D1: agent has identical authority "
        "to its user; a non-vouched user is walled, so their credential-issuance "
        "must be walled too (ADR-008 D3)."
    ),
)
def agents_register(request):
    """
    Leg 1 of the auth chain (ADR-016 D3).

    Issue a Bearer API key bound to the authenticated, VOUCHED session user.
    The raw key is returned once and never stored — store it securely.
    Vouching enforced via SessionMarkerAuth (same gate as protected endpoints).
    Actor-marker is web_session (user authenticated via Django session).
    """
    _credential, raw_key = register_agent_credential(request.auth)
    return {"api_key": raw_key}


@api.post(
    "/agents/token",
    auth=None,  # Public — API key is the credential
    response={200: TokenResponse, 401: dict},
    summary="Exchange API key for a short-lived identity token",
    description=(
        "Leg 2: validate the long-lived Bearer API key and receive a "
        "short-lived (~1h) identity token (reusable within its TTL). "
        "Pass this token as 'Authorization: Bearer <identity_token>' on "
        "protected endpoints. The API key is long-lived — reuse it for "
        "new tokens as needed."
    ),
)
def agents_token(request, body: TokenRequest):
    """
    Leg 2 of the auth chain (ADR-016 D3).

    Validates the long-lived API key (reusable; fails loud on invalid/revoked
    key per ADR-008 D3). Issues a fresh short-lived identity token (~1h TTL,
    reusable within that window).

    Vouching is enforced here (ADR-017 D1, ADR-008 D3): the credential's owning
    user must be vouched. A non-vouched user who somehow holds a credential (e.g.
    registered while vouched, then un-vouched) is rejected — agent-provisioning
    must mirror the user's wall.
    """
    try:
        identity_token, user = exchange_api_key_for_identity_token(body.api_key)
    except (AgentCredential.DoesNotExist, ValueError):
        return Status(401, {"detail": "Invalid or revoked API key."})

    if not _is_vouched(user):
        return Status(401, {"detail": "User is not vouched."})

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
    response=StubListResponse,
    summary="List events — STUBBED (C3/kb-a4u.3)",
)
def events_list(request):
    """Stub — body implemented by C3/kb-a4u.3.

    Returns HttpResponse directly so X-Actor-Marker header is preserved.
    Ninja passes HttpResponse through unchanged; the declared response schema
    stabilises the OpenAPI contract for downstream beads.
    """
    return _stub_response_with_marker(
        request,
        "Event list not yet implemented (C3/kb-a4u.3).",
    )


@api.get(
    "/posts/",
    auth=_RESOURCE_AUTH,
    response=StubListResponse,
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
    response=StubListResponse,
    summary="List projections — STUBBED (C4/kb-a4u.4)",
)
def projections_list(request):
    """Stub — body implemented by C4/kb-a4u.4."""
    return _stub_response_with_marker(
        request,
        "Projection list not yet implemented (C4/kb-a4u.4).",
    )
