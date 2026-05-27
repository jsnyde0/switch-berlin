"""
Syndication service layer (kb-a4u.2, ADR-016 D6).

Per ADR-016 D6: the API handlers and HTMX views share ONE auth + service
layer. Persistence logic lives here, not in the Ninja handlers, so the
co-equal-API test (kb-a4u.9) can assert both surfaces hit identical
persistence + auth.

Actor-marker (ADR-017 D1): agent (Bearer) and web (session) have identical
authority — they both resolve to the same User. The actor_marker string is
audit-only provenance for the generated_by / provenance projection fields.
"""

from django.http import HttpRequest

from syndication.models import AgentCredential, IdentityToken

# ---------------------------------------------------------------------------
# Actor-marker (ADR-017 D1)
# ---------------------------------------------------------------------------

ACTOR_SESSION = "web_session"
ACTOR_BEARER = "agent_bearer"


def get_actor_marker(request: HttpRequest) -> str:
    """
    Return the actor-marker string for this request.

    'agent_bearer' if authenticated via identity token (Bearer auth);
    'web_session' if authenticated via Django session.

    The marker is set on request by the Ninja auth callables and read here
    for use in service-layer writes (provenance, generated_by).
    """
    return getattr(request, "_actor_marker", ACTOR_SESSION)


# ---------------------------------------------------------------------------
# Agent registration service
# ---------------------------------------------------------------------------

def register_agent_credential(user):
    """
    Issue a new AgentCredential for user.

    Returns (credential, raw_key). The caller MUST return raw_key to the
    user exactly once — it is never stored and cannot be recovered.
    """
    return AgentCredential.issue(user)


# ---------------------------------------------------------------------------
# Identity token exchange service
# ---------------------------------------------------------------------------

def exchange_api_key_for_identity_token(raw_api_key: str):
    """
    Consume a one-use Bearer API key and issue a short-lived identity token.

    Returns (identity_token, user) on success.
    Raises AgentCredential.DoesNotExist or ValueError on failure (fail loud
    per ADR-008 D3 — no silent fallback).
    """
    credential, user = AgentCredential.consume(raw_api_key)
    identity_token = IdentityToken.issue(user)
    return identity_token, user


# ---------------------------------------------------------------------------
# Identity token validation (used by Ninja auth callable)
# ---------------------------------------------------------------------------

def validate_identity_token(raw_token: str):
    """
    Validate and consume an identity token.

    Returns (identity_token, user) on success.
    Raises IdentityToken.DoesNotExist or ValueError on failure.
    """
    return IdentityToken.consume(raw_token)
