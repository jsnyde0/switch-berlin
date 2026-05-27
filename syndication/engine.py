"""
Syndication engine (kb-a4u.4).

Provides three public callables:
- generate_projection(kind, connection, source_event|source_post, mode, body?)
- render_projection(proj) → str
- transition_status(proj, new_status) → None (saves, raises on illegal transition)

ADR-016 D2 (kb-a4u.20 hybrid content model):
    Draft projections TRACK the live canonical — override_data layered on top,
    absent key means use live canonical. Stability is achieved at draft→ready.

    At draft→ready, the FULL effective structured content is materialized into
    frozen_content: all content-relevant canonical fields with override_data
    applied. For kind=listing this includes body, title, start, end, dress_code,
    age_restriction, capacity, content_warnings, tickets_url, and description;
    for kind=promotion this includes body, headline, post_body, cta, and imagery.

    From ready onward (ready, published, failed), render_projection returns
    frozen_content["body"]; other consumers (e.g. publish carriers) may read
    any field from frozen_content without touching the live canonical.

    rule_based draft: does NOT write override_data["body"] — draft derives from
    live canonical. At draft→ready, _materialize_*_fields() captures the full
    effective content including a freshly composed body.

    agent_assisted draft: WRITES override_data["body"] as an explicit per-field
    override. At draft→ready, the override is included in the freeze snapshot.

ADR-016 D4: PlatformProjection FKs to PlatformConnection — not a bare
    platform string. The connection carries the platform identifier; callers
    pass a PlatformConnection.

ADR-016 carried-forward (REVISED 2026-05-27): There is NO visibility write-gate.
    Event.visibility governs read-side rendering on switch.berlin (visible_to) only —
    it does NOT gate outbound syndication. Eager creation is uniform across all
    visibility tiers (unlisted/semi_public/public produce the same draft set).

ADR-008 D3: fail loud — illegal transitions raise ValueError, missing body
    raises ValueError. No silent provenance defaults — mode→provenance mapping
    is always written explicitly.
ADR-008 D4: retry policy seam — transport errors get ≤2 retries,
    data-integrity errors never retry. Modelled as status machine (failed
    state) + policy constants exported here. Actual platform push logic
    lives in separate adapter beads.
"""

from syndication.cleaning import clean_for_platform
from syndication.models import PlatformConnection, PlatformProjection

# ---------------------------------------------------------------------------
# Status state-machine
# ---------------------------------------------------------------------------

