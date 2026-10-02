"""
Collected-event feed (sb-7wzb.2, Track A): collector rows in, landed events out.

Two ends of the RawMessage seam for rows that a collector (switch-cli
`collect web` / `collect telegram`) gathered rather than a human forwarded:

- ingest_collected_rows: the staff-only API verb's service — one RawMessage per
  row, extraction enqueued exactly as the forward-bot does.
- process_collected_row: called by process_raw_message — extracts the events a
  post announces, credits the organizer and artists (ADR-007 D9), consolidates
  copies of one event by model judgement over code-found candidates (D10),
  derives the tier from the source shape (ADR-012 D2) and publishes by claim
  state (ADR-017 D4).

Plain functions over the existing seam; no source framework (sb-7wzb.2 D3).
"""

import base64
import hashlib
import io
import re
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

import logfire
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, connection, models, transaction
from django.utils import timezone
from django.utils.text import slugify
from django_q.tasks import async_task
from PIL import Image, ImageOps

from events.backfill_visibility import derive_visibility_from_sources, rawmessage_source_to_conceptual
from events.models import TIER_RANK
from organizers.duplicate_names import normalize
from organizers.names import find_profile, find_venue, name_key
from venues.address import split_street_address, validate_no_street_address

# RawMessage.source_type values a collector may write. The bot forward stays the
# bot's own door; its rows keep the draft-for-admin-review path.
COLLECTED_SOURCE_TYPES = ("website", "telegram_telethon", "telegram_private_channel", "telegram_private_group")

# Placeholder names a model returns when the text names no host.
_NO_NAME = {"", "unknown", "n/a", "none", "not specified", "unbekannt"}

# Title similarity at which a re-read's draft pairs with an event its row landed before (pg_trgm).
_PAIRING_SIMILARITY = 0.4
_PAIRING_TIE = 0.05  # two own events this close in score: the draft pairs with neither

# The kept flyer copy (sb-7wzb.12 D1): web size, re-encoded, never the original bytes.
_FLYER_LONG_EDGE = 1600
_FLYER_WEBP_QUALITY = 80


def content_hash(text: str, enriched_payload: dict | None, images: list[str] = ()) -> str:
    """The digest of what a collected row says: its text, the link content the collector fetched, its images.

    A row without images keeps the digest it had before images were hashed.
    """
    url_content = (enriched_payload or {}).get("url_content", "")
    said = f"{text}\0{url_content}"
    if images:
        said += "\0" + "\0".join(hashlib.sha256(image.encode()).hexdigest() for image in images)
    return hashlib.sha256(said.encode()).hexdigest()


def ingest_collected_rows(rows: list[dict]) -> dict:
    """Write one RawMessage per collected row and enqueue its extraction.

    A row already collected (same source_type, channel_id, message_id) is
    counted, not re-written, while it says the same: re-running a collector is
    idempotent. When its content_hash changed, the row takes the new content
    and is read again (sb-7wzb.16). A website row re-listing an earlier one
    (same_listing) is stored without an extraction.
    """
    from .models import RawMessage

    counts = {"created": 0, "already_collected": 0, "re_read": 0, "same_listing": 0, "re_run": 0}
    for row in rows:
        if row["source_type"] not in COLLECTED_SOURCE_TYPES:
            raise ValueError(f"source_type {row['source_type']!r} is not a collected feed")
        digest = content_hash(row["text"], row.get("enriched_payload"), row.get("raw_payload", {}).get("images", []))
        content = dict(
            sender_id=row.get("sender_id", ""),
            text=row["text"],
            raw_payload=row.get("raw_payload", {}),
            enriched_payload=row.get("enriched_payload", {}),
            collect_only=row.get("collect_only", False),
            content_hash=digest,
        )
        key = dict(source_type=row["source_type"], channel_id=row["channel_id"], message_id=row["message_id"])
        raw = RawMessage.objects.filter(**key).first()
        if raw is not None and _says_the_same(raw, row["text"], digest):
            if not raw.content_hash:
                raw.content_hash = digest
                raw.save(update_fields=["content_hash"])
            if raw.extraction_status == "failed":  # read again: a failed row kept everything it said
                raw.extraction_status, raw.extraction_error = "pending", ""
                raw.save(update_fields=["extraction_status", "extraction_error"])
                async_task("ingestion.tasks.process_raw_message", raw.id)
                counts["re_run"] += 1
                continue
            counts["already_collected"] += 1
            continue
        if raw is not None:
            was_pending = raw.extraction_status == "pending"
            for field, value in content.items():
                setattr(raw, field, value)
            raw.extraction_status, raw.extraction_error = "pending", ""
            raw.save(update_fields=[*content, "extraction_status", "extraction_error"])
            outcome = "re_read"
        else:
            try:
                with transaction.atomic():
                    raw = RawMessage.objects.create(**key, **content)
            except IntegrityError:
                counts["already_collected"] += 1
                continue
            was_pending, outcome = False, "created"
        if mark_same_listing(raw):
            outcome = "same_listing"
        elif not was_pending:  # a queued task reads the row's new content itself
            async_task("ingestion.tasks.process_raw_message", raw.id)
        counts[outcome] += 1
    logfire.info("collected.rows_ingested", **counts)
    return counts


def _says_the_same(raw, text: str, digest: str) -> bool:
    """True when a re-collected row brings nothing new.

    A row collected before hashing has only its stored text to compare (URL
    enrichment rewrote its link column); a non-event post wiped then kept no
    text, so it is taken as unchanged and gets its hash from now on.
    """
    if raw.content_hash:
        return raw.content_hash == digest
    return raw.text == text or raw.extraction_error == "not_event"


def _listing_key(title: str) -> str:
    """'19 00 - 23 00 Bondage Jam!' and '19 00 - 23 00 BONDAGE-JAM' share one key."""
    return re.sub(r"[\W_]+", "", normalize(title).casefold())


def mark_same_listing(raw) -> bool:
    """Pre-AI dedup for website rows: same source, same day, same normalized listing title.

    The collector names a website row's listing as raw_payload.listing
    {date, title}. A row re-listing an earlier row is stored as a duplicate of
    that row's event, with no extraction call. An earlier listing that ended
    without an event (needs_review, failed, skipped) does not count: the row
    is read normally. Returns True when it was.
    """
    from events.models import Event

    from .models import ExtractionAttempt, RawMessage

    listing = raw.raw_payload.get("listing") or {}
    if raw.source_type != "website" or not listing.get("date") or not listing.get("title"):
        return False
    key = _listing_key(listing["title"])
    earlier, event = None, None
    for other in (
        RawMessage.objects.filter(
            source_type="website", channel_id=raw.channel_id, raw_payload__listing__date=listing["date"]
        )
        .exclude(id=raw.id)
        .exclude(extraction_error="same_listing")
        .order_by("id")
    ):
        if _listing_key(other.raw_payload["listing"].get("title", "")) != key:
            continue
        landed = (
            Event.objects.filter(extraction_attempts__raw_message=other)
            .exclude(status__in=["rejected", "cancelled"])
            .order_by("id")
            .first()
        )
        if landed is not None or other.extraction_status == "pending":  # a pending row may still land one
            earlier, event = other, landed
            break
    if earlier is None:
        return False
    raw.extraction_status, raw.extraction_error = "duplicate", "same_listing"
    raw.save(update_fields=["extraction_status", "extraction_error"])
    ExtractionAttempt.objects.create(
        raw_message=raw,
        model_name="none",
        prompt_version="same_listing",
        raw_response={"same_listing_as": earlier.id},
        event=event,
        error="same_listing",
    )
    logfire.info("collected.same_listing", raw_message_id=raw.id, same_as=earlier.id)
    return True


