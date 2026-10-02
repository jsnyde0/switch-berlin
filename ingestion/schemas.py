from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    # The post's link for this event (tickets, info page); it becomes the source's link row (ADR-007 D11).
    external_url: str | None = None
    tags: list[str] = []
    # Event.CATEGORY_CHOICES key, "" when none fits.
    category: Literal["", "play_party", "workshop", "munch", "performance", "social", "festival", "talk", "other"] = ""
    # in_person | online | hybrid (ADR-007 D11), only as the post states it; None when it does not say.
    # An online-only event is kept wherever it is run from.
    presence: Literal["in_person", "online", "hybrid"] | None = None
    # The IANA timezone the post states for its times; None = Europe/Berlin (ADR-007 D11).
    timezone: str | None = None
    # The post says this event is cancelled.
    cancelled: bool = False
    confidence: float  # self-reported 0.0-1.0
    # True when the source gives the date but no start time; start is then that day at 00:00.
    start_time_unknown: bool = False
    # When the post says the event moved: the start it had before (finds the event under its old date).
    moved_from: datetime | None = None
    # False when an in-person event happens outside Berlin and its surroundings.
    in_berlin_area: bool = True

    @pydantic.field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"timezone {value!r} is not an IANA zone") from exc
        return value


PostKind = Literal["announcement", "about_event", "other"]


class CollectedEvents(pydantic.BaseModel):
    """The events one collected post announces, read from its text and images, and what the post is (ADR-007 D10).

    announcement: it announces events (a change of date, time or place announces the changed event).
    about_event: it is about an event without announcing it (a helper call, sold-out notice, reminder,
    recap) and returns none. other: chat, questions, no event.
    """

    post_kind: PostKind
    events: list[EventDraft]


class Decision(pydantic.BaseModel):
    """The consolidation call's judgement on one of the post's events (ADR-007 D10)."""

    draft: int  # index into the post's events, as numbered in the request
    same_as: int | None = None  # the existing event's id when it IS that event
    possibly_same_as: int | None = None  # when unsure: a new event, flagged for staff against this id
    # With same_as: the event written out in full from every eligible announcement attached to it.
    event: EventDraft | None = None
    # With same_as: the eligible announcement whose description the event takes, copied verbatim
    # (0 = this post event); None when no eligible announcement has one.
    description_from: int | None = None


class Consolidation(pydantic.BaseModel):
    decisions: list[Decision]
