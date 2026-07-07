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

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from ninja import File, NinjaAPI, Schema, Status
from ninja.files import UploadedFile
from ninja.security import HttpBearer
from ninja.security import SessionAuth as NinjaSessionAuth

from syndication.models import AgentCredential, IdentityToken, TelegramDialogType, TelegramPlacementStatus, TelegramPostability
from syndication.services import (
    ACTOR_BEARER,
    ACTOR_SESSION,
    approve_projection,
    create_event,
    create_post,
    enable_promotion,
    exchange_api_key_for_identity_token,
    ingest_telegram_inventory,
    mark_projection_published,
    publish_all_ready_projections,
    publish_projection,
    redeem_pairing_token,
    register_agent_credential,
    report_telegram_placements,
    set_event_cover,
    update_event,
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
        "detail": ("verify-identity is stubbed at v0 (ADR-008 D2). No external consumer yet."),
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
    end: datetime | None = None
    description: str = ""
    dress_code: str = ""
    content_warnings: list[str] = []
    age_restriction: int | None = None
    capacity: int | None = None
    visibility: str = "public"
    language: str = ""
    is_free: bool = False
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    currency: str = "EUR"
    sliding_scale: bool = False
    price_description: str = ""
    external_url: str = ""
    tickets_url: str = ""
    registration_required: bool = False
    registration_url: str = ""
    registration_email: str = ""
    category: str = ""
    venue: int | None = None
    tags: list[str] | None = None


class EventUpdateIn(Schema):
    """
    Partial-update schema for PATCH /events/{id}/.

    All fields are optional (PATCH semantics — only non-None fields are applied).
    Kept at parity with EventCreateIn for the full updatable set (ADR-016 D3:
    co-equal API — an agent must be able to read back what it wrote).
    """

    title: str | None = None
    slug: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    description: str | None = None
    dress_code: str | None = None
    content_warnings: list[str] | None = None
    age_restriction: int | None = None
    capacity: int | None = None
    visibility: str | None = None
    language: str | None = None
    is_free: bool | None = None
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    currency: str | None = None
    sliding_scale: bool | None = None
    price_description: str | None = None
    external_url: str | None = None
    tickets_url: str | None = None
    registration_required: bool | None = None
    registration_url: str | None = None
    registration_email: str | None = None
    category: str | None = None
    venue: int | None = None
    tags: list[str] | None = None


class EventOut(Schema):
    """
    Response schema for Event endpoints (ADR-016 D3: co-equal API).

    Includes the full v0 readable field set so an agent can read back what
    it wrote (start, end, slug, registration_* were previously missing).
    """

    id: int
    title: str
    slug: str
    start: datetime | None
    end: datetime | None
    description: str
    status: str
    visibility: str
    dress_code: str
    content_warnings: list[str]
    age_restriction: int | None
    capacity: int | None
    language: str
    is_free: bool
    price_min_cents: int | None
    price_max_cents: int | None
    currency: str
    sliding_scale: bool
    price_description: str
    external_url: str
    tickets_url: str
    registration_required: bool
    registration_url: str
    registration_email: str
    category: str
    venue_id: int | None
    tags: list[str]


# --- Post schemas ---


class PostCreateIn(Schema):
    headline: str
    body: str
    cta: str = ""
    voice: str = ""
    imagery: list[str] | None = None


class PostUpdateIn(Schema):
    headline: str | None = None
    body: str | None = None
    cta: str | None = None
    voice: str | None = None


class PostOut(Schema):
    id: int
    event_id: int
    headline: str
    body: str
    cta: str
    voice: str


# --- Projection schema (kb-k2ds.2 — real list, replaces the C4 stub) ---


class ProjectionOut(Schema):
    """
    Response schema for GET /api/projections/ rows.

    Carries at least: projection id, connection (channel) identity, kind,
    status (bead kb-k2ds.2 acceptance (2)) — plus event_id/post_id so an
    agent can correlate a row back to the publishable it came from.
    """

    id: int
    kind: str
    status: str
    event_id: int | None
    post_id: int | None
    connection_id: int
    connection_platform: str
    connection_destination_id: str
    connection_title: str | None


# --- Connection schema (kb-k2ds.3 — discoverability + enable-promotion) ---


class ConnectionOut(Schema):
    """
    Response schema for GET /api/connections/ rows and the enable-promotion
    action response (bead kb-k2ds.3 acceptance (2)).

    Carries at least id/platform/destination_id/title/kinds/enabled so an
    agent can discover a connection id and confirm its promotion-enabled
    state without any web HTMX fast-path.
    """

    id: int
    platform: str
    destination_id: str
    title: str | None
    kinds: list[str]
    enabled: bool


# ---------------------------------------------------------------------------
# Event field resolution helpers (venue-id → Venue, tag-slugs → Tag pks)
# ---------------------------------------------------------------------------


def _resolve_venue(venue_id):
    """
    Resolve a venue id to a Venue instance.

    ADR-008 D3: fail loud on unknown venue id — raises Http404 (→ 404 response).
    Returns None if venue_id is None (venue is optional at draft time).

    Mirrors syndication/forms.py clean_venue().
    """
    if venue_id is None:
        return None
    from django.http import Http404

    from venues.models import Venue

    try:
        return Venue.objects.get(pk=venue_id)
    except Venue.DoesNotExist:
        raise Http404(f"Venue with id {venue_id} does not exist.") from None


def _resolve_tag_pks(tag_slugs):
    """
    Resolve a list of tag slugs to a list of Tag PKs.

    Unknown slugs are silently skipped (lenient — mirrors forms.py clean_tags).
    Returns None if tag_slugs is None (tags not supplied → no-op in service).
    """
    if tag_slugs is None:
        return None
    from events.models import Tag

    return list(Tag.objects.filter(slug__in=tag_slugs).values_list("pk", flat=True))


def _event_to_dict(event):
    """
    Serialize an Event instance to a dict matching EventOut.

    Centralises the field mapping used by events_list, events_create,
    events_detail, and events_update — avoiding 4× repetition.
    """
    return {
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
        "venue_id": event.venue_id,
        "tags": list(event.tags.values_list("slug", flat=True)),
    }


# ---------------------------------------------------------------------------
# Event CRUD endpoints
# ---------------------------------------------------------------------------


@api.get(
    "/events/",
    auth=_RESOURCE_AUTH,
    response=list[EventOut],
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
    profile_ids = ProfileClaim.objects.filter(user=request.auth, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )

    # Get event IDs where those profiles are organizers
    event_ids = EventOrganizer.objects.filter(profile_id__in=profile_ids).values_list("event_id", flat=True)

    events = Event.objects.filter(pk__in=event_ids).order_by("-start")
    data = [_event_to_dict(e) for e in events]
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

    Venue resolution (ADR-008 D3: fail loud on unknown id) and tag-slug resolution
    (lenient skip of unknown slugs, mirroring forms.py clean_venue / clean_tags)
    happen here before calling the service.
    """
    kwargs = body.dict(exclude_none=False)

    # Resolve venue id → Venue instance (raises 404 on unknown id — ADR-008 D3).
    venue_id = kwargs.pop("venue", None)
    venue = _resolve_venue(venue_id)
    if venue is not None:
        kwargs["venue"] = venue

    # Resolve tag slugs → Tag PKs (lenient: unknown slugs silently skipped).
    tag_slugs = kwargs.pop("tags", None)
    tag_pks = _resolve_tag_pks(tag_slugs)
    if tag_pks is not None:
        kwargs["tags"] = tag_pks

    event = create_event(user=request.auth, **kwargs)
    return _actor_marker_response(request, _event_to_dict(event), status=201)


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
    return _actor_marker_response(request, _event_to_dict(event))


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

    Venue resolution (ADR-008 D3: fail loud on unknown id) and tag-slug resolution
    (lenient skip of unknown slugs, mirroring forms.py clean_venue / clean_tags)
    happen here before calling the service.
    """
    from django.shortcuts import get_object_or_404

    from events.models import Event

    event = get_object_or_404(Event, pk=event_id)
    # Only pass non-None fields so unset optional fields don't zero-out existing values
    patch_kwargs = {k: v for k, v in body.dict().items() if v is not None}

    # Resolve venue id → Venue instance (raises 404 on unknown id — ADR-008 D3).
    if "venue" in patch_kwargs:
        venue = _resolve_venue(patch_kwargs.pop("venue"))
        if venue is not None:
            patch_kwargs["venue"] = venue

    # Resolve tag slugs → Tag PKs (lenient: unknown slugs silently skipped).
    if "tags" in patch_kwargs:
        tag_slugs = patch_kwargs.pop("tags")
        tag_pks = _resolve_tag_pks(tag_slugs)
        if tag_pks is not None:
            patch_kwargs["tags"] = tag_pks

    event = update_event(user=request.auth, event=event, **patch_kwargs)
    return _actor_marker_response(request, _event_to_dict(event))


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
def events_cover_upload(request, event_id: int, file: UploadedFile = File(...)):  # noqa: B008
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
    response=list[PostOut],
    summary="List Posts for an Event",
)
def event_posts_list(request, event_id: int):
    """List all Posts for a given Event (ownership-gated, finding #2 — same authz as PATCH)."""
    from django.shortcuts import get_object_or_404

    from events.models import Event
    from syndication.authz import can_edit
    from syndication.models import Post

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
    response=list[PostOut],
    summary="List all Posts for authenticated user's events",
)
def posts_list(request):
    """
    List all Posts across all Events where the user is an organizer.
    Returns HttpResponse directly so X-Actor-Marker header is preserved.
    """
    from events.models import EventOrganizer
    from organizers.models import ProfileClaim
    from syndication.models import Post

    profile_ids = ProfileClaim.objects.filter(user=request.auth, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )

    event_ids = EventOrganizer.objects.filter(profile_id__in=profile_ids).values_list("event_id", flat=True)

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


