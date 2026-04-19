import logfire

from .models import HeartbeatLog


def heartbeat(note="scheduled heartbeat"):
    """Inserted every 5 minutes by django-q2 scheduler. Proves worker loop is alive."""
    log = HeartbeatLog.objects.create(note=note)
    logfire.info("heartbeat ok", heartbeat_log_id=log.pk, ran_at=log.ran_at.isoformat())


def process_raw_message(raw_message_id: int) -> None:
    """django-q2 task: enrichment -> extraction -> entity match -> Event creation."""
    import uuid

    from django.conf import settings
    from django.utils.text import slugify

    from events.models import Event

    from .enrichment import enrich_urls
    from .extraction import extract_event_draft, match_entities
    from .models import ExtractionAttempt, RawMessage, SourceFailure

    # NOTE: logfire is already imported at module level -- do not re-import here.

    try:
        raw_message = RawMessage.objects.get(id=raw_message_id)
    except RawMessage.DoesNotExist:
        logfire.warning(
            "pipeline.raw_message_not_found",
            raw_message_id=raw_message_id,
        )
        return

    # Step 1: URL enrichment (best-effort)
    try:
        enriched = enrich_urls(raw_message.text)
        raw_message.enriched_payload = enriched
        raw_message.save(update_fields=["enriched_payload"])
    except Exception as exc:
        logfire.error(
            "pipeline.enrichment_failed",
            raw_message_id=raw_message_id,
            error=str(exc),
        )
        SourceFailure.objects.create(
            source_type=raw_message.source_type,
            raw_message=raw_message,
            stage="enrichment",
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        enriched = {}

    # Step 2: LLM extraction
    try:
        draft, prompt_version = extract_event_draft(raw_message.text, enriched)
    except Exception as exc:
        raw_message.extraction_status = "failed"
        raw_message.extraction_error = str(exc)
        raw_message.save(update_fields=["extraction_status", "extraction_error"])
        logfire.error(
            "pipeline.extraction_failed",
            raw_message_id=raw_message_id,
            error=str(exc),
        )
        SourceFailure.objects.create(
            source_type=raw_message.source_type,
            raw_message=raw_message,
            stage="extraction",
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        return

    # Step 3: Entity matching
    matched = match_entities(draft)

    # Step 4: Confidence threshold check
    LOW_CONFIDENCE_THRESHOLD = 0.4
    model_name = getattr(settings, "LLM_MODEL_NAME", "claude-opus-4-7")
    draft_json = draft.model_dump(mode="json")
    attempt_kwargs = dict(
        raw_message=raw_message,
        model_name=model_name,
        prompt_version=prompt_version,
        raw_response=draft_json,
        extracted_draft=draft_json,
        confidence_score=draft.confidence,
    )

    if draft.confidence < LOW_CONFIDENCE_THRESHOLD:
        raw_message.extraction_status = "needs_review"
        raw_message.save(update_fields=["extraction_status"])
        ExtractionAttempt.objects.create(
            **attempt_kwargs, success=False, error="low_confidence"
        )
        logfire.info(
            "pipeline.skipped_low_confidence",
            raw_message_id=raw_message_id,
            confidence=draft.confidence,
        )
        return

    # Step 5: Create draft Event
    # UUID suffix ensures slug uniqueness even when organizer is NULL.
    slug = slugify(draft.title)[:190] + "-" + str(uuid.uuid4())[:8]

    event = Event.objects.create(
        title=draft.title,
        slug=slug,
        description=draft.description or "",
        organizer=matched["organizer"],  # may be None (nullable as of 0.2 migration)
        venue=matched["venue"],
        start=draft.start,
        end=draft.end,
        price_min_cents=draft.price_min_cents,
        price_max_cents=draft.price_max_cents,
        is_free=draft.is_free,
        external_url=draft.external_url or "",
        status="draft",
        raw_message=raw_message,
        suggested_tags=matched["unmatched_tags"],
    )
    event.tags.set(matched["matched_tags"])

    ExtractionAttempt.objects.create(**attempt_kwargs, success=True, event=event)

    raw_message.extraction_status = "extracted"
    raw_message.save(update_fields=["extraction_status"])

    logfire.info(
        "pipeline.draft_created",
        event_id=event.id,
        organizer_matched=bool(matched["organizer"]),
        venue_matched=bool(matched["venue"]),
        unmatched_tags_count=len(matched["unmatched_tags"]),
    )


def archive_past_events() -> None:
    """Nightly: archive published events where end < now-24h
    (or start < now-24h if end is NULL). Drafts are left untouched."""
    from datetime import timedelta

    from django.db import models as _models
    from django.utils import timezone

    from events.models import Event

    cutoff = timezone.now() - timedelta(hours=24)
    qs = Event.objects.filter(status="published").filter(
        _models.Q(end__lt=cutoff) | _models.Q(end__isnull=True, start__lt=cutoff)
    )
    count = qs.update(status="archived")
    logfire.info("scheduled.archive_past_events", archived_count=count)


def soft_purge_rawmessages() -> None:
    """Nightly: nullify text/raw_payload/enriched_payload on RawMessages older than
    90 days. Preserves the RawMessage row and all linked ExtractionAttempt rows
    (audit trail) -- only clears PII-bearing raw content."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import RawMessage

    cutoff = timezone.now() - timedelta(days=90)
    count = RawMessage.objects.filter(received_at__lt=cutoff).update(
        text="", raw_payload={}, enriched_payload={}
    )
    logfire.info("scheduled.soft_purge_rawmessages", purged_count=count)
