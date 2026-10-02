"""
The consolidation eval (sb-7wzb.30 acceptance (1), ADR-007 D10/D11): real collected
posts, frozen from the dev DB into eval/consolidation_cases.json, run through the
whole collector pipeline against the REAL model, one case per test, each scored by
its scorer below. The score is the number of cases passed.

Run (needs REQUESTY_API_KEY in .env; costs a few model calls per case):

    uv run pytest ingestion/tests/test_consolidation_eval.py -m agentic -s -p no:warnings

Each post runs at its own "now" (when it was posted), so the eval stays valid after
the events are past. -s prints each case's scorecard (the events it ended with).
"""

import io
import json
import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command
from django.utils import timezone

from events.models import Event
from ingestion.models import ExtractionAttempt, RawMessage
from ingestion.schemas import CollectedEvents, EventDraft

# Read before the autouse fixture (ingestion/tests/conftest.py) swaps in a fake key.
_REAL_KEY = django_settings.LLM_API_KEY
CASES = json.loads((Path(__file__).parent / "eval" / "consolidation_cases.json").read_text())["cases"]


def _run_post(post: dict) -> RawMessage:
    from ingestion.tasks import process_raw_message

    raw = RawMessage.objects.create(
        source_type=post["source_type"],
        channel_id=post["channel_id"],
        message_id=post["message_id"],
        text=post["text"],
        raw_payload=post["raw_payload"],
        enriched_payload={"url_content": post["url_content"]} if post["url_content"] else {},
    )
    now = datetime.fromisoformat(post["now"])
    with (
        patch("django.utils.timezone.now", return_value=now),
        patch("ingestion.enrichment.enrich_urls", return_value={}),  # the frozen link content stands in
    ):
        process_raw_message(raw.id)
    raw.refresh_from_db()
    return raw


def _seed_event(seed: dict) -> None:
    """A collected event landed before the case's posts, through the same pipeline (its draft scripted)."""
    draft = EventDraft(
        title=seed["title"],
        start=datetime.fromisoformat(seed["start"]),
        start_time_unknown=seed["start_time_unknown"],
        description=seed["description"],
        confidence=0.9,
    )
    post = {
        "source_type": "telegram_private_group",
        "channel_id": seed["channel_id"],
        "message_id": "seed",
        "text": seed["description"],
        "url_content": "",
        "raw_payload": {"default_organizer": "poster", "poster": seed["organizer"]},
        "now": "2026-09-20T12:00:00+00:00",
    }
    read = CollectedEvents(post_kind="announcement", events=[draft])
    with patch("ingestion.extraction.extract_collected_events", return_value=read):
        raw = _run_post(post)
    assert raw.extraction_status == "extracted", raw.extraction_error


def _live(**filters):
    return Event.objects.exclude(status__in=["rejected", "cancelled"]).filter(**filters)


def _matching(pattern: str):
    rx = re.compile(pattern, re.IGNORECASE)
    return [e for e in _live() if rx.search(f"{e.title}\n{e.description}\n{e.location_note}")]


def _day(event) -> str:
    return timezone.localtime(event.start).date().isoformat()


def _card(case_id: str, raws: list[RawMessage]) -> str:
    lines = [f"== {case_id}"]
    for raw in raws:
        kinds = sorted({a.post_kind for a in raw.attempts.all()})
        lines.append(f"  raw {raw.message_id}: {raw.extraction_status} {raw.extraction_error!r} kind={kinds}")
    for e in _live().order_by("start", "id"):
        links = list(e.links.values_list("url", flat=True))
        lines.append(
            f"  event {e.id} {_day(e)} {e.title!r} presence={e.presence} venue={e.venue} "
            f"dup_of={e.possible_duplicate_of_id} links={links}\n    {e.description[:300]!r}"
        )
    return "\n".join(lines)


# -- scorers: each returns the failures, empty = pass --------------------------


