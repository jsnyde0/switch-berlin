"""
The consolidation eval (sb-7wzb.30 acceptance (1), ADR-007 D10/D11): real collected
posts, frozen from the dev DB into eval/consolidation_cases.json, run through the
whole collector pipeline against the REAL model, one case per test, each scored by
its scorer below. The score is the number of cases passed.

Run (needs REQUESTY_API_KEY in .env; costs a few model calls per case):

    uv run pytest ingestion/tests/test_consolidation_eval.py -m agentic -s -p no:warnings

Posts run in the listed order, each at its own "now" (when it was posted, unless the
case sets one), so the eval stays valid after the events are past. Each case runs
RUNS times; a case passes only when every run does. A row whose read failed is read
again once, as the next collect run would (sb-7wzb.30 ruling 8); the scorecard lists
every such re-run, so first-read failures stay visible. -s prints each case's scorecard (the events it ended with).
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


def _run_post(post: dict, now: str | None = None) -> RawMessage:
    """Collect one post (a post already collected is re-read with its new text) and run the pipeline on it."""
    from ingestion.tasks import process_raw_message

    content = dict(
        text=post["text"],
        raw_payload=post["raw_payload"],
        enriched_payload={"url_content": post["url_content"]} if post["url_content"] else {},
        extraction_status="pending",
    )
    raw, _ = RawMessage.objects.update_or_create(
        source_type=post["source_type"], channel_id=post["channel_id"], message_id=post["message_id"], defaults=content
    )
    with (
        patch("django.utils.timezone.now", return_value=datetime.fromisoformat(now or post["now"])),
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
        "source_type": seed.get("source_type", "telegram_private_group"),
        "channel_id": seed["channel_id"],
        "message_id": "seed",
        "text": seed["description"],
        "url_content": "",
        "raw_payload": seed.get("raw_payload") or {"default_organizer": "poster", "poster": seed["organizer"]},
        "now": "2026-09-15T12:00:00+00:00",
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


def _retreats():
    return [e for e in _matching(r"retreat|spitzm") if _day(e) == "2026-10-08"]


def _score_a(raws):
    failures = []
    retreats = _retreats()
    if len(retreats) != 1:
        failures.append(f"expected ONE retreat event on 2026-10-08, got {[(e.id, e.title) for e in retreats]}")
    else:
        retreat = retreats[0]
        description = retreat.description
        if not re.search(r"temple night", description, re.IGNORECASE):
            failures.append("the retreat description lacks the programme ('Temple Nights')")
        if "530" not in description:
            failures.append("the retreat description lacks the price (530€)")
        if re.search(r"helper", description, re.IGNORECASE):
            failures.append("the retreat description carries the helper call")
        organizers = [(r.profile.name, r.attribution) for r in retreat.event_organizer_set.order_by("order")]
        if organizers != [("Till & Shirka", "publisher")]:
            failures.append(f"the retreat is credited to {organizers}, expected Till & Shirka (publisher)")
    helper = next(r for r in raws if r.message_id == "174")
    attempts = list(ExtractionAttempt.objects.filter(raw_message=helper))
    if [a.post_kind for a in attempts] != ["about_event"]:
        failures.append(f"helper post kinds {[a.post_kind for a in attempts]}, expected ['about_event']")
    if any(a.event_id for a in attempts) or Event.objects.filter(raw_message=helper).exists():
        failures.append("the helper post is attached to an event")
    return failures


def _score_privacy(raws):
    """Nothing the private post alone said shows on the public event: fields, credits, links, cover, page."""
    from django.test import Client
    from django.urls import reverse

    retreats = _retreats()
    if len(retreats) != 1:
        return [f"expected ONE retreat event, got {[(e.id, e.title) for e in retreats]}"]
    event = retreats[0]
    failures = []
    if event.visibility != "public":
        failures.append(f"visibility {event.visibility!r}, expected public (a public source is attached)")
    shown = "\n".join(
        [
            event.title,
            event.description,
            event.location_note,
            event.venue.address if event.venue else "",
            str(event.price_min_cents),
            str(event.price_max_cents),
            *event.artist_credits.values_list("name", flat=True),
            *(link.url for link in event.source_links),
        ]
    )
    organizer = event.event_organizer_set.order_by("order").first()
    page = (
        Client()
        .get(reverse("event-detail", kwargs={"org_slug": organizer.profile.slug, "event_slug": event.slug}))
        .content.decode()
    )
    for private_only in ("Mühlenweg", "444", "Hidden Guest", "members.example", "Centre to yourself"):
        if private_only in shown or private_only in page:
            failures.append(f"the public event shows private-only {private_only!r}")
    if event.shown_cover is not None and not event.shows_source(event.shown_cover.raw_message):
        failures.append("the cover comes from a less public source")
    return failures


def _score_separate_hosts(raws):
    events = {a.event_id for r in raws for a in r.attempts.all()}
    if None in events or len(events) != 2:
        return [f"expected two separate events, attempts point at {sorted(map(str, events))}"]
    return []


def _score_undated_cancellation(raws):
    zurich = Event.objects.get(title="Temple Zurich")
    if zurich.status == "cancelled":
        return ["an undated cancellation cancelled the Zurich event"]
    return []


def _score_dated_cancellation(raws):
    jams = _matching(r"erotic\s*jam") + [
        e for e in Event.objects.filter(status="cancelled") if "jam" in e.title.lower()
    ]
    jams = list({e.id: e for e in jams}.values())
    if len(jams) != 1:
        return [f"expected ONE Erotic Jam event, got {[(e.id, e.status) for e in jams]}"]
    if jams[0].status != "cancelled":
        return [f"the Erotic Jam is {jams[0].status}, expected cancelled"]
    return []


def _score_re_read(raws):
    retreats = _retreats()
    if len(retreats) != 1:
        return [f"expected ONE retreat event after the re-read, got {[(e.id, e.title) for e in retreats]}"]
    return []


def _score_b(raws):
    """Each listed event lands on its own event: identity, not counts."""
    landed = {}
    for raw in raws:
        events = {a.event_id for a in raw.attempts.all()}
        if len(events) != 1 or None in events:
            return [f"listing {raw.message_id!r} landed on {sorted(map(str, events))}, expected one event"]
        landed[raw.message_id] = events.pop()
    shared = len(landed) - len(set(landed.values()))
    return [f"{shared} listing(s) share an event: {landed}"] if shared else []


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
    "a_retreat_reverse_order": _score_a,
    "privacy_private_then_public": _score_privacy,
    "privacy_public_then_private": _score_privacy,
    "different_explicit_organizers_stay_separate": _score_separate_hosts,
    "undated_cancellation_cancels_nothing": _score_undated_cancellation,
    "dated_cancellation_cancels_the_event": _score_dated_cancellation,
    "re_read_after_consolidation": _score_re_read,
    "b_iksk_one_day_separate": _score_b,
    "c_moved_date_no_duplicate": _score_c,
    "c_moved_date_from_old_date": _score_c,
    "d_cross_post_one_event_with_link": _score_d,
    "e_online_only_kept": _score_e,
}


RUNS = 3  # a case passes only when every run passes (the model is not deterministic)


@pytest.mark.agentic
@pytest.mark.django_db
@pytest.mark.parametrize("run", range(1, RUNS + 1), ids=lambda n: f"run{n}")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_consolidation_eval(case, run, settings, tmp_path):
    if not _REAL_KEY:
        pytest.skip("REQUESTY_API_KEY is not set: the eval needs the real model")
    settings.LLM_API_KEY = _REAL_KEY
    settings.MEDIA_ROOT = str(tmp_path)
    call_command("seed_collector_sources", stdout=io.StringIO())
    if "seed_event" in case:
        _seed_event(case["seed_event"])
    ran = {}  # raw id -> (raw, the post it last read); a re-read post counts once
    for post in case["posts"]:
        raw = _run_post(post, case.get("now"))
        ran[raw.id] = (raw, post)
    raws = [raw for raw, _ in ran.values()]
    # The next collect run reads a failed row again (ruling 8): the eval runs that pass too, and says so.
    for raw, post in [(raw, post) for raw, post in ran.values() if raw.extraction_status == "failed"]:
        print(f"  re-run {raw.message_id}: first read failed: {raw.extraction_error[:300]!r}")
        _run_post(post, case.get("now"))
    for raw in raws:
        raw.refresh_from_db()
    failures = SCORERS[case["id"]](raws)
    print(_card(f"{case['id']} run{run}", raws))
    print("  PASS" if not failures else "  FAIL: " + "; ".join(failures))
    assert not failures, f"{case['criterion']}: {failures}"


def test_every_case_has_a_scorer():
    assert {c["id"] for c in CASES} == set(SCORERS)
