import base64
import time

import logfire
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ingestion.schemas import CollectedEvents, Consolidation, EventDraft

PROMPT_VERSION = "v3"

EXTRACTION_PROMPT = """
Extract event details from the following text and return a JSON object
matching the schema.

Known venues (prefer exact match): {venue_names}
Known tag slugs (prefer exact match): {tag_slugs}

Set confidence between 0.0 and 1.0 based on completeness and certainty.
If key fields (title, start datetime) are missing or ambiguous, set confidence < 0.4.

{people}

Set in_berlin_area to false when the event takes place outside Berlin and its
surroundings (another city or country), or only online.

Text:
{text}

Enriched content from URLs:
{enriched_content}
"""

COLLECTED_PROMPT_VERSION = "collected-v6"

# Longest description the prompt allows; the organizer's promotional text is covered by
# docs/compliance/organizer-lia.md §1 (sb-7wzb.27).
DESCRIPTION_CAP_CHARS = 3000

# Who runs the event versus who is on the program (ADR-007 D9): never guessed.
PEOPLE_RULES = """explicit_organizer is who runs the event, ONLY when the text uses explicit
organizer wording for them: "organised by", "hosted by", "presented by",
"Veranstalter", "Host:", "Organizer:". Copy the name(s) as written. Return ""
when there is no such wording. Never fill it from a logo, page title, header,
footer or website name, from the channel, group or website the post appears in,
or from a line that names the venue.

artist_names lists every other person or act the text names: teachers, guides,
DJs, performers, speakers ("mit", "with", "w/", "led by"). One entry per person:
"Tina, Ricardo & Mal" is three entries. Leave out the organizer and the venue."""

COLLECTED_PROMPT = """
Below is one post a collector gathered from an organizer website or a Telegram
channel or group, together with the images attached to it (flyers, posters).
Read the text AND the images.

First say what the post is (post_kind):
- "announcement": it announces one or more events, inviting people to come. A
  post that changes an event's date, time or place announces the changed event;
  a post that cancels an event announces it with cancelled true.
- "about_event": it is about an event but does not announce it: a call for
  helpers or volunteers, a sold-out or waiting-list notice, a reminder, a recap
  or thank-you after the event.
- "other": chat messages, questions, replies, general discussion.

Then return the events the post ANNOUNCES as a list of objects matching the
schema: one object per event (one per date when a series lists several dates).
An event the post mentions twice (in a list of dates and again in a "last
call" line) is one object.
Return an empty list for "about_event" and "other": their events are announced
elsewhere.

Known venues (prefer exact match): {venue_names}
Known tag slugs (prefer exact match): {tag_slugs}

Set confidence between 0.0 and 1.0 based on completeness and certainty.
If key fields (title, start datetime) are missing or ambiguous, set confidence < 0.4.
When a date is given but no start time, set start to that date at 00:00 and
start_time_unknown to true; a missing time alone does not lower confidence.
When the post says the event moved, set moved_from to the start it had before.
Give times as the post states them. timezone is the IANA zone the post states
for them ("Europe/Vienna" for times given in Vienna time); null when it states
none.

{people}

presence is "online" when the post says the event happens only online (Zoom,
livestream), "hybrid" when it says it happens in a place and online,
"in_person" when it names a place; null when it does not say.
Set in_berlin_area to false only when an in-person or hybrid event happens
outside Berlin and its surroundings (another city or country). An online event
keeps in_berlin_area true.

venue_name is the place the event happens, as the post names it. venue_address
is the street address the post gives for it, if any. location_note is where-info
that names no place: "Online (Zoom)", a city or district, "Secret location,
shared with ticket holders". Never put a street address in location_note. Leave
all three empty when the post says nothing about where. An online event has no
venue_name.

external_url is the link the post gives for this event (tickets, sign-up or
info page), copied exactly; null when the post gives none.

category is one of: play_party, workshop, munch, performance, social, festival,
talk (a talk, lecture, colloquium or online intro), other; "" when unsure.

description is the organizer's own prose about this event, copied unchanged from
the post text or the link content: same words, no summary, no rewriting, no
translation, nothing added. Keep every line about the event, in order,
including its programme and its date, place and price lines. Leave out menus, navigation, cookie notices and booking
boilerplate that is not about the event. Keep at most {description_cap}
characters (cut at the end of a sentence). Return "" when the source has no prose
about the event; never write one yourself.

Post:
{text}

Enriched content from URLs:
{enriched_content}
"""

