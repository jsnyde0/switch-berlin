"""One name resolver for Profiles and Venues, merge-aware (sb-7wzb.25; sb-x5xh.2 rule 5).

A name resolves to the live row that carries it; failing that, to the winner
of the staff merge that removed a row of that name (MergeRecord), so a merged
duplicate is never recreated. Never fuzzy (ADR-007 D9). Used by the collector
for organizer, venue and source-config names.
"""

import re

from .duplicate_names import normalize
from .models import MergeRecord, Profile


def name_key(name: str) -> str:
    """Exact-match key for a name: casefold, punctuation dropped, whitespace collapsed."""
    return " ".join(re.sub(r"[^\w\s]", " ", normalize(name).casefold()).split())


def _merged_into(model, kind: str, name: str):
    """The live `model` row the merge records send `name` to, following a chain of merges, or None."""
    key = name_key(name)
    # debt: scans every merge record of the kind per hop, because records store the
    # looser normalize() form; fine at today's handful of merges, move to a stored
    # name_key column when merges reach the thousands.
    records = list(MergeRecord.objects.filter(kind=kind).order_by("-merged_at", "-id"))
    seen = set()
    while key not in seen:
        seen.add(key)
        record = next((r for r in records if name_key(r.loser_name) == key), None)
        if record is None:
            return None
        winner = model.objects.filter(pk=record.winner_id).first()
        if winner is not None:
            return winner
        key = name_key(record.winner_name)  # the winner was itself merged away
    return None


def find_profile(name: str):
    """The Profile carrying `name` (name_key match), else the winner of its merge, else None."""
    key = name_key(name)
    # debt: scans every profile per lookup; fine at today's tens of profiles, move
    # to a stored normalized-name column when profiles reach the thousands.
    for profile in Profile.objects.all():
        if name_key(profile.name) == key:
            return profile
    return _merged_into(Profile, "profile", name)


def find_venue(name: str, address: str | None = None):
    """The Venue with this normalized name (and address, when given), else the winner of its merge, else None.

    A lookup by address never consults merges: the address names the place, the name is only a label.
    """
    from venues.models import Venue

    key = (name_key(name), None if address is None else normalize(address))
    # debt: scans every venue per event; fine at today's tens of venues, move
    # to a stored normalized-name column when venues reach the thousands.
    for venue in Venue.objects.all():
        if (name_key(venue.name), None if address is None else normalize(venue.address)) == key:
            return venue
    return None if address is not None else _merged_into(Venue, "venue", name)
