from datetime import datetime

import pydantic


class EventDraft(pydantic.BaseModel):
    title: str
    description: str | None = None
    # Who runs the event, only as explicit organizer wording names them
    # ("organised/hosted/presented by", "Veranstalter", "Host:"); "" when the text has none.
    explicit_organizer: str = ""
    # Every other person the post names (teachers, DJs, performers), one entry per name.
    artist_names: list[str] = []
    # The place as the post names it: a real place, or a placeholder (online, a city, "secret").
    venue_name: str | None = None
    # A street address the post gives for the place, if any.
    venue_address: str | None = None
    # Where-info that is not a place name (online, district, "shared with ticket holders").
    location_note: str | None = None
    start: datetime
    end: datetime | None = None
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    is_free: bool = False
    external_url: str | None = None
    tags: list[str] = []
    confidence: float  # self-reported 0.0-1.0
    # True when the source gives the date but no start time; start is then that day at 00:00.
    start_time_unknown: bool = False
    # False when the event happens outside Berlin and its surroundings, or only online.
    in_berlin_area: bool = True


class CollectedEvents(pydantic.BaseModel):
    """Every event one collected post announces, read from its text and images; empty = not an event."""

    events: list[EventDraft]