_BERLIN = "Europe/Berlin"


def _aware(dt, zone: str | None = None):
    """`dt` made aware in `zone` (the IANA zone a post states; Europe/Berlin when none)."""
    return timezone.make_aware(dt, ZoneInfo(zone or _BERLIN)) if timezone.is_naive(dt) else dt


def create_collected_profile(name: str, origin: str):
    """Unclaimed organizer Profile for a name no Profile carries (ADR-007 D9: one profile per name).

    `origin` says where the name came from, for the consent note. status=approved
    so the organizer page, and with it the claim affordance (ADR-014), resolves
    (mem auto-created-records-reachable-default). The lawful basis is the
    organizer LIA (docs/compliance/organizer-lia.md).
    """
    from organizers.models import Profile

    base = slugify(name)[:40] or "organizer"
    slug = base if not Profile.objects.filter(slug=base).exists() else f"{base}-{uuid.uuid4().hex[:6]}"
    now = timezone.now()
    return Profile.objects.create(
        name=name,
        slug=slug,
        status="approved",
        approved_at=now,
        consent_recorded_at=now,
        consent_method="legitimate_interest",
        consent_notes=f"Auto-created by the event collector from {origin} on {now.date()}.",
    )


def _create_row_profile(name: str, raw):
    return create_collected_profile(name, f"{raw.raw_payload.get('source') or raw.channel_id} ({raw.source_type})")


# Separators between names in one string: "A, B & C", "A und B", "A + B".
_NAME_SPLIT = re.compile(r"\s*(?:[,;]|\s(?:&|\+|and|und)\s)\s*", re.IGNORECASE)


def split_names(text: str) -> list[str]:
    """'Tina, Ricardo & Mal' -> ['Tina', 'Ricardo', 'Mal']; placeholder names dropped."""
    return [n for n in (part.strip() for part in _NAME_SPLIT.split(text)) if n.lower() not in _NO_NAME]


# An attempt error "re_read_<status>: <reason>" marks a paired draft that ended skipped or held and wrote nothing.
_RE_READ_ENDED = "re_read_"
POSTER = "poster"  # default_organizer value: the post's author is the organizer
_DEFAULTS = ("publisher", POSTER)  # organizer attributions taken from the source, not named by the post


def organizer_names(raw, draft) -> tuple[list[str], str]:
    """(names, attribution) for one collected event (ADR-007 D9), first name primary.

    One chain for every source, first hit wins: the post names its organizer
    (explicit; one name per person, a string that is an existing profile's
    whole name stays one); else the source's default_organizer, a Profile name
    (publisher: the source is that organizer's own site or channel; a name no
    Profile carries raises, a typo never creates a public profile); else
    default_organizer "poster", the post's author by display name (a community
    board where members post their own events). ([], reason) when the event
    must be held for review.
    """
    explicit = (draft.explicit_organizer or "").strip()
    if explicit and explicit.lower() not in _NO_NAME:
        return ([explicit] if find_profile(explicit) else split_names(explicit)), "explicit"
    default = (raw.raw_payload.get("default_organizer") or "").strip()
    if default == POSTER:
        poster = (raw.raw_payload.get("poster") or "").strip()
        return ([poster], "poster") if poster else ([], "no_organizer")
    if default:
        if find_profile(default) is None:
            raise ValueError(f"source config names default_organizer {default!r}, which matches no profile")
        return [default], "publisher"
    return [], "no_organizer"


def credit_people(
    event, raw, names: list[str], attribution: str, artist_names: list[str], taken_names: list[str] = ()
) -> None:
    """Organizer rows (matched or created, never inferred) and artist credits as text, never linked.

    An artist name equal to an organizer name (`names` or `taken_names`) is not credited again,
    nor one a credited artist had removed for this source (ArtistCreditSuppression, sb-7wzb.23).
    """
    from events.models import EventArtist, EventOrganizer

    from .models import ArtistCreditSuppression

    seen = set()
    for order, name in enumerate(names):
        profile = find_profile(name) or _create_row_profile(name, raw)
        if profile.id in seen:
            continue
        seen.add(profile.id)
        EventOrganizer.objects.create(
            event=event, profile=profile, is_primary=order == 0, order=order, attribution=attribution
        )
    taken = {name_key(part) for name in [*names, *taken_names] for part in [name, *split_names(name)]}
    taken |= set(ArtistCreditSuppression.objects.filter(channel_id=raw.channel_id).values_list("name_key", flat=True))
    order = 0
    for entry in artist_names:
        for name in split_names(entry):
            if name_key(name) in taken:
                continue
            taken.add(name_key(name))
            EventArtist.objects.create(event=event, name=name, order=order)
            order += 1


# Location strings that name no place (sb-x5xh.2 ruling (b)): they become the
# event's location note, never a venue.
_PLACEHOLDER = re.compile(
    r"\b(?:online|zoom|livestream|virtual|secret|geheim|on request|auf anfrage|ticket ?holders?|tba|tbd"
    r"|private (?:venue|location|address|flat|apartment)"
    r"|(?:location|address) (?:will be )?(?:shared|sent|announced))\b"
    r"|^\s*(?:near|nahe|close to)\b",  # a hint near somewhere, not a place
    re.IGNORECASE,
)
# A name made only of these words is a city or district, not a place.
_AREAS = set(
    "berlin brandenburg potsdam vienna wien hamburg leipzig munich münchen köln cologne dresden prague prag amsterdam"
    " germany deutschland austria mitte pankow kreuzberg neukölln friedrichshain prenzlauer berg wedding schöneberg"
    " charlottenburg moabit lichtenberg tempelhof treptow köpenick spandau steglitz zehlendorf wilmersdorf"
    " reinickendorf marzahn hellersdorf weißensee"
    " friedenau".split()
)
# Words that mark an address as not for publication: its venue is created private.
_RESTRICTED = re.compile(
    r"\b(?:on request|auf anfrage|ticket ?holders?|private|privat|secret|geheim|nach anmeldung|after registration)\b",
    re.IGNORECASE,
)
# Source shapes whose posts are not public: a venue first seen there is created private.
_PRIVATE_SHAPES = ("telegram_private_channel", "telegram_private_group")