def _projection_to_dict(projection):
    """
    Serialize a PlatformProjection to a dict matching ProjectionOut.

    event_id/post_id: exactly one is set per row (listing → event_id via
    source_event; promotion → post_id via source_post, with event_id derived
    from the post's event for correlation convenience).
    """
    from syndication.models import PlatformProjection

    if projection.kind == PlatformProjection.Kind.LISTING:
        event_id = projection.source_event_id
        post_id = None
    else:
        post_id = projection.source_post_id
        event_id = projection.source_post.event_id if projection.source_post_id else None

    return {
        "id": projection.pk,
        "kind": projection.kind,
        "status": projection.status,
        "event_id": event_id,
        "post_id": post_id,
        "connection_id": projection.connection_id,
        "connection_platform": projection.connection.platform,
        "connection_destination_id": projection.connection.destination_id,
        "connection_title": projection.connection.title,
    }


@api.get(
    "/projections/",
    auth=_RESOURCE_AUTH,
    response=list[ProjectionOut],
    summary="List the caller's own projections, optionally filtered by event/post",
)
def projections_list(request, event: int | None = None, post: int | None = None):
    """
    List the authenticated user's own PlatformProjection rows (kb-k2ds.2 —
    replaces the C4/kb-a4u.4 stub).

    Delegates to services.list_projections_for_user (co-equal REST seam,
    ADR-016 D3) — scoped to the caller's owned rows, mirroring events_list's
    auth-scoping pattern. Optional ?event=<id> and/or ?post=<id> query params
    narrow the result. Raises 404 (fail loud, ADR-008 D3) if a given event/post
    id does not exist at all.
    """
    from syndication.services import list_projections_for_user

    projections = list_projections_for_user(request.auth, event_id=event, post_id=post)
    data = [_projection_to_dict(p) for p in projections]
    return _actor_marker_response(request, data)


