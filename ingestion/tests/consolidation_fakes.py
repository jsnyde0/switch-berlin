"""Stand-ins for the consolidation call (ADR-007 D10): tests script the judgement, code does the rest."""

from contextlib import contextmanager
from unittest.mock import patch

from ingestion.schemas import Consolidation, Decision, EventDraft


def as_draft(view: dict, **overrides) -> EventDraft:
    """An EventDraft from a request's draft view (the JSON the call receives)."""
    return EventDraft(**{"confidence": 0.9, **view, **overrides})


def same_as_first(request: list[dict], **merged) -> Consolidation:
    """Every post event is its first candidate, written out as the post event (plus `merged` overrides)."""
    return Consolidation(
        decisions=[
            Decision(draft=e["draft"], same_as=e["candidates"][0]["id"], event=as_draft(e["event"], **merged))
            for e in request
        ]
    )


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