def _is_area(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", normalize(text))
    return bool(words) and all(w in _AREAS for w in words)


def _is_placeholder(name: str) -> bool:
    return bool(_PLACEHOLDER.search(name)) or _is_area(name)


def _drop_area_brackets(name: str) -> str:
    """'IKSK Berlin (Berlin)' -> 'IKSK Berlin': a bracket left holding only a city adds nothing."""
    return re.sub(r"\s*\(([^)]*)\)", lambda m: "" if _is_area(m.group(1)) else m.group(0), name).strip()


def find_or_create_venue(
    name: str, address: str = "", private: bool = False, by_address: bool = False, create: bool = True
):
    """The venue with this exact normalized name (and address, when `by_address`), else a new one.

    With create=False a missing venue is None instead.

    New venues carry the address text and no coordinates (no geocoding). They
    never create or link a profile.
    """
    from venues.models import Venue

    found = find_venue(name, address if by_address else None)
    if found is not None or not create:
        return found
    base = slugify(name)[:40] or "venue"
    slug = base if not Venue.objects.filter(slug=base).exists() else f"{base}-{uuid.uuid4().hex[:6]}"
    venue = Venue.objects.create(name=name, slug=slug, address=address, privacy_mode="private" if private else "public")
    logfire.info("collected.venue_created", venue_id=venue.id, privacy_mode=venue.privacy_mode)
    return venue


def apply_source_venue(raw):
    """The source config's default venue, with its run-by profile set from config. None when unset.

    The venue and the run-by profile must already exist: a config name matching
    neither fails the row (a typo never makes a second venue; venues never
    create profiles). A staff-set run-by is never overwritten.
    """
    name = (raw.raw_payload.get("venue") or "").strip()
    if not name:
        return None
    venue = find_venue(name)
    if venue is None:
        raise ValueError(f"source config names default venue {name!r}, which does not exist")
    runner_name = (raw.raw_payload.get("venue_run_by") or "").strip()
    if runner_name:
        runner = find_profile(runner_name)
        if runner is None:
            raise ValueError(f"source config names venue run-by profile {runner_name!r}, which does not exist")
        if venue.run_by_id is None:
            venue.run_by = runner
            venue.save(update_fields=["run_by"])
        elif venue.run_by_id != runner.id:
            logfire.warn("collected.venue_run_by_differs", venue_id=venue.id, config=runner_name)
    return venue


def resolve_place(raw, draft, create: bool = True) -> tuple:
    """(venue, location_note) for one collected event (sb-x5xh.2 ruling (b)).

    A placeholder goes to the note; a street address goes to a venue, never the
    note; a real place name matches or creates a venue; a post naming neither
    lands on the source's default venue; an online event has only a note. With
    create=False a place no venue holds yet resolves to None (candidate finding
    looks, it never creates).
    """
    name = (draft.venue_name or "").strip()
    note = (draft.location_note or "").strip()
    address = (draft.venue_address or "").strip()
    if draft.presence == "online":  # an online event has no venue (ADR-007 D11)
        note = ", ".join(part for part in (name, note) if part)[:200] or "Online"
        validate_no_street_address(note)
        return None, note
    row_text = " ".join((raw.text, raw.enriched_payload.get("url_content", ""), name, note, address))
    private = raw.source_type in _PRIVATE_SHAPES or bool(_RESTRICTED.search(row_text))
    default = apply_source_venue(raw)

    # A known venue matches on its whole name, even one that holds its address.
    known = find_venue(name) if name and not _is_placeholder(name) else None
    if known is None:
        found, name = split_street_address(name)
        address = address or found
        name = _drop_area_brackets(name) if found else name
    found, note = split_street_address(note)
    address = address or found
    placeholder = bool(note) and _is_placeholder(note)
    if name and _is_placeholder(name):
        note = ", ".join(part for part in (name, note) if part)
        name, placeholder = "", True
    validate_no_street_address(note)

    if known is not None:
        venue = known
    elif name:
        venue = find_or_create_venue(name, address, private, create=create)
    elif address:
        # No place name, only an address: name the venue without it, so a
        # private address never shows through the venue name.
        label = re.sub(r"\s*\([^)]*\)", "", note).split(",")[0].strip()
        label = label or ("Private venue" if private else address)
        venue = find_or_create_venue(label, address, private, by_address=True, create=create)
    elif not placeholder:
        venue = default
    else:
        venue = None
    return venue, note


def collector_owned(event) -> bool:
    """True when the collector may still change `event` (sb-7wzb.16).

    The collector landed it (raw_message set) and no organizer profile on it
    has an active claim. Organizer edits need an active claim
    (syndication.authz.can_edit), so a claimed event covers an organizer-edited
    one; an event a person made has no raw_message. Anything else is frozen.
    """
    from syndication.authz import collector_may_publish

    return event.raw_message_id is not None and collector_may_publish(event)


def _similarity(a: str, b: str) -> float:
    with connection.cursor() as cursor:
        cursor.execute("SELECT similarity(%s, %s)", [a, b])
        return cursor.fetchone()[0]


def _organizer_key(name: str) -> str:
    """One key per organizer: its profile (merge-aware), else its normalized name."""
    profile = find_profile(name)
    return f"p{profile.id}" if profile else f"n{name_key(name)}"


def _explicit_keys(event) -> set[str]:
    """The event's named organizers: explicit rows; on an event a person made, the rows they set.

    Publisher and poster rows never count; nor does an organizer staff added to a collected event.
    """
    named = ("explicit",) if event.raw_message_id else ("explicit", "")
    return {f"p{row.profile_id}" for row in event.event_organizer_set.all() if row.attribution in named}


# --- Candidate finding (ADR-007 D10) ------------------------------------------
# A live event is a candidate for a draft when their times overlap AND at least one
# signal below matches. Loose on purpose: the consolidation call decides. Tune the
# signals here, toward fewer false positives, from dogfood findings.

_SIMILAR = 0.3  # pg_trgm similarity at which two titles or two host names count as similar
_TITLE_WORD_MIN = 5  # a shared title word this long counts ("retreat", "bondage"), short filler does not
_TITLE_STOPWORDS = {"berlin", "event", "events", "night", "party", "workshop", "special", "edition"}
_UNKNOWN_END = timedelta(hours=6)  # an event with no end overlaps as if it ran this long
_MAX_CANDIDATES = 5  # the most-signalled candidates one post event shows the judgement


def _title_words(title: str) -> set[str]:
    return {w for w in name_key(title).split() if len(w) >= _TITLE_WORD_MIN and w not in _TITLE_STOPWORDS}


def _similar_names(a: str, b: str) -> bool:
    """'Till & Shirka' ~ 'Till & Shirka - sexpositive Workshops': one name holds the other, or trigram-similar."""
    ka, kb = name_key(a), name_key(b)
    return bool(ka and kb) and (ka in kb or kb in ka or _similarity(ka, kb) >= _SIMILAR)


def _host_signal(event, draft, names, venue) -> bool:
    rows = list(event.event_organizer_set.all())
    mine = {p.id for p in map(find_profile, names) if p}  # merge-aware: a merged-away name finds its winner
    return any(row.profile_id in mine for row in rows) or any(
        _similar_names(name, row.profile.name) for name in names for row in rows
    )


def _artist_signal(event, draft, names, venue) -> bool:
    mine = {name_key(n) for entry in draft.artist_names for n in split_names(entry)}
    return bool(mine & {name_key(credit.name) for credit in event.artist_credits.all()})


def _venue_signal(event, draft, names, venue) -> bool:
    return venue is not None and event.venue_id == venue.id


def _title_signal(event, draft, names, venue) -> bool:
    shared_word = bool(_title_words(draft.title) & _title_words(event.title))
    return shared_word or _similarity(draft.title, event.title) >= _SIMILAR


CANDIDATE_SIGNALS = {"host": _host_signal, "artist": _artist_signal, "venue": _venue_signal, "title": _title_signal}


def _times(draft) -> tuple:
    """(start, end) of a draft, aware in the timezone it states (Europe/Berlin when none)."""
    return _aware(draft.start, draft.timezone), _aware(draft.end, draft.timezone) if draft.end else None


def _windows(draft) -> list[tuple]:
    """The whole Berlin days a draft occupies, as [start, end) windows; a moved event's old day too."""
    start, end = _times(draft)
    spans = [(start, end or start + _UNKNOWN_END)]
    if draft.moved_from is not None:
        old = _aware(draft.moved_from, draft.timezone)
        spans.append((old, old + _UNKNOWN_END))
    windows = []
    for first, last in spans:
        day0 = timezone.localtime(first).date()
        day1 = max(day0, timezone.localtime(last - timedelta(microseconds=1)).date())
        midnight = timezone.make_aware(datetime.combine(day0, time()))
        windows.append((midnight, timezone.make_aware(datetime.combine(day1 + timedelta(days=1), time()))))
    return windows


def find_candidates(
    draft, names: list[str], venue, explicit: set[str] = frozenset(), exclude: set[int] = frozenset()
) -> list[tuple]:
    """[(event, signals)] for the live events that may be the draft's event, at most _MAX_CANDIDATES (ADR-007 D10).

    Times overlap (by Berlin day, an unknown end counted as start + 6h; the day the
    post says the event moved from counts too) AND at least one CANDIDATE_SIGNALS
    entry matches. Overlapping times alone never make a candidate. Two explicit
    organizer sets that share nobody never consolidate (`explicit`: the draft's
    explicit organizer keys). `names` = the draft's organizer names (the D9 chain);
    `venue` = its resolved venue, looked up only; `exclude` = events spoken for.
    """
    from django.db.models import ExpressionWrapper, F, Q, Value
    from django.db.models.functions import Coalesce

    from events.models import Event

    overlaps = Q()
    for begin, finish in _windows(draft):
        overlaps |= Q(start__lt=finish, until__gt=begin)
    events = (
        Event.objects.exclude(status__in=["rejected", "cancelled"])
        .annotate(
            until=Coalesce(
                "end", ExpressionWrapper(F("start") + Value(_UNKNOWN_END), output_field=models.DateTimeField())
            )
        )
        .filter(overlaps)
        .exclude(id__in=exclude)
        .prefetch_related("event_organizer_set__profile", "artist_credits")
        .order_by("id")
    )
    found = []
    for event in events:
        theirs = _explicit_keys(event)
        if explicit and theirs and not explicit & theirs:
            continue
        signals = [name for name, signal in CANDIDATE_SIGNALS.items() if signal(event, draft, names, venue)]
        if signals:
            found.append((event, signals))
    found.sort(key=lambda pair: (-len(pair[1]), pair[0].id))
    return found[:_MAX_CANDIDATES]


# debt: the consolidation model call runs inside this lock, holding a transaction open for its length;
# fine for the nightly batch, revisit if collection runs continuously or in parallel at scale.
def lock_days(drafts) -> None:
    """Serialize candidate finding and writing per Berlin day (Postgres advisory lock, released at commit).

    Two posts landing the same event at once both wait for the day's lock, so the
    second sees the first's event as a candidate. Days lock in order: no deadlock.
    """
    if connection.vendor != "postgresql":
        return
    days = sorted(
        {
            day.toordinal()
            for draft in drafts
            for begin, finish in _windows(draft)
            for day in (timezone.localtime(begin).date() + timedelta(days=n) for n in range((finish - begin).days))
        }
    )
    with connection.cursor() as cursor:
        for day in days:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_DAY_LOCK, day])