# Legal transitions: (from_status, to_status)
_LEGAL_TRANSITIONS = frozenset(
    [
        ("draft", "ready"),
        ("ready", "published"),
        ("ready", "failed"),
        ("ready", "draft"),   # re-open for re-approval (kb-a4u.20 hybrid model)
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

    if from_status == "draft" and new_status == "ready":
        # ADR-016 D2 (kb-a4u.20 hybrid model): freeze the FULL effective structured
        # content at draft→ready. Materialize all content-relevant canonical fields
        # + override_data into frozen_content so from-ready reads never touch the
        # live canonical. Includes body, title, start, end, and all other fields
        # so a publish carrier (FetLife/TT adapter) can fill structured fields
        # from the snapshot without touching the live canonical.
        # ADR-008 D3: fail loud if the effective content cannot be derived.
        projection.frozen_content = _materialize_effective_fields(projection)
        projection.save(update_fields=["status", "frozen_content", "updated_at"])
    elif new_status == "draft":
        # Re-opening (ready→draft or failed→draft): clear frozen_content so
        # the draft tracks the live canonical again.
        projection.frozen_content = None
        projection.save(update_fields=["status", "frozen_content", "updated_at"])
    else:
        projection.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# Retry policy constants (ADR-008 D4)
# ---------------------------------------------------------------------------

# Transport errors (network blips): up to 2 retries then fail.
TRANSPORT_MAX_RETRIES = 2

# Data-integrity errors (4xx/5xx, parse/schema mismatch): never retry.
DATA_INTEGRITY_MAX_RETRIES = 0


# ---------------------------------------------------------------------------
# Template body composition (rule_based)
# ---------------------------------------------------------------------------

def _compose_listing_body(event, platform: str) -> str:
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
    return clean_for_platform(raw, platform)


def _compose_promotion_body(post, platform: str) -> str:
    """
    Deterministically compose a promotion projection body from canonical Post fields.
    """
    parts = [post.headline]
    if post.body:
        parts.append(post.body)
    if post.cta:
        parts.append(post.cta)
    raw = "\n\n".join(parts)
    return clean_for_platform(raw, platform)


# ---------------------------------------------------------------------------
# generate_projection — public entry point
# ---------------------------------------------------------------------------

def generate_projection(
    kind: str,
    connection: PlatformConnection,
    source_event=None,
    source_post=None,
    mode: str = "rule_based",
    body: str | None = None,
) -> PlatformProjection:
    """
    Generate (and persist) a PlatformProjection.

    Args:
        kind: 'listing' or 'promotion'
        connection: PlatformConnection instance. The specific destination
                    this projection targets (ADR-016 D4).
        source_event: Event instance. Required when kind='listing'.
        source_post: Post instance. Required when kind='promotion'.
        mode: 'rule_based' (default) or 'agent_assisted'.
        body: Required when mode='agent_assisted'; ignored for 'rule_based'.

    Returns:
        Persisted PlatformProjection in status=draft.

    Raises:
        ValueError: if mode=agent_assisted without body, or unknown mode/kind.

    ADR-016 D2 (hybrid content model): Draft projections track the live canonical.
                rule_based: override_data["body"] is NOT written at generation —
                draft renders from live canonical fields; freeze happens at draft→ready.
                agent_assisted: override_data["body"] IS written (explicit override);
                the agent-supplied body persists through draft and is included in
                the frozen snapshot at draft→ready.

    ADR-016 D4: connection is a PlatformConnection FK, not a bare platform string.

    ADR-008 D3: fail loud on all integrity violations.
    """
    # --- Validate kind and resolve the source ---
    if kind == "listing":
        if source_event is None:
            raise ValueError("source_event is required for kind='listing'")
        canonical_event = source_event
    elif kind == "promotion":
        if source_post is None:
            raise ValueError("source_post is required for kind='promotion'")
        canonical_event = source_post.event
    else:
        raise ValueError(f"Unknown kind {kind!r}. Valid: 'listing', 'promotion'")

    # ADR-016 carried-forward (REVISED 2026-05-27): NO visibility write-gate.
    # Event.visibility is a read-side concern (switch.berlin visible_to) only.
    # Eager creation is uniform across all visibility tiers.

    # --- Compose the body ---
    platform = connection.platform
    if mode == "rule_based":
        if kind == "listing":
            composed_body = _compose_listing_body(canonical_event, platform)
        else:
            composed_body = _compose_promotion_body(source_post, platform)
        provenance = PlatformProjection.Provenance.RULE_TEMPLATE
    elif mode == "agent_assisted":
        if body is None:
            raise ValueError(
                "mode='agent_assisted' requires a body argument. "
                "The external agent must supply the finished copy."
            )
        # Agent-supplied body is accepted as-is; the agent does the voice work.
        # ADR-011 D1: agent layer is additive — we accept + persist, not re-process.
        composed_body = body
        provenance = PlatformProjection.Provenance.AGENT_SUPPLIED
    else:
        raise ValueError(
            f"Unknown mode {mode!r}. Valid: 'rule_based', 'agent_assisted'"
        )

    # --- Persist: override_data and override_data only for explicit overrides ---
    # ADR-016 D2 (kb-a4u.20 hybrid model): Draft projections track the live
    # canonical. Stability is achieved by freezing at draft→ready, NOT by
    # snapshotting into override_data["body"] at generation time.
    #
    # rule_based: do NOT write override_data["body"] — the draft will derive
    # the body from the live canonical fields. At draft→ready, _render_draft_body
    # composes from the live canonical at that instant and freezes into
    # frozen_content. This is what makes canonical edits visible in draft but
    # not after ready.
    #
    # agent_assisted: WRITE override_data["body"] — the agent-supplied body is
    # an explicit per-field override that must persist in draft (and will be
    # included in the frozen snapshot at draft→ready).
    #
    # ADR-008 D3: provenance is always set explicitly — no silent model-default.
    if mode == "rule_based":
        override_data = {}
    else:
        # agent_assisted: store the agent-supplied body as an explicit override
        override_data = {"body": composed_body}

    proj = PlatformProjection.objects.create(
        kind=kind,
        status=PlatformProjection.Status.DRAFT,
        connection=connection,
        source_event=source_event,
        source_post=source_post,
        override_data=override_data,
        provenance=provenance,
    )
    return proj


# ---------------------------------------------------------------------------
# Full-field materialization helpers (Fix 1, kb-a4u.20 adversarial review)
# ---------------------------------------------------------------------------

def _isoformat_or_none(dt) -> str | None:
    """Return ISO 8601 string for a datetime, or None if dt is None."""
    if dt is None:
        return None
    return dt.isoformat()


def _materialize_listing_fields(projection: PlatformProjection) -> dict:
    """
    Materialize the full effective structured content for a kind=listing projection.

    Returns a dict of all content-relevant Event fields with override_data applied.
    This is the canonical "effective content" at a point in time — the frozen
    snapshot stored in frozen_content captures exactly this dict so that a publish
    carrier (e.g. FetLife/TT adapter agent) can fill structured date/location fields
    from the snapshot without touching the live canonical.

    override_data keys shadow the corresponding canonical field. Unknown override_data
    keys are passed through as-is (forward-compatible for future per-field overrides).

    ADR-008 D3: fail loud if source_event is missing.
    """
    event = projection.source_event
    if event is None:
        raise ValueError(
            f"Cannot materialize listing fields for projection {projection.pk!r}: "
            "source_event is None. (ADR-008 D3: fail loud)"
        )

    platform = projection.connection.platform
    override = projection.override_data or {}

    # Compose body from live canonical + override, then apply override if present
    if "body" in override:
        body = override["body"]
    else:
        body = _compose_listing_body(event, platform)

    return {
        "body": body,
        "title": override.get("title", event.title),
        "description": override.get("description", event.description),
        "start": override.get("start", _isoformat_or_none(event.start)),
        "end": override.get("end", _isoformat_or_none(event.end)),
        "dress_code": override.get("dress_code", event.dress_code),
        "age_restriction": override.get("age_restriction", event.age_restriction),
        "capacity": override.get("capacity", event.capacity),
        "content_warnings": override.get("content_warnings", event.content_warnings),
        "tickets_url": override.get("tickets_url", event.tickets_url),
    }


def _materialize_promotion_fields(projection: PlatformProjection) -> dict:
    """
    Materialize the full effective structured content for a kind=promotion projection.

    Returns a dict of all content-relevant Post fields with override_data applied.
    Analogous to _materialize_listing_fields for kind=promotion.

    ADR-008 D3: fail loud if source_post is missing.
    """
    post = projection.source_post
    if post is None:
        raise ValueError(
            f"Cannot materialize promotion fields for projection {projection.pk!r}: "
            "source_post is None. (ADR-008 D3: fail loud)"
        )

    platform = projection.connection.platform
    override = projection.override_data or {}

    if "body" in override:
        body = override["body"]
    else:
        body = _compose_promotion_body(post, platform)

    return {
        "body": body,
        "headline": override.get("headline", post.headline),
        "post_body": override.get("post_body", post.body),
        "cta": override.get("cta", post.cta),
        "imagery": override.get("imagery", post.imagery),
        "voice": override.get("voice", post.voice),
    }


def _materialize_effective_fields(projection: PlatformProjection) -> dict:
    """
    Dispatch to the appropriate materialization helper based on projection.kind.

    Called at draft→ready to produce the frozen_content snapshot.
    ADR-008 D3: fail loud on unknown kind.
    """
    if projection.kind == PlatformProjection.Kind.LISTING:
        return _materialize_listing_fields(projection)
    if projection.kind == PlatformProjection.Kind.PROMOTION:
        return _materialize_promotion_fields(projection)
    raise ValueError(
        f"Cannot materialize fields for projection {projection.pk!r}: "
        f"unknown kind={projection.kind!r}. (ADR-008 D3: fail loud)"
    )


# ---------------------------------------------------------------------------
# render_projection — produce the final output string
# ---------------------------------------------------------------------------

def _render_draft_body(projection: PlatformProjection) -> str:
    """
    Derive the effective body for a DRAFT projection.

    Draft projections track the live canonical: if override_data contains
    'body', that per-field override is the effective body. Otherwise, compose
    from the live canonical source (listing from source_event fields, promotion
    from source_post fields).

    Used both by render_projection (when status==draft) and by
    transition_status (to materialize the freeze snapshot at draft→ready).

    ADR-008 D3: fail loud if no body can be derived.
    """
    if "body" in projection.override_data:
        return projection.override_data["body"]

    # No override → derive from live canonical source fields.
    platform = projection.connection.platform
    if projection.kind == PlatformProjection.Kind.LISTING and projection.source_event:
        return _compose_listing_body(projection.source_event, platform)
    if projection.kind == PlatformProjection.Kind.PROMOTION and projection.source_post:
        return _compose_promotion_body(projection.source_post, platform)

    raise ValueError(
        f"Cannot render projection {projection.pk!r}: "
        "no body override and no source to derive from. "
        "(ADR-008 D3: fail loud — no silent zero-fill)"
    )


def render_projection(projection: PlatformProjection) -> str:
    """
    Render the projection's output body.

    ADR-016 D2 (kb-a4u.20 hybrid content model):
    - status=draft: track live canonical — return _render_draft_body()
      (override_data["body"] if present, else compose from live canonical fields).
    - status=ready/published/failed: return frozen_content["body"] (the snapshot
      materialized at draft→ready). Fail loud if frozen_content is absent —
      that is a data-integrity bug, not a fallback opportunity (ADR-008 D3).

    No hidden live-canonical fallback for non-draft projections.
    """
    if projection.status == PlatformProjection.Status.DRAFT:
        return _render_draft_body(projection)

    # Non-draft (ready / published / failed): return the frozen snapshot.
    if projection.frozen_content is None:
        raise ValueError(
            f"Cannot render projection {projection.pk!r}: "
            f"status={projection.status!r} but frozen_content is None. "
            "frozen_content must be set at draft→ready transition. "
            "(ADR-008 D3: fail loud — no silent fallback to live canonical)"
        )
    return projection.frozen_content["body"]
