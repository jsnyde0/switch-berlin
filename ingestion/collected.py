"""
Collected-event feed (sb-7wzb.2, Track A): collector rows in, landed events out.

Two ends of the RawMessage seam for rows that a collector (switch-cli
`collect web` / `collect telegram`) gathered rather than a human forwarded:

- ingest_collected_rows: the staff-only API verb's service — one RawMessage per
  row, extraction enqueued exactly as the forward-bot does.
- land_collected_event: called by process_raw_message after extraction —
  resolves the organizer, drops past events and duplicates, derives the tier
  from the source shape (ADR-012 D2) and publishes by claim state (ADR-017 D4).

Plain functions over the existing seam; no source framework (sb-7wzb.2 D3).
"""

import uuid
from datetime import timedelta

import logfire
from django.contrib.postgres.search import TrigramSimilarity
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from django_q.tasks import async_task

from events.backfill_visibility import derive_visibility_from_sources, rawmessage_source_to_conceptual

# RawMessage.source_type values a collector may write. The bot forward stays the
# bot's own door; its rows keep the draft-for-admin-review path.
COLLECTED_SOURCE_TYPES = ("website", "telegram_telethon", "telegram_private_channel", "telegram_private_group")

# Title similarity at which two same-day events count as one (pg_trgm, case-folded).
_DUPLICATE_TITLE_SIMILARITY = 0.4


def ingest_collected_rows(rows: list[dict]) -> dict:
    """Write one RawMessage per collected row and enqueue its extraction.

    A row already collected (same source_type, channel_id, message_id) is
    counted, not re-written: re-running a collector is idempotent.
    """
    from .models import RawMessage

    created = already = 0
    for row in rows:
        if row["source_type"] not in COLLECTED_SOURCE_TYPES:
            raise ValueError(f"source_type {row['source_type']!r} is not a collected feed")
        try:
            with transaction.atomic():
                raw = RawMessage.objects.create(
                    source_type=row["source_type"],
                    channel_id=row["channel_id"],
                    message_id=row["message_id"],
                    sender_id=row.get("sender_id", ""),
                    text=row["text"],
                    raw_payload=row.get("raw_payload", {}),
                    collect_only=row.get("collect_only", False),
                )
        except IntegrityError:
            already += 1
            continue
        async_task("ingestion.tasks.process_raw_message", raw.id)
        created += 1
    logfire.info("collected.rows_ingested", created=created, already_collected=already)
    return {"created": created, "already_collected": already}


def _aware(dt):
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _create_collected_profile(name: str, raw):
    """Unclaimed organizer Profile for a collected event (sb-7wzb.2 organizer waterfall, last step).

    status=approved so the organizer page, and with it the claim affordance
    (ADR-014), resolves (mem auto-created-records-reachable-default). The lawful
    basis is the organizer LIA (docs/compliance/organizer-lia.md).
    """
    from organizers.models import Profile

    base = slugify(name)[:40] or "organizer"
    slug = base if not Profile.objects.filter(slug=base).exists() else f"{base}-{uuid.uuid4().hex[:6]}"
    source = raw.raw_payload.get("source") or raw.channel_id
    now = timezone.now()
    return Profile.objects.create(
        name=name,
        slug=slug,
        status="approved",
        approved_at=now,
        consent_recorded_at=now,
        consent_method="legitimate_interest",
        consent_notes=f"Auto-created by the event collector from {source} ({raw.source_type}) on {now.date()}.",
    )


def resolve_organizer(raw, draft, matched_organizer):
    """Organizer waterfall: the source's declared identity, then the name in the text.

    A name that matches no Profile gets an unclaimed one; an event without any
    organizer name returns None and is held.
    """
    from organizers.models import Profile

    declared = (raw.raw_payload.get("organizer") or "").strip()
    if declared:
        return Profile.objects.filter(name__iexact=declared).first() or _create_collected_profile(declared, raw)
    if matched_organizer is not None:
        return matched_organizer
    name = (draft.organizer_name or "").strip()
    return _create_collected_profile(name, raw) if name else None


def find_duplicate(title: str, start):
    """An existing live event on the same Berlin day whose title matches."""
    from events.models import Event

    day = timezone.localtime(start).date()
    return (
        Event.objects.exclude(status__in=["rejected", "cancelled"])
        .filter(start__date=day)
        .annotate(sim=TrigramSimilarity("title", title))
        .filter(sim__gte=_DUPLICATE_TITLE_SIMILARITY)
        .order_by("-sim")
        .first()
    )


def land_collected_event(raw, draft, matched, attempt_kwargs) -> None:
    """Land one extracted collected row: skipped, held, duplicate, draft or published."""
    from events.models import Event
    from syndication.authz import collector_may_publish

    from .models import ExtractionAttempt

    start = _aware(draft.start)
    end = _aware(draft.end) if draft.end else None

    def _finish(status, error="", event=None, success=False):
        raw.extraction_status = status
        raw.extraction_error = error
        raw.save(update_fields=["extraction_status", "extraction_error"])
        ExtractionAttempt.objects.create(**attempt_kwargs, success=success, error=error, event=event)
        logfire.info("collected.landed", raw_message_id=raw.id, outcome=status, error=error)

    if (end or start) < timezone.now() - timedelta(hours=1):
        return _finish("skipped", "past_event")

    duplicate = find_duplicate(draft.title, start)
    if duplicate is not None:
        return _finish("duplicate", "duplicate", event=duplicate)

    organizer = resolve_organizer(raw, draft, matched["organizer"])
    if organizer is None:
        return _finish("needs_review", "no_organizer")

    event = Event.objects.create(
        title=draft.title,
        slug=slugify(draft.title)[:190] + "-" + uuid.uuid4().hex[:8],
        description=draft.description or "",
        organizer=organizer,
        venue=matched["venue"],
        start=start,
        end=end,
        price_min_cents=draft.price_min_cents,
        price_max_cents=draft.price_max_cents,
        is_free=draft.is_free,
        external_url=draft.external_url or "",
        status="draft",
        visibility=derive_visibility_from_sources([rawmessage_source_to_conceptual(raw.source_type)]),
        raw_message=raw,
        suggested_tags=matched["unmatched_tags"],
    )
    event.tags.set(matched["matched_tags"])
    if not raw.collect_only and collector_may_publish(event):
        event.status = "published"
        event.published_at = timezone.now()
        event.save(update_fields=["status", "published_at"])
    _finish("extracted", event=event, success=True)