_DAY_LOCK = 7030  # advisory-lock namespace for the collector's per-day lock


def pair_with_own_events(raw, drafts) -> tuple[dict, list]:
    """Pair a re-read's drafts one-to-one with the events this row landed before (sb-7wzb.16 ruling 3).

    Returns ({draft index: (event, what this row said about it last time)},
    [own events no draft pairs with]). A draft pairs by title similarity with
    the event's title or the row's last reading of it, on any day: a re-read
    may move the date. A draft that ties between two events pairs with neither.
    """
    from events.models import Event

    from .models import ExtractionAttempt
    from .schemas import EventDraft

    own = {}
    for event in Event.objects.filter(raw_message=raw).exclude(status__in=["rejected", "cancelled"]).order_by("id"):
        attempt = (
            ExtractionAttempt.objects.filter(raw_message=raw, event=event)
            .exclude(extracted_draft={})
            .exclude(error__startswith=_RE_READ_ENDED)  # a paired draft that ended skipped or held wrote nothing
            .order_by("-id")
            .first()
        )
        own[event.id] = (event, EventDraft.model_validate(attempt.extracted_draft) if attempt else None)
    scored = sorted(
        (
            -max(_similarity(draft.title, event.title), _similarity(draft.title, said.title) if said else 0),
            i,
            event_id,
        )
        for i, draft in enumerate(drafts)
        for event_id, (event, said) in own.items()
    )
    best: dict[int, list[float]] = {}
    for score, i, _ in scored:
        best.setdefault(i, []).append(-score)
    # A draft whose two best events score within a hair of each other cannot say which it is:
    # it pairs with neither and goes through candidate finding.
    ambiguous = {i for i, top in best.items() if len(top) > 1 and top[0] - top[1] <= _PAIRING_TIE}
    pairs = {}
    for score, i, event_id in scored:
        if i in ambiguous:
            continue
        if -score >= _PAIRING_SIMILARITY and i not in pairs and event_id in own:
            pairs[i] = own.pop(event_id)
    return pairs, [event for event, _ in own.values()]


# --- Announcements and privacy (ADR-007 D10, ADR-012 D2) -------------------------
# An event's announcements are the posts attached to it. Its visibility is the most
# public tier among their sources; only announcements from a source of that tier
# ("eligible") supply its text and place.

_DRAFT_VIEW = {
    "title", "description", "start", "end", "start_time_unknown", "moved_from", "timezone", "price_min_cents",
    "price_max_cents", "is_free", "venue_name", "location_note", "explicit_organizer", "artist_names",
    "external_url", "presence", "category", "tags", "cancelled",
}  # fmt: skip


class Announcement(NamedTuple):
    id: int  # the attempt that read it; 0 = the post being landed now
    raw: object
    draft: object


def _tier(raw) -> str:
    return derive_visibility_from_sources([rawmessage_source_to_conceptual(raw.source_type)])


def _event_tier(announcements) -> str:
    return derive_visibility_from_sources([rawmessage_source_to_conceptual(a.raw.source_type) for a in announcements])


