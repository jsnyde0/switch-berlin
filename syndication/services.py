"""
Syndication service layer (kb-a4u.2 + kb-a4u.3, ADR-016 D6).

Per ADR-016 D6: the API handlers and HTMX views share ONE auth + service
layer. Persistence logic lives here, not in the Ninja handlers, so the
co-equal-API test (kb-a4u.9) can assert both surfaces hit identical
persistence + auth.

Actor-marker (ADR-017 D1): agent (Bearer) and web (session) have identical
authority — they both resolve to the same User. The actor_marker string is
audit-only provenance for the generated_by / provenance projection fields.

kb-a4u.3 additions:
- create_event: persist all ADR-016 D1 fields, create EventOrganizer row,
  eager-create listing projections per enabled listing-capable connection.
- update_event: patch an event through the authz seam.
- create_post: persist Post with FK to Event, eager-create promotion
  projections per enabled promotion-capable connection.
- update_post: patch a post through the authz seam.
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
    Validate the long-lived Bearer API key and issue a short-lived identity token.

    The API key is NOT consumed — it is long-lived and reusable for many exchanges.
    Each call issues a fresh identity token (caller should cache within its TTL).

    Returns (identity_token, user) on success.
    Raises AgentCredential.DoesNotExist or ValueError on failure (fail loud
    per ADR-008 D3 — no silent fallback).
    """
    credential, user = AgentCredential.validate(raw_api_key)
    identity_token = IdentityToken.issue(user)
    return identity_token, user


# ---------------------------------------------------------------------------
# Identity token validation (used by Ninja auth callable)
# ---------------------------------------------------------------------------

def validate_identity_token(raw_token: str):
    """
    Validate an identity token (must exist and not be expired).

    The token is NOT consumed — it is reusable within its TTL.
    Returns (identity_token, user) on success.
    Raises IdentityToken.DoesNotExist or ValueError on failure.
    """
    return IdentityToken.validate(raw_token)


# ---------------------------------------------------------------------------
# Event CRUD (kb-a4u.3, ADR-016 D1/D4/D5)
# ---------------------------------------------------------------------------


def _get_primary_profile_for_user(user):
    """
    Return the primary Profile for a user — the first active ProfileClaim.

    Raises ValueError if the user has no claimed profile (fail-loud per ADR-008 D3).
    Used for associating event creation with an organizer profile.
    """
    from organizers.models import ProfileClaim
    claim = (
        ProfileClaim.objects.filter(user=user, rejected_at__isnull=True)
        .select_related("profile")
        .first()
    )
    if claim is None:
        raise ValueError(
            f"User {user} has no active ProfileClaim. "
            "Cannot create Event without an organizer profile (ADR-017 D1)."
        )
    return claim.profile


def _eager_create_listing_projections(event):
    """
    ADR-016 D4: For each enabled PlatformConnection that supports 'listing'
    owned by the event's organizer profiles, create a draft PlatformProjection.

    Called after an Event is saved. Visibility tier is irrelevant (ADR-016
    carried-forward, revised 2026-05-26 — no visibility write-gate).
    """
    from events.models import EventOrganizer
    from syndication.models import PlatformConnection, PlatformProjection

    # Get all organizer Profile IDs for this event
    organizer_profile_ids = EventOrganizer.objects.filter(
        event=event
    ).values_list("profile_id", flat=True)

    if not organizer_profile_ids:
        return

    # Find enabled connections owned by those profiles that support 'listing'
    connections = PlatformConnection.objects.filter(
        organizer_id__in=organizer_profile_ids,
        enabled=True,
    )

    for conn in connections:
        kinds = conn.kinds or []
        if "listing" not in kinds:
            continue
        PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=event,
            provenance=PlatformProjection.Provenance.RULE_TEMPLATE,
        )


def _eager_create_promotion_projections(post):
    """
    ADR-016 D4: For each enabled PlatformConnection that supports 'promotion'
    owned by the post's event's organizer profiles, create a draft PlatformProjection.

    Called after a Post is saved.
    """
    from events.models import EventOrganizer
    from syndication.models import PlatformConnection, PlatformProjection

    # Get all organizer Profile IDs for this post's event
    organizer_profile_ids = EventOrganizer.objects.filter(
        event=post.event
    ).values_list("profile_id", flat=True)

    if not organizer_profile_ids:
        return

    # Find enabled connections owned by those profiles that support 'promotion'
    connections = PlatformConnection.objects.filter(
        organizer_id__in=organizer_profile_ids,
        enabled=True,
    )

    for conn in connections:
        kinds = conn.kinds or []
        if "promotion" not in kinds:
            continue
        PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=post,
            provenance=PlatformProjection.Provenance.RULE_TEMPLATE,
        )


# Event field names accepted by create_event / update_event.
# Covers the full v0 field set per kb-a4u acceptance criterion 1.
# venue is a direct FK column; tags is M2M and handled separately.
_EVENT_FIELDS = {
    "title",
    "slug",
    "description",
    "start",
    "end",
    "venue",
    "dress_code",
    "content_warnings",
    "age_restriction",
    "capacity",
    "visibility",
    "language",
    "is_free",
    "price_min_cents",
    "price_max_cents",
    "currency",
    "sliding_scale",
    "price_description",
    "external_url",
    "tickets_url",
    "registration_required",
    "registration_url",
    "registration_email",
    "status",
}