# ---------------------------------------------------------------------------
# PlatformConnection discoverability + enable-promotion (kb-k2ds.3)
#
# Co-equal seam (ADR-016 D3/D6): closes the gap where the only way to
# discover a connection id or enable it for promotion was the web HTMX
# destination picker (syndication/views.py connections_list / destination_select).
# ---------------------------------------------------------------------------


def _connection_to_dict(connection):
    """Serialize a PlatformConnection to a dict matching ConnectionOut."""
    return {
        "id": connection.pk,
        "platform": connection.platform,
        "destination_id": connection.destination_id,
        "title": connection.title,
        "kinds": connection.kinds or [],
        "enabled": connection.enabled,
    }


@api.get(
    "/connections/",
    auth=_RESOURCE_AUTH,
    response=list[ConnectionOut],
    summary="List the caller's own PlatformConnections (kb-k2ds.3 discoverability)",
)
def connections_list(request):
    """
    List all PlatformConnection rows owned by the authenticated user's claimed
    profiles (mirrors the events_list auth-scoping pattern and the web
    connections_list view — no cross-tenant leak).

    Gives an agent an id it can pass to POST /connections/{id}/enable-promotion/
    without any web HTMX fast-path (kb-k2ds.3 acceptance (2)).
    """
    from organizers.models import ProfileClaim
    from syndication.models import PlatformConnection

    profile_ids = ProfileClaim.objects.filter(user=request.auth, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )
    connections = PlatformConnection.objects.filter(organizer_id__in=profile_ids).order_by(
        "platform", "destination_id"
    )
    data = [_connection_to_dict(c) for c in connections]
    return _actor_marker_response(request, data)