def _announcements(event, raw) -> list[Announcement]:
    """The latest reading of every other post attached to `event`, oldest post first."""
    from .models import ExtractionAttempt
    from .schemas import EventDraft

    latest = {}
    for attempt in (
        ExtractionAttempt.objects.filter(event=event)
        .exclude(raw_message=raw)
        .exclude(extracted_draft={})
        .exclude(error__startswith=_RE_READ_ENDED)
        .select_related("raw_message")
        .order_by("id")
    ):
        draft = EventDraft.model_validate(attempt.extracted_draft)
        latest[attempt.raw_message_id] = Announcement(attempt.id, attempt.raw_message, draft)
    return [latest[key] for key in sorted(latest)]


def _draft_json(draft) -> dict:
    view = draft.model_dump(mode="json", include=_DRAFT_VIEW)
    view["description"] = (view.get("description") or "")[:DESCRIPTION_VIEW_CHARS]
    return view


DESCRIPTION_VIEW_CHARS = 3000  # the longest description one announcement shows the judgement


def _rank(tier: str) -> int:
    return TIER_RANK[tier]


def _tier_after(event, announcements) -> str:
    """The event's tier with these announcements attached: the most public source's, unless a person set it."""
    return event.visibility if "visibility" in event.edited_groups else _event_tier(announcements)


def _event_view(event, raw, draft) -> dict:
    """One candidate as the judgement sees it (sb-7wzb.30 rulings 1, 17).

    Announcements from a source less public than the event would become carry no
    text, only their id, dates and organizer keys: they inform the same-event
    judgement and never the written event. The event's current fields show only
    when they came from sources that public.
    """
    earlier = _announcements(event, raw)
    tier = _tier_after(event, [*earlier, Announcement(0, raw, draft)])
    content_tier = _event_tier(earlier) if earlier and "visibility" not in event.edited_groups else event.visibility
    view = {
        "id": event.id,
        "start": timezone.localtime(event.start).isoformat(),
        "end": timezone.localtime(event.end).isoformat() if event.end else None,
        "start_time_unknown": event.start_time_unknown,
        "organizer_keys": sorted(f"p{row.profile_id}" for row in event.event_organizer_set.all()),
        "post_event_eligible": _rank(_tier(raw)) >= _rank(tier),
        "announcements": [
            {"id": a.id, "eligible": True, **_draft_json(a.draft)}
            if _rank(_tier(a.raw)) >= _rank(tier)
            else {"id": a.id, "eligible": False, **_bare(a.draft)}
            for a in earlier
        ],
    }
    if _rank(content_tier) >= _rank(tier):
        view.update(
            title=event.title,
            venue=event.venue.name if event.venue_id else None,
            location_note=event.location_note,
            presence=event.presence,
            organizers=[
                {"name": row.profile.name, "attribution": row.attribution or "set by a person"}
                for row in event.event_organizer_set.select_related("profile")
            ],
            artists=list(event.artist_credits.values_list("name", flat=True)),
        )
    return view


def _bare(draft) -> dict:
    """An announcement without its text: dates and organizer keys only."""
    explicit = (draft.explicit_organizer or "").strip()
    names = ([explicit] if find_profile(explicit) else split_names(explicit)) if explicit else []
    return {
        "start": draft.model_dump(mode="json")["start"],
        "end": draft.model_dump(mode="json")["end"],
        "organizer_keys": sorted(_organizer_key(n) for n in names),
    }


def _decide(raw, request: list[dict]) -> dict:
    """{draft index: Decision} from one consolidation call, checked against the request (ADR-008 D3: fail loud)."""
    from .extraction import consolidate

    decisions = consolidate(request).decisions
    by_draft = {}
    for entry in request:
        mine = [d for d in decisions if d.draft == entry["draft"]]
        if len(mine) != 1:
            raise ValueError(f"consolidation gave {len(mine)} decisions for post event {entry['draft']}")
        decision = mine[0]
        candidates = {c["id"]: c for c in entry["candidates"]}
        if decision.same_as is not None:
            if decision.same_as not in candidates:
                raise ValueError(f"consolidation named event {decision.same_as}, not a candidate of {entry['draft']}")
            if decision.event is None:
                raise ValueError(f"consolidation matched post event {entry['draft']} without writing the event")
            chosen = candidates[decision.same_as]
            eligible = {a["id"] for a in chosen["announcements"] if a["eligible"]}
            if chosen["post_event_eligible"]:
                eligible.add(0)
            if decision.description_from is not None and decision.description_from not in eligible:
                raise ValueError(
                    f"consolidation took the description of announcement {decision.description_from}, "
                    f"not an eligible announcement of event {decision.same_as}"
                )
        if "is" in entry and decision.same_as != entry["is"]:
            raise ValueError(f"consolidation did not keep re-read post event {entry['draft']} on event {entry['is']}")
        if decision.possibly_same_as is not None and decision.possibly_same_as not in candidates:
            decision.possibly_same_as = None  # a suspicion about a non-candidate names nothing staff can check
            logfire.warn("collected.suspected_non_candidate", raw_message_id=raw.id, draft=entry["draft"])
        by_draft[entry["draft"]] = decision
    extra = {d.draft for d in decisions} - set(by_draft)
    if extra:
        raise ValueError(f"consolidation answered post events {sorted(extra)} that were not asked about")
    return by_draft


# --- Writing a consolidated event ---------------------------------------------------
# Each collector-owned group is written whole or not at all; a group a person edited
# (Event.edited_groups, recorded where the person saved) is never rewritten. The
# attempt keeps the values from before the rewrite, so staff can undo by hand.

_GROUPS = ("title", "description", "date", "price", "presence", "category", "place", "tags", "artists")


def _utc(dt):
    return _aware(dt).astimezone(UTC).isoformat() if dt else None


def _group_values(event) -> dict:
    return {
        "title": event.title,
        "description": event.description,
        "date": [_utc(event.start), _utc(event.end), event.start_time_unknown, event.timezone],
        "price": [event.price_min_cents, event.price_max_cents, event.is_free],
        "presence": event.presence,
        "category": event.category,
        "place": [event.venue_id, event.location_note],
        "tags": [sorted(event.tags.values_list("slug", flat=True)), list(event.suggested_tags)],
        "artists": list(event.artist_credits.values_list("name", flat=True)),
    }


def _snapshot(event) -> dict:
    """Everything a consolidation may change, as it is now."""
    return {
        **_group_values(event),
        "visibility": event.visibility,
        "status": event.status,
        "organizers": [
            [row.profile.name, row.attribution, row.is_primary]
            for row in event.event_organizer_set.select_related("profile").order_by("order", "id")
        ],
    }


def _empty(value) -> bool:
    if isinstance(value, list):
        return all(_empty(v) for v in value)
    return value in ("", None, False)


def _has_place(draft) -> bool:
    return any((value or "").strip() for value in (draft.venue_name, draft.venue_address, draft.location_note))


