"""
Syndication engine (kb-a4u.4).

Provides three public callables:
- generate_projection(kind, platform_id, source_event|source_post, mode, body?) → PlatformProjection
- render_projection(proj) → str
- transition_status(proj, new_status) → None (saves in place, raises on illegal transition)

ADR-016 D2: Projections are editable copies, not live views.
    rule_based: body is SNAPSHOTTED at generation time into override_data["body"].
    agent_assisted: agent-supplied body is stored in override_data["body"].
    Either way, override_data["body"] is the stable rendered output; absent "body" key
    means "use canonical" (not applicable post-generation since rule_based always writes
    override_data["body"]).

ADR-012: unlisted Events generate NO external projections (write-side gate).
    This is a WRITE-side gate; the read-side filter lives in events/managers.py.

ADR-008 D3: fail loud — illegal transitions raise ValueError, missing body raises ValueError.
ADR-008 D4: retry policy seam — transport errors get ≤2 retries, data-integrity errors never
    retry. Modelled as status machine (failed state) + policy constants exported here.
    Actual platform push logic lives in separate adapter beads.
"""

from syndication.cleaning import clean_for_platform
from syndication.models import PlatformProjection, Post

# ---------------------------------------------------------------------------
# Status state-machine
# ---------------------------------------------------------------------------

# Legal transitions: (from_status, to_status)
_LEGAL_TRANSITIONS = frozenset(
    [
        ("draft", "ready"),
        ("ready", "published"),
        ("ready", "failed"),
        ("published", "failed"),
        ("failed", "draft"),  # reset for retry
    ]
)


def transition_status(projection: PlatformProjection, new_status: str) -> None:
    """
    Transition projection to new_status, saving in place.

    Raises ValueError for illegal transitions and unknown statuses.

    ADR-008 D3: fail loud — no silent state coercions.
    """
    known_statuses = {s for s, _ in PlatformProjection.Status.choices}
    if new_status not in known_statuses:
        raise ValueError(
            f"Unknown status {new_status!r}. Valid statuses: {sorted(known_statuses)}"
        )

    from_status = projection.status
    if (from_status, new_status) not in _LEGAL_TRANSITIONS:
        raise ValueError(
            f"Illegal status transition: {from_status!r} → {new_status!r}. "
            f"Legal transitions from {from_status!r}: "
            f"{[t for t in _LEGAL_TRANSITIONS if t[0] == from_status]}"
        )

    projection.status = new_status
    projection.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# Retry policy constants (ADR-008 D4)
# ---------------------------------------------------------------------------

# Transport errors (network blips): up to 2 retries then fail.
TRANSPORT_MAX_RETRIES = 2

# Data-integrity errors (4xx/5xx, parse/schema mismatch): never retry.
DATA_INTEGRITY_MAX_RETRIES = 0


# ---------------------------------------------------------------------------
# Visibility write-gate (ADR-012)
# ---------------------------------------------------------------------------

def _check_visibility_gate(event) -> None:
    """
    Raise ValueError if the Event's visibility disallows external projection generation.

    ADR-012 + ADR-016 Consequences: unlisted Events generate no external projections.
    This is a write-side gate distinct from events/managers.py visible_to() (read-side).

    ADR-008 D3: fail loud — raise, never silently drop.
    """
    if event.visibility == "unlisted":
        raise ValueError(
            f"Event {event.pk!r} (title={event.title!r}) has visibility='unlisted'. "
            "Unlisted Events generate no external projections per ADR-012 + ADR-016."
        )


# ---------------------------------------------------------------------------
# Template body composition (rule_based)
# ---------------------------------------------------------------------------

def _compose_listing_body(event, platform_id: str) -> str:
    """
    Deterministically compose a listing projection body from canonical Event fields.

    The composed text passes through clean_for_platform (identity at v0).
    ADR-008 D2: no platform-specific branching here; cleaning seam handles that.
    """
    parts = [event.title]
    if event.description:
        parts.append(event.description)
    if event.dress_code:
        parts.append(f"Dress code: {event.dress_code}")
    if event.age_restriction:
        parts.append(f"Age restriction: {event.age_restriction}+")
    if event.tickets_url:
        parts.append(f"Tickets: {event.tickets_url}")
    raw = "\n\n".join(parts)
    return clean_for_platform(raw, platform_id)