@api.post(
    "/connections/{connection_id}/enable-promotion/",
    auth=_RESOURCE_AUTH,
    response={200: ConnectionOut},
    summary="Enable a synced connection for promotion (kb-k2ds.3)",
    description=(
        "Co-equal REST verb for the web destination_select 'select' action "
        "(syndication/views.py, kb-sbhs.3). Adds 'promotion' to the "
        "connection's kinds (additive) and sets enabled=True. "
        "Calls the SAME enable_promotion service function as the web path — "
        "no separate implementation, no divergent fail-loud gate (ADR-008 D3). "
        "Idempotent: enabling an already-promotion-enabled connection is a "
        "success no-op. Raises 404 on an unknown/not-owned connection id, "
        "400 if the connection is not selectable (flagged_missing, "
        "agent-tier locked, forum-cluster parent) or its platform does not "
        "support post promotion (e.g. 'switch')."
    ),
)
def api_connection_enable_promotion(request, connection_id: int):
    """
    Enable a PlatformConnection for promotion.

    Ownership scoping mirrors the web destination_select view: 404 (never a
    generic 500 or a cross-tenant leak) if the connection does not exist or
    is not owned by the caller's claimed profiles.
    Gate: enable_promotion service raises ValueError on the fail-loud
    selectability/platform-capability gates — mapped to 400 here.
    """
    from django.shortcuts import get_object_or_404

    from organizers.models import ProfileClaim
    from syndication.models import PlatformConnection

    profile_ids = ProfileClaim.objects.filter(user=request.auth, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )
    connection = get_object_or_404(PlatformConnection, pk=connection_id, organizer_id__in=profile_ids)

    try:
        enable_promotion(user=request.auth, connection=connection)
    except ValueError as exc:
        logger.warning("enable-promotion: rejected connection %s: %s", connection_id, exc)
        return api.create_response(request, {"detail": str(exc)}, status=400)

    connection.refresh_from_db()
    return _actor_marker_response(request, _connection_to_dict(connection))


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
    published_ids: list[int]
    failures: list[BatchPublishFailureOut] = []


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
    failure_details = [{"projection_id": proj.pk, "error": str(exc)} for proj, exc in failures]

    return _actor_marker_response(
        request,
        {
            "published_count": len(published),
            "published_ids": [p.pk for p in published],
            "failures": failure_details,
        },
    )


# ---------------------------------------------------------------------------
# Telegram inventory ingest endpoint (kb-ru55.2)
# ---------------------------------------------------------------------------


class TelegramInventoryItemIn(Schema):
    """
    Schema for a single postable Telegram destination in an inventory payload.

    Metadata-only (ADR-018 D4 / bead D2): carries dialog metadata, NOT
    session credentials or message content.

    extra="forbid": any unrecognised field (including session_string, access_hash,
    content, and any future credential field) causes Pydantic → Ninja to return 422.
    This is the server-side enforcement of ADR-018 D4 / bead D2: fail loud on
    any credential or content leakage in the inventory payload.

    topic_id is required for forum_topic rows; optional (None) for others.
    """

    model_config = {"extra": "forbid"}

    chat_id: str
    title: str
    type: TelegramDialogType
    postability: TelegramPostability
    topic_id: int | None = None


class TelegramInventoryIngestOut(Schema):
    """Response for the Telegram inventory ingest verb."""

    upserted: int
    flagged: int