def create_event(user, **kwargs):
    """
    Create a new Event owned by user's primary Profile.

    Steps:
    1. Resolve user → primary Profile (fail-loud if no profile).
    2. Create the Event with all supplied ADR-016 D1 fields. Status defaults to 'draft'
       (ADR-016 D5 — save-always; completeness gated at draft→ready, never at save).
    3. If tags (list of Tag PKs or instances) supplied, set M2M after create.
    4. Create an EventOrganizer through-table row (is_primary=True) linking the Profile.
    5. Eager-create draft listing projections per enabled listing-capable connection
       (ADR-016 D4).

    The slug field is required. All other fields are optional (draft allows incomplete state).
    Raises ValueError if user has no Profile (fail-loud per ADR-008 D3).
    """
    from events.models import Event, EventOrganizer

    profile = _get_primary_profile_for_user(user)

    # Extract tags before filtering (M2M — cannot pass to objects.create)
    tags = kwargs.pop("tags", None)

    # Filter to only known Event fields to avoid unexpected kwargs.
    # Skip None and empty-string values for optional fields; let model defaults apply.
    # ADR-016 D5: save-always — never refuse a partial draft.
    event_kwargs = {}
    for k, v in kwargs.items():
        if k not in _EVENT_FIELDS:
            continue
        if v is None:
            continue
        # Skip empty strings for choice/FK fields where blank is invalid;
        # model defaults handle unset values. Required fields (title, slug, start)
        # are always present from the form.
        if v == "" and k in ("visibility", "language", "currency"):
            continue
        event_kwargs[k] = v
    event_kwargs.setdefault("status", "draft")
    event_kwargs.setdefault("visibility", "public")
    event_kwargs.setdefault("currency", "EUR")

    event = Event.objects.create(**event_kwargs)

    # Set M2M tags if supplied (list of Tag PKs or Tag instances)
    if tags:
        event.tags.set(tags)

    # Create the EventOrganizer through-table row (ADR-007 D2, ADR-017 D1)
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)

    # Eager-create draft listing projections (ADR-016 D4)
    _eager_create_listing_projections(event)

    return event


def update_event(user, event, **kwargs):
    """
    Update an existing Event, gated through the can_edit seam (ADR-017 D2).

    Only updates fields listed in _EVENT_FIELDS.
    Tags (M2M) are handled separately — passed as list of Tag PKs/instances.
    Raises PermissionError if user cannot edit this event.
    ADR-016 D5: saves are always allowed (completeness enforced at draft→ready).
    """
    from syndication.authz import can_edit

    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot edit event '{event}' (ADR-017 D1/D2)."
        )

    # Extract tags before iterating (M2M — not a model field for setattr)
    tags = kwargs.pop("tags", None)

    update_fields = []
    for field, value in kwargs.items():
        if field in _EVENT_FIELDS:
            setattr(event, field, value)
            update_fields.append(field)

    if update_fields:
        event.save(update_fields=update_fields)

    # Set M2M tags if supplied
    if tags is not None:
        event.tags.set(tags)

    return event


# ---------------------------------------------------------------------------
# Post CRUD (kb-a4u.3, ADR-016 D1/D4)
# ---------------------------------------------------------------------------

_POST_FIELDS = {
    "headline",
    "body",
    "imagery",
    "cta",
    "voice",
    "sequence_order",
    "lifecycle_moment",
    "scheduled_for",
}


def create_post(user, event, **kwargs):
    """
    Create a Post for an Event, gated through the can_edit seam (ADR-017 D2).

    Steps:
    1. Gate: user must be able to edit the event (organizer claimant).
    2. Create Post with FK to Event.
    3. Eager-create draft promotion projections per enabled promotion-capable connection
       (ADR-016 D4).

    Raises PermissionError if user cannot edit the event.
    """
    from syndication.authz import can_edit
    from syndication.models import Post

    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot create a post for event '{event}' (ADR-017 D1/D2)."
        )

    post_kwargs = {k: v for k, v in kwargs.items() if k in _POST_FIELDS}
    post = Post.objects.create(event=event, **post_kwargs)

    # Eager-create draft promotion projections (ADR-016 D4)
    _eager_create_promotion_projections(post)

    return post


def update_post(user, post, **kwargs):
    """
    Update a Post, gated through the can_edit seam (ADR-017 D2).

    Raises PermissionError if user cannot edit the post's event.
    """
    from syndication.authz import can_edit

    if not can_edit(user, post.event):
        raise PermissionError(
            f"User {user} cannot update post '{post}' (ADR-017 D1/D2)."
        )

    update_fields = []
    for field, value in kwargs.items():
        if field in _POST_FIELDS:
            setattr(post, field, value)
            update_fields.append(field)

    if update_fields:
        post.save(update_fields=update_fields)

    return post
