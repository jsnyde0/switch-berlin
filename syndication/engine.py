"""
Syndication engine (kb-a4u.4, kb-wz8m.2 content-version cutover).

Provides three public callables:
- generate_projection(kind, connection, source_event|source_post, mode, body?)
- render_projection(proj) → str
- transition_status(proj, new_status) → None (saves, raises on illegal transition)

ADR-016 D2 (kb-wz8m.2 content-version model):
    Draft projections TRACK the live canonical — ContentVersion fields layered on
    top; a NULL field on ContentVersion means "derive from live canonical at render
    time". Stability is achieved at draft→ready.

    At draft→ready, the FULL effective structured content is materialized into
    frozen_content: all content-relevant canonical fields with ContentVersion
    explicit fields applied. For kind=listing this includes body, title, start,
    end, dress_code, age_restriction, capacity, content_warnings, tickets_url,
    and description; for kind=promotion this includes body, headline, post_body,
    cta, and imagery.

    From ready onward (ready, published, failed), render_projection returns
    frozen_content["body"]; other consumers (e.g. publish carriers) may read
    any field from frozen_content without touching the live canonical.

    rule_based draft: ContentVersion body is NULL — draft derives from live
    canonical. At draft→ready, _materialize_*_fields() captures the full
    effective content including a freshly composed body.

    agent_assisted draft: ContentVersion body is set to the agent-supplied copy.
    At draft→ready, the explicit body is included in the freeze snapshot.

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

from django.conf import settings
from django.urls import reverse

from syndication.cleaning import clean_for_platform
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection

# ---------------------------------------------------------------------------
# Status state-machine
# ---------------------------------------------------------------------------

# Legal transitions: (from_status, to_status)
_LEGAL_TRANSITIONS = frozenset(
    [
        ("draft", "ready"),
        ("ready", "published"),
        ("ready", "failed"),
        ("ready", "draft"),  # re-open for re-approval (kb-a4u.20 hybrid model)
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
        raise ValueError(f"Unknown status {new_status!r}. Valid statuses: {sorted(known_statuses)}")

    from_status = projection.status
    if (from_status, new_status) not in _LEGAL_TRANSITIONS:
        raise ValueError(
            f"Illegal status transition: {from_status!r} → {new_status!r}. "
            f"Legal transitions from {from_status!r}: "
            f"{[t for t in _LEGAL_TRANSITIONS if t[0] == from_status]}"
        )

    projection.status = new_status

    if from_status == "draft" and new_status == "ready":
        # ADR-016 D2 (kb-wz8m.2 content-version model): freeze the FULL effective
        # structured content at draft→ready. Materialize all content-relevant
        # canonical fields + ContentVersion explicit fields into frozen_content so
        # from-ready reads never touch the live canonical.
        # ADR-008 D3: fail loud if the effective content cannot be derived.
        # kb-6d7o.2: bump publish_rev BEFORE materialization so the frozen body
        # carries the bumped rev in the embedded versioned URL.
        _bump_publish_rev(projection)
        projection.frozen_content = _materialize_effective_fields(projection)
        projection.save(update_fields=["status", "frozen_content", "publish_rev", "updated_at"])
    elif from_status == "ready" and new_status == "published":
        # ADR-016 D5: re-freeze at ready→published so published frozen_content
        # reflects the current effective content, not the ready-time snapshot.
        # This is necessary when the source ContentVersion is edited AFTER
        # consumers reach 'ready' (permitted by version_edit's
        # _allow_edit_after_publish=True path). Without this re-freeze, the
        # published frozen_content would be stale (the ready-time snapshot).
        # republish_projection (services.py) already re-freezes for re-publish;
        # this branch closes the gap for FIRST-publish only.
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
# Publish-revision bump helper (kb-6d7o.2)
# ---------------------------------------------------------------------------


def _bump_publish_rev(projection: PlatformProjection) -> None:
    """
    Increment projection.publish_rev by 1 (in memory only — caller saves).

    Called IMMEDIATELY BEFORE _materialize_effective_fields at the two
    body-freeze sites that feed a send:
      - draft→ready branch of transition_status
      - republish_projection re-materialize (services.py)

    NOT called at ready→published (that re-freeze is AFTER the Telegram send
    — bumping there would desync the sent body's rev from the snapshot).
    NOT called on draft ContentVersion edits (ADR-016 D2 freeze rule).

    ADR-008 D2: thin helper, no abstraction beyond the minimum needed here.
    ADR-008 D3: does NOT validate projection kind — callers own that gate.
    """
    projection.publish_rev = (projection.publish_rev or 0) + 1


# ---------------------------------------------------------------------------
# Template body composition (rule_based)
# ---------------------------------------------------------------------------


def _compose_listing_body(event, platform: str) -> str:
    """
    Deterministically compose a listing projection body from canonical Event fields.

    Includes: title, start datetime, end datetime (if present), venue name (if present),
    description, dress_code, age_restriction, tickets_url.

    The date/location fields were a carried-forward gap — now included so all
    listing adapters (Switch own-page, FetLife, etc.) get complete listings.

    The composed text passes through clean_for_platform (identity at v0).
    ADR-008 D2: no platform-specific branching here; cleaning seam handles that.
    ADR-008 D3: fail loud — if required fields are absent the caller should
    surface an error, not zero-fill.
    """
    parts = [event.title]

    # Date/time block (carried-forward gap fix — benefits all listing adapters)
    if event.start:
        if event.end:
            parts.append(f"Date: {event.start.strftime('%Y-%m-%d %H:%M')} – {event.end.strftime('%Y-%m-%d %H:%M')}")
        else:
            parts.append(f"Date: {event.start.strftime('%Y-%m-%d %H:%M')}")

    # Location block (venue FK, optional)
    if event.venue:
        parts.append(f"Location: {event.venue.name}")

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

    ADR-016 D2 (kb-wz8m.2 content-version model): Draft projections track the
                live canonical via ContentVersion.
                rule_based: ContentVersion body is NULL — draft renders from
                live canonical fields; freeze happens at draft→ready.
                agent_assisted: ContentVersion body IS set (explicit override);
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
        canonical_post = None
    elif kind == "promotion":
        if source_post is None:
            raise ValueError("source_post is required for kind='promotion'")
        canonical_event = None  # promotion CVs are post-owned, not event-owned
        canonical_post = source_post
    else:
        raise ValueError(f"Unknown kind {kind!r}. Valid: 'listing', 'promotion'")

    # ADR-016 carried-forward (REVISED 2026-05-27): NO visibility write-gate.
    # Event.visibility is a read-side concern (switch.berlin visible_to) only.
    # Eager creation is uniform across all visibility tiers.

    # --- Resolve or create a ContentVersion for this publishable ---
    # get-or-create the canonical version for the publishable so generate_projection
    # can be called standalone (without having gone through create_event/create_post).
    # ADR-016 D2 / kb-q4u9.2: promotion projections use the POST's canonical
    # (post FK set, event FK null), not the event's canonical.
    if canonical_post is not None:
        canonical_cv, _ = ContentVersion.objects.get_or_create(
            post=canonical_post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
    else:
        canonical_cv, _ = ContentVersion.objects.get_or_create(
            event=canonical_event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )

    # --- Resolve the ContentVersion this projection will use ---
    if mode == "rule_based":
        # rule_based points at the shared canonical track-live version.
        # Body remains NULL — derives from live canonical at render time.
        cv = canonical_cv
    elif mode == "agent_assisted":
        if body is None:
            raise ValueError(
                "mode='agent_assisted' requires a body argument. The external agent must supply the finished copy."
            )
        # F6 (adversarial review): agent-supplied copy for one target is divergence.
        # Create a DEDICATED new ContentVersion — NEVER mutate the shared canonical.
        # This prevents the agent's body from bleeding into sibling projections that
        # share the canonical track-live version.
        # Preserve publishable scope (post or event) for the agent-assisted version.
        cv = ContentVersion.objects.create(
            event=canonical_event,
            post=canonical_post,
            name=f"agent-{connection.platform}-{connection.destination_id}",
            provenance=ContentVersion.Provenance.AGENT_SUPPLIED,
            body=body,
        )
    else:
        raise ValueError(f"Unknown mode {mode!r}. Valid: 'rule_based', 'agent_assisted'")

    # --- Persist the projection ---
    proj = PlatformProjection.objects.create(
        kind=kind,
        status=PlatformProjection.Status.DRAFT,
        connection=connection,
        source_event=source_event,
        source_post=source_post,
        content_version=cv,
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

    Returns a dict of all content-relevant Event fields with ContentVersion
    explicit fields applied (null field = use canonical).

    This is the canonical "effective content" at a point in time — the frozen
    snapshot stored in frozen_content captures exactly this dict so that a publish
    carrier (e.g. FetLife/TT adapter agent) can fill structured date/location fields
    from the snapshot without touching the live canonical.

    ContentVersion null field = canonical value (null-means-derive semantics).
    ContentVersion explicit value = override.

    ADR-008 D3: fail loud if source_event is missing.
    """
    event = projection.source_event
    if event is None:
        raise ValueError(
            f"Cannot materialize listing fields for projection {projection.pk!r}: "
            "source_event is None. (ADR-008 D3: fail loud)"
        )

    platform = projection.connection.platform
    cv = projection.content_version

    # Body: ContentVersion.body if explicit (override), else compose from live canonical.
    # cv is always non-null (A1 invariant). cv.body null = derive from live canonical.
    if cv.body is not None:
        body = cv.body
    else:
        body = _compose_listing_body(event, platform)

    # Structured venue key — so a publish carrier can read location without
    # parsing the body string.  None when the event has no venue FK.
    venue_name = event.venue.name if event.venue else None

    return {
        "body": body,
        "title": event.title,
        "description": event.description,
        "start": _isoformat_or_none(event.start),
        "end": _isoformat_or_none(event.end),
        "dress_code": event.dress_code,
        "age_restriction": event.age_restriction,
        "capacity": event.capacity,
        "content_warnings": event.content_warnings,
        "tickets_url": event.tickets_url,
        "venue": venue_name,
    }


def _materialize_promotion_fields(projection: PlatformProjection) -> dict:
    """
    Materialize the full effective structured content for a kind=promotion projection.

    Returns a dict of all content-relevant Post fields with ContentVersion
    explicit fields applied (null field = use canonical).
    Analogous to _materialize_listing_fields for kind=promotion.

    kb-6d7o.2: Appends the canonical Switch event URL with ?v=<publish_rev> to the
    composed promotion body so it lands in frozen_content["body"] at every freeze.
    The URL is built via reverse("event-detail", ...) + settings.SITE_URL + ?v=rev,
    where rev is projection.publish_rev (already bumped before this call at draft→ready
    and republish_projection). Route name is "event-detail" (hyphen — confirmed at
    events/urls.py:12). ADR-008 D2: inline reverse, no premature extraction.

    ADR-008 D3: fail loud if source_post is missing.
    """
    post = projection.source_post
    if post is None:
        raise ValueError(
            f"Cannot materialize promotion fields for projection {projection.pk!r}: "
            "source_post is None. (ADR-008 D3: fail loud)"
        )

    platform = projection.connection.platform
    cv = projection.content_version

    # cv is always non-null (A1 invariant). cv fields null = derive from live canonical.
    if cv.body is not None:
        body = cv.body
    else:
        body = _compose_promotion_body(post, platform)

    # kb-6d7o.2: For Telegram-only — embed the canonical Switch event URL with
    # ?v=<publish_rev> as a link-preview cache-bust. Non-telegram platforms
    # (FetLife, Switch, etc.) do NOT receive the URL suffix.
    # ADR-008 D3: if the event or organizer slug is missing for a telegram
    # promotion, raise loud — do not silently omit (silent omission = cache-bust
    # silently fails with no error signal).
    if projection.connection.platform == "telegram":
        event = post.event
        if event is None or not event.slug:
            raise ValueError(
                f"Cannot embed versioned URL for telegram promotion projection "
                f"{projection.pk!r}: post.event is missing or has no slug. "
                "A telegram promotion requires a linkable event. (ADR-008 D3: fail loud)"
            )
        organizer = getattr(event, "organizer", None)
        if organizer is None or not organizer.slug:
            raise ValueError(
                f"Cannot embed versioned URL for telegram promotion projection "
                f"{projection.pk!r}: event {event.pk!r} ({event.slug!r}) has no "
                "organizer with a slug. A telegram promotion requires a linkable event. "
                "(ADR-008 D3: fail loud)"
            )
        event_path = reverse(
            "event-detail",
            kwargs={
                "org_slug": organizer.slug,
                "event_slug": event.slug,
            },
        )
        site_url = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
        versioned_url = f"{site_url}{event_path}?v={projection.publish_rev}"
        body = f"{body}\n\n{versioned_url}"

    # For structured fields: ContentVersion explicit value overrides canonical.
    headline = cv.headline if cv.headline is not None else post.headline
    cta = cv.cta if cv.cta is not None else post.cta
    imagery = cv.imagery if cv.imagery is not None else post.imagery
    voice = cv.voice if cv.voice is not None else post.voice

    return {
        "body": body,
        "headline": headline,
        "post_body": post.body,
        "cta": cta,
        "imagery": imagery,
        "voice": voice,
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

    Draft projections track the live canonical:
    - If ContentVersion.body is set (non-null), that explicit value is the body.
    - Otherwise, compose from the live canonical source (listing from source_event
      fields, promotion from source_post fields).

    ADR-008 D3: fail loud if no body can be derived.
    """
    cv = projection.content_version

    # cv is always non-null (A1 invariant). Explicit body on ContentVersion takes precedence.
    if cv.body is not None:
        return cv.body

    # NULL body on ContentVersion → derive from live canonical source fields.
    platform = projection.connection.platform
    if projection.kind == PlatformProjection.Kind.LISTING and projection.source_event:
        return _compose_listing_body(projection.source_event, platform)
    if projection.kind == PlatformProjection.Kind.PROMOTION and projection.source_post:
        return _compose_promotion_body(projection.source_post, platform)

    raise ValueError(
        f"Cannot render projection {projection.pk!r}: "
        "no explicit body on ContentVersion and no source to derive from. "
        "(ADR-008 D3: fail loud — no silent zero-fill)"
    )


def render_projection(projection: PlatformProjection) -> str:
    """
    Render the projection's output body.

    ADR-016 D2 (kb-wz8m.2 content-version model):
    - status=draft: track live canonical — return _render_draft_body()
      (ContentVersion.body if explicit, else compose from live canonical fields).
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
