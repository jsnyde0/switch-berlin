"""
Syndication platform adapters (kb-a4u.10, kb-a4u.14).

Per ADR-008 D2: NO per-platform adapter abstraction/framework here.
The Switch own-page publish path is written directly — abstraction emerges
later from observed divergence across multiple platform adapters.

Per ADR-008 D3: fail loud, no silent fallbacks. Data-integrity failures
(missing source_event, missing organizer) set status=failed and raise
ValueError — never silently succeed.

Per ADR-016 D5: Switch own-page is a push-API-style platform. The publish
verb performs the in-app render/list and AUTO-CONFIRMS → status=published
(or failed on data-integrity error). No out-of-band attestation needed.

Per ADR-016 carried-forward (REVISED): NO visibility gate on any adapter.
Event.visibility governs read-side rendering on switch.berlin only.
"""

import json
import time

import httpx
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from syndication.engine import render_projection, transition_status
from syndication.models import PlatformProjection


def publish_switch_own_page(projection: PlatformProjection) -> None:
    """
    Publish a kind=listing projection to the Switch own-page destination.

    Switch own-page is the canonical Switch event detail page — no external
    API call is needed. The publish verb:
    1. Precondition: projection.status must be ready (fail loud otherwise).
    2. Validates the projection is kind=listing (fail loud otherwise).
    3. Resolves the public external_url via reverse('event-detail', ...).
       Requires: projection.source_event with a non-empty slug AND a primary
       organizer with a non-empty slug.
    4. Transitions status: ready → published.
    5. Stamps external_url and syndicated_at.

    On data-integrity failure (missing source_event, missing primary organizer,
    missing/empty slug on event or organizer):
    - Sets status=failed via the state machine (ready → failed).
    - Raises ValueError (ADR-008 D3 — fail loud, never silently succeed).

    Note: ContentVersion editorial overrides are a no-op for own-page listing —
    the listing IS the live canonical detail page (/events/<org_slug>/<event_slug>/),
    so there is no body to override. This is correct, not an oversight.

    Args:
        projection: A PlatformProjection in status=ready on a Switch own-page
                    PlatformConnection with kind=listing.

    Raises:
        ValueError: if status != ready, kind != listing, source_event is
                    missing, event/organizer slug is empty, or event has no
                    primary organizer (needed to resolve org_slug for the URL).
    """
    # Precondition guard: status must be ready before ANY data-integrity checks
    # or state transitions. Without this, a draft projection would hit the
    # fail-loud branches below, which call transition_status(proj, "failed") —
    # but "draft→failed" is not a legal transition, masking the real error.
    # (ADR-008 D3: the correct error must surface, not an opaque state-machine error)
    if projection.status != PlatformProjection.Status.READY:
        raise ValueError(
            f"publish_switch_own_page requires status=ready; "
            f"got status={projection.status!r}. "
            "Advance the projection to ready before publishing. "
            "(ADR-008 D3 — fail loud)"
        )

    # Guard: only listing kind is valid for Switch own-page
    if projection.kind != PlatformProjection.Kind.LISTING:
        raise ValueError(
            f"publish_switch_own_page only handles kind=listing projections; "
            f"got kind={projection.kind!r}. (ADR-008 D3 — fail loud)"
        )

    # Guard: source_event required for listing
    event = projection.source_event
    if event is None:
        # Fail loud: set status=failed then raise
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Switch own-page projection {projection.pk!r}: "
            "source_event is None. (ADR-008 D3 — fail loud, no silent fallback)"
        )

    # Resolve the primary organizer for the event-detail URL (org_slug + event_slug)
    organizer = event.organizer
    if organizer is None:
        # Fail loud: set status=failed then raise
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Switch own-page projection {projection.pk!r}: "
            f"event {event.slug!r} has no primary organizer — "
            "cannot resolve org_slug for the event-detail URL. "
            "(ADR-008 D3 — fail loud, no silent fallback)"
        )

    # Guard: slug presence required before reverse() — an empty slug produces
    # NoReverseMatch (or a malformed URL), bypassing the fail-loud-to-failed
    # pattern and leaving the projection in ready with an opaque error.
    # (ADR-008 D3: data-integrity errors must set status=failed and raise clearly)
    if not event.slug:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Switch own-page projection {projection.pk!r}: "
            f"event {event.pk!r} has an empty slug — "
            "cannot resolve event_slug for the event-detail URL. "
            "(ADR-008 D3 — fail loud, no silent fallback)"
        )
    if not organizer.slug:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Switch own-page projection {projection.pk!r}: "
            f"organizer {organizer.pk!r} has an empty slug — "
            "cannot resolve org_slug for the event-detail URL. "
            "(ADR-008 D3 — fail loud, no silent fallback)"
        )

    # Resolve the public listing URL via Django's URL reversal.
    # Reuses the existing events/views.py detail view — no path hardcoding.
    external_url = reverse(
        "event-detail",
        kwargs={
            "org_slug": organizer.slug,
            "event_slug": event.slug,
        },
    )

    # Transition status: ready → published (state machine enforces legality)
    transition_status(projection, PlatformProjection.Status.PUBLISHED)

    # Stamp external_url and syndicated_at after successful status transition
    projection.external_url = external_url
    projection.syndicated_at = timezone.now()
    projection.save(update_fields=["external_url", "syndicated_at", "updated_at"])


