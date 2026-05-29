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


def _ensure_canonical_content_version(event):
    """
    Ensure a canonical ContentVersion exists for event and return it.

    Creates it with all editorial fields NULL (track-live semantics) if absent.
    This is idempotent: if a canonical version already exists, it is returned as-is.

    ADR-016 D2 (kb-wz8m.2): A1 canonical version is seeded EMPTY.
    NULL editorial fields = derive from live canonical Event at render time.
    """
    from syndication.models import ContentVersion

    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={
            "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
            # All editorial fields intentionally omitted → DB default None
            # (null-means-derive semantics per ADR-016 D2 revised 2026-05-29).
        },
    )
    return cv


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

    Called after a Post is saved.

    All created projections FK to the canonical ContentVersion (A1 seed,
    kb-wz8m.2). canonical_cv is passed in to avoid redundant DB round-trips.
    """
    from events.models import EventOrganizer
    from syndication.models import PlatformConnection, PlatformProjection

    if canonical_cv is None:
        canonical_cv = _ensure_canonical_content_version(post.event)

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

    # A1 seed (kb-wz8m.2): ensure the canonical ContentVersion exists for the
    # event so eager promotion projections can FK to it.
    canonical_cv = _ensure_canonical_content_version(event)

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

    Raises PermissionError if user cannot edit the ContentVersion's event.
    ContentVersion.event is the binding event; we resolve through that.
    """
    from syndication.authz import can_edit
    event = content_version.event
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


def content_version_consumers_map(event):
    """
    Return the per-event aggregate the board reads for the "live on <channels>" cue.

    Shape: {ContentVersion: [PlatformProjection, ...]}

    Maps each ContentVersion for the given event to the list of PlatformProjections
    currently pointing at it. Versions with zero consumers are included (they still
    belong to the event). Versions from other events are excluded.

    kb-wz8m.5 (UI) consumes this for the board's per-version channel summary.
    """
    from syndication.models import ContentVersion, PlatformProjection

    versions = ContentVersion.objects.filter(event=event).prefetch_related("projections")
    result = {}
    for cv in versions:
        result[cv] = list(cv.projections.all())
    return result


def _unique_copy_name(source_name):
    """
    Generate a unique name for a new ContentVersion copied from source_name.

    The (event, name) pair is UNIQUE-constrained; callers creating multiple
    copies of the same source in one operation would collide on a plain
    "copy-of-<name>" slug. A short UUID suffix guarantees uniqueness.
    """
    import uuid as _uuid
    suffix = _uuid.uuid4().hex[:8]
    return f"copy-of-{source_name}-{suffix}"


def duplicate(user, version):
    """
    Create and return a NEW independent ContentVersion seeded (copied) from an
    existing one (same Event, copied editorial fields, fresh row).

    Gate: user must be able to edit the version's event (can_edit seam).

    The new version is not attached to any projection — callers (copy_from,
    copy_to, customize) wire up the FK after calling this.
    """
    from syndication.models import ContentVersion

    _gate_can_edit_for_cv(user, version)

    new_cv = ContentVersion(
        event=version.event,
        name=_unique_copy_name(version.name),
        provenance=version.provenance,
    )
    _copy_cv_fields(version, new_cv)
    new_cv.save()
    return new_cv


def copy_from(user, projection, source_version):
    """
    Repoint the projection at a NEW independent copy taken from source_version
    (mint a new row from source, FK the projection to it).

    Gate: user must be able to edit the projection's event (can_edit seam).
    The original ContentVersion the projection was pointing at is left as-is
    (GC is out of scope).

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

    new_cv = ContentVersion(
        event=source_version.event,
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

    Gate: user must be able to edit the source_version's event (can_edit seam).
    All target projections must belong to the same event as source_version
    (enforced implicitly via the can_edit gate on the shared event).

    Returns the list of new ContentVersions (in target order).
    """
    from syndication.models import ContentVersion

    _gate_can_edit_for_cv(user, source_version)

    new_versions = []
    for proj in target_projections:
        new_cv = ContentVersion(
            event=source_version.event,
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
    Repoint the projection's FK back at the Event's canonical ContentVersion
    (pure FK reassignment, NO new row; re-enters single-row sharing).

    Gate: user must be able to edit the projection's event (can_edit seam).

    Uses _ensure_canonical_content_version to locate the canonical row reliably.
    If a customized version row is left with zero consumers after reset, it is
    left in place (GC is out of scope per kb-wz8m.3 acceptance).
    """
    from syndication.authz import can_edit

    event = _resolve_projection_event(projection)
    if not can_edit(user, event):
        raise PermissionError(
            f"User {user} cannot reset projection {projection.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )

    canonical_cv = _ensure_canonical_content_version(event)
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
    — mutating the version would make the freeze stale / contradict the frozen
    snapshot). Editing a version shared by ANY frozen projection is blocked.

    Only known editorial fields (_CV_EDITORIAL_FIELDS) are applied; unknown
    kwargs are silently ignored (forward-compatible).

    Returns the updated ContentVersion.
    """
    from syndication.models import ContentVersion, PlatformProjection

    _gate_can_edit_for_cv(user, version)

    # Guard: check for any non-draft consumers (ADR-008 D3).
    non_draft_consumers = version.projections.exclude(
        status=PlatformProjection.Status.DRAFT
    )
    if non_draft_consumers.exists():
        non_draft_pks = list(non_draft_consumers.values_list("pk", flat=True))
        raise ValueError(
            f"Cannot edit ContentVersion {version.pk!r}: "
            f"consumer projections {non_draft_pks!r} are not in draft status. "
            "Editing would contradict their frozen content. "
            "(ADR-008 D3: fail loud — no silent mutation of frozen content)"
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
    Publish a ready projection: transition ready→published.

    EXPLICIT action — never auto-triggers on approve (ADR-016 D5).
    For push-API platforms, the actual push lives in an adapter bead; this
    service records the intent and status change. The adapter will call
    mark_projection_published after a successful push.

    Gate: user must be able to publish the projection's event (can_publish seam,
    ADR-017 D2).

    Raises PermissionError if user lacks publish authority.
    Raises ValueError if the transition is illegal.
    """
    from syndication.authz import can_publish

    event = _resolve_projection_event(projection)
    if not can_publish(user, event):
        raise PermissionError(
            f"User {user} cannot publish projection {projection.pk!r} "
            f"(event '{event}'). (ADR-017 D2)"
        )

    from syndication.engine import transition_status
    transition_status(projection, "published")
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
    (via Posts linked to the event) that are in 'ready' status, then transitions
    each to 'published'.

    Gate: user must be able to publish the event (can_publish seam, ADR-017 D2).
    Raises PermissionError if user lacks publish authority.
    Skips non-ready projections (they're simply not eligible).

    Returns the list of projections that were published.

    Co-equal seam (ADR-016 D6): called by both the HTMX view and the Ninja API verb.
    """
    from syndication.authz import can_publish
    from syndication.models import PlatformProjection, Post
    from syndication.engine import transition_status
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
            transition_status(proj, "published")
            published.append(proj)
        except ValueError as exc:
            # ADR-008 D3: fail loud — collect per-item failures, publish the rest.
            # Caller is responsible for surfacing failures as a visible error state.
            failures.append((proj, exc))

    return published, failures