@api.post(
    "/telegram/inventory",
    auth=_RESOURCE_AUTH,
    response={200: TelegramInventoryIngestOut},
    summary="Ingest Telegram inventory (metadata-only upsert, kb-ru55.2)",
    description=(
        "Metadata-only inventory sync: accepts a list of postable Telegram destinations "
        "and upserts one PlatformConnection per item. "
        "Auth: identity token (agent path) or session (web path) per ADR-016 D3/D6. "
        "Destinations absent from this payload are FLAGGED (not deleted) per ADR-008 D3. "
        "Payload must NOT carry session_string, access_hash, or content — "
        "those fields are rejected loud (HTTP 422) per ADR-018 D4 / bead D2."
    ),
)
def telegram_inventory_ingest(request, body: list[TelegramInventoryItemIn]):
    """
    Ingest a metadata-only Telegram destination inventory.

    Upserts one PlatformConnection per item (keyed by chat_id + topic_id).
    Flags destinations absent from this payload as flagged_missing=True.
    No server-side credential is stored (ADR-018 D4).

    Fail loud (ADR-008 D3):
    - Any item containing session_string, access_hash, or content → 422.
    - forum_topic item missing topic_id → 422.
    """
    raw_inventory = [item.dict() for item in body]

    try:
        result = ingest_telegram_inventory(user=request.auth, inventory=raw_inventory)
    except ValueError as exc:
        logger.warning("telegram/inventory: rejected payload: %s", exc)
        return api.create_response(
            request,
            {"detail": str(exc)},
            status=422,
        )

    return _actor_marker_response(request, result)


# ---------------------------------------------------------------------------
# Telegram placement report endpoint (kb-56c2.1 — C3a co-equal seam)
# ---------------------------------------------------------------------------


class TelegramPlacementItemIn(Schema):
    """
    Schema for a single placement outcome in a placement report payload.

    Mirrors TelegramInventoryItemIn (extra="forbid" guard) — rejects any
    unrecognised field (session_string, access_hash, content, or any credential/
    content field) with HTTP 422 (ADR-018 D4 / kb-56c2.1 D2).

    status is constrained to TelegramPlacementStatus values:
    {placed, failed, skipped-pre-existing-draft}. "sent" is NOT a valid status
    (ADR-018 D2 FIRM draft-only firewall). Non-canonical values → 422.

    topic_id is optional — forum-level coverage uses forum's destination_id (kb-56c2 D5).
    error_detail is optional — only set for failed placements.
    """

    model_config = {"extra": "forbid"}

    destination_id: str
    topic_id: int | None = None
    status: TelegramPlacementStatus
    error_detail: str | None = None


class TelegramPlacementReportOut(Schema):
    """Response for the Telegram placement report verb."""

    written: int
    errors: list


@api.post(
    "/telegram/placements",
    auth=_RESOURCE_AUTH,
    response={200: TelegramPlacementReportOut},
    summary="Report Telegram placement outcomes (co-equal seam, kb-56c2.1)",
    description=(
        "Agent-tier co-equal verb: accepts a list of per-destination placement outcomes "
        "and writes/updates TelegramPlacement records. "
        "Auth: identity token (agent path) or session (web path) per ADR-016 D3/D6. "
        "Payload must NOT carry session_string, access_hash, or content — "
        "those fields are rejected loud (HTTP 422) per ADR-018 D4. "
        "'sent' is NOT a valid status (ADR-018 D2 FIRM draft-only firewall). "
        "Valid statuses: {placed, failed, skipped-pre-existing-draft}."
    ),
)
def telegram_placement_report(request, body: list[TelegramPlacementItemIn]):
    """
    Receive and persist agent-tier placement outcomes.

    Each item in body must be {destination_id, status, topic_id?, error_detail?}.
    Writes/updates one TelegramPlacement record per item.

    Fail loud (ADR-008 D3 / ADR-018 D4):
    - Any item containing session_string, access_hash, or content → 422
      (enforced by extra="forbid" on TelegramPlacementItemIn schema).
    - status not in {placed, failed, skipped-pre-existing-draft} → 422
      (enforced by TelegramPlacementStatus enum constraint on schema).

    Returns {"written": int, "errors": list} with per-item errors for
    destinations not found or not resolvable.
    """
    raw_placements = [item.dict() for item in body]

    try:
        result = report_telegram_placements(user=request.auth, placements=raw_placements)
    except ValueError as exc:
        logger.warning("telegram/placements: rejected payload: %s", exc)
        return api.create_response(
            request,
            {"detail": str(exc)},
            status=422,
        )

    return _actor_marker_response(request, result)
