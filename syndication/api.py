"""
HTTP API for Switch syndication (kb-a4u.2 skeleton + kb-a4u.3 Event/Post CRUD).

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

Co-equal seam (ADR-016 D3/D6): Event/Post CRUD handlers call the same
syndication.services functions as the HTMX web views — no parallel implementations.
"""

import json as _json
import logging
from datetime import datetime
from typing import List, Optional

from django.http import HttpResponse
from ninja import File, NinjaAPI, Schema, Status
from ninja.files import UploadedFile
from ninja.security import HttpBearer
from ninja.security import SessionAuth as NinjaSessionAuth

from syndication.models import AgentCredential, IdentityToken
from syndication.services import (
    ACTOR_BEARER,
    ACTOR_SESSION,
    create_event,
    create_post,
    exchange_api_key_for_identity_token,
    redeem_pairing_token,
    register_agent_credential,
    set_event_cover,
    update_event,
    update_post,
    approve_projection,
    publish_projection,
    mark_projection_published,
    publish_all_ready_projections,
    _resolve_projection_event,
)

logger = logging.getLogger(__name__)

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


@api.exception_handler(PermissionError)
def handle_permission_error(request, exc):
    """
    Map PermissionError → HTTP 403 JSON response.

    service functions (update_event, create_post, …) raise PermissionError
    when the caller fails the can_edit gate. Without this handler Ninja would
    surface a 500. ADR-008 D3: fail loud with the correct status code.

    Security: the exception message (which contains the user repr and event title)
    is logged server-side for operators but NEVER returned to the caller — that
    would leak PII / internal identifiers to unauthorized parties.
    """
    logger.warning("Permission denied: %s", exc, extra={"path": request.path})
    return api.create_response(
        request,
        {"detail": "Permission denied."},
        status=403,
    )


from django.core.exceptions import ValidationError as DjangoValidationError


