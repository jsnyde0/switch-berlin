import base64

import logfire
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ingestion.schemas import CollectedEvents, EventDraft

PROMPT_VERSION = "v2"

EXTRACTION_PROMPT = """
Extract event details from the following text and return a JSON object
matching the schema.

Known organizers (prefer exact match): {organizer_names}
Known venues (prefer exact match): {venue_names}
Known tag slugs (prefer exact match): {tag_slugs}

Set confidence between 0.0 and 1.0 based on completeness and certainty.
If key fields (title, start datetime) are missing or ambiguous, set confidence < 0.4.

organizer_name is the person or collective hosting the event, as the text names
them. A Telegram group, forum or website the post merely appears in is not the
organizer unless the text says it hosts. If the text names no host, return "".

Set in_berlin_area to false when the event takes place outside Berlin and its
surroundings (another city or country), or only online.

Text:
{text}

Enriched content from URLs:
{enriched_content}
"""

COLLECTED_PROMPT_VERSION = "collected-v1"

COLLECTED_PROMPT = """
Below is one post a collector gathered from an organizer website or a Telegram
channel or group, together with the images attached to it (flyers, posters).
Return every upcoming or past event the post announces, reading the text AND the
images, as a list of objects matching the schema: one object per event (one per
date when a series lists several dates). Return an empty list when the post
announces no specific event with its own date: chat messages, questions,
replies, thank-yous, general discussion.

Known organizers (prefer exact match): {organizer_names}
Known venues (prefer exact match): {venue_names}
Known tag slugs (prefer exact match): {tag_slugs}

Set confidence between 0.0 and 1.0 based on completeness and certainty.
If key fields (title, start datetime) are missing or ambiguous, set confidence < 0.4.
When only a date is given and no time, still return the event but set confidence < 0.4.

organizer_name is the person or collective hosting the event, as the post names
them. A Telegram group, forum or website the post merely appears in is not the
organizer unless the post says it hosts. If the post names no host, return "".

Set in_berlin_area to false when the event takes place outside Berlin and its
surroundings (another city or country), or only online.

Post:
{text}

Enriched content from URLs:
{enriched_content}
"""


def router_model(model_name: str) -> OpenAIChatModel:
    """A pydantic-ai model on the LLM router (settings.LLM_BASE_URL). Fails loud without a key."""
    from django.conf import settings

    if not settings.LLM_API_KEY:
        raise RuntimeError("REQUESTY_API_KEY is not set; the LLM router needs it (ADR-008 D3).")
    return OpenAIChatModel(
        model_name, provider=OpenAIProvider(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)
    )


def _known_names() -> dict:
    from events.models import Tag
    from organizers.models import Profile
    from venues.models import Venue

    return dict(
        organizer_names=", ".join(Profile.objects.values_list("name", flat=True)) or "(none)",
        venue_names=", ".join(Venue.objects.values_list("name", flat=True)) or "(none)",
        tag_slugs=", ".join(Tag.objects.values_list("slug", flat=True)) or "(none)",
    )


def extract_collected_events(text: str, images_b64: list[str], enriched_payload: dict) -> list[EventDraft]:
    """Every event one collected post announces, from its text and images (sb-7wzb.4). Empty = not an event."""
    from django.conf import settings

    prompt = COLLECTED_PROMPT.format(
        **_known_names(),
        text=text or "(no text; read the images)",
        enriched_content=enriched_payload.get("url_content", ""),
    )
    parts = [prompt] + [BinaryContent(data=base64.b64decode(b), media_type="image/jpeg") for b in images_b64]
    result = Agent(router_model(settings.LLM_MODEL_NAME), output_type=CollectedEvents).run_sync(parts)
    events = result.output.events
    logfire.info(
        "extraction.collected_llm_call",
        model_name=settings.LLM_MODEL_NAME,
        prompt_version=COLLECTED_PROMPT_VERSION,
        images=len(images_b64),
        events=len(events),
    )
    return events


def extract_event_draft(
    raw_message_text: str, enriched_payload: dict, model_name: str | None = None
) -> tuple[EventDraft, str]:
    """Returns (draft, prompt_version). Runs synchronously inside a django-q2 worker."""
    prompt = EXTRACTION_PROMPT.format(
        **_known_names(),
        text=raw_message_text,
        enriched_content=enriched_payload.get("url_content", ""),
    )

    from django.conf import settings

    model_name = model_name or settings.LLM_MODEL_NAME
    agent = Agent(router_model(model_name), output_type=EventDraft)
    result = agent.run_sync(prompt)
    draft = result.output

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
    from organizers.models import Profile
    from venues.models import Venue

    # Profile matching: exact first, then trigram fuzzy
    organizer = Profile.objects.filter(name__iexact=draft.organizer_name).first()
    if organizer is None:
        candidates = (
            Profile.objects.annotate(sim=TrigramSimilarity("name", draft.organizer_name))
            .filter(sim__gte=0.6)
            .order_by("-sim")
        )
        count = candidates.count()
        if count == 1:
            organizer = candidates.first()
        # If count == 0 or count > 1: leave organizer as None

    # Venue matching: exact only, no fuzzy fallback
    venue = Venue.objects.filter(name__iexact=draft.venue_name).first() if draft.venue_name else None

    # Tag matching: exact on slug, unmatched -> suggested_tags
    # Fetch all tags in one query and match in Python to avoid N+1.
    all_tags = {tag.slug.lower(): tag for tag in Tag.objects.all()}
    matched_tags = []
    unmatched_tags = []
    for tag_str in draft.tags:
        tag = all_tags.get(tag_str.lower())
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
