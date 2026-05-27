"""
Syndication platform adapters (kb-a4u.10).

Per ADR-008 D2: NO per-platform adapter abstraction/framework here.
The Switch own-page publish path is written directly — abstraction emerges
later from observed divergence across multiple platform adapters.

Per ADR-008 D3: fail loud, no silent fallbacks. Data-integrity failures
(missing source_event, missing organizer) set status=failed and raise
ValueError — never silently succeed.

Per ADR-016 D5: Switch own-page is a push-API-style platform. The publish
verb performs the in-app render/list and AUTO-CONFIRMS → status=published
(or failed on data-integrity error). No out-of-band attestation needed.
"""

from django.urls import reverse
from django.utils import timezone

from syndication.engine import transition_status
from syndication.models import PlatformProjection


def publish_switch_own_page(projection: PlatformProjection) -> None:
    """
    Publish a kind=listing projection to the Switch own-page destination.

    Switch own-page is the canonical Switch event detail page — no external
    API call is needed. The publish verb:
    1. Validates the projection is kind=listing (fail loud otherwise).
    2. Resolves the public external_url via reverse('event-detail', ...).
       Requires: projection.source_event with a slug AND a primary organizer.
    3. Transitions status: ready → published.
    4. Stamps external_url and syndicated_at.

    On data-integrity failure (missing source_event, missing primary organizer):
    - Sets status=failed via the state machine (ready → failed).
    - Raises ValueError (ADR-008 D3 — fail loud, never silently succeed).

    Args:
        projection: A PlatformProjection in status=ready on a Switch own-page
                    PlatformConnection with kind=listing.

    Raises:
        ValueError: if kind != listing, source_event is missing, or event has
                    no primary organizer (needed to resolve org_slug for the URL).
    """
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