def _sync_artists(event, announcements, names: list[str]) -> None:
    """Make the event's credits `names`, by difference: kept rows stay as they are (sb-7wzb.30 ruling 11).

    A name an organizer carries, or one a credited artist had removed for ANY source
    attached to the event, is never credited.
    """
    from events.models import EventArtist

    from .models import ArtistCreditSuppression

    channels = {a.raw.channel_id for a in announcements}
    taken = {name_key(row.profile.name) for row in event.event_organizer_set.select_related("profile")}
    taken |= set(ArtistCreditSuppression.objects.filter(channel_id__in=channels).values_list("name_key", flat=True))
    wanted = []
    for entry in names:
        for name in split_names(entry):
            if name_key(name) not in taken and name_key(name) not in {name_key(w) for w in wanted}:
                wanted.append(name)
    keys = {name_key(w) for w in wanted}
    have = {name_key(credit.name): credit for credit in event.artist_credits.all()}
    for key, credit in have.items():
        if key not in keys:
            credit.delete()
    order = max((c.order for c in have.values()), default=-1) + 1
    for name in wanted:
        if name_key(name) not in have:
            EventArtist.objects.create(event=event, name=name, order=order)
            order += 1


def _organizer_rows(merged, announcements) -> tuple[list[str], str]:
    """(names, attribution) the collector credits a consolidated event with, whatever order its posts came in.

    The judgement's merged explicit organizer (every name must appear in an
    announcement's explicit organizer); with none explicit, a publisher outranks a
    poster (ADR-007 D9). Names sort, so arrival order never picks the winner.
    """
    explicit = (merged.explicit_organizer or "").strip()
    if explicit and explicit.lower() not in _NO_NAME:
        names = [explicit] if find_profile(explicit) else split_names(explicit)
        said = {
            name_key(part)
            for a in announcements
            for part in [a.draft.explicit_organizer, *split_names(a.draft.explicit_organizer or "")]
            if part
        }
        unsaid = [n for n in names if name_key(n) not in said]
        if unsaid:
            raise ValueError(f"consolidation named organizer(s) {unsaid} no announcement names")
        return names, "explicit"
    by_kind = {"publisher": set(), POSTER: set()}
    for a in announcements:
        names, attribution = organizer_names(a.raw, a.draft.model_copy(update={"explicit_organizer": ""}))
        if attribution in by_kind:
            by_kind[attribution].update(names)
    for attribution in ("publisher", POSTER):
        if by_kind[attribution]:
            return sorted(by_kind[attribution], key=name_key), attribution
    return [], ""


def _set_organizers(event, raw, names: list[str], attribution: str) -> bool:
    """Make the collector's organizer rows `names` (none: remove them); a person's rows are never touched."""
    from events.models import EventOrganizer

    rows = list(event.event_organizer_set.all())
    mine = [row for row in rows if row.attribution in (*_DEFAULTS, "explicit")]
    people = [row for row in rows if row.attribution not in (*_DEFAULTS, "explicit")]
    if not names:  # no eligible announcement names one: the collector's rows go, a person's stay (ruling 20)
        EventOrganizer.objects.filter(id__in=[row.id for row in mine]).delete()
        return bool(mine)
    wanted = []
    for name in names:
        profile = find_profile(name) or _create_row_profile(name, raw)
        if profile.id not in [p.id for p in wanted]:
            wanted.append(profile)
    if [(r.profile_id, r.attribution) for r in sorted(mine, key=lambda r: r.order)] == [
        (p.id, attribution) for p in wanted
    ]:
        return False
    EventOrganizer.objects.filter(id__in=[row.id for row in mine]).delete()
    person_ids = {row.profile_id for row in people}
    order = max((row.order for row in people), default=-1) + 1
    has_primary = any(row.is_primary for row in people)
    for profile in wanted:
        if profile.id in person_ids:
            continue
        EventOrganizer.objects.create(
            event=event, profile=profile, is_primary=not has_primary, order=order, attribution=attribution
        )
        has_primary, order = True, order + 1
    return True


def merge_into(event, raw, draft, merged, description_from, flyer, written_files) -> tuple[list[str], dict]:
    """Attach this post's `draft` to `event` and rewrite the event from all its eligible announcements.

    `merged` is the event written out in full (by the judgement, or the draft itself
    when the event has no other announcement); `description_from` names the
    announcement whose description is copied verbatim (0 = this post). Returns
    (what changed, the values before). A frozen event (claimed, or made by a
    person) never changes: the match is recorded, nothing is written.
    """
    from .extraction import match_entities

    if not collector_owned(event):
        return [], {}
    announcements = [*_announcements(event, raw), Announcement(0, raw, draft)]
    edited = set(event.edited_groups)
    tier = _tier_after(event, announcements)  # ruling 21: a person-set visibility stands
    eligible = [a for a in announcements if _rank(_tier(a.raw)) >= _rank(tier)]
    before = _snapshot(event)
    if _rank(_tier(raw)) < _rank(tier):
        # A post less public than the event attaches and shows nothing: everything it says stays with
        # it (its link and flyer kept, hidden while the event is more public; sb-7wzb.30 ruling 17).
        changed = []
        if event.visibility != tier:
            event.visibility = tier
            event.save(update_fields=["visibility"])
            changed.append("visibility")
        changed += _attach_media(event, raw, draft, flyer, written_files)
        return changed, before
    changed = []
    # The event just became more public: every shown field is rewritten from eligible announcements,
    # blanks included, and the same-tier guards below do not apply (privacy first, ruling 19).
    raised = _rank(tier) > _rank(event.visibility)

    names, attribution = _organizer_rows(merged, eligible)
    if "organizers" not in edited and _set_organizers(event, raw, names, attribution):
        changed.append("organizers")

    columns = {"visibility": tier}  # privacy first: the most public source decides, every attach
    if "title" not in edited:
        columns["title"] = merged.title
    if "description" not in edited:
        source = next((a for a in eligible if a.id == description_from and a.draft.description), None)
        if source is not None:
            columns["description"] = source.draft.description or ""
        elif event.description not in {a.draft.description for a in eligible}:
            columns["description"] = ""  # text no eligible announcement gave never stays on the event
    start, end = _times(merged)
    if "date" not in edited and (raised or not (merged.start_time_unknown and not event.start_time_unknown)):
        columns.update(
            start=start, end=end, start_time_unknown=merged.start_time_unknown, timezone=merged.timezone or _BERLIN
        )
    price = (merged.price_min_cents, merged.price_max_cents, merged.is_free)
    if "price" not in edited and (raised or not _empty(list(price))):
        columns.update(zip(("price_min_cents", "price_max_cents", "is_free"), price, strict=True))
    if "presence" not in edited and (raised or merged.presence is not None):
        columns["presence"] = merged.presence or "in_person"
    if "category" not in edited and (raised or merged.category):
        columns["category"] = merged.category
    if "place" not in edited:
        placed = [a for a in eligible if _has_place(a.draft)] or eligible
        source = max(placed, key=lambda a: a.id or float("inf"))  # the latest eligible announcement that says where
        presence = columns.get("presence", event.presence)
        venue, note = resolve_place(source.raw, source.draft.model_copy(update={"presence": presence}))
        if venue is not None and venue.privacy_mode == "private" and _rank(tier) > _rank("semi_public"):
            # A private venue (its address from a less public post, or kept for ticket holders) never
            # hangs on a public event through another post: the public one names the place, no more.
            if not _RESTRICTED.search(f"{source.raw.text} {source.raw.enriched_payload.get('url_content', '')}"):
                venue, note = None, ", ".join(part for part in (venue.name, note) if part)[:200]
        columns["venue"], columns["location_note"] = venue, note
    matched = match_entities(merged)
    tags = "tags" not in edited and (raised or matched["matched_tags"] or matched["unmatched_tags"])
    if tags:
        columns["suggested_tags"] = matched["unmatched_tags"]
    if merged.cancelled or draft.cancelled:
        columns["status"] = "cancelled"
    for field, value in columns.items():
        setattr(event, field, value)
    if "start_time_unknown" in columns:
        # The collector states whether the time is known: Event.save must not read the new start
        # as a person typing in a real time (its sb-7wzb.4 B1 rule) and flip a date-only start.
        event._loaded_start = event.start
    event.save(update_fields=list(columns))
    if tags:
        event.tags.set(matched["matched_tags"])
    if "artists" not in edited:
        _sync_artists(event, announcements, merged.artist_names)

    after = _snapshot(event)
    changed += [key for key in after if key != "organizers" and after[key] != before[key]]
    changed += _attach_media(event, raw, draft, flyer, written_files)
    return changed, before