CONSOLIDATION_PROMPT_VERSION = "consolidate-v1"

CONSOLIDATION_PROMPT = """
A collector read one post and found the events it announces ("post events"
below). For each post event it also found existing events around the same dates
that share something with it (a similar host, a shared artist, the same venue
or a similar title): the candidates. Many organizers run several different
events on one day at one venue; a post may also be a copy of an announcement we
already have, reposted in another channel or with different wording.

Each candidate lists its announcements (id, the post's reading of the event,
eligible). Only ELIGIBLE announcements may supply the event's text. The others
come from a less public source: they show only their dates and organizer keys
(an organizer key names one organizer; equal keys are the same organizer), to
help you judge whether it is the same event, and nothing of them may show on
the event. The post event itself counts as announcement id 0, eligible as
"post_event_eligible" says; when it is not eligible, still judge same_as, but
write `event` from the eligible announcements only.

For each post event, decide:
- same_as: the candidate's id when the post event IS that event (the same
  occasion: same organizer or host, same dates, the same happening even under a
  different title). Then write out `event`, the event in full, from the
  eligible announcements only (its eligible earlier announcements plus the post
  event when eligible), so the result does not depend on which came first:
  - title: the clearest full title an eligible announcement gives.
  - dates, times, timezone, price, artists, tags, category: the most complete
    and most recent information; presence only as an announcement states it.
  - cancelled: true when an announcement says the event is cancelled.
  - explicit_organizer: the names eligible announcements give with organizer
    wording, joined with ", "; "" when none does.
  - description, venue and links are taken by code: leave description "".
  And set description_from: the id of the eligible announcement with the
  fullest description of the event itself (never a call for helpers, a reminder
  or other text not describing the event); null when none has one.
- possibly_same_as: when you are unsure, give no same_as and name the candidate
  you suspect here; the post event becomes a new event a person will check.
- neither: a new event.

Two different explicit organizers are a strong sign of different events.
Different events at one venue on one day are different events. Two post events
of one post may be the same candidate only when they are the same event. A post
event marked "is" is a newer reading of a post already attached to that event:
give that id as same_as.

Answer with one decision per post event, numbered as below.

Post events and their candidates (JSON):
{request}
"""


# ADR-008 D4 (FIRM): a connection error or timeout is retried up to twice, with linear backoff; any
# HTTP 4xx/5xx response and any reply that does not fit the schema fails loud at once. The client
# itself never retries (max_retries=0): this loop is the only retry.
TRANSPORT_RETRIES = 2
TRANSPORT_BACKOFF_SECONDS = 2
# One call's limit: all three attempts end inside django-q's 300s task timeout, so a hung call
# fails loud as a transport timeout instead of the task dying mid-call (sb-7wzb.33).
MODEL_CALL_TIMEOUT_SECONDS = 90.0


def router_model(model_name: str) -> OpenAIChatModel:
    """A pydantic-ai model on the LLM router (settings.LLM_BASE_URL). Fails loud without a key."""
    from django.conf import settings
    from openai import AsyncOpenAI

    if not settings.LLM_API_KEY:
        raise RuntimeError("REQUESTY_API_KEY is not set; the LLM router needs it (ADR-008 D3).")
    client = AsyncOpenAI(
        base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY, max_retries=0, timeout=MODEL_CALL_TIMEOUT_SECONDS
    )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _is_transport_error(exc: Exception) -> bool:
    """A connection error or timeout: no HTTP response came back."""
    from openai import APIConnectionError

    return (
        isinstance(exc, ModelAPIError)
        and not isinstance(exc, ModelHTTPError)
        and isinstance(exc.__cause__, APIConnectionError)
    )


