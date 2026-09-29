from datetime import datetime

import pydantic


class EventDraft(pydantic.BaseModel):
    title: str
    description: str | None = None
    organizer_name: str
    venue_name: str | None = None
    start: datetime
    end: datetime | None = None
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    is_free: bool = False
    external_url: str | None = None
    tags: list[str] = []
    confidence: float  # self-reported 0.0-1.0
    # False when the event happens outside Berlin and its surroundings, or only online.
    in_berlin_area: bool = True


class CollectedEvents(pydantic.BaseModel):
    """Every event one collected post announces, read from its text and images; empty = not an event."""

    events: list[EventDraft]
