"""
Collected-event feed (sb-7wzb.2, Track A): collector rows in, landed events out.

Two ends of the RawMessage seam for rows that a collector (switch-cli
`collect web` / `collect telegram`) gathered rather than a human forwarded:

- ingest_collected_rows: the staff-only API verb's service — one RawMessage per
  row, extraction enqueued exactly as the forward-bot does.
- land_collected_event: called by process_raw_message after extraction —
  credits the organizer and artists (ADR-007 D9), drops past events and duplicates, derives the tier
  from the source shape (ADR-012 D2) and publishes by claim state (ADR-017 D4).

Plain functions over the existing seam; no source framework (sb-7wzb.2 D3).
"""

import base64
import hashlib
import io
import re
import uuid
from datetime import timedelta

import logfire
from django.contrib.postgres.search import TrigramSimilarity
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from django_q.tasks import async_task
from PIL import Image, ImageOps

from events.backfill_visibility import derive_visibility_from_sources, rawmessage_source_to_conceptual
from organizers.duplicate_names import normalize
from venues.address import split_street_address, validate_no_street_address

# RawMessage.source_type values a collector may write. The bot forward stays the
# bot's own door; its rows keep the draft-for-admin-review path.
COLLECTED_SOURCE_TYPES = ("website", "telegram_telethon", "telegram_private_channel", "telegram_private_group")

# Placeholder names a model returns when the text names no host.
_NO_NAME = {"", "unknown", "n/a", "none", "not specified", "unbekannt"}

# Title similarity at which two same-day events count as one (pg_trgm, case-folded).
_DUPLICATE_TITLE_SIMILARITY = 0.4

# The kept flyer copy (sb-7wzb.12 D1): web size, re-encoded, never the original bytes.
_FLYER_LONG_EDGE = 1600
_FLYER_WEBP_QUALITY = 80


def content_hash(text: str, enriched_payload: dict | None) -> str:
    """The digest of what a collected row says: its text plus the link content the collector fetched."""
    url_content = (enriched_payload or {}).get("url_content", "")
    return hashlib.sha256(f"{text}\0{url_content}".encode()).hexdigest()