def _score_a(raws):
    failures = []
    retreats = [e for e in _matching(r"retreat|spitzm") if _day(e) == "2026-10-08"]
    if len(retreats) != 1:
        failures.append(f"expected ONE retreat event on 2026-10-08, got {[(e.id, e.title) for e in retreats]}")
    else:
        description = retreats[0].description
        if not re.search(r"temple night", description, re.IGNORECASE):
            failures.append("the retreat description lacks the programme ('Temple Nights')")
        if "530" not in description:
            failures.append("the retreat description lacks the price (530€)")
        if re.search(r"helper", description, re.IGNORECASE):
            failures.append("the retreat description carries the helper call")
    helper = next(r for r in raws if r.message_id == "174")
    attempts = list(ExtractionAttempt.objects.filter(raw_message=helper))
    if [a.post_kind for a in attempts] != ["about_event"]:
        failures.append(f"helper post kinds {[a.post_kind for a in attempts]}, expected ['about_event']")
    if any(a.event_id for a in attempts) or Event.objects.filter(raw_message=helper).exists():
        failures.append("the helper post is attached to an event")
    return failures


def _score_b(raws):
    failures = []
    for day, expected in (("2026-10-05", 4), ("2026-10-07", 2)):
        events = [e for e in _live() if _day(e) == day]
        if len(events) != expected:
            failures.append(f"{day}: expected {expected} separate events, got {[e.title for e in events]}")
    if any(r.extraction_status != "extracted" for r in raws):
        failures.append(f"statuses {[(r.message_id, r.extraction_status) for r in raws]}, expected all extracted")
    return failures


def _score_c(raws):
    jams = _matching(r"erotic\s*jam")
    if len(jams) != 1:
        return [f"expected ONE Erotic Jam event, got {[(e.id, _day(e)) for e in jams]}"]
    if _day(jams[0]) != "2026-11-21":
        return [f"the Erotic Jam is on {_day(jams[0])}, expected the new date 2026-11-21"]
    return []


def _score_d(raws):
    events = _matching(r"ecstati\s*kink")
    if len(events) != 1:
        return [f"expected ONE EcstatiKink event, got {[(e.id, e.title) for e in events]}"]
    links = list(events[0].links.values_list("url", flat=True))
    if not any("eventbrite.com/e/ecstatikink" in url for url in links):
        return [f"no Eventbrite EventLink on the event: {links}"]
    return []


def _score_e(raws):
    events = list(_live(raw_message=raws[0]))
    if len(events) != 1:
        return [f"expected the online event kept, got {[e.title for e in events]}"]
    event = events[0]
    failures = []
    if event.presence != "online":
        failures.append(f"presence {event.presence!r}, expected 'online'")
    if event.venue_id is not None:
        failures.append(f"an online event has a venue: {event.venue}")
    return failures


SCORERS = {
    "a_retreat_one_event": _score_a,
    "b_iksk_one_day_separate": _score_b,
    "c_moved_date_no_duplicate": _score_c,
    "c_moved_date_from_old_date": _score_c,
    "d_cross_post_one_event_with_link": _score_d,
    "e_online_only_kept": _score_e,
}


@pytest.mark.agentic
@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_consolidation_eval(case, settings, tmp_path):
    if not _REAL_KEY:
        pytest.skip("REQUESTY_API_KEY is not set: the eval needs the real model")
    settings.LLM_API_KEY = _REAL_KEY
    settings.MEDIA_ROOT = str(tmp_path)
    call_command("seed_collector_sources", stdout=io.StringIO())
    if "seed_event" in case:
        _seed_event(case["seed_event"])
    raws = [_run_post(post) for post in sorted(case["posts"], key=lambda p: p["now"])]
    failures = SCORERS[case["id"]](raws)
    print(_card(case["id"], raws))
    print("  PASS" if not failures else "  FAIL: " + "; ".join(failures))
    assert not failures, f"{case['criterion']}: {failures}"


def test_every_case_has_a_scorer():
    assert {c["id"] for c in CASES} == set(SCORERS)
