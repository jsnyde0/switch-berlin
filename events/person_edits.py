"""Which collector-owned field groups a person edited (ADR-007 D10, sb-7wzb.30 ruling 3).

The collector rewrites an event's fields from its announcements, group by group.
A group a person edited is recorded here, where the person saves (admin,
syndication), and the collector never rewrites it again. Nothing is inferred.
"""

# Event field (or "artists" / "tags") -> the collector group it belongs to.
FIELD_GROUPS = {
    "title": "title",
    "description": "description",
    "start": "date",
    "end": "date",
    "start_time_unknown": "date",
    "price_min_cents": "price",
    "price_max_cents": "price",
    "is_free": "price",
    "presence": "presence",
    "category": "category",
    "venue": "place",
    "location_note": "place",
    "tags": "tags",
    "suggested_tags": "tags",
    "artists": "artists",
}


def record_person_edit(event, fields) -> None:
    """Mark the groups of `fields` (names a person changed) as person-edited on `event`."""
    groups = {FIELD_GROUPS[f] for f in fields if f in FIELD_GROUPS}
    if not groups or groups <= set(event.edited_groups):
        return
    event.edited_groups = sorted(groups | set(event.edited_groups))
    event.save(update_fields=["edited_groups"])
