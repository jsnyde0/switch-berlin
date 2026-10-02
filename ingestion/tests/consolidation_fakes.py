"""Stand-ins for the consolidation call (ADR-007 D10): tests script the judgement, code does the rest."""

from contextlib import contextmanager
from unittest.mock import patch

from ingestion.schemas import Consolidation, Decision, EventDraft


def as_draft(view: dict, **overrides) -> EventDraft:
    """An EventDraft from a request's draft view (the JSON the call receives)."""
    return EventDraft(**{"confidence": 0.9, **view, **overrides})


def same_as_first(request: list[dict], description_from=0, **merged) -> Consolidation:
    """Every post event is its first candidate, written out as the post event (plus `merged` overrides).

    The description comes from `description_from` (0 = the post event), when that announcement is eligible.
    """
    decisions = []
    for e in request:
        candidate = e["candidates"][0]
        eligible = {a["id"] for a in candidate["announcements"] if a["eligible"]}
        if candidate["post_event_eligible"]:
            eligible.add(0)
        decisions.append(
            Decision(
                draft=e["draft"],
                same_as=candidate["id"],
                event=as_draft(e["event"], **merged),
                description_from=description_from if description_from in eligible else None,
            )
        )
    return Consolidation(decisions=decisions)


def all_new(request: list[dict]) -> Consolidation:
    return Consolidation(decisions=[Decision(draft=e["draft"]) for e in request])


def unexpected(request: list[dict]) -> Consolidation:
    raise AssertionError(f"no consolidation call expected, got {request}")


@contextmanager
def judge(decide=unexpected):
    """Patch the consolidation call with `decide(request) -> Consolidation`; yields the list of requests seen."""
    seen = []

    def call(request):
        seen.append(request)
        return decide(request)

    with patch("ingestion.extraction.consolidate", side_effect=call):
        yield seen