# ---------------------------------------------------------------------------
# Telegram channel promotion adapter (kb-a4u.14)
# ---------------------------------------------------------------------------

# ADR-008 D4: transport retry policy constants
_TELEGRAM_MAX_TRANSPORT_RETRIES = 2  # up to 2 retries → 3 total attempts
_TELEGRAM_RETRY_SLEEP_SECONDS = 1    # linear backoff between attempts


def publish_telegram_promotion(projection: PlatformProjection) -> None:
    """
    Publish a kind=promotion projection to a Telegram channel via the Bot API.

    Telegram is a push-API platform (ADR-016 D5): the publish verb POSTs to
    the Bot API and AUTO-CONFIRMS → status=published (or failed on error).

    Preconditions (fail-loud, ADR-008 D3 — mirror publish_switch_own_page ordering):
    1. projection.status must be ready (else raise, NO transition —
       draft→failed is an illegal transition; the precondition guard fires first).
    2. projection.kind must be promotion (else raise).
    3. source_post must be present (else transition→failed + raise).
    4. connection.destination_id must be non-empty (channel ref — else fail).
    5. A bot token must be resolvable (per-channel override or settings.TELEGRAM_BOT_TOKEN).

    Retry policy (ADR-008 D4):
    - Transport errors (httpx.TransportError subclasses): retry up to 2 times
      (3 total attempts). After final failure → transition→failed + raise.
    - HTTP 4xx/5xx OR {"ok": false} in response body: NO retry (data-integrity
      error). → transition→failed + raise ValueError.

    On success (HTTP 200 AND {"ok": true}):
    - transition_status(projection, "published")
    - external_id = str(message_id) (authoritative platform ref)
    - syndicated_at = now()
    - external_url is NOT set (t.me deep-links require a public username —
      not available here; ADR-008 D3: never synthesize a URL that may be wrong)

    ADR-016 carried-forward (REVISED): NO visibility gate — Event.visibility
    must not gate outbound syndication. This function does not read or check
    Event.visibility.

    ADR-008 D2: NO adapter base class, NO dispatcher — this is a direct
    standalone function. Cross-platform dispatch abstraction emerges later
    from observed divergence.

    Args:
        projection: A PlatformProjection in status=ready on a Telegram
                    PlatformConnection with kind=promotion.

    Raises:
        ValueError: if preconditions fail, API reports an error, or all
                    transport retries are exhausted.
        httpx.TransportError: re-raised (wrapped in the ValueError surface)
                              after retries exhausted.
    """
    # ---- Precondition 1: status must be ready (fires before any transition) ----
    # Without this guard, a draft projection would hit the data-integrity
    # fail-loud branches below which call transition_status(proj, "failed") —
    # but "draft→failed" is not a legal transition (ADR-008 D3).
    if projection.status != PlatformProjection.Status.READY:
        raise ValueError(
            f"publish_telegram_promotion requires status=ready; "
            f"got status={projection.status!r}. "
            "Advance the projection to ready before publishing. "
            "(ADR-008 D3 — fail loud)"
        )

    # ---- Precondition 2: kind must be promotion ----
    if projection.kind != PlatformProjection.Kind.PROMOTION:
        raise ValueError(
            f"publish_telegram_promotion only handles kind=promotion projections; "
            f"got kind={projection.kind!r}. (ADR-008 D3 — fail loud)"
        )

    # ---- Precondition 3: source_post must be present ----
    post = projection.source_post
    if post is None:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            "source_post is None. (ADR-008 D3 — fail loud, no silent fallback)"
        )

    # ---- Precondition 4: channel ref (destination_id) must be non-empty ----
    channel = projection.connection.destination_id
    if not channel:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            "connection.destination_id is empty — no channel to send to. "
            "(ADR-008 D3 — fail loud, no silent fallback)"
        )

    # ---- Precondition 5: resolve bot token ----
    # Per-channel override takes priority; fallback to settings.TELEGRAM_BOT_TOKEN.
    token = projection.connection.credentials.get("bot_token") or getattr(
        settings, "TELEGRAM_BOT_TOKEN", ""
    )
    if not token:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            "no bot token available — set connection.credentials['bot_token'] "
            "or settings.TELEGRAM_BOT_TOKEN. (ADR-008 D3 — fail loud)"
        )

    # ---- Render body (effective content = content_version fields + live canonical fallbacks) ----
    body = render_projection(projection)

    # ---- Bot API URL ----
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": channel, "text": body}

    # ---- Send with transport-error retry (ADR-008 D4) ----
    last_transport_error = None
    for attempt in range(_TELEGRAM_MAX_TRANSPORT_RETRIES + 1):
        try:
            response = httpx.post(url, json=payload)
            break  # exit retry loop — we got a response
        except httpx.TransportError as exc:
            last_transport_error = exc
            if attempt < _TELEGRAM_MAX_TRANSPORT_RETRIES:
                time.sleep(_TELEGRAM_RETRY_SLEEP_SECONDS)
            # else: fall through to exhausted-retries handling
    else:
        # All attempts exhausted (httpx.TransportError every time)
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            f"transport error after {_TELEGRAM_MAX_TRANSPORT_RETRIES + 1} attempts: "
            f"{last_transport_error!r}. (ADR-008 D4 — transport retries exhausted)"
        ) from last_transport_error

    # ---- Inspect response (ADR-008 D4: HTTP 4xx/5xx or ok=false → no retry) ----
    if response.status_code >= 400:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            f"Bot API returned HTTP {response.status_code}. "
            "(ADR-008 D4 — data-integrity error, no retry)"
        )

    # ADR-008 D3: non-JSON body is a data-integrity error → fail loud, no retry
    try:
        response_body = response.json()
    except json.JSONDecodeError as exc:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            f"Bot API returned HTTP 200 with non-JSON body: {exc!r}. "
            "(ADR-008 D3 — data-integrity error, no retry)"
        ) from exc

    if not response_body.get("ok"):
        transition_status(projection, PlatformProjection.Status.FAILED)
        description = response_body.get("description", "(no description)")
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            f"Bot API returned ok=false: {description!r}. "
            "(ADR-008 D4 — data-integrity error, no retry)"
        )

    # ADR-008 D3: missing result/message_id in a 200+ok=true body is a data-integrity
    # error → fail loud, no retry. Never strand the projection in ready.
    try:
        message_id = response_body["result"]["message_id"]
    except KeyError as exc:
        transition_status(projection, PlatformProjection.Status.FAILED)
        raise ValueError(
            f"Cannot publish Telegram promotion projection {projection.pk!r}: "
            f"Bot API returned HTTP 200 with ok=true but malformed body "
            f"(missing key {exc!r}). "
            "(ADR-008 D3 — data-integrity error, no retry)"
        ) from exc

    # ---- Success: transition and stamp result fields ----

    # Transition status: ready → published (state machine enforces legality)
    transition_status(projection, PlatformProjection.Status.PUBLISHED)

    # Stamp result fields (external_url intentionally left blank — see docstring)
    projection.external_id = str(message_id)
    projection.syndicated_at = timezone.now()
    projection.save(update_fields=["external_id", "syndicated_at", "updated_at"])
