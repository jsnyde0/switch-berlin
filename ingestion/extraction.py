import json

import httpx
import logfire
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

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


def router_model(model_name: str) -> OpenAIChatModel:
    """A pydantic-ai model on the LLM router (settings.LLM_BASE_URL). Fails loud without a key."""
    from django.conf import settings

    if not settings.LLM_API_KEY:
        raise RuntimeError("REQUESTY_API_KEY is not set; the LLM router needs it (ADR-008 D3).")
    return OpenAIChatModel(
        model_name, provider=OpenAIProvider(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)
    )


EVENT_QUESTION = (
    "Is this post an announcement that promotes a specific upcoming event (party, workshop, class, ritual, "
    "meetup) with its own date, written to invite people to it? Answer no for chat messages, questions, "
    "replies, thank-yous and general discussion."
)


def event_announcement_score(text: str) -> float:
    """Probability (0-1) that a post announces an event, from the classifier model (a Jev 'noul' question)."""
    from django.conf import settings

    if not settings.LLM_API_KEY:
        raise RuntimeError("REQUESTY_API_KEY is not set; the LLM router needs it (ADR-008 D3).")
    response = httpx.post(
        f"{settings.LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
        json={
            "model": settings.EVENT_CLASSIFIER_MODEL,
            "messages": [{"role": "user", "content": text}],
            "response_format": {
                "type": "questions",
                "questions": {"is_event": {"type": "noul", "instructions": EVENT_QUESTION}},
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    return float(json.loads(response.json()["choices"][0]["message"]["content"])["is_event"]["noul"])


def extract_event_draft(raw_message_text: str, enriched_payload: dict) -> tuple[EventDraft, str]:
    """Returns (draft, prompt_version). Runs synchronously inside a django-q2 worker."""
    from events.models import Tag
    from organizers.models import Profile
    from venues.models import Venue

    organizer_names = list(Profile.objects.values_list("name", flat=True))
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

    model_name = settings.LLM_MODEL_NAME
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
