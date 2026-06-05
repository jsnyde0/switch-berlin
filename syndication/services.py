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
                AgentPairingToken.objects.select_for_update().select_related("user").get(token_hash=token_hash)
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

    claim = ProfileClaim.objects.filter(user=user, rejected_at__isnull=True).select_related("profile").first()
    if claim is None:
        raise ValueError(
            f"User {user} has no active ProfileClaim. Cannot create Event without an organizer profile (ADR-017 D1)."
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

    # Fetch full Event objects for the profile (no visibility filter — ADR-012).
    # .distinct() guards against duplicate rows from the organizers M2M join
    # (EventOrganizer has no (event, profile) unique constraint).
    event_qs = list(Event.objects.filter(organizers=profile).distinct())
    # Posts for all events belonging to this profile; .distinct() because the
    # event__organizers M2M join can otherwise repeat a Post.
    post_qs = list(Post.objects.filter(event__organizers=profile).distinct())

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
    organizer_profile_ids = EventOrganizer.objects.filter(event=event).values_list("profile_id", flat=True)

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


# ---------------------------------------------------------------------------
# Platform capability: which platforms support promotion projections for posts
# ---------------------------------------------------------------------------
#
# ADR-010 D1 + ADR-008 D3: Switch does not yet support post/promotion publishing,
# so no switch promotion projection should be minted for posts.
# This is a capability-aware gate, NOT a hard permanent ban — when Switch posting
# ships, removing 'switch' from this set is the cheap flip (ADR-003).
#
# Platforms absent from this set are skipped at promotion-projection minting time.
# A platform NOT listed here is implicitly capable (opt-out rather than opt-in),
# so adding new platforms doesn't require updating this set.
_PLATFORMS_WITHOUT_POST_PROMOTION = frozenset({"switch"})


def _supports_post_promotion(platform: str) -> bool:
    """Return True if the platform supports post promotion projections."""
    return platform not in _PLATFORMS_WITHOUT_POST_PROMOTION


def _eager_create_promotion_projections(post, canonical_cv=None):
    """
    ADR-016 D4: For each enabled PlatformConnection that supports 'promotion'
    owned by the post's event's organizer profiles, create a draft PlatformProjection.

    Called after a Post is saved. Projections FK to the POST's canonical
    ContentVersion (ADR-016 D2), not the event's canonical.

    canonical_cv is passed in to avoid redundant DB round-trips; must be the
    POST's canonical (post FK set, event FK null).

    ADR-010 D1 + ADR-008 D3: platforms in _PLATFORMS_WITHOUT_POST_PROMOTION
    (currently: switch) are skipped even if their connection has 'promotion'
    in kinds — Switch does not support post promotion yet. When Switch posting
    ships, remove 'switch' from _PLATFORMS_WITHOUT_POST_PROMOTION (cheap flip,
    ADR-003).
    """
    import logging as _logging

    from events.models import EventOrganizer
    from syndication.models import PlatformConnection, PlatformProjection

    _logger = _logging.getLogger(__name__)

    if canonical_cv is None:
        canonical_cv = _ensure_canonical_content_version(post=post)

    # Get all organizer Profile IDs for this post's event
    organizer_profile_ids = EventOrganizer.objects.filter(event=post.event).values_list("profile_id", flat=True)

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
        # ADR-010 D1 capability gate: skip platforms that don't support post promotion yet.
        if not _supports_post_promotion(conn.platform):
            _logger.info(
                "_eager_create_promotion_projections: skipping %r connection %r "
                "— platform does not support post promotion (ADR-010 D1). "
                "Remove from _PLATFORMS_WITHOUT_POST_PROMOTION when Switch posting ships.",
                conn.platform,
                conn.pk,
            )
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
        raise PermissionError(f"User {user} cannot edit event '{event}' (ADR-017 D1/D2).")

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
    from events.models import EventImage
    from syndication.authz import can_edit

    if not can_edit(user, event):
        raise PermissionError(f"User {user} cannot set cover image for event '{event}' (ADR-017 D2).")

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
        raise PermissionError(f"User {user} cannot create a post for event '{event}' (ADR-017 D1/D2).")

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
        raise PermissionError(f"User {user} cannot update post '{post}' (ADR-017 D1/D2).")

    update_fields = []
    for field, value in kwargs.items():
        if field in _POST_FIELDS:
            setattr(post, field, value)
            update_fields.append(field)

    if update_fields:
        post.save(update_fields=update_fields)

    return post


# ---------------------------------------------------------------------------
# Edit-after-publish policy seam (ADR-016 D5, ADR-003 cheap foresight)
#
# v0 applies the dirty-marker uniformly: editing a published projection's
# ContentVersion marks it "dirty" (is_dirty=True on the model property) and
# re-publish is an explicit act. Future platforms that cannot be edited after
# posting (e.g. a no-edit-API channel) will resolve a different policy here —
# a value change in ONE place, not a rewrite of the dirty logic.
#
# This is the SINGLE named resolution point (grep "edit_after_publish_policy"
# must find exactly ONE def site — here). Callers import this function; they
# do NOT inline the policy logic.
# ---------------------------------------------------------------------------


def edit_after_publish_policy(platform: str) -> str:
    """
    Resolve the edit-after-publish behaviour for a given platform.

    Returns a policy string consumed by the dirty-marker / publish path:
      "dirty_then_republish" — editing a published channel marks it dirty;
                               re-publish is an explicit act that re-freezes
                               frozen_content (the v0 default for all platforms).

    Future values (ADR-008 D2 — do NOT implement these now; only make the seam):
      "lock"                — editing is disabled for published channels (e.g.
                              a platform with no edit API where a second post
                              would duplicate, not update, the content).
      "auto_rebroadcast"   — editing automatically re-pushes to the platform
                              (e.g. a platform with a safe in-place edit API).

    ADR-003 cheap foresight: the seam is here so a future per-platform "lock"
    is a value-change in this lookup, NOT a rewrite of every dirty code path.
    ADR-008 D2: do NOT add branches for the alternate behaviours now (no first
    caller). Just return the v0 default for all platforms.
    """
    # v0: all platforms → dirty_then_republish (single value, no branching needed).
    # When a platform needs a different policy, add it as a lookup entry here
    # (e.g. _PLATFORM_EDIT_AFTER_PUBLISH_POLICY = {"fetlife-no-api": "lock"}).
    return "dirty_then_republish"


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
            raise ValueError(f"Listing projection {projection.pk!r} has no source_event. (ADR-008 D3: fail loud)")
        return projection.source_event
    if projection.kind == PlatformProjection.Kind.PROMOTION:
        if projection.source_post is None:
            raise ValueError(f"Promotion projection {projection.pk!r} has no source_post. (ADR-008 D3: fail loud)")
        return projection.source_post.event
    raise ValueError(
        f"Unknown projection kind {projection.kind!r} for projection {projection.pk!r}. (ADR-008 D3: fail loud)"
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
            f"User {user} cannot edit ContentVersion {content_version.pk!r} (event '{event}'). (ADR-017 D2)"
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
        versions = ContentVersion.objects.filter(event=event).prefetch_related("projections")
    elif post is not None and event is None:
        versions = ContentVersion.objects.filter(post=post).prefetch_related("projections")
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
        raise PermissionError(f"User {user} cannot edit projection {projection.pk!r} (event '{event}'). (ADR-017 D2)")

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


def sync_projection_from(user, target, source):
    """
    Sync a target projection FROM a source projection (kb-ide0.4 D4).

    Mechanism: snapshot + persisted pointer (ADR-016 D2 evolved):
    1. Cycle guard (ADR-008 D3 fail-loud): RAISE if source.sync_source is non-null.
       A projection is a legal sync source iff its own sync_source IS NULL.
       This prevents A→B→C chains (which would create implicit transitive coupling).
    2. Copy source's CURRENT content_version into target as an INDEPENDENT new row
       (calls the existing copy_from op).
    3. Set target.sync_source = source (persisted pointer for reload survival + UI state).

    NO live propagation: source edits after this call do NOT flow to target.
    This is intentional — ToS-divergent destinations want divergence.

    Gate: user must be able to edit target's event (can_edit seam via copy_from).

    Returns the new ContentVersion minted for the target.
    """
    # Cycle guard (ADR-008 D3 — fail loud, backend-enforced, not UI-only).
    if source.sync_source_id is not None:
        raise ValueError(
            f"sync_projection_from: source projection {source.pk!r} already has "
            f"sync_source={source.sync_source_id!r}. "
            "A projection is only a legal sync source when its own sync_source IS NULL. "
            "This prevents cycle chains (A→B→C transitive coupling). "
            "(ADR-008 D3: fail loud — cycle guard, backend-enforced)"
        )

    # One-time snapshot: copy source's current content_version to target.
    new_cv = copy_from(user=user, projection=target, source_version=source.content_version)

    # Persist the pointer so the state survives reload.
    target.sync_source = source
    target.save(update_fields=["sync_source", "updated_at"])

    return new_cv


def detach_sync_source(projection):
    """
    Detach a projection from its sync source — clear sync_source to None.

    Called when the user edits a synced channel (no confirm required; the
    content_version already has its own independent row from the original
    copy_from — detach just records that the link is broken).

    No auth gate here: this is called from the edit flow which is already
    gated (edit_version / event_hub_edit call can_edit). Detach is a
    lightweight metadata clear, not a destructive op.

    Returns the projection (updated in-place, not refreshed).
    """
    projection.sync_source = None
    projection.save(update_fields=["sync_source", "updated_at"])
    return projection


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
        raise PermissionError(f"User {user} cannot reset projection {projection.pk!r} (event '{event}'). (ADR-017 D2)")

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


def edit_version(user, version, _allow_edit_after_publish=False, **fields):
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

    _allow_edit_after_publish=True: skip the "all-consumers-non-draft" guard.
    Used by detach_and_edit (kb-kgza.2) when the newly-detached CV's single
    consumer is published (ADR-016 D5 edit-after-publish). The edit dirties
    the projection; frozen_content (the published snapshot) is unchanged, so
    there is no silent corruption. Fail loud only on genuine corruption.

    Only known editorial fields (_CV_EDITORIAL_FIELDS) are applied; unknown
    kwargs are silently ignored (forward-compatible).

    Returns the updated ContentVersion.
    """
    from syndication.models import ContentVersion, PlatformProjection

    _gate_can_edit_for_cv(user, version)

    # Guard: blocked only when EVERY consumer is non-draft (ADR-008 D3).
    # Frozen consumers are isolated (render returns frozen_content["body"]);
    # at least one draft consumer means the live row is still being read.
    # Exception: _allow_edit_after_publish=True skips this guard for the
    # detach-and-edit-published path (ADR-016 D5 — dirty, but not corrupt).
    if not _allow_edit_after_publish:
        all_consumers = list(version.projections.all())
        if all_consumers:
            draft_consumers = [p for p in all_consumers if p.status == PlatformProjection.Status.DRAFT]
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


def detach_and_edit(user, projection, **fields):
    """
    Customize-then-edit for a per-channel projection (kb-kgza.2).

    Used when a promotion or listing projection is in state (i) — sharing the
    canonical CV (content_version.name == 'canonical', sync_source NULL) — and
    the user edits the body on that channel's tab. The expected semantics per
    ADR-016 D2 are:

      editing a per-channel tab AUTO-DETACHES it to an independent version.

    Idempotent (FIX A, kb-kgza.2): if the projection is ALREADY on its own
    independent CV (sole consumer, not the canonical), edit IN PLACE via
    edit_version — do NOT call customize again (which would mint a new orphaned
    CV on every autosave keystroke-batch).

    The "needs detach" condition: the projection's current CV is shared —
    either it IS the canonical (name == 'canonical') OR it has more than one
    consumer projection. Any of these cases means a customize is required
    before editing.

    FIX B (kb-kgza.2): if the projection has sync_source set (state ii: own CV
    + sync_source SET), clear it after detach so the result is a clean state-iii
    (own CV + sync_source NULL), as ADR-016 D2 mandates.

    Procedure:
    1. If the projection shares its CV (state i or multi-consumer), call
       customize(user, projection) — mints a new independent CV, repoints the
       FK. Clear sync_source if set (→ state iii).
    2. If already on its own independent CV (state iii), skip customize.
       Clear sync_source if set (state ii → state iii).
    3. Call edit_version(user, cv, **fields) — applies body/headline/etc. edits.
       Passes _allow_edit_after_publish=True so the guard does not trip when the
       projection is published (ADR-016 D5: editing a published projection
       dirties it but does NOT corrupt frozen_content).

    Returns: (cv, updated_projection) after the full detach-and-edit.

    Gate: inherited from customize (can_edit check) and edit_version (same gate).
    ADR-008 D3: no silent fallback — both steps raise on invalid input.
    """
    current_cv = projection.content_version

    # Determine whether a customize (mint new CV) is needed.
    # Need to detach when the CV is shared:
    #   - it is the canonical (name == 'canonical') — always shared by design, OR
    #   - it has more than one consumer projection — siblings still share it.
    # If neither condition holds, the projection already owns its own independent CV.
    consumer_count = current_cv.projections.count()
    needs_customize = current_cv.name == "canonical" or consumer_count > 1

    if needs_customize:
        cv = customize(user, projection)
        # Refresh so content_version FK resolves to the newly minted CV.
        projection.refresh_from_db()
    else:
        # Already on an independent CV — edit in place, no new row.
        cv = current_cv

    # FIX B: clear sync_source if set (state ii → state iii).
    # ADR-016 D2: detached = own CV + sync_source NULL.
    if projection.sync_source_id is not None:
        detach_sync_source(projection)

    edit_version(user, cv, _allow_edit_after_publish=True, **fields)
    return cv, projection


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
            f"User {user} cannot approve projection {projection.pk!r} (event '{event}'). (ADR-017 D2)"
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
            f"User {user} cannot publish projection {projection.pk!r} (event '{event}'). (ADR-017 D2)"
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


def republish_projection(user, projection):
    """
    Re-publish a dirty published projection (ADR-016 D5 edit-after-publish).

    When a published projection's ContentVersion has been edited (making it dirty),
    the facilitator must explicitly re-publish to update the live post. This verb:
      1. Re-materializes frozen_content (captures the current effective content).
      2. Saves the updated frozen_content (status stays 'published').
      3. Re-dispatches to the platform adapter for push-API platforms, OR records
         the re-freeze as an attestation update for no-API platforms.

    Gate: user must be able to publish the projection's event (can_publish seam).

    ADR-016 D5: re-publish is EXPLICIT — never automatic on edit.
    ADR-008 D3: fail loud if projection is not 'published' (wrong verb for
                non-published projections).
    ADR-016 D6: co-equal seam — callable by both HTMX views and the Ninja API.
    """
    from syndication.authz import can_publish
    from syndication.engine import _materialize_effective_fields
    from syndication.models import PlatformProjection as _PP

    event = _resolve_projection_event(projection)
    if not can_publish(user, event):
        raise PermissionError(
            f"User {user} cannot re-publish projection {projection.pk!r} (event '{event}'). (ADR-017 D2)"
        )

    if projection.status != _PP.Status.PUBLISHED:
        raise ValueError(
            f"republish_projection requires status=published; "
            f"got status={projection.status!r} for projection {projection.pk!r}. "
            "Use publish_projection_direct for first-publish of draft/ready rows. "
            "(ADR-008 D3 — fail loud)"
        )

    # Re-materialize: capture the current effective content into frozen_content.
    # This is the re-freeze step that makes the dirty projection clean again.
    new_frozen = _materialize_effective_fields(projection)
    projection.frozen_content = new_frozen
    projection.save(update_fields=["frozen_content", "updated_at"])

    # Re-dispatch to platform adapter for push-API platforms.
    # For push-API: the adapter re-sends the content (implementation deferred —
    # per-adapter edit-in-place API is a future optimization per ADR-016 D5).
    # For now: re-freeze is the source-of-truth update; the push adapters would
    # need explicit "update post" API calls not yet implemented.
    # No-API platforms (fetlife): the re-freeze IS the re-publish attestation —
    # the facilitator has already re-posted manually and calls this to update
    # Switch's record of what's live.
    # v0 implementation: re-freeze only (frozen_content updated above).
    # The platform-specific push is a per-adapter follow-up (ADR-008 D2: no first caller).

    return projection


def publish_projection_direct(user, projection):
    """
    Direct-publish: drive the internal draft→ready→published two-step transparently,
    OR re-publish a dirty published projection.

    Solo-flow CTA (kb-ide0.2 D6): the user sees one Publish / Re-publish button;
    this service drives the correct path based on current status.

    - If projection is 'draft': call approve_projection (draft→ready, freezes
      frozen_content), THEN publish_projection (ready→published).
    - If projection is already 'ready': call publish_projection directly (freeze
      already happened at approve time).
    - If projection is 'published' (dirty — edited after publish): call
      republish_projection (re-freezes frozen_content, ADR-016 D5).
    - If projection is in any other status: delegate to publish_projection which
      will raise ValueError via the engine (ADR-008 D3 — fail loud).

    The three-state engine model (_LEGAL_TRANSITIONS) is UNCHANGED; this service
    sequences the existing service calls for the common solo case.

    ADR-008 D3: frozen_content is NEVER null on a published row — the approve
    step materializes it before the publish step runs.

    Raises PermissionError if user lacks edit or publish authority.
    Raises ValueError if the transition is illegal (engine invariant).
    """
    from syndication.models import PlatformProjection as _PP

    if projection.status == _PP.Status.PUBLISHED:
        # Re-publish path: dirty published projection → re-freeze frozen_content.
        # ADR-016 D5: explicit re-publish is the only way to update the live post.
        return republish_projection(user=user, projection=projection)

    if projection.status == _PP.Status.DRAFT:
        # Step 1: draft → ready (materializes frozen_content)
        approve_projection(user=user, projection=projection)
        # projection is now in 'ready' status; frozen_content is set

    # Step 2: ready → published (or raises if status is unexpected)
    publish_projection(user=user, projection=projection)
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
            f"User {user} cannot mark projection {projection.pk!r} as published (event '{event}'). (ADR-017 D2)"
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
    from itertools import chain

    from syndication.authz import can_publish
    from syndication.models import PlatformProjection, Post

    if not can_publish(user, event):
        raise PermissionError(f"User {user} cannot publish projections for event '{event}'. (ADR-017 D2)")

    listing_ready = PlatformProjection.objects.filter(source_event=event, status=PlatformProjection.Status.READY)
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


# ---------------------------------------------------------------------------
# Post-hoc projection reconciliation (kb-96tn.4, ADR-016 D4)
#
# add_projection(publishable, connection): mint a draft PlatformProjection for
# an existing Event/Post × connection IF none exists; idempotent; fail loud on
# wrong-kind (ADR-008 D3); never delete/overwrite a published projection.
#
# reconcile_projections(publishable): fan add_projection across all enabled
# connections for the publishable's organizer profiles, returning newly created
# projections. Co-equal service verbs (ADR-016 D3): callable by both UI and
# a future API.
# ---------------------------------------------------------------------------


def _publishable_kind(publishable):
    """
    Return the applicable projection kind for a publishable.

    An Event publishable maps to 'listing'; a Post publishable maps to 'promotion'.
    Fail loud if the publishable is neither (ADR-008 D3).
    """
    from events.models import Event
    from syndication.models import PlatformProjection, Post

    if isinstance(publishable, Event):
        return PlatformProjection.Kind.LISTING
    if isinstance(publishable, Post):
        return PlatformProjection.Kind.PROMOTION
    raise ValueError(
        f"add_projection: publishable must be an Event or Post, got {type(publishable)!r}. "
        "(ADR-008 D3: fail loud — unknown publishable type)"
    )


def _get_organizer_profile_ids_for_publishable(publishable):
    """
    Return the list of organizer Profile IDs for a publishable (Event or Post).

    For Events: from EventOrganizer through-table.
    For Posts: via the post's Event → EventOrganizer.
    Fail loud if the publishable type is unknown (ADR-008 D3).
    """
    from events.models import Event, EventOrganizer
    from syndication.models import Post

    if isinstance(publishable, Event):
        return list(EventOrganizer.objects.filter(event=publishable).values_list("profile_id", flat=True))
    if isinstance(publishable, Post):
        return list(EventOrganizer.objects.filter(event=publishable.event).values_list("profile_id", flat=True))
    raise ValueError(
        f"_get_organizer_profile_ids_for_publishable: unknown publishable type {type(publishable)!r}. "
        "(ADR-008 D3: fail loud)"
    )


def add_projection(publishable, connection):
    """
    Mint a draft PlatformProjection for an existing Event/Post × connection.

    ADR-016 D4 (post-hoc projection reconciliation) + ADR-008 D3 (fail loud):

    - Idempotent: if a projection already exists for this (publishable, connection)
      pair, return the existing one WITHOUT creating a duplicate. This covers the
      case where the projection is published — published projections are NEVER
      touched, deleted, or overwritten.
    - Raises ValueError (fail loud) if the connection's kinds do not include the
      applicable kind for the publishable:
        Event → must include 'listing'
        Post  → must include 'promotion'
    - Wires the new projection to the canonical ContentVersion + the same defaults
      the eager-fan path uses (status=draft, canonical_cv FK).

    Co-equal service verb (ADR-016 D3): callable by both the UI and a future API.
    """
    from events.models import Event
    from syndication.models import PlatformProjection

    applicable_kind = _publishable_kind(publishable)

    # Fail loud on wrong-kind (ADR-008 D3): the connection must support the
    # applicable kind for this publishable. A telegram-promotion-only connection
    # cannot be used for an Event listing, and a switch-listing-only connection
    # cannot be used for a Post promotion.
    kinds = connection.kinds or []
    kind_value = applicable_kind.value if hasattr(applicable_kind, "value") else str(applicable_kind)
    if kind_value not in kinds:
        raise ValueError(
            f"add_projection: connection {connection.pk!r} (platform={connection.platform!r}, "
            f"kinds={kinds!r}) does not support kind={kind_value!r} required by "
            f"{type(publishable).__name__} publishable {getattr(publishable, 'pk', None)!r}. "
            "(ADR-008 D3: fail loud — wrong-kind mismatch)"
        )

    # Build the filter kwargs for the (publishable, connection) pair lookup.
    if isinstance(publishable, Event):
        lookup_kwargs = {"source_event": publishable, "connection": connection}
    else:  # Post
        lookup_kwargs = {"source_post": publishable, "connection": connection}

    # Idempotency check: return existing projection if it already exists.
    # This covers all statuses including published — never delete/overwrite.
    existing = PlatformProjection.objects.filter(**lookup_kwargs).first()
    if existing is not None:
        return existing

    # No existing projection — mint a new draft.
    # Wire to the canonical ContentVersion (A1 seed, parallel to eager-fan path).
    if isinstance(publishable, Event):
        canonical_cv = _ensure_canonical_content_version(event=publishable)
        return PlatformProjection.objects.create(
            connection=connection,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=publishable,
            content_version=canonical_cv,
        )
    else:  # Post
        canonical_cv = _ensure_canonical_content_version(post=publishable)
        return PlatformProjection.objects.create(
            connection=connection,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=publishable,
            content_version=canonical_cv,
        )


def reconcile_projections(publishable):
    """
    For every enabled PlatformConnection on the publishable's organizer profile(s)
    that supports the applicable kind, call add_projection.

    Returns the list of NEWLY-CREATED projections (existing projections are
    returned by add_projection but filtered out here — callers see only new ones).

    Co-equal service verb (ADR-016 D3): callable by both the UI and a future API.
    Mirrors the eager-fan logic of _eager_create_listing_projections /
    _eager_create_promotion_projections but operates on an existing publishable.

    ADR-008 D3: fail loud on unknown publishable types (via _publishable_kind).
    """
    from syndication.models import PlatformConnection, PlatformProjection

    applicable_kind = _publishable_kind(publishable)
    kind_value = applicable_kind.value if hasattr(applicable_kind, "value") else str(applicable_kind)

    organizer_profile_ids = _get_organizer_profile_ids_for_publishable(publishable)
    if not organizer_profile_ids:
        return []

    connections = PlatformConnection.objects.filter(
        organizer_id__in=organizer_profile_ids,
        enabled=True,
    )

    # Build the set of existing (publishable, connection) projection pairs so we
    # can identify which add_projection calls are new.
    from events.models import Event

    if isinstance(publishable, Event):
        existing_conn_ids = set(
            PlatformProjection.objects.filter(source_event=publishable).values_list("connection_id", flat=True)
        )
    else:  # Post
        existing_conn_ids = set(
            PlatformProjection.objects.filter(source_post=publishable).values_list("connection_id", flat=True)
        )

    newly_created = []
    for conn in connections:
        conn_kinds = conn.kinds or []
        if kind_value not in conn_kinds:
            continue
        # Also apply the post-promotion platform gate (mirrors _eager_create_promotion_projections).
        if kind_value == "promotion" and not _supports_post_promotion(conn.platform):
            continue
        if conn.pk in existing_conn_ids:
            # Already projected — add_projection would return the existing one;
            # we track only newly-created ones so skip here (idempotency path).
            continue
        proj = add_projection(publishable, conn)
        newly_created.append(proj)

    return newly_created


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
            f"User {user} cannot publish projections for post '{post}' (event '{event}'). (ADR-017 D2)"
        )

    ready_projections = list(
        PlatformProjection.objects.filter(source_post=post, status=PlatformProjection.Status.READY)
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
