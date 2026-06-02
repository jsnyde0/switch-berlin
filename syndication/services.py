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

from syndication.adapters import publish_switch_own_page, publish_telegram_promotion
from syndication.models import AgentCredential, AgentPairingToken, IdentityToken

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
    Issue a new AgentPairingToken for user (kb-a4u.6 pairing-token mechanic).

    The v0 decided mechanic is one-time pairing-token redemption (NOT raw key-paste):
    1. This function mints a SHORT-LIVED, SINGLE-USE pairing token.
    2. The facilitator hands the pairing token to their agent.
    3. The agent redeems it via redeem_pairing_token() to receive the long-lived
       Bearer key. The long-lived secret NEVER transits the facilitator's clipboard.

    Returns (pairing_token_record, raw_pairing_token). The caller MUST return
    raw_pairing_token to the facilitator exactly once — it is never stored
    (SHA-256 hash only) and cannot be recovered.

    Per ADR-008 D1 (no backward-compat shims, pre-launch): this replaces the
    old raw-key model inline — the old `return AgentCredential.issue(user)` path
    is removed. The Bearer key now only issues at redemption.
    """
    return AgentPairingToken.issue(user)


def redeem_pairing_token(raw_pairing_token: str):
    """
    Redeem a pairing token: validate it, mark it used, and issue a long-lived
    Bearer key (AgentCredential) bound to the registering User.

    This is the second step of the pairing flow (kb-a4u.6):
    - Acquires a row-level lock on the pairing token (SELECT FOR UPDATE) inside
      an atomic transaction to prevent TOCTOU double-redemption (finding #1).
    - Re-checks validity under the lock (expired / used) — fail loud (ADR-008 D3).
    - Marks the token used within the same transaction (atomic mark-and-issue).
    - Issues a new AgentCredential bound to the token's user.
    - Returns (credential, raw_key). The caller MUST return raw_key to the
      agent exactly once — it is never stored and cannot be recovered.

    The issued credential→User binding is the load-bearing ADR-017 D1 seam:
    authz resolves through credential.user's ProfileClaim set.

    Raises AgentPairingToken.DoesNotExist or ValueError on failure
    (ADR-008 D3: fail loud — invalid/expired/used token → raise, never succeed silently).

    Concurrency guarantee: two simultaneous requests with the same token cannot
    both issue a credential — the row lock serialises the check+mark block.
    """
    from django.db import transaction
    from syndication.models import _hash_key  # module-private helper

    token_hash = _hash_key(raw_pairing_token)

    with transaction.atomic():
        # SELECT FOR UPDATE: acquire row-level lock before any validity check.
        # A concurrent request for the same token blocks here until we commit,
        # then it will see used_at stamped and raise (finding #1 TOCTOU fix).
        try:
            pairing_token = (
                AgentPairingToken.objects
                .select_for_update()
                .select_related("user")
                .get(token_hash=token_hash)
            )
        except AgentPairingToken.DoesNotExist as exc:
            raise AgentPairingToken.DoesNotExist("Invalid pairing token.") from exc

        # Re-check validity under the lock (ADR-008 D3: fail loud, no silent fallback).
        if pairing_token.is_used:
            raise ValueError("Pairing token has already been redeemed.")
        if pairing_token.is_expired:
            raise ValueError("Pairing token has expired.")

        user = pairing_token.user
        # Mark used BEFORE issuing — within the same transaction so the lock
        # is held until both writes commit atomically.
        pairing_token.mark_used()
        # Issue long-lived Bearer key bound to the registering User (ADR-017 D1)
        credential, raw_key = AgentCredential.issue(user)

    return credential, raw_key


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


def get_publishables_for_profile(profile):
    """
    Return the profile's Events and Posts merged into one list sorted by
    updated_at descending.

    NO visibility filter — this lists an owner's OWN assets; visibility is a
    public-render concept that does NOT gate owner-management (ADR-012 read-side-
    only scope header).

    NO UNION SQL, NO pagination at V0 (ADR-008 D2 — add on a real volume signal).
    Python-level merge of two querysets spanning two apps (events.models.Event
    lives in the events app; syndication.models.Post lives here).

    Lives beside _get_primary_profile_for_user (parent D5).
    """
    from events.models import Event
    from syndication.models import Post

    # Fetch full Event objects for the profile (no visibility filter — ADR-012)
    event_qs = list(Event.objects.filter(organizers=profile))
    # Fetch Posts for all events belonging to this profile
    post_qs = list(Post.objects.filter(event__organizers=profile))

    merged = event_qs + post_qs
    merged.sort(key=lambda p: p.updated_at, reverse=True)
    return merged


def _ensure_canonical_content_version(event=None, post=None):
    """
    Ensure a canonical ContentVersion exists for a publishable (event OR post)
    and return it.

    Exactly one of event/post must be provided (ADR-008 D3: fail loud if both
    or neither are given — mirrors the DB check constraint).

    Creates it with all editorial fields NULL (track-live semantics) if absent.
    This is idempotent: if a canonical version already exists, it is returned as-is.

    ADR-016 D2 (kb-wz8m.2): A1 canonical version is seeded EMPTY.
    NULL editorial fields = derive from live canonical Event/Post at render time.
    """
    from syndication.models import ContentVersion

    if event is not None and post is None:
        cv, _ = ContentVersion.objects.get_or_create(
            event=event,
            name="canonical",
            defaults={
                "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
            },
        )
        return cv
    elif post is not None and event is None:
        cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={
                "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
            },
        )
        return cv
    else:
        raise ValueError(
            "_ensure_canonical_content_version requires exactly one of event or post, "
            f"got event={event!r}, post={post!r}. "
            "(ADR-008 D3: fail loud — exactly-one-publishable invariant)"
        )


def _eager_create_listing_projections(event, canonical_cv=None):
    """
    ADR-016 D4: For each enabled PlatformConnection that supports 'listing'
    owned by the event's organizer profiles, create a draft PlatformProjection.

    Called after an Event is saved. Visibility tier is irrelevant (ADR-016
    carried-forward, revised 2026-05-26 — no visibility write-gate).

    All created projections FK to the canonical ContentVersion (A1 seed,
    kb-wz8m.2). canonical_cv is passed in to avoid redundant DB round-trips.
    """
    from events.models import EventOrganizer
    from syndication.models import PlatformConnection, PlatformProjection

    if canonical_cv is None:
        canonical_cv = _ensure_canonical_content_version(event)

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
            content_version=canonical_cv,
        )


def _eager_create_promotion_projections(post, canonical_cv=None):
    """
    ADR-016 D4: For each enabled PlatformConnection that supports 'promotion'
    owned by the post's event's organizer profiles, create a draft PlatformProjection.

    Called after a Post is saved. Projections FK to the POST's canonical
    ContentVersion (ADR-016 D2), not the event's canonical.

    canonical_cv is passed in to avoid redundant DB round-trips; must be the
    POST's canonical (post FK set, event FK null).
    """
    from events.models import EventOrganizer
    from syndication.models import PlatformConnection, PlatformProjection

    if canonical_cv is None:
        canonical_cv = _ensure_canonical_content_version(post=post)

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
            content_version=canonical_cv,
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
    "category",
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

    # A1 seed (kb-wz8m.2): create the canonical ContentVersion FIRST so that
    # eager projections can FK to it in the same call.
    canonical_cv = _ensure_canonical_content_version(event)

    # Eager-create draft listing projections (ADR-016 D4)
    _eager_create_listing_projections(event, canonical_cv=canonical_cv)

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
# Cover image authoring (kb-a4u.19, ADR-016 D1)
# ---------------------------------------------------------------------------


def set_event_cover(user, event, uploaded_file):
    """
    Set the cover image for an Event (creates or replaces the single is_cover=True row).

    can_edit-gated (ADR-017 D2): raises PermissionError if user cannot edit the event.
    Single-cover invariant: replaces any prior cover so there is never more than one
    is_cover=True EventImage for the event.
    Validation: calls full_clean() on the EventImage so validators (validate_image_size,
    FileExtensionValidator) run — fails loud on oversize / wrong extension (ADR-008 D3).
    """
    from syndication.authz import can_edit
    from events.models import EventImage

    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot set cover image for event '{event}' (ADR-017 D2)."
        )

    from django.db import transaction

    # Build new EventImage (do not save yet — full_clean first)
    img = EventImage(event=event, image=uploaded_file, is_cover=True, order=0)
    img.full_clean()  # Runs validate_image_size + FileExtensionValidator; raises ValidationError on failure

    # Wrap delete + save atomically so a save failure rolls back the delete
    # (prevents the event being left with zero cover rows if img.save() fails).
    # full_clean() is intentionally BEFORE the atomic block — validation should
    # fail before we touch existing rows.
    with transaction.atomic():
        # Replace any prior cover(s) to maintain single-cover invariant
        EventImage.objects.filter(event=event, is_cover=True).delete()
        img.save()
    return img


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

    # A1 seed (kb-q4u9.2): create the canonical ContentVersion for the POST
    # (ADR-016 D2: promotion projections FK the post's canonical, not the
    # event's). ContentVersion.post=post, ContentVersion.event=None.
    canonical_cv = _ensure_canonical_content_version(post=post)

    # Eager-create draft promotion projections (ADR-016 D4)
    _eager_create_promotion_projections(post, canonical_cv=canonical_cv)

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


# ---------------------------------------------------------------------------
# Projection lifecycle actions (kb-a4u.5, ADR-016 D5)
#
# Co-equal seam (ADR-016 D6): all lifecycle actions are service functions
# called by BOTH the Ninja API handlers and the HTMX view actions.
# No duplicate persistence logic in views or API handlers.
#
# Status writes go EXCLUSIVELY through transition_status in engine.py.
# Do NOT write projection.status = ... directly anywhere.
# ---------------------------------------------------------------------------


def _resolve_projection_event(projection):
    """
    Return the Event for a projection regardless of kind.

    listing → source_event
    promotion → source_post.event

    ADR-008 D3: fail loud if neither is set.
    """
    from syndication.models import PlatformProjection

    if projection.kind == PlatformProjection.Kind.LISTING:
        if projection.source_event is None:
            raise ValueError(
                f"Listing projection {projection.pk!r} has no source_event. "
                "(ADR-008 D3: fail loud)"
            )
        return projection.source_event
    if projection.kind == PlatformProjection.Kind.PROMOTION:
        if projection.source_post is None:
            raise ValueError(
                f"Promotion projection {projection.pk!r} has no source_post. "
                "(ADR-008 D3: fail loud)"
            )
        return projection.source_post.event
    raise ValueError(
        f"Unknown projection kind {projection.kind!r} for projection {projection.pk!r}. "
        "(ADR-008 D3: fail loud)"
    )


# ---------------------------------------------------------------------------
# ContentVersion snapshot-semantic operations (kb-wz8m.3, ADR-016 D2, ADR-017 D2)
#
# All version ops are can_edit-gated through the existing auth seam (ADR-017 D2).
# Non-claimant → PermissionError.
#
# Co-equal-ready: no HTTP endpoints here (deferred per ADR-008 D2; kb-f6yp).
# These service functions are callable identically by HTMX views (kb-wz8m.5)
# and any future Ninja handler (ADR-016 D3).
#
# Deferred (ADR-008 D2, no first caller): cross-row Link, derived_from lineage,
# per-Profile preset.
# ---------------------------------------------------------------------------

# Editorial fields on ContentVersion that version ops may copy/mutate.
_CV_EDITORIAL_FIELDS = frozenset({"headline", "body", "imagery", "cta", "voice"})


def _copy_cv_fields(source_cv, target_cv):
    """
    Copy editorial fields from source_cv to target_cv (in-memory, does not save).
    Helper shared by duplicate, copy_from, copy_to.
    """
    for field in _CV_EDITORIAL_FIELDS:
        setattr(target_cv, field, getattr(source_cv, field))


def _gate_can_edit_for_cv(user, content_version):
    """
    Resolve the event from a ContentVersion and gate on can_edit.

    For event-owned versions: event = content_version.event.
    For post-owned versions: event = content_version.post.event.
    Never calls can_edit(user, None) — fail loud if neither is resolvable
    (ADR-008 D3).

    Raises PermissionError if user cannot edit the resolved event.
    """
    from syndication.authz import can_edit

    if content_version.event_id is not None:
        # Event-owned ContentVersion — resolve directly
        event = content_version.event
    elif content_version.post_id is not None:
        # Post-owned ContentVersion — resolve event via post (ADR-016 D2)
        event = content_version.post.event
    else:
        raise ValueError(
            f"ContentVersion {content_version.pk!r} has neither event nor post FK set. "
            "Check constraint violation — exactly one must be non-null. "
            "(ADR-008 D3: fail loud)"
        )

    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot edit ContentVersion {content_version.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )


def consumers(version):
    """
    Return the queryset of PlatformProjections whose content_version FK points
    at this ContentVersion.

    This is the per-version "live on" data — how many projections share this row.

    No auth gate: consumers is a read-only query callable by any service layer
    code (e.g. the board rendering in kb-wz8m.5).
    """
    return version.projections.all()


def content_version_consumers_map(event=None, post=None):
    """
    Return the per-publishable aggregate the board reads for the "live on" cue.

    Shape: {ContentVersion: [PlatformProjection, ...]}

    Maps each ContentVersion for the given publishable (event OR post) to the
    list of PlatformProjections currently pointing at it. Versions with zero
    consumers are included. Versions from other publishables are excluded.

    Exactly one of event/post must be provided (ADR-008 D3: fail loud if both
    or neither are given).

    kb-wz8m.5 (UI) consumes this for the board's per-version channel summary.
    """
    from syndication.models import ContentVersion

    if event is not None and post is None:
        versions = ContentVersion.objects.filter(event=event).prefetch_related(
            "projections"
        )
    elif post is not None and event is None:
        versions = ContentVersion.objects.filter(post=post).prefetch_related(
            "projections"
        )
    else:
        raise ValueError(
            "content_version_consumers_map requires exactly one of event or post, "
            f"got event={event!r}, post={post!r}. "
            "(ADR-008 D3: fail loud — exactly-one-publishable invariant)"
        )

    result = {}
    for cv in versions:
        result[cv] = list(cv.projections.all())
    return result


def _unique_copy_name(source_name):
    """
    Generate a unique name for a new ContentVersion copied from source_name.

    The name uniqueness is enforced by two partial constraints (migration 0006):
    - (event, name) WHERE event IS NOT NULL
    - (post, name) WHERE post IS NOT NULL
    Callers creating multiple copies of the same source in one operation
    would collide on a plain "copy-of-<name>" slug. A short UUID suffix
    guarantees uniqueness across both partial constraints.
    """
    import uuid as _uuid
    suffix = _uuid.uuid4().hex[:8]
    return f"copy-of-{source_name}-{suffix}"


def duplicate(user, version):
    """
    Create and return a NEW independent ContentVersion seeded (copied) from an
    existing one (same publishable — event or post — copied fields, fresh row).

    Gate: user must be able to edit the version's publishable (can_edit seam).

    The new version is not attached to any projection — callers (copy_from,
    copy_to, customize) wire up the FK after calling this.

    ADR-016 D2 / ADR-008 D3: the new version inherits the publishable scope
    (event or post) of the source — never collapses a post-owned version to
    event-owned or vice versa.
    """
    from syndication.models import ContentVersion

    _gate_can_edit_for_cv(user, version)

    # Preserve publishable scope: post-owned → post FK; event-owned → event FK.
    new_cv = ContentVersion(
        event=version.event,
        post=version.post,
        name=_unique_copy_name(version.name),
        provenance=version.provenance,
    )
    _copy_cv_fields(version, new_cv)
    new_cv.save()
    return new_cv


def _resolve_publishable_for_cv(content_version):
    """
    Return the owning publishable of a ContentVersion as (event_or_none, post_or_none).

    For event-owned: returns (event, None).
    For post-owned: returns (None, post).
    Fail loud if neither is set (ADR-008 D3).
    """
    if content_version.event_id is not None:
        return content_version.event, None
    if content_version.post_id is not None:
        return None, content_version.post
    raise ValueError(
        f"ContentVersion {content_version.pk!r} has neither event nor post FK set. "
        "Check constraint violation — exactly one must be non-null. "
        "(ADR-008 D3: fail loud)"
    )


def copy_from(user, projection, source_version):
    """
    Repoint the projection at a NEW independent copy taken from source_version
    (mint a new row from source, FK the projection to it).

    Gate: user must be able to edit the projection's event (can_edit seam).
    The original ContentVersion the projection was pointing at is left as-is
    (GC is out of scope).

    ADR-016 D2 / ADR-008 D3: the new CV inherits the publishable scope of the
    source version (event or post). A post-owned source → new CV has post FK.
    Cross-publishable copy (source owned by a different event than the target
    projection's event) raises fail loud.

    Returns the new ContentVersion.
    """
    from syndication.authz import can_edit
    from syndication.models import ContentVersion

    event = _resolve_projection_event(projection)
    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot edit projection {projection.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )

    # Guard: source_version's owning event must match the projection's event.
    # For event-owned source: source.event must equal projection's event.
    # For post-owned source: source.post.event must equal projection's event.
    # Cross-event copy is a data-integrity violation — fail loud before any DB
    # mutation (ADR-008 D3).
    if source_version.event_id is not None:
        source_event = source_version.event
    elif source_version.post_id is not None:
        source_event = source_version.post.event
    else:
        raise ValueError(
            f"copy_from: source_version {source_version.pk!r} has neither event "
            "nor post FK — check constraint violation. (ADR-008 D3: fail loud)"
        )

    if source_event != event:
        raise ValueError(
            f"copy_from: source_version {source_version.pk!r} belongs to event "
            f"{source_event.pk!r} but target projection {projection.pk!r} "
            f"belongs to event {event.pk!r}. "
            "Source version must belong to the same event as the target projection. "
            "(ADR-008 D3: fail loud — cross-event data-integrity violation)"
        )

    # Preserve publishable scope: post-owned source → new CV has post FK set.
    new_cv = ContentVersion(
        event=source_version.event,
        post=source_version.post,
        name=_unique_copy_name(source_version.name),
        provenance=source_version.provenance,
    )
    _copy_cv_fields(source_version, new_cv)
    new_cv.save()

    projection.content_version = new_cv
    projection.save(update_fields=["content_version", "updated_at"])
    return new_cv


def copy_to(user, source_version, target_projections):
    """
    For each target projection, mint an INDEPENDENT new ContentVersion copied
    from source_version and repoint that projection's FK at its own copy.

    N targets → N independent rows (so each target can diverge independently).

    Gate: user must be able to edit the source_version's publishable (can_edit seam).
    All target projections must belong to the same event as source_version
    (ADR-008 D3: fail loud on cross-event data-integrity violation).

    ADR-016 D2 / ADR-008 D3: the new CVs inherit the publishable scope of the
    source version (event or post).

    Returns the list of new ContentVersions (in target order).
    """
    from syndication.models import ContentVersion

    _gate_can_edit_for_cv(user, source_version)

    # Resolve source_version's owning event for cross-publishable guard.
    if source_version.event_id is not None:
        source_event = source_version.event
    elif source_version.post_id is not None:
        source_event = source_version.post.event
    else:
        raise ValueError(
            f"copy_to: source_version {source_version.pk!r} has neither event "
            "nor post FK — check constraint violation. (ADR-008 D3: fail loud)"
        )

    # Guard: all targets must belong to the same event as source_version.
    # Cross-event repointing is a data-integrity violation — fail loud before
    # any DB mutation (ADR-008 D3).
    for proj in target_projections:
        proj_event = _resolve_projection_event(proj)
        if proj_event != source_event:
            raise ValueError(
                f"copy_to: target projection {proj.pk!r} belongs to event "
                f"{proj_event.pk!r} but source_version {source_version.pk!r} "
                f"belongs to event {source_event.pk!r}. "
                "All targets must belong to the same event as source_version. "
                "(ADR-008 D3: fail loud — cross-event data-integrity violation)"
            )

    new_versions = []
    for proj in target_projections:
        # Preserve publishable scope: post-owned source → new CV has post FK set.
        new_cv = ContentVersion(
            event=source_version.event,
            post=source_version.post,
            name=_unique_copy_name(source_version.name),
            provenance=source_version.provenance,
        )
        _copy_cv_fields(source_version, new_cv)
        new_cv.save()
        proj.content_version = new_cv
        proj.save(update_fields=["content_version", "updated_at"])
        new_versions.append(new_cv)

    return new_versions


def customize(user, projection):
    """
    Duplicate the projection's CURRENT version into the projection's OWN new row
    and repoint the FK at it (opt-in divergence).

    Gate: user must be able to edit the projection's event (can_edit seam).

    Returns the new ContentVersion (the customized row).

    Semantics: after customize, editing the new row is isolated — it does not
    affect sibling projections that still share the original (canonical) version.
    This is the core single-row-sharing divergence primitive.
    """
    return copy_from(user, projection, projection.content_version)


def reset_to_canonical(user, projection):
    """
    Repoint the projection's FK back at the publishable's canonical ContentVersion
    (pure FK assignment, NO new row; re-enters single-row sharing).

    Gate: user must be able to edit the projection's event (can_edit seam).

    For listing projections: resolves the event's canonical.
    For promotion projections: resolves the POST's canonical (NOT the event's —
    ADR-016 D2, ADR-008 D3: post-owned versions must never silently collapse to
    the event's canonical).

    Fetch-or-raise: a missing canonical is a violated A1 invariant. This is
    a data bug — fail loud (ADR-008 D3), do NOT silently create a new row.

    If a customized version row is left with zero consumers after reset, it is
    left in place (GC is out of scope per kb-wz8m.3 acceptance).
    """
    from syndication.authz import can_edit
    from syndication.models import ContentVersion, PlatformProjection

    event = _resolve_projection_event(projection)
    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot reset projection {projection.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )

    if projection.kind == PlatformProjection.Kind.PROMOTION:
        # Promotion: resolve the POST's canonical, not the event's.
        # ADR-016 D2 / ADR-008 D3: a promotion projection belongs to a Post;
        # resetting it to the event's canonical would be a silent wrong target.
        post = projection.source_post
        if post is None:
            raise ValueError(
                f"reset_to_canonical: promotion projection {projection.pk!r} has no "
                "source_post. (ADR-008 D3: fail loud)"
            )
        try:
            canonical_cv = ContentVersion.objects.get(post=post, name="canonical")
        except ContentVersion.DoesNotExist as exc:
            raise ValueError(
                f"reset_to_canonical: post {post.pk!r} has no canonical "
                "ContentVersion. A1 invariant violated — every post must be "
                "seeded with a canonical version at creation. "
                "(ADR-008 D3: fail loud — missing canonical is a data bug)"
            ) from exc
    else:
        # Listing: resolve the event's canonical.
        try:
            canonical_cv = ContentVersion.objects.get(event=event, name="canonical")
        except ContentVersion.DoesNotExist as exc:
            raise ValueError(
                f"reset_to_canonical: event {event.pk!r} has no canonical "
                "ContentVersion. A1 invariant violated — every event must be "
                "seeded with a canonical version at creation. "
                "(ADR-008 D3: fail loud — missing canonical is a data bug)"
            ) from exc

    projection.content_version = canonical_cv
    projection.save(update_fields=["content_version", "updated_at"])


def edit_version(user, version, **fields):
    """
    Mutate a pre-publish version's editorial fields; set provenance=manual on
    human edit.

    Gate: user must be able to edit the version's event (can_edit seam).

    Propagates to ALL projections sharing the row (single-row shared-edit —
    that IS the v0 default).

    Guard (ADR-008 D3 fail loud): raises ValueError if ANY consumer projection
    is in a non-draft status (ready, published, or failed have frozen content
    — render_projection returns frozen_content["body"] for them, so they are
    fully isolated from version edits by design (A2 freeze)).

    Guard: blocked ONLY when ALL consumer projections are non-draft (every
    consumer is frozen; no live reader exists). A mixed state (at least one
    draft consumer) is always permitted — frozen consumers are unaffected.

    Only known editorial fields (_CV_EDITORIAL_FIELDS) are applied; unknown
    kwargs are silently ignored (forward-compatible).

    Returns the updated ContentVersion.
    """
    from syndication.models import ContentVersion, PlatformProjection

    _gate_can_edit_for_cv(user, version)

    # Guard: blocked only when EVERY consumer is non-draft (ADR-008 D3).
    # Frozen consumers are isolated (render returns frozen_content["body"]);
    # at least one draft consumer means the live row is still being read.
    all_consumers = list(version.projections.all())
    if all_consumers:
        draft_consumers = [
            p for p in all_consumers
            if p.status == PlatformProjection.Status.DRAFT
        ]
        if not draft_consumers:
            non_draft_pks = [p.pk for p in all_consumers]
            raise ValueError(
                f"Cannot edit ContentVersion {version.pk!r}: "
                f"ALL consumer projections {non_draft_pks!r} are non-draft "
                "(ready/published/failed). Every consumer has frozen content. "
                "(ADR-008 D3: fail loud — no live readers of this version)"
            )

    update_fields = []
    for field, value in fields.items():
        if field in _CV_EDITORIAL_FIELDS:
            setattr(version, field, value)
            update_fields.append(field)

    if update_fields:
        version.provenance = ContentVersion.Provenance.MANUAL
        update_fields.extend(["provenance", "updated_at"])
        version.save(update_fields=update_fields)

    return version


def approve_projection(user, projection):
    """
    Approve a draft projection: transition draft→ready, freeze content.

    Gate: user must be able to edit the projection's event (can_edit seam,
    ADR-017 D2). Edit authority is sufficient for approve at v0.

    Delegates to transition_status (ADR-016 D5 — sole production status-writer).
    transition_status freezes frozen_content at draft→ready.

    Raises PermissionError if user lacks edit authority.
    Raises ValueError if the transition is illegal (not in LEGAL_TRANSITIONS).
    """
    from syndication.authz import can_edit

    event = _resolve_projection_event(projection)
    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot approve projection {projection.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )

    from syndication.engine import transition_status
    transition_status(projection, "ready")
    return projection


def publish_projection(user, projection):
    """
    Publish a ready projection by routing to the correct platform adapter.

    EXPLICIT action — never auto-triggers on approve (ADR-016 D5).

    Platform dispatch (ADR-008 D2: thin dict map, NOT a base-class/plugin
    registry — simplest thing that works, one clear path):
    - "switch"   → publish_switch_own_page(projection)  — real URL resolution,
                   auto-confirms (ready→published inside the adapter).
    - "telegram" → publish_telegram_promotion(projection) — real Bot API send,
                   auto-confirms + stamps message_id (adapter owns transition).
    - "fetlife"  (and any no-API platform) → mark_projection_published path —
                   actor-attested, out-of-band. FetLife has NO send adapter,
                   so publish_projection calls transition_status directly as
                   the attestation that the organizer posted manually.
                   Push platforms (switch/telegram) delegate the transition to
                   their adapter — publish_projection does NOT call
                   transition_status for those (double-transition is a bug).
    - unknown    → ValueError (ADR-008 D3: fail loud, no silent fallback).

    Gate: user must be able to publish the projection's event (can_publish seam,
    ADR-017 D2).

    Raises PermissionError if user lacks publish authority.
    Raises ValueError for unknown platform or illegal transition.
    """
    from syndication.authz import can_publish

    event = _resolve_projection_event(projection)
    if not can_publish(user, event):
        raise PermissionError(
            f"User {user} cannot publish projection {projection.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )

    # Precondition: projection must be in ready status before dispatch.
    # Fail loud here (ADR-008 D3) — do NOT delegate a non-ready projection to
    # an adapter (the adapter would also raise, but we gate early so the
    # error message is clear and no adapter side-effect occurs).
    from syndication.models import PlatformProjection as _PP
    if projection.status != _PP.Status.READY:
        raise ValueError(
            f"publish_projection requires status=ready; "
            f"got status={projection.status!r} for projection {projection.pk!r}. "
            "Advance the projection to ready before publishing. "
            "(ADR-008 D3 — fail loud)"
        )

    # Thin platform→callable map (ADR-008 D2).
    # Push-API platforms: adapter owns the ready→published transition + stamps.
    # No-API platforms (fetlife): attestation path — transition_status called
    # directly here (same as mark_projection_published), re-using the already-
    # gated auth from above. Do NOT double-call transition_status for push
    # platforms — the adapters own that transition.
    platform = projection.connection.platform

    # --- Push-API platforms ---
    if platform == "switch":
        publish_switch_own_page(projection)
    elif platform == "telegram":
        publish_telegram_promotion(projection)
    # --- No-API / manual-assisted platforms (attestation path) ---
    elif platform == "fetlife":
        # Route to the attestation path: engine transition directly.
        # Same as what mark_projection_published does, but we skip the outer
        # can_publish re-check (already gated above).
        from syndication.engine import transition_status
        transition_status(projection, "published")
    # --- Unknown platform: fail loud (ADR-008 D3) ---
    else:
        raise ValueError(
            f"publish_projection: unknown platform {platform!r} for projection "
            f"{projection.pk!r}. Add a dispatch entry for this platform. "
            "(ADR-008 D3 — fail loud, no silent fallback)"
        )

    return projection


def mark_projection_published(user, projection):
    """
    Mark a projection as published (actor-attested, out-of-band posting).

    Used for no-API platforms (e.g. FetLife) where the organizer copies
    content and posts manually, then attests via this action.

    This is a CO-EQUAL API verb (in syndication/api.py) — an agent calls the
    same service function the HTMX view button calls. It is NOT a UI-only button.

    Gate: user must be able to publish the projection's event (can_publish seam).

    Raises PermissionError if user lacks publish authority.
    Raises ValueError if the transition is illegal (e.g. not in ready state).

    ADR-016 D5: transition goes through transition_status exclusively.
    ADR-016 D6: co-equal seam — identical logic for API and UI paths.
    """
    from syndication.authz import can_publish

    event = _resolve_projection_event(projection)
    if not can_publish(user, event):
        raise PermissionError(
            f"User {user} cannot mark projection {projection.pk!r} as published "
            f"(event '{event}'). (ADR-017 D2)"
        )

    from syndication.engine import transition_status
    transition_status(projection, "published")
    return projection


def publish_all_ready_projections(user, event):
    """
    Batch-publish every ready projection for the given event.

    Collects both listing projections (source_event) and promotion projections
    (via Posts linked to the event) that are in 'ready' status, then routes
    each through publish_projection (which dispatches to the correct platform
    adapter or attestation path).

    Gate: user must be able to publish the event (can_publish seam, ADR-017 D2).
    Raises PermissionError if user lacks publish authority.
    Skips non-ready projections (they're simply not eligible).

    Returns (published, failures) where failures is a list of (proj, exc) tuples.
    Per-item adapter failures are collected (publish the rest) — ADR-008 D3.

    Co-equal seam (ADR-016 D6): called by both the HTMX view and the Ninja API verb.
    """
    from syndication.authz import can_publish
    from syndication.models import PlatformProjection, Post
    from itertools import chain

    if not can_publish(user, event):
        raise PermissionError(
            f"User {user} cannot publish projections for event '{event}'. "
            "(ADR-017 D2)"
        )

    listing_ready = PlatformProjection.objects.filter(
        source_event=event, status=PlatformProjection.Status.READY
    )
    post_ids = Post.objects.filter(event=event).values_list("pk", flat=True)
    promotion_ready = PlatformProjection.objects.filter(
        source_post_id__in=post_ids, status=PlatformProjection.Status.READY
    )
    ready_projections = list(chain(listing_ready, promotion_ready))

    published = []
    failures = []
    for proj in ready_projections:
        try:
            publish_projection(user, proj)
            published.append(proj)
        except ValueError as exc:
            # ADR-008 D3: collect per-item ValueError (adapter data/transport
            # failure) so one channel failing doesn't abort the batch.
            # Caller is responsible for surfacing failures as a visible error state.
            # PermissionError and unexpected exceptions propagate (fail loud).
            failures.append((proj, exc))

    return published, failures


def publish_all_ready_projections_for_post(user, post):
    """
    Batch-publish every ready promotion projection for the given post.

    Scoped to a single Post publishable — only publishes ready projections
    with source_post=post. Does NOT touch listing projections or projections
    of sibling posts under the same event.

    Gate: user must be able to publish the post's event (can_publish seam,
    ADR-017 D2). Raises PermissionError if user lacks publish authority.

    Returns (published, failures) where failures is a list of (proj, exc) tuples.
    Per-item adapter failures are collected (publish the rest) — ADR-008 D3.

    Co-equal seam (ADR-016 D6): called by the HTMX view and usable from the API.
    """
    from syndication.authz import can_publish
    from syndication.models import PlatformProjection

    event = post.event
    if not can_publish(user, event):
        raise PermissionError(
            f"User {user} cannot publish projections for post '{post}' "
            f"(event '{event}'). (ADR-017 D2)"
        )

    ready_projections = list(
        PlatformProjection.objects.filter(
            source_post=post, status=PlatformProjection.Status.READY
        )
    )

    published = []
    failures = []
    for proj in ready_projections:
        try:
            publish_projection(user, proj)
            published.append(proj)
        except ValueError as exc:
            # ADR-008 D3: collect per-item ValueError so one channel failing
            # does not abort the batch. Caller surfaces failures as visible error.
            # PermissionError and unexpected exceptions propagate (fail loud).
            failures.append((proj, exc))

    return published, failures
