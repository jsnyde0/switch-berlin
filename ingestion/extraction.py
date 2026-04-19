import logfire
from pydantic_ai import Agent

from ingestion.schemas import EventDraft

PROMPT_VERSION = "v1"

EXTRACTION_PROMPT_V1 = """
Extract event details from the following text and return a JSON object
matching the schema.

Known organizers (prefer exact match): {organizer_names}
Known venues (prefer exact match): {venue_names}
Known tag slugs (prefer exact match): {tag_slugs}

Set confidence between 0.0 and 1.0 based on completeness and certainty.
If key fields (title, start datetime) are missing or ambiguous, set confidence < 0.4.

Text:
{text}

Enriched content from URLs:
{enriched_content}
"""


def extract_event_draft(
    raw_message_text: str, enriched_payload: dict
) -> tuple[EventDraft, str]:
    """Returns (draft, prompt_version). Runs synchronously inside a django-q2 worker."""
    from events.models import Tag
    from organizers.models import Organizer
    from venues.models import Venue

    organizer_names = list(Organizer.objects.values_list("name", flat=True))
    venue_names = list(Venue.objects.values_list("name", flat=True))
    tag_slugs = list(Tag.objects.values_list("slug", flat=True))

    prompt = EXTRACTION_PROMPT_V1.format(
        organizer_names=", ".join(organizer_names) or "(none)",
        venue_names=", ".join(venue_names) or "(none)",
        tag_slugs=", ".join(tag_slugs) or "(none)",
        text=raw_message_text,
        enriched_content=enriched_payload.get("url_content", ""),
    )

    from django.conf import settings

    model_name = getattr(settings, "LLM_MODEL_NAME", "claude-opus-4-7")
    agent = Agent(model_name, result_type=EventDraft)
    result = agent.run_sync(prompt)
    draft = result.data

    logfire.info(
        "extraction.llm_call",
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        confidence=draft.confidence,
    )
    return (draft, PROMPT_VERSION)


def match_entities(draft: EventDraft) -> dict:
    """
    Returns dict with keys:
      organizer (Organizer|None), venue (Venue|None),
      matched_tags (list[Tag]), unmatched_tags (list[str])
    """
    from django.contrib.postgres.search import TrigramSimilarity

    from events.models import Tag
    from organizers.models import Organizer
    from venues.models import Venue

    # Organizer matching: exact first, then trigram fuzzy
    organizer = Organizer.objects.filter(name__iexact=draft.organizer_name).first()
    if organizer is None:
        candidates = (
            Organizer.objects.annotate(
                sim=TrigramSimilarity("name", draft.organizer_name)
            )
            .filter(sim__gte=0.6)
            .order_by("-sim")
        )
        count = candidates.count()
        if count == 1:
            organizer = candidates.first()
        # If count == 0 or count > 1: leave organizer as None

    # Venue matching: exact only, no fuzzy fallback
    venue = (
        Venue.objects.filter(name__iexact=draft.venue_name).first()
        if draft.venue_name
        else None
    )

    # Tag matching: exact on slug, unmatched -> suggested_tags
    matched_tags = []
    unmatched_tags = []
    for tag_str in draft.tags:
        tag = Tag.objects.filter(slug__iexact=tag_str).first()
        if tag:
            matched_tags.append(tag)
        else:
            unmatched_tags.append(tag_str)

    logfire.info(
        "extraction.entity_match",
        organizer_matched=bool(organizer),
        venue_matched=bool(venue),
        unmatched_tags_count=len(unmatched_tags),
    )

    return {
        "organizer": organizer,
        "venue": venue,
        "matched_tags": matched_tags,
        "unmatched_tags": unmatched_tags,
    }