def _attach_media(event, raw, draft, flyer, written_files) -> list[str]:
    """This post's link row, and its flyer as a cover when the event shows none; both remember their source."""
    changed = []
    if _add_link(event, raw, draft.external_url):
        changed.append("link")
    if flyer is not None and event.shown_cover is None and not event.images.filter(raw_message=raw).exists():
        _add_cover(event, raw, draft, flyer, written_files)
        changed.append("cover")
    return changed


def _add_link(event, raw, url: str | None) -> bool:
    """This source's link row for the event (ADR-007 D11). A link that is not a URL is logged and left out."""
    from django.core.exceptions import ValidationError
    from django.core.validators import URLValidator

    from events.models import EventLink

    url = (url or "").strip()
    if not url:
        return False
    try:
        URLValidator()(url)
    except ValidationError:
        logfire.warn("collected.link_not_a_url", raw_message_id=raw.id, url=url[:200])
        return False
    return EventLink.objects.get_or_create(event=event, url=url[:1000], raw_message=raw)[1]


def _add_cover(event, raw, draft, flyer: bytes, written_files: list[str] | None) -> None:
    from events.models import EventImage

    cover = EventImage(event=event, is_cover=True, alt=draft.title[:300], raw_message=raw)
    # A random name: a hidden flyer (less public source) is not reachable by guessing it from the slug.
    cover.image.save(f"{uuid.uuid4().hex}.webp", ContentFile(flyer), save=False)
    if written_files is not None:
        written_files.append(cover.image.name)
    cover.save()


# Row status when a post's events land differently: the most-landed outcome wins.
_OUTCOME_RANK = ("extracted", "duplicate", "needs_review", "skipped")

_LOW_CONFIDENCE = 0.4


def set_aside(raw, post_kind: str) -> None:
    """A post announcing no event: an `other` post (chat) is wiped at once, keeping only its ids and the verdict
    (LIA §1); an `about_event` post (helper call, sold-out, reminder, recap) keeps its text (sb-7wzb.30 ruling 9).
    """
    from django.conf import settings

    from .extraction import COLLECTED_PROMPT_VERSION
    from .models import ExtractionAttempt

    fields = ["extraction_status", "extraction_error"]
    if post_kind == "about_event":  # the text stays; its images go, as for any read post
        raw.raw_payload = {k: v for k, v in raw.raw_payload.items() if k != "images"}
        raw.extraction_status, raw.extraction_error = "skipped", "about_event"
        fields.append("raw_payload")
    else:
        raw.text, raw.raw_payload, raw.enriched_payload, raw.sender_id = "", {}, {}, ""
        raw.extraction_status, raw.extraction_error = "skipped", "not_event"
        fields += ["text", "raw_payload", "enriched_payload", "sender_id"]
    raw.save(update_fields=fields)
    ExtractionAttempt.objects.create(
        raw_message=raw,
        model_name=settings.LLM_MODEL_NAME,
        prompt_version=COLLECTED_PROMPT_VERSION,
        raw_response={"post_kind": post_kind, "events": []},
        post_kind=post_kind,
        success=False,
        error=raw.extraction_error,
    )
    logfire.info("collected.no_event", raw_message_id=raw.id, post_kind=post_kind)


def process_collected_row(raw, enriched: dict) -> None:
    """Extract the events a collected post announces (text + images) and land each one (ADR-007 D10).

    No events = the post announces none: set aside (an `other` post wiped at once).
    Otherwise each event is held, skipped or landed; events with candidates go through
    one consolidation call that says which existing event each one is. The first
    image becomes a landed event's cover as a downsized copy (sb-7wzb.12 D1), then the
    original bytes are dropped; the post text stays with its events. The row lands
    whole or not at all: on any failure the events roll back, the images stay and
    the cover files already written are deleted. A failed row keeps everything so the
    next collect run can read it again.
    """
    from django.conf import settings

    from .extraction import COLLECTED_PROMPT_VERSION, extract_collected_events

    images = raw.raw_payload.get("images", [])
    read = extract_collected_events(raw.text, images, enriched)
    if not read.events:
        return set_aside(raw, read.post_kind)

    flyer = downsize_flyer(images[0]) if images else None
    written_files: list[str] = []
    try:
        with transaction.atomic():
            if "images" in raw.raw_payload:
                raw.raw_payload = {k: v for k, v in raw.raw_payload.items() if k != "images"}
                raw.save(update_fields=["raw_payload"])
            attempt = dict(
                raw_message=raw,
                model_name=settings.LLM_MODEL_NAME,
                prompt_version=COLLECTED_PROMPT_VERSION,
                post_kind=read.post_kind,
            )
            outcomes = land_post_events(raw, read.events, attempt, flyer, written_files)
            status, error = min(outcomes, key=lambda o: _OUTCOME_RANK.index(o[0]))
            raw.extraction_status, raw.extraction_error = status, error
            raw.save(update_fields=["extraction_status", "extraction_error"])
    except Exception:
        # The rollback took the events and kept the images; the cover files are not transactional.
        for name in written_files:
            default_storage.delete(name)
        raise
    logfire.info("collected.row_landed", raw_message_id=raw.id, events=len(read.events), outcome=status)


def downsize_flyer(image_b64: str) -> bytes:
    """One web-size WebP of a collected flyer: long edge <= 1600 px, metadata dropped.

    An undecodable image raises (ADR-008 D3), before any event lands, so the row
    fails whole and keeps its images for a re-run.
    """
    with Image.open(io.BytesIO(base64.b64decode(image_b64))) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((_FLYER_LONG_EDGE, _FLYER_LONG_EDGE))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=_FLYER_WEBP_QUALITY)
    return out.getvalue()