def _compose_promotion_body(post, platform_id: str) -> str:
    """
    Deterministically compose a promotion projection body from canonical Post fields.
    """
    parts = [post.headline]
    if post.body:
        parts.append(post.body)
    if post.cta:
        parts.append(post.cta)
    raw = "\n\n".join(parts)
    return clean_for_platform(raw, platform_id)


# ---------------------------------------------------------------------------
# generate_projection — public entry point
# ---------------------------------------------------------------------------

def generate_projection(
    kind: str,
    platform_id: str,
    source_event=None,
    source_post=None,
    mode: str = "rule_based",
    body: str | None = None,
) -> PlatformProjection:
    """
    Generate (and persist) a PlatformProjection.

    Args:
        kind: 'listing' or 'promotion'
        platform_id: Target platform identifier.
        source_event: Event instance. Required when kind='listing';
                      also used as the visibility gate source for kind='promotion'.
        source_post: Post instance. Required when kind='promotion'.
        mode: 'rule_based' (default) or 'agent_assisted'.
        body: Required when mode='agent_assisted'; ignored for 'rule_based'.

    Returns:
        Persisted PlatformProjection in status=draft.

    Raises:
        ValueError: if event is unlisted, mode=agent_assisted without body,
                    or unknown mode/kind.

    ADR-016 D2: The body is ALWAYS snapshotted into override_data["body"] at
                generation time. This makes the projection immune to later
                canonical mutations (override_data["body"] is stable).

    ADR-012: Visibility write-gate runs before any DB write.
    ADR-008 D3: fail loud on all integrity violations.
    """
    # --- Resolve the governing Event for the visibility gate ---
    if kind == "listing":
        if source_event is None:
            raise ValueError("source_event is required for kind='listing'")
        gate_event = source_event
    elif kind == "promotion":
        if source_post is None:
            raise ValueError("source_post is required for kind='promotion'")
        gate_event = source_post.event
    else:
        raise ValueError(f"Unknown kind {kind!r}. Valid: 'listing', 'promotion'")

    # --- Visibility write-gate (ADR-012 + ADR-016 Consequences) ---
    _check_visibility_gate(gate_event)

    # --- Compose the body ---
    if mode == "rule_based":
        if kind == "listing":
            composed_body = _compose_listing_body(gate_event, platform_id)
        else:
            composed_body = _compose_promotion_body(source_post, platform_id)
    elif mode == "agent_assisted":
        if body is None:
            raise ValueError(
                "mode='agent_assisted' requires a body argument. "
                "The external agent must supply the finished copy."
            )
        # Agent-supplied body is accepted as-is; the agent does the voice work.
        # ADR-011 D1: agent layer is additive — we accept + persist, not re-process.
        composed_body = body
    else:
        raise ValueError(f"Unknown mode {mode!r}. Valid: 'rule_based', 'agent_assisted'")

    # --- Persist: snapshot body into override_data (ADR-016 D2) ---
    # override_data["body"] is the stable rendered output for this projection.
    # Absent key would mean "use canonical" but post-generation there is always
    # a snapshotted value here.
    override_data = {"body": composed_body}

    proj = PlatformProjection.objects.create(
        kind=kind,
        status=PlatformProjection.Status.DRAFT,
        platform_id=platform_id,
        source_event=source_event,
        source_post=source_post,
        override_data=override_data,
    )
    return proj


# ---------------------------------------------------------------------------
# render_projection — produce the final output string
# ---------------------------------------------------------------------------

def render_projection(projection: PlatformProjection) -> str:
    """
    Render the projection's output body.

    If override_data contains 'body', that is the stable rendered output
    (snapshotted at generation time — ADR-016 D2 override-independence).

    ADR-016 D2: "Absent override means use canonical value."
    For body, absent override means we fall back to the canonical source body.
    But rule_based generation always writes override_data["body"], so this
    fallback path is for manually-created projections only.

    ADR-008 D3: fail loud if neither override nor canonical body is available.
    """
    if "body" in projection.override_data:
        return projection.override_data["body"]

    # Fallback: derive from canonical source (only reached for projections not
    # generated through generate_projection — e.g. manually created).
    if projection.kind == PlatformProjection.Kind.LISTING and projection.source_event:
        return _compose_listing_body(projection.source_event, projection.platform_id)
    if projection.kind == PlatformProjection.Kind.PROMOTION and projection.source_post:
        return _compose_promotion_body(projection.source_post, projection.platform_id)

    raise ValueError(
        f"Cannot render projection {projection.pk!r}: "
        "no body override and no source to derive from. "
        "(ADR-008 D3: fail loud — no silent zero-fill)"
    )