@api.exception_handler(DjangoValidationError)
def handle_django_validation_error(request, exc):
    """
    Map Django's ValidationError → HTTP 422 JSON response.

    Used by the cover upload endpoint (set_event_cover calls full_clean() which
    raises django.core.exceptions.ValidationError on invalid image size or extension).
    ADR-008 D3: fail loud with the correct status code.

    Registered on DjangoValidationError specifically (not Exception) so Ninja's
    default Exception handler remains intact for genuinely unexpected exceptions.
    """
    logger.info("Validation error on upload: %s", exc)
    return api.create_response(
        request,
        {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
        status=422,
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterResponse(Schema):
    """
    Response for agents/register: returns the one-time pairing token (kb-a4u.6).

    The pairing token is shown once and handed to the agent. The agent redeems it
    at agents/redeem to receive the long-lived Bearer key. The Bearer key never
    transits the facilitator's clipboard.
    """
    pairing_token: str


class RedeemRequest(Schema):
    pairing_token: str


class RedeemResponse(Schema):
    """
    Response for agents/redeem: returns the long-lived Bearer API key.

    The agent redeems the one-time pairing token to receive the Bearer key.
    The Bearer key is long-lived and reusable for many identity-token exchanges.
    It is shown once and never stored in plaintext.
    """
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
    summary="Register agent — issue one-time pairing token (kb-a4u.6)",
    description=(
        "Vouched (session) facilitator starts agent-pairing: mints a SHORT-LIVED, "
        "SINGLE-USE pairing token. The facilitator shows this token to their agent. "
        "The agent redeems the pairing token at /agents/redeem to receive the "
        "long-lived Bearer API key. The Bearer key NEVER transits the facilitator's "
        "clipboard — only the agent ever holds it (kb-a4u.6 v0 decided mechanic). "
        "Non-vouched users are rejected — ADR-017 D1: agent has identical authority "
        "to its user; a non-vouched user is walled, so their credential-issuance "
        "must be walled too (ADR-008 D3)."
    ),
)
def agents_register(request):
    """
    Leg 1 of the pairing flow (kb-a4u.6, ADR-016 D3).

    Issue a short-lived, single-use pairing token for the authenticated VOUCHED
    session user. The raw pairing token is returned once and never stored.
    The facilitator hands it to their agent; the agent redeems it at /agents/redeem.
    Vouching enforced via SessionMarkerAuth (same gate as protected endpoints).
    """
    _token_record, raw_pairing_token = register_agent_credential(request.auth)
    return {"pairing_token": raw_pairing_token}


@api.post(
    "/agents/redeem",
    auth=None,  # Public — pairing token is the credential
    response={200: RedeemResponse, 400: dict, 401: dict},
    summary="Redeem pairing token — issue long-lived Bearer API key (kb-a4u.6)",
    description=(
        "Leg 1b of the pairing flow (kb-a4u.6): the agent redeems the one-time "
        "pairing token to receive the long-lived Bearer API key. "
        "The pairing token is SINGLE-USE — second redemption is rejected. "
        "The pairing token is SHORT-LIVED (~15 min) — expired token is rejected. "
        "The issued Bearer key is bound to the registering User (ADR-017 D1). "
        "Exchange the Bearer key at /agents/token to receive a short-lived identity token."
    ),
)
def agents_redeem(request, body: RedeemRequest):
    """
    Leg 1b of the pairing flow (kb-a4u.6).

    Agent redeems the one-time pairing token and receives the long-lived Bearer key.
    The Bearer key is bound to the registering facilitator User (ADR-017 D1).

    Fail loud (ADR-008 D3):
    - Invalid/unknown pairing token → 401
    - Expired pairing token → 400
    - Already-used pairing token → 400
    """
    from syndication.models import AgentPairingToken
    try:
        _credential, raw_key = redeem_pairing_token(body.pairing_token)
    except AgentPairingToken.DoesNotExist:
        logger.warning("agents/redeem: invalid pairing token (DoesNotExist)")
        return Status(401, {"detail": "Invalid pairing token."})
    except ValueError as exc:
        # Log specific reason server-side but return generic message to caller
        # (avoids enumeration oracle distinguishing used vs. expired — finding #4).
        logger.warning("agents/redeem: pairing token rejected: %s", exc)
        return Status(400, {"detail": "Invalid pairing token."})
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
# Protected resource endpoints (kb-a4u.3 — Event + Post CRUD)
# Co-equal seam: these handlers call the same service functions as HTMX views.
# ---------------------------------------------------------------------------


def _actor_marker_response(request, data: dict, status: int = 200) -> HttpResponse:
    """
    Build a JSON response and attach X-Actor-Marker header (audit-only).

    Returns an HttpResponse directly — Ninja passes through HttpResponse objects
    unchanged, so the header survives routing.
    """
    marker = getattr(request, "_actor_marker", ACTOR_SESSION)
    body = _json.dumps(data, default=str)
    response = HttpResponse(body, content_type="application/json", status=status)
    response["X-Actor-Marker"] = marker
    return response


# --- Event schemas ---

class EventCreateIn(Schema):
    title: str
    slug: str
    start: datetime
    end: Optional[datetime] = None
    description: str = ""
    dress_code: str = ""
    content_warnings: List[str] = []
    age_restriction: Optional[int] = None
    capacity: Optional[int] = None
    visibility: str = "public"
    language: str = ""
    is_free: bool = False
    price_min_cents: Optional[int] = None
    price_max_cents: Optional[int] = None
    currency: str = "EUR"
    sliding_scale: bool = False
    price_description: str = ""
    external_url: str = ""
    tickets_url: str = ""
    registration_required: bool = False
    registration_url: str = ""
    registration_email: str = ""
    category: str = ""


class EventUpdateIn(Schema):
    """
    Partial-update schema for PATCH /events/{id}/.

    All fields are optional (PATCH semantics — only non-None fields are applied).
    Kept at parity with EventCreateIn for the full updatable set (ADR-016 D3:
    co-equal API — an agent must be able to read back what it wrote).
    """
    title: Optional[str] = None
    slug: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    description: Optional[str] = None
    dress_code: Optional[str] = None
    content_warnings: Optional[List[str]] = None
    age_restriction: Optional[int] = None
    capacity: Optional[int] = None
    visibility: Optional[str] = None
    language: Optional[str] = None
    is_free: Optional[bool] = None
    price_min_cents: Optional[int] = None
    price_max_cents: Optional[int] = None
    currency: Optional[str] = None
    sliding_scale: Optional[bool] = None
    price_description: Optional[str] = None
    external_url: Optional[str] = None
    tickets_url: Optional[str] = None
    registration_required: Optional[bool] = None
    registration_url: Optional[str] = None
    registration_email: Optional[str] = None
    category: Optional[str] = None


class EventOut(Schema):
    """
    Response schema for Event endpoints (ADR-016 D3: co-equal API).

    Includes the full v0 readable field set so an agent can read back what
    it wrote (start, end, slug, registration_* were previously missing).
    """
    id: int
    title: str
    slug: str
    start: Optional[datetime]
    end: Optional[datetime]
    description: str
    status: str
    visibility: str
    dress_code: str
    content_warnings: List[str]
    age_restriction: Optional[int]
    capacity: Optional[int]
    language: str
    is_free: bool
    price_min_cents: Optional[int]
    price_max_cents: Optional[int]
    currency: str
    sliding_scale: bool
    price_description: str
    external_url: str
    tickets_url: str
    registration_required: bool
    registration_url: str
    registration_email: str
    category: str


# --- Post schemas ---

class PostCreateIn(Schema):
    headline: str
    body: str
    cta: str = ""
    voice: str = ""
    imagery: Optional[List[str]] = None


class PostUpdateIn(Schema):
    headline: Optional[str] = None
    body: Optional[str] = None
    cta: Optional[str] = None
    voice: Optional[str] = None


class PostOut(Schema):
    id: int
    event_id: int
    headline: str
    body: str
    cta: str
    voice: str


# --- Stub schema preserved for projections list (C4) ---

class StubListResponse(Schema):
    stub: bool
    detail: str


def _stub_response_with_marker(request, detail: str) -> HttpResponse:
    """
    Build a JSON stub response and attach X-Actor-Marker header (audit-only).
    """
    return _actor_marker_response(
        request, {"stub": True, "detail": detail}, status=200
    )


# ---------------------------------------------------------------------------
# Event CRUD endpoints
# ---------------------------------------------------------------------------

@api.get(
    "/events/",
    auth=_RESOURCE_AUTH,
    response=List[EventOut],
    summary="List events for authenticated user",
)
def events_list(request):
    """
    List all Events where the authenticated user is an EventOrganizer claimant.
    Returns HttpResponse directly so X-Actor-Marker header is preserved.
    """
    from events.models import Event, EventOrganizer
    from organizers.models import ProfileClaim

    # Get profile IDs this user has active claims on
    profile_ids = ProfileClaim.objects.filter(
        user=request.auth, rejected_at__isnull=True
    ).values_list("profile_id", flat=True)

    # Get event IDs where those profiles are organizers
    event_ids = EventOrganizer.objects.filter(
        profile_id__in=profile_ids
    ).values_list("event_id", flat=True)

    events = Event.objects.filter(pk__in=event_ids).order_by("-start")
    data = [
        {
            "id": e.pk,
            "title": e.title,
            "slug": e.slug,
            "start": e.start,
            "end": e.end,
            "description": e.description,
            "status": e.status,
            "visibility": e.visibility,
            "dress_code": e.dress_code,
            "content_warnings": e.content_warnings or [],
            "age_restriction": e.age_restriction,
            "capacity": e.capacity,
            "language": e.language,
            "is_free": e.is_free,
            "price_min_cents": e.price_min_cents,
            "price_max_cents": e.price_max_cents,
            "currency": e.currency,
            "sliding_scale": e.sliding_scale,
            "price_description": e.price_description,
            "external_url": e.external_url,
            "tickets_url": e.tickets_url,
            "registration_required": e.registration_required,
            "registration_url": e.registration_url,
            "registration_email": e.registration_email,
            "category": e.category,
        }
        for e in events
    ]
    return _actor_marker_response(request, data)


@api.post(
    "/events/",
    auth=_RESOURCE_AUTH,
    response={201: EventOut},
    summary="Create a new Event",
)
def events_create(request, body: EventCreateIn):
    """
    Create a new Event via the service layer (co-equal with web form path).
    Auth: identity token (agent) or session (web). ADR-016 D3/D6.
    Eager-creates draft listing projections per enabled listing-capable connection
    (ADR-016 D4).
    """
    kwargs = body.dict(exclude_none=False)
    event = create_event(user=request.auth, **kwargs)
    data = {
        "id": event.pk,
        "title": event.title,
        "slug": event.slug,
        "start": event.start,
        "end": event.end,
        "description": event.description,
        "status": event.status,
        "visibility": event.visibility,
        "dress_code": event.dress_code,
        "content_warnings": event.content_warnings or [],
        "age_restriction": event.age_restriction,
        "capacity": event.capacity,
        "language": event.language,
        "is_free": event.is_free,
        "price_min_cents": event.price_min_cents,
        "price_max_cents": event.price_max_cents,
        "currency": event.currency,
        "sliding_scale": event.sliding_scale,
        "price_description": event.price_description,
        "external_url": event.external_url,
        "tickets_url": event.tickets_url,
        "registration_required": event.registration_required,
        "registration_url": event.registration_url,
        "registration_email": event.registration_email,
        "category": event.category,
    }
    return _actor_marker_response(request, data, status=201)


@api.get(
    "/events/{event_id}/",
    auth=_RESOURCE_AUTH,
    response=EventOut,
    summary="Get Event detail",
)
def events_detail(request, event_id: int):
    """Get a single Event by ID (ownership-gated, finding #2 — same authz as PATCH)."""
    from django.shortcuts import get_object_or_404
    from events.models import Event
    from syndication.authz import can_edit
    event = get_object_or_404(Event, pk=event_id)
    if not can_edit(request.auth, event):
        # Raises PermissionError → handled by @api.exception_handler(PermissionError) → 403.
        # Same pattern as update_event/create_post service layer (ADR-008 D3, finding #2).
        raise PermissionError("Agent lacks authority over this event.")
    data = {
        "id": event.pk,
        "title": event.title,
        "slug": event.slug,
        "start": event.start,
        "end": event.end,
        "description": event.description,
        "status": event.status,
        "visibility": event.visibility,
        "dress_code": event.dress_code,
        "content_warnings": event.content_warnings or [],
        "age_restriction": event.age_restriction,
        "capacity": event.capacity,
        "language": event.language,
        "is_free": event.is_free,
        "price_min_cents": event.price_min_cents,
        "price_max_cents": event.price_max_cents,
        "currency": event.currency,
        "sliding_scale": event.sliding_scale,
        "price_description": event.price_description,
        "external_url": event.external_url,
        "tickets_url": event.tickets_url,
        "registration_required": event.registration_required,
        "registration_url": event.registration_url,
        "registration_email": event.registration_email,
        "category": event.category,
    }
    return _actor_marker_response(request, data)


@api.patch(
    "/events/{event_id}/",
    auth=_RESOURCE_AUTH,
    response=EventOut,
    summary="Update an Event (partial update)",
)
def events_update(request, event_id: int, body: EventUpdateIn):
    """
    Partially update an Event via the service layer (gated by can_edit seam).
    Only non-None fields are applied.
    """
    from django.shortcuts import get_object_or_404
    from events.models import Event
    event = get_object_or_404(Event, pk=event_id)
    # Only pass non-None fields so unset optional fields don't zero-out existing values
    patch_kwargs = {k: v for k, v in body.dict().items() if v is not None}
    event = update_event(user=request.auth, event=event, **patch_kwargs)
    data = {
        "id": event.pk,
        "title": event.title,
        "slug": event.slug,
        "start": event.start,
        "end": event.end,
        "description": event.description,
        "status": event.status,
        "visibility": event.visibility,
        "dress_code": event.dress_code,
        "content_warnings": event.content_warnings or [],
        "age_restriction": event.age_restriction,
        "capacity": event.capacity,
        "language": event.language,
        "is_free": event.is_free,
        "price_min_cents": event.price_min_cents,
        "price_max_cents": event.price_max_cents,
        "currency": event.currency,
        "sliding_scale": event.sliding_scale,
        "price_description": event.price_description,
        "external_url": event.external_url,
        "tickets_url": event.tickets_url,
        "registration_required": event.registration_required,
        "registration_url": event.registration_url,
        "registration_email": event.registration_email,
        "category": event.category,
    }
    return _actor_marker_response(request, data)


# ---------------------------------------------------------------------------
# Cover image upload endpoint (kb-a4u.19, ADR-016 D1)
# ---------------------------------------------------------------------------


class CoverUploadOut(Schema):
    id: int
    event_id: int
    is_cover: bool


@api.post(
    "/events/{event_id}/cover",
    auth=_RESOURCE_AUTH,
    response={200: CoverUploadOut},
    summary="Upload cover image for an Event",
)
def events_cover_upload(request, event_id: int, file: UploadedFile = File(...)):
    """
    Upload (or replace) the cover image for an Event.

    Accepts multipart/form-data with a single 'file' field.
    can_edit-gated (ADR-017 D2) — PermissionError → existing @api.exception_handler → 403.
    Validation: validate_image_size + FileExtensionValidator run via full_clean();
    ValidationError is mapped to 422 by the existing Django-Ninja exception handler.
    OUT OF SCOPE at v0: projection/adapter rendering of the cover image.
    """
    from django.shortcuts import get_object_or_404
    from events.models import Event

    event = get_object_or_404(Event, pk=event_id)
    img = set_event_cover(request.auth, event, file)
    return Status(200, {"id": img.pk, "event_id": event.pk, "is_cover": img.is_cover})


# ---------------------------------------------------------------------------
# Post CRUD endpoints (scoped to Event)
# ---------------------------------------------------------------------------

@api.get(
    "/events/{event_id}/posts/",
    auth=_RESOURCE_AUTH,
    response=List[PostOut],
    summary="List Posts for an Event",
)
def event_posts_list(request, event_id: int):
    """List all Posts for a given Event (ownership-gated, finding #2 — same authz as PATCH)."""
    from django.shortcuts import get_object_or_404
    from events.models import Event
    from syndication.models import Post
    from syndication.authz import can_edit
    event = get_object_or_404(Event, pk=event_id)
    if not can_edit(request.auth, event):
        # Raises PermissionError → handled by @api.exception_handler(PermissionError) → 403.
        raise PermissionError("Agent lacks authority over this event.")
    posts = Post.objects.filter(event=event).order_by("-created_at")
    data = [
        {
            "id": p.pk,
            "event_id": p.event_id,
            "headline": p.headline,
            "body": p.body,
            "cta": p.cta,
            "voice": p.voice,
        }
        for p in posts
    ]
    return _actor_marker_response(request, data)


@api.post(
    "/events/{event_id}/posts/",
    auth=_RESOURCE_AUTH,
    response={201: PostOut},
    summary="Create a Post for an Event",
)
def event_posts_create(request, event_id: int, body: PostCreateIn):
    """
    Create a Post scoped to an Event via the service layer (co-equal with web form).
    Gated by can_edit seam (ADR-017 D2).
    Eager-creates draft promotion projections per enabled promotion-capable connection
    (ADR-016 D4).
    """
    from django.shortcuts import get_object_or_404
    from events.models import Event
    event = get_object_or_404(Event, pk=event_id)
    kwargs = body.dict(exclude_none=False)
    post = create_post(user=request.auth, event=event, **kwargs)
    data = {
        "id": post.pk,
        "event_id": post.event_id,
        "headline": post.headline,
        "body": post.body,
        "cta": post.cta,
        "voice": post.voice,
    }
    return _actor_marker_response(request, data, status=201)


@api.get(
    "/posts/",
    auth=_RESOURCE_AUTH,
    response=List[PostOut],
    summary="List all Posts for authenticated user's events",
)
def posts_list(request):
    """
    List all Posts across all Events where the user is an organizer.
    Returns HttpResponse directly so X-Actor-Marker header is preserved.
    """
    from events.models import Event, EventOrganizer
    from organizers.models import ProfileClaim
    from syndication.models import Post

    profile_ids = ProfileClaim.objects.filter(
        user=request.auth, rejected_at__isnull=True
    ).values_list("profile_id", flat=True)

    event_ids = EventOrganizer.objects.filter(
        profile_id__in=profile_ids
    ).values_list("event_id", flat=True)

    posts = Post.objects.filter(event_id__in=event_ids).order_by("-created_at")
    data = [
        {
            "id": p.pk,
            "event_id": p.event_id,
            "headline": p.headline,
            "body": p.body,
            "cta": p.cta,
            "voice": p.voice,
        }
        for p in posts
    ]
    return _actor_marker_response(request, data)


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


# ---------------------------------------------------------------------------
# Projection lifecycle action endpoints (kb-a4u.5, ADR-016 D5/D6)
#
# Co-equal seam: these API handlers call the SAME service functions as
# the HTMX view actions. No duplicate logic.
# ---------------------------------------------------------------------------


class ProjectionActionOut(Schema):
    """Response for projection lifecycle actions."""
    id: int
    status: str
    provenance: str


@api.post(
    "/projections/{projection_id}/mark-published/",
    auth=_RESOURCE_AUTH,
    response={200: ProjectionActionOut},
    summary="Mark projection as published (actor-attested, out-of-band posting)",
    description=(
        "Co-equal API verb for mark-published (ADR-016 D6). "
        "Used for no-API platforms (e.g. FetLife) where the organizer posts "
        "manually then attests via this action. "
        "Calls the same mark_projection_published service function as the "
        "HTMX view button — NOT a separate implementation."
    ),
)
def api_projection_mark_published(request, projection_id: int):
    """
    Mark a projection as published (actor-attested).

    Gate: user must have publish authority (can_publish seam, ADR-017 D2).
    Delegates to mark_projection_published service (co-equal with UI path).
    Returns 403 on permission error, 400 on illegal transition.
    """
    from django.shortcuts import get_object_or_404
    from syndication.models import PlatformProjection

    projection = get_object_or_404(PlatformProjection, pk=projection_id)

    try:
        mark_projection_published(user=request.auth, projection=projection)
    except PermissionError as exc:
        logger.warning("Permission denied on mark-published: %s", exc)
        return api.create_response(request, {"detail": "Permission denied."}, status=403)
    except ValueError as exc:
        logger.warning("Illegal transition on mark-published: %s", exc)
        return api.create_response(request, {"detail": str(exc)}, status=400)

    projection.refresh_from_db()
    return _actor_marker_response(
        request,
        {
            "id": projection.pk,
            "status": projection.status,
            "provenance": projection.content_version.provenance,
        },
    )


@api.post(
    "/projections/{projection_id}/approve/",
    auth=_RESOURCE_AUTH,
    response={200: ProjectionActionOut},
    summary="Approve a draft projection (draft→ready)",
    description=(
        "Co-equal API verb for approve (ADR-016 D6). "
        "Transitions draft→ready and freezes content. "
        "Calls approve_projection service (co-equal with HTMX view)."
    ),
)
def api_projection_approve(request, projection_id: int):
    """
    Approve a draft projection: transition draft→ready, freeze content.
    Gate: user must have edit authority (can_edit seam, ADR-017 D2).
    """
    from django.shortcuts import get_object_or_404
    from syndication.models import PlatformProjection

    projection = get_object_or_404(PlatformProjection, pk=projection_id)

    try:
        approve_projection(user=request.auth, projection=projection)
    except PermissionError as exc:
        logger.warning("Permission denied on approve: %s", exc)
        return api.create_response(request, {"detail": "Permission denied."}, status=403)
    except ValueError as exc:
        logger.warning("Illegal transition on approve: %s", exc)
        return api.create_response(request, {"detail": str(exc)}, status=400)

    projection.refresh_from_db()
    return _actor_marker_response(
        request,
        {
            "id": projection.pk,
            "status": projection.status,
            "provenance": projection.content_version.provenance,
        },
    )


@api.post(
    "/projections/{projection_id}/publish/",
    auth=_RESOURCE_AUTH,
    response={200: ProjectionActionOut},
    summary="Publish a ready projection (ready→published)",
    description=(
        "Co-equal API verb for publish (ADR-016 D6). "
        "EXPLICIT action — never auto-triggers on approve (ADR-016 D5). "
        "Calls publish_projection service (co-equal with HTMX view)."
    ),
)
def api_projection_publish(request, projection_id: int):
    """
    Publish a ready projection: transition ready→published. EXPLICIT only.
    Gate: user must have publish authority (can_publish seam, ADR-017 D2).
    """
    from django.shortcuts import get_object_or_404
    from syndication.models import PlatformProjection

    projection = get_object_or_404(PlatformProjection, pk=projection_id)

    try:
        publish_projection(user=request.auth, projection=projection)
    except PermissionError as exc:
        logger.warning("Permission denied on publish: %s", exc)
        return api.create_response(request, {"detail": "Permission denied."}, status=403)
    except ValueError as exc:
        logger.warning("Illegal transition on publish: %s", exc)
        return api.create_response(request, {"detail": str(exc)}, status=400)

    projection.refresh_from_db()
    return _actor_marker_response(
        request,
        {
            "id": projection.pk,
            "status": projection.status,
            "provenance": projection.content_version.provenance,
        },
    )


class BatchPublishFailureOut(Schema):
    """Details of a single per-projection publish failure."""
    projection_id: int
    error: str


class BatchPublishOut(Schema):
    """Response for batch publish-all-ready action."""
    published_count: int
    published_ids: List[int]
    failures: List[BatchPublishFailureOut] = []


@api.post(
    "/events/{event_id}/projections/publish-all-ready/",
    auth=_RESOURCE_AUTH,
    response={200: BatchPublishOut},
    summary="Batch-publish all ready projections for an event",
    description=(
        "Co-equal API verb for batch publish (ADR-016 D6). "
        "Publishes every ready projection for the event in a single call. "
        "Skips non-ready rows. Gated by can_publish seam (ADR-017 D2). "
        "Calls the same publish_all_ready_projections service as the HTMX view."
    ),
)
def api_batch_publish_ready(request, event_id: int):
    """
    Batch-publish all ready projections for an event.
    Gate: user must have publish authority (can_publish seam, ADR-017 D2).
    Returns 403 on permission error.
    """
    from django.shortcuts import get_object_or_404
    from events.models import Event

    event = get_object_or_404(Event, pk=event_id)

    try:
        published, failures = publish_all_ready_projections(user=request.auth, event=event)
    except PermissionError as exc:
        logger.warning("Permission denied on batch publish-all-ready: %s", exc)
        return api.create_response(request, {"detail": "Permission denied."}, status=403)

    # ADR-008 D3: fail loud — surface partial failures in the API response body.
    failure_details = [
        {"projection_id": proj.pk, "error": str(exc)}
        for proj, exc in failures
    ]

    return _actor_marker_response(
        request,
        {
            "published_count": len(published),
            "published_ids": [p.pk for p in published],
            "failures": failure_details,
        },
    )