def ingest_collected_rows(rows: list[dict]) -> dict:
    """Write one RawMessage per collected row and enqueue its extraction.

    A row already collected (same source_type, channel_id, message_id) is
    counted, not re-written, while it says the same: re-running a collector is
    idempotent. When its content_hash changed, the row takes the new content
    and is read again (sb-7wzb.16). A website row re-listing an earlier one
    (same_listing) is stored without an extraction.
    """
    from .models import RawMessage

    counts = {"created": 0, "already_collected": 0, "re_read": 0, "same_listing": 0}
    for row in rows:
        if row["source_type"] not in COLLECTED_SOURCE_TYPES:
            raise ValueError(f"source_type {row['source_type']!r} is not a collected feed")
        digest = content_hash(row["text"], row.get("enriched_payload"))
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
    that row's event, with no extraction call. Returns True when it was.
    """
    from events.models import Event

    from .models import ExtractionAttempt, RawMessage

    listing = raw.raw_payload.get("listing") or {}
    if raw.source_type != "website" or not listing.get("date") or not listing.get("title"):
        return False
    key = _listing_key(listing["title"])
    earlier = next(
        (
            other
            for other in RawMessage.objects.filter(
                source_type="website", channel_id=raw.channel_id, raw_payload__listing__date=listing["date"]
            )
            .exclude(id=raw.id)
            .exclude(extraction_error="same_listing")
            .order_by("id")
            if _listing_key(other.raw_payload["listing"].get("title", "")) == key
        ),
        None,
    )
    if earlier is None:
        return False
    raw.extraction_status, raw.extraction_error = "duplicate", "same_listing"
    raw.save(update_fields=["extraction_status", "extraction_error"])
    ExtractionAttempt.objects.create(
        raw_message=raw,
        model_name="none",
        prompt_version="same_listing",
        raw_response={"same_listing_as": earlier.id},
        event=Event.objects.filter(raw_message=earlier).order_by("id").first(),
        error="same_listing",
    )
    logfire.info("collected.same_listing", raw_message_id=raw.id, same_as=earlier.id)
    return True


def _aware(dt):
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _create_collected_profile(name: str, raw):
    """Unclaimed organizer Profile for a name no Profile carries (ADR-007 D9: one profile per name).

    status=approved so the organizer page, and with it the claim affordance
    (ADR-014), resolves (mem auto-created-records-reachable-default). The lawful
    basis is the organizer LIA (docs/compliance/organizer-lia.md).
    """
    from organizers.models import Profile

    base = slugify(name)[:40] or "organizer"
    slug = base if not Profile.objects.filter(slug=base).exists() else f"{base}-{uuid.uuid4().hex[:6]}"
    source = raw.raw_payload.get("source") or raw.channel_id
    now = timezone.now()
    return Profile.objects.create(
        name=name,
        slug=slug,
        status="approved",
        approved_at=now,
        consent_recorded_at=now,
        consent_method="legitimate_interest",
        consent_notes=f"Auto-created by the event collector from {source} ({raw.source_type}) on {now.date()}.",
    )


def _name_key(name: str) -> str:
    """Exact-match key for a profile name: casefold, punctuation dropped, whitespace collapsed."""
    return " ".join(re.sub(r"[^\w\s]", " ", normalize(name).casefold()).split())


def find_profile(name: str):
    """The Profile whose name equals `name` under _name_key, or None. Never fuzzy (ADR-007 D9)."""
    from organizers.models import Profile

    key = _name_key(name)
    # debt: scans every profile per lookup; fine at today's tens of profiles, move
    # to a stored normalized-name column when profiles reach the thousands.
    for profile in Profile.objects.all():
        if _name_key(profile.name) == key:
            return profile
    return None


# Separators between names in one string: "A, B & C", "A und B", "A + B".
_NAME_SPLIT = re.compile(r"\s*(?:[,;]|\s(?:&|\+|and|und)\s)\s*", re.IGNORECASE)


def split_names(text: str) -> list[str]:
    """'Tina, Ricardo & Mal' -> ['Tina', 'Ricardo', 'Mal']; placeholder names dropped."""
    return [n for n in (part.strip() for part in _NAME_SPLIT.split(text)) if n.lower() not in _NO_NAME]


def organizer_names(raw, draft) -> tuple[list[str], str]:
    """(names, attribution) for one collected event (ADR-007 D9), first name primary.

    Explicit organizer wording wins (one name per person; a string that is an
    existing profile's whole name stays one); else the publisher the source
    config names. ([], reason) when the event must be held for review.
    """
    explicit = (draft.explicit_organizer or "").strip()
    if explicit and explicit.lower() not in _NO_NAME:
        return ([explicit] if find_profile(explicit) else split_names(explicit)), "explicit"
    if raw.raw_payload.get("aggregator"):
        return [], "no_explicit_organizer"
    publisher = (raw.raw_payload.get("organizer") or "").strip()
    if publisher:
        return [publisher], "publisher"
    return [], "no_organizer"


def credit_people(
    event, raw, names: list[str], attribution: str, artist_names: list[str], taken_names: list[str] = ()
) -> None:
    """Organizer rows (matched or created, never inferred) and artist credits as text, never linked.

    An artist name equal to an organizer name (`names` or `taken_names`) is not credited again.
    """
    from events.models import EventArtist, EventOrganizer

    seen = set()
    for order, name in enumerate(names):
        profile = find_profile(name) or _create_collected_profile(name, raw)
        if profile.id in seen:
            continue
        seen.add(profile.id)
        EventOrganizer.objects.create(
            event=event, profile=profile, is_primary=order == 0, order=order, attribution=attribution
        )
    taken = {_name_key(part) for name in [*names, *taken_names] for part in [name, *split_names(name)]}
    order = 0
    for entry in artist_names:
        for name in split_names(entry):
            if _name_key(name) in taken:
                continue
            taken.add(_name_key(name))
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


def _find_venue(name: str, address: str | None = None):
    """The venue with this exact normalized name (and address, when given), or None."""
    from venues.models import Venue

    key = (normalize(name), None if address is None else normalize(address))
    # debt: scans every venue per event; fine at today's tens of venues, move
    # to a stored normalized-name column when venues reach the thousands.
    for venue in Venue.objects.all():
        if (normalize(venue.name), None if address is None else normalize(venue.address)) == key:
            return venue
    return None


def _venue(name: str, address: str = "", private: bool = False, by_address: bool = False, create: bool = True):
    """The venue with this exact normalized name (and address, when `by_address`), else a new one.

    With create=False a missing venue is None instead.

    New venues carry the address text and no coordinates (no geocoding). They
    never create or link a profile.
    """
    from venues.models import Venue

    found = _find_venue(name, address if by_address else None)
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
    from organizers.models import Profile

    name = (raw.raw_payload.get("venue") or "").strip()
    if not name:
        return None
    venue = _find_venue(name)
    if venue is None:
        raise ValueError(f"source config names default venue {name!r}, which does not exist")
    runner_name = (raw.raw_payload.get("venue_run_by") or "").strip()
    if runner_name:
        runner = Profile.objects.filter(name__iexact=runner_name).first()
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
    lands on the source's default venue. With create=False a place no venue
    holds yet resolves to None (the duplicate check looks, it never creates).
    """
    name = (draft.venue_name or "").strip()
    note = (draft.location_note or "").strip()
    address = (draft.venue_address or "").strip()
    row_text = " ".join((raw.text, raw.enriched_payload.get("url_content", ""), name, note, address))
    private = raw.source_type in _PRIVATE_SHAPES or bool(_RESTRICTED.search(row_text))
    default = apply_source_venue(raw)

    # A known venue matches on its whole name, even one that holds its address.
    known = _find_venue(name) if name and not _is_placeholder(name) else None
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
        venue = _venue(name, address, private, create=create)
    elif address:
        # No place name, only an address: name the venue without it, so a
        # private address never shows through the venue name.
        label = re.sub(r"\s*\([^)]*\)", "", note).split(",")[0].strip()
        label = label or ("Private venue" if private else address)
        venue = _venue(label, address, private, by_address=True, create=create)
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


def _provisional(row, owned: bool) -> bool:
    """A publisher-attributed organizer row, or a blank one (collected before 7d39889) on a collector-owned event."""
    return row.attribution == "publisher" or (row.attribution == "" and owned)


def _explicit_ids(event) -> set[int]:
    """The event's organizer profiles that count for matching: every row that is not provisional."""
    owned = collector_owned(event)
    return {row.profile_id for row in event.event_organizer_set.all() if not _provisional(row, owned)}


def find_duplicate(raw, title: str, start, time_known: bool, venue, explicit: set[int], explicit_named: bool):
    """The live event on the same Berlin day that is this event, or None (sb-x5xh.2 ruling (d)).

    Same event when the titles are similar, or when both start at the same
    known time and share an explicit organizer or the venue; never when both
    name explicit organizers and the two sets share none. `explicit` holds the
    draft's explicit organizers that already have a profile; `explicit_named`
    says whether it names any. The event this row landed itself comes first,
    and the organizer exclusion keeps sources apart, never a row from its own
    event: a re-read naming a new host is the same listing.
    """
    from events.models import Event

    day = timezone.localtime(start).date()
    candidates = (
        Event.objects.exclude(status__in=["rejected", "cancelled"])
        .filter(start__date=day)
        .annotate(sim=TrigramSimilarity("title", title))
        .prefetch_related("event_organizer_set")
    )

    def same(event) -> bool:
        theirs = _explicit_ids(event)
        if explicit_named and theirs and not theirs & explicit and event.raw_message_id != raw.id:
            return False
        if event.sim >= _DUPLICATE_TITLE_SIMILARITY:
            return True
        if not time_known or event.start_time_unknown or event.start != start:
            return False
        return bool(theirs & explicit) or (venue is not None and event.venue_id == venue.id)

    matches = [event for event in candidates if same(event)]
    return min(matches, key=lambda e: (e.raw_message_id != raw.id, -e.sim, e.id), default=None)


def _previous_reading(raw, event) -> dict | None:
    """What this row said about `event` last time it landed it, or None when another row landed it."""
    from .models import ExtractionAttempt

    if event.raw_message_id != raw.id:
        return None
    attempt = ExtractionAttempt.objects.filter(raw_message=raw, event=event, success=True).order_by("-id").first()
    return attempt.extracted_draft if attempt else None


def fill_gaps(event, raw, draft, matched, names, attribution, flyer, written_files) -> list[str]:
    """Fill the kept event's weaker fields from a matching draft; return the fields filled (sb-7wzb.16).

    A field is weaker when empty, or, on the event this same row landed, when
    it still holds what the row said last time (the source updated itself,
    nobody edited it since). A filled field is never overwritten otherwise. An
    explicit organizer replaces the provisional publisher row; explicit sets
    are united, one row per profile. A frozen event (collector_owned False)
    never changes.
    """
    from events.models import EventImage, EventOrganizer

    if not collector_owned(event):
        return []
    before = _previous_reading(raw, event)

    def weaker(current, said_before) -> bool:
        return current in ("", None, (None, None, False)) or (before is not None and current == said_before)

    said = before or {}
    columns = {}  # model field -> new value
    for field in ("description", "external_url"):
        new = getattr(draft, field) or ""
        if new and new != getattr(event, field) and weaker(getattr(event, field), said.get(field) or ""):
            columns[field] = new
    price_fields = ("price_min_cents", "price_max_cents", "is_free")
    price = tuple(getattr(draft, f) for f in price_fields)
    current = tuple(getattr(event, f) for f in price_fields)
    if price != (None, None, False) and price != current and weaker(current, tuple(said.get(f) for f in price_fields)):
        columns.update(zip(price_fields, price, strict=True))
    if not event.suggested_tags and matched["unmatched_tags"]:
        columns["suggested_tags"] = matched["unmatched_tags"]
    if event.venue_id is None or not event.location_note:
        venue, note = resolve_place(raw, draft, create=event.venue_id is None)
        if event.venue_id is None and venue is not None:
            columns["venue"] = venue
        if note and not event.location_note:
            columns["location_note"] = note
    for field, value in columns.items():
        setattr(event, field, value)
    if columns:
        event.save(update_fields=list(columns))
    filled = ["price" if f in price_fields else f for f in columns]
    filled = list(dict.fromkeys(filled))
    if not event.tags.exists() and matched["matched_tags"]:
        event.tags.set(matched["matched_tags"])
        filled.append("tags")

    if attribution == "explicit":
        owned_rows = list(event.event_organizer_set.all())
        if all(_provisional(row, True) for row in owned_rows):
            EventOrganizer.objects.filter(id__in=[row.id for row in owned_rows]).delete()
            credit_people(event, raw, names, attribution, [])
            filled.append("organizers")
        else:
            have = {row.profile_id: row for row in owned_rows}
            order = max(row.order for row in owned_rows) + 1
            for name in names:
                profile = find_profile(name) or _create_collected_profile(name, raw)
                if profile.id in have:
                    if have[profile.id].attribution != "explicit":
                        have[profile.id].attribution = "explicit"
                        have[profile.id].save(update_fields=["attribution"])
                    continue
                have[profile.id] = EventOrganizer.objects.create(
                    event=event, profile=profile, order=order, attribution="explicit"
                )
                order += 1
                if "organizers" not in filled:
                    filled.append("organizers")

    if not event.artist_credits.exists() and draft.artist_names:
        organizer_names_ = [row.profile.name for row in event.event_organizer_set.select_related("profile")]
        credit_people(event, raw, [], "", draft.artist_names, taken_names=organizer_names_)
        if event.artist_credits.exists():
            filled.append("artists")
    if flyer is not None and not EventImage.objects.filter(event=event).exists():
        _add_cover(event, draft, flyer, written_files)
        filled.append("cover")
    return filled


def _add_cover(event, draft, flyer: bytes, written_files: list[str] | None) -> None:
    from events.models import EventImage

    cover = EventImage(event=event, is_cover=True, alt=draft.title[:300])
    cover.image.save(f"{event.slug}.webp", ContentFile(flyer), save=False)
    if written_files is not None:
        written_files.append(cover.image.name)
    cover.save()


# Row status when a post's events land differently: the most-landed outcome wins.
_OUTCOME_RANK = ("extracted", "duplicate", "needs_review", "skipped")

_LOW_CONFIDENCE = 0.4


def wipe_non_event(raw) -> None:
    """Drop everything a non-event post said, images included; keep only its ids and the verdict."""
    from django.conf import settings

    from .extraction import COLLECTED_PROMPT_VERSION
    from .models import ExtractionAttempt

    raw.text, raw.raw_payload, raw.enriched_payload, raw.sender_id = "", {}, {}, ""
    raw.extraction_status, raw.extraction_error = "skipped", "not_event"
    raw.save(
        update_fields=["text", "raw_payload", "enriched_payload", "sender_id", "extraction_status", "extraction_error"]
    )
    ExtractionAttempt.objects.create(
        raw_message=raw,
        model_name=settings.LLM_MODEL_NAME,
        prompt_version=COLLECTED_PROMPT_VERSION,
        raw_response={"events": []},
        success=False,
        error="not_event",
    )
    logfire.info("collected.not_event", raw_message_id=raw.id)


def process_collected_row(raw, enriched: dict) -> None:
    """Extract every event a collected post announces (text + images) and land each one.

    No events = not an event post = wiped at once (LIA §1). Otherwise the first
    image becomes each landed event's cover as a downsized copy (sb-7wzb.12 D1),
    then the original bytes are dropped; the post text stays with its events.
    The row lands whole or not at all: on any failure the events roll back, the
    images stay and the cover files already written are deleted.
    A failed extraction keeps the row whole so it can be re-run.
    """
    from django.conf import settings

    from .extraction import COLLECTED_PROMPT_VERSION, extract_collected_events, match_entities

    images = raw.raw_payload.get("images", [])
    drafts = extract_collected_events(raw.text, images, enriched)
    if not drafts:
        return wipe_non_event(raw)

    flyer = downsize_flyer(images[0]) if images else None
    written_files: list[str] = []
    try:
        with transaction.atomic():
            if "images" in raw.raw_payload:
                raw.raw_payload = {k: v for k, v in raw.raw_payload.items() if k != "images"}
                raw.save(update_fields=["raw_payload"])

            outcomes = []
            for draft in drafts:
                draft_json = draft.model_dump(mode="json")
                attempt_kwargs = dict(
                    raw_message=raw,
                    model_name=settings.LLM_MODEL_NAME,
                    prompt_version=COLLECTED_PROMPT_VERSION,
                    raw_response=draft_json,
                    extracted_draft=draft_json,
                    confidence_score=draft.confidence,
                )
                landed = land_collected_event(raw, draft, match_entities(draft), attempt_kwargs, flyer, written_files)
                outcomes.append(landed)

            status, error = min(outcomes, key=lambda o: _OUTCOME_RANK.index(o[0]))
            raw.extraction_status, raw.extraction_error = status, error
            raw.save(update_fields=["extraction_status", "extraction_error"])
    except Exception:
        # The rollback took the events and kept the images; the cover files are not transactional.
        for name in written_files:
            default_storage.delete(name)
        raise
    logfire.info("collected.row_landed", raw_message_id=raw.id, events=len(drafts), outcome=status)


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


def _record(attempt_kwargs, status, error="", event=None, success=False) -> tuple[str, str]:
    from .models import ExtractionAttempt

    ExtractionAttempt.objects.create(**attempt_kwargs, success=success, error=error, event=event)
    logfire.info("collected.landed", raw_message_id=attempt_kwargs["raw_message"].id, outcome=status, error=error)
    return status, error


def land_collected_event(
    raw, draft, matched, attempt_kwargs, flyer: bytes | None = None, written_files: list[str] | None = None
) -> tuple[str, str]:
    """Land one extracted event: skipped, held, duplicate, draft or published. Returns (outcome, reason).

    A newly landed event takes `flyer` (downsized bytes) as its cover, its stored
    name appended to `written_files`; a duplicate fills its gaps (fill_gaps),
    a cover only when it has none.
    """
    from events.models import Event
    from syndication.authz import collector_may_publish

    start = _aware(draft.start)
    end = _aware(draft.end) if draft.end else None

    if (end or start) < timezone.now() - timedelta(hours=1):
        return _record(attempt_kwargs, "skipped", "past_event")

    if not draft.in_berlin_area:
        return _record(attempt_kwargs, "skipped", "not_berlin")

    if draft.confidence < _LOW_CONFIDENCE:
        return _record(attempt_kwargs, "needs_review", "low_confidence")

    names, attribution = organizer_names(raw, draft)
    if not names:
        return _record(attempt_kwargs, "needs_review", attribution)

    # Organizer and venue resolve before the duplicate check, looked up only:
    # nothing is created for an event that turns out to exist (sb-7wzb.16 (f)).
    explicit = {p.id for p in map(find_profile, names) if p} if attribution == "explicit" else set()
    known_venue, _ = resolve_place(raw, draft, create=False)
    duplicate = find_duplicate(
        raw,
        draft.title,
        start,
        time_known=not draft.start_time_unknown,
        venue=known_venue,
        explicit=explicit,
        explicit_named=attribution == "explicit",
    )
    if duplicate is not None:
        filled = fill_gaps(duplicate, raw, draft, matched, names, attribution, flyer, written_files)
        if duplicate.raw_message_id == raw.id:  # this row's own event, read again
            return _record(attempt_kwargs, "extracted", "re_read", event=duplicate, success=True)
        reason = f"duplicate (filled: {', '.join(filled)})" if filled else "duplicate"
        return _record(attempt_kwargs, "duplicate", reason, event=duplicate)

    venue, location_note = resolve_place(raw, draft)
    event = Event.objects.create(
        title=draft.title,
        slug=slugify(draft.title)[:190] + "-" + uuid.uuid4().hex[:8],
        description=draft.description or "",
        venue=venue,
        location_note=location_note,
        start=start,
        end=end,
        start_time_unknown=draft.start_time_unknown,
        price_min_cents=draft.price_min_cents,
        price_max_cents=draft.price_max_cents,
        is_free=draft.is_free,
        external_url=draft.external_url or "",
        status="draft",
        visibility=derive_visibility_from_sources([rawmessage_source_to_conceptual(raw.source_type)]),
        raw_message=raw,
        suggested_tags=matched["unmatched_tags"],
    )
    credit_people(event, raw, names, attribution, draft.artist_names)
    event.tags.set(matched["matched_tags"])
    if flyer is not None:
        _add_cover(event, draft, flyer, written_files)
    if not raw.collect_only and collector_may_publish(event):
        event.status = "published"
        event.published_at = timezone.now()
        event.save(update_fields=["status", "published_at"])
    return _record(attempt_kwargs, "extracted", event=event, success=True)