def _record(attempt, draft, status, error="", event=None, success=False, decision=None, before=None):
    from .models import ExtractionAttempt

    draft_json = draft.model_dump(mode="json")
    ExtractionAttempt.objects.create(
        **attempt,
        raw_response={"draft": draft_json, "decision": decision.model_dump(mode="json") if decision else None},
        extracted_draft=draft_json,
        confidence_score=draft.confidence,
        success=success,
        error=error,
        event=event,
        before=before or {},
    )
    logfire.info("collected.landed", raw_message_id=attempt["raw_message"].id, outcome=status, error=error)
    return status, error


def _hold_reason(draft) -> tuple[str, str] | None:
    """(status, reason) when the draft must not land, else None.

    A cancelled event only ever updates one we have, so place and confidence do not hold it.
    """
    start, end = _times(draft)
    if (end or start) < timezone.now() - timedelta(hours=1):
        return "skipped", "past_event"
    if draft.cancelled:
        return None
    if not draft.in_berlin_area and draft.presence != "online":  # an online event is kept wherever it runs from
        return "skipped", "not_berlin"
    if draft.confidence < _LOW_CONFIDENCE:
        return "needs_review", "low_confidence"
    return None


def _distinct(drafts) -> list:
    """A post's drafts with repeats dropped: one event per title and start."""
    seen, kept = set(), []
    for draft in drafts:
        key = (name_key(draft.title), _times(draft)[0])
        if key not in seen:
            seen.add(key)
            kept.append(draft)
    return kept


def land_post_events(raw, drafts, attempt, flyer=None, written_files=None) -> list[tuple[str, str]]:
    """Land a post's drafts; one (status, reason) per distinct draft (ADR-007 D10).

    A re-read's draft paired with an event its row landed before updates that event
    (sb-7wzb.16 ruling 3). Every other draft looks for candidates; drafts with
    candidates, and paired drafts whose event other posts also announce, go through
    one consolidation call, under the day lock. Same event: rewritten from all its
    eligible announcements. New: created, flagged possible_duplicate_of when the
    call was unsure. A cancelled draft only updates an event we have.
    """
    from events.models import Event

    from .models import ExtractionAttempt

    drafts = _distinct(drafts)
    lock_days(drafts)
    pairs, unpaired = pair_with_own_events(raw, drafts)
    spoken_for = {event.id for event, _ in pairs.values()}
    outcomes: dict[int, tuple[str, str]] = {}
    ready = {}  # draft index -> (names, attribution)
    for i, draft in enumerate(drafts):
        hold = _hold_reason(draft)
        names, attribution = ([], "") if hold else organizer_names(raw, draft)
        # A draft naming no organizer may still be a copy of an event we have; it is held only
        # when it matches none (below), never created without one (ADR-007 D9).
        if hold is None and not names and i in pairs:
            hold = ("needs_review", attribution)
        if hold is None:
            ready[i] = (names, attribution)
            continue
        status, reason = hold
        if i in pairs:  # a paired draft that ends here still leaves its trail on its event
            _record(attempt, draft, status, f"{_RE_READ_ENDED}{status}: {reason}", event=pairs[i][0])
            outcomes[i] = (status, reason)
        else:
            outcomes[i] = _record(attempt, draft, status, reason)

    request = []
    for i, (names, attribution) in ready.items():
        draft = drafts[i]
        if i in pairs:
            event = pairs[i][0]
            if _announcements(event, raw):
                view = [_event_view(event, raw, draft)]
                request.append({"draft": i, "is": event.id, "event": _draft_json(draft), "candidates": view})
            continue
        known_venue, _ = resolve_place(raw, draft, create=False)
        explicit = {_organizer_key(n) for n in names} if attribution == "explicit" else set()
        found = find_candidates(draft, names, known_venue, explicit, exclude=spoken_for)
        if found:
            views = [dict(_event_view(event, raw, draft), signals=signals) for event, signals in found]
            request.append({"draft": i, "event": _draft_json(draft), "candidates": views})
    decisions = _decide(raw, request) if request else {}

    for i, (names, attribution) in ready.items():
        draft, decision = drafts[i], decisions.get(i)
        if i in pairs or (decision and decision.same_as is not None):
            event = pairs[i][0] if i in pairs else Event.objects.get(id=decision.same_as)
            merged, description_from = (decision.event, decision.description_from) if decision else (draft, 0)
            changed, before = merge_into(event, raw, draft, merged, description_from, flyer, written_files)
            if event.raw_message_id == raw.id:  # an event this row landed before
                outcomes[i] = _record(attempt, draft, "extracted", "re_read", event, True, decision, before)
            else:
                reason = f"duplicate (rewrote: {', '.join(changed)})" if changed else "duplicate"
                outcomes[i] = _record(attempt, draft, "duplicate", reason, event, False, decision, before)
            continue
        if draft.cancelled:  # cancels an event we never had: nothing to create
            outcomes[i] = _record(attempt, draft, "skipped", "cancelled", decision=decision)
            continue
        if not names:  # no organizer and no event of ours it is: held for review
            outcomes[i] = _record(attempt, draft, "needs_review", attribution, decision=decision)
            continue
        suspected = decision.possibly_same_as if decision else None
        event = create_collected_event(raw, draft, names, attribution, flyer, written_files, suspected)
        outcomes[i] = _record(attempt, draft, "extracted", "", event, True, decision)

    for event in unpaired:  # left as it is: a re-read never deletes
        ExtractionAttempt.objects.create(**attempt, raw_response={}, event=event, error="unpaired_on_re_read")
    return [outcomes[i] for i in range(len(drafts))]


def create_collected_event(raw, draft, names, attribution, flyer, written_files, possible_duplicate_of=None):
    """A new event from one draft."""
    from events.models import Event
    from syndication.authz import collector_may_publish

    from .extraction import match_entities

    matched = match_entities(draft)
    venue, location_note = resolve_place(raw, draft)
    start, end = _times(draft)
    event = Event.objects.create(
        title=draft.title,
        slug=slugify(draft.title)[:190] + "-" + uuid.uuid4().hex[:8],
        description=draft.description or "",
        venue=venue,
        location_note=location_note,
        presence=draft.presence or "in_person",
        category=draft.category,
        start=start,
        end=end,
        start_time_unknown=draft.start_time_unknown,
        timezone=draft.timezone or _BERLIN,
        price_min_cents=draft.price_min_cents,
        price_max_cents=draft.price_max_cents,
        is_free=draft.is_free,
        status="draft",
        visibility=_tier(raw),
        raw_message=raw,
        suggested_tags=matched["unmatched_tags"],
        possible_duplicate_of_id=possible_duplicate_of,
    )
    credit_people(event, raw, names, attribution, draft.artist_names)
    event.tags.set(matched["matched_tags"])
    _add_link(event, raw, draft.external_url)
    if flyer is not None:
        _add_cover(event, raw, draft, flyer, written_files)
    if not raw.collect_only and collector_may_publish(event):
        event.status = "published"
        event.published_at = timezone.now()
        event.save(update_fields=["status", "published_at"])
    return event