def with_transport_retries(call):
    """`call()`, retried up to TRANSPORT_RETRIES times on a transport error only (ADR-008 D4)."""
    for attempt in range(TRANSPORT_RETRIES + 1):
        try:
            return call()
        except ModelAPIError as exc:
            if attempt == TRANSPORT_RETRIES or not _is_transport_error(exc):
                raise
            logfire.warn("extraction.transport_retry", attempt=attempt + 1, error=str(exc))
            time.sleep(TRANSPORT_BACKOFF_SECONDS * (attempt + 1))


def _ask(output_type, prompt):
    """One model call returning `output_type`. A reply that does not fit is never retried (ADR-008 D4):
    it raises with the reason, so the row fails loud and the next collect run reads it again."""
    from django.conf import settings

    agent = Agent(router_model(settings.LLM_MODEL_NAME), output_type=output_type, retries=0)
    try:
        return with_transport_retries(lambda: agent.run_sync(prompt)).output
    except UnexpectedModelBehavior as exc:
        reason = exc.__cause__ or exc.body or exc
        raise ValueError(f"the model's reply did not fit {output_type.__name__}: {reason}") from exc


def _known_names() -> dict:
    from events.models import Tag
    from venues.models import Venue

    return dict(
        venue_names=", ".join(Venue.objects.values_list("name", flat=True)) or "(none)",
        tag_slugs=", ".join(Tag.objects.values_list("slug", flat=True)) or "(none)",
    )


def extract_collected_events(text: str, images_b64: list[str], enriched_payload: dict) -> CollectedEvents:
    """The events one collected post announces and its post_kind, from its text and images (ADR-007 D10)."""
    from django.conf import settings

    prompt = COLLECTED_PROMPT.format(
        **_known_names(),
        people=PEOPLE_RULES,
        description_cap=DESCRIPTION_CAP_CHARS,
        text=text or "(no text; read the images)",
        enriched_content=enriched_payload.get("url_content", ""),
    )
    parts = [prompt] + [BinaryContent(data=base64.b64decode(b), media_type="image/jpeg") for b in images_b64]
    output = _ask(CollectedEvents, parts)
    logfire.info(
        "extraction.collected_llm_call",
        model_name=settings.LLM_MODEL_NAME,
        prompt_version=COLLECTED_PROMPT_VERSION,
        images=len(images_b64),
        events=len(output.events),
        post_kind=output.post_kind,
    )
    return output


def consolidate(request: list[dict]) -> Consolidation:
    """One call: which existing candidate each post event is, and that event rewritten in full (ADR-007 D10).

    `request` = one entry per post event with candidates: {"draft": i, "event": ..., "candidates": [...]}.
    The caller validates the decisions against the request.
    """
    import json

    from django.conf import settings

    prompt = CONSOLIDATION_PROMPT.format(request=json.dumps(request, ensure_ascii=False, indent=1, default=str))
    output = _ask(Consolidation, prompt)
    logfire.info(
        "extraction.consolidation_llm_call",
        model_name=settings.LLM_MODEL_NAME,
        prompt_version=CONSOLIDATION_PROMPT_VERSION,
        post_events=len(request),
        candidates=sum(len(entry["candidates"]) for entry in request),
    )
    return output


def extract_event_draft(
    raw_message_text: str, enriched_payload: dict, model_name: str | None = None
) -> tuple[EventDraft, str]:
    """Returns (draft, prompt_version). Runs synchronously inside a django-q2 worker."""
    prompt = EXTRACTION_PROMPT.format(
        **_known_names(),
        people=PEOPLE_RULES,
        text=raw_message_text,
        enriched_content=enriched_payload.get("url_content", ""),
    )

    from django.conf import settings

    model_name = model_name or settings.LLM_MODEL_NAME
    agent = Agent(router_model(model_name), output_type=EventDraft)
    result = with_transport_retries(lambda: agent.run_sync(prompt))
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
    from events.models import Tag
    from organizers.names import find_profile, find_venue

    # Profile matching: exact normalized name only, never fuzzy (ADR-007 D9)
    organizer = find_profile(draft.explicit_organizer) if draft.explicit_organizer.strip() else None

    # Venue matching: exact only, no fuzzy fallback
    venue = find_venue(draft.venue_name) if draft.venue_name else None

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
