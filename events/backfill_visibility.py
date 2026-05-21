"""
Shared helper for visibility backfill logic (ADR-012 D2).

Extracted into a standalone module so it can be:
  1. Imported by the data migration for bulk backfill.
  2. Tested in isolation (events/tests/test_visibility.py).
  3. Called from future ingestion code when new events are created.

Two-level mapping:
  - `derive_visibility_from_sources(conceptual_source_list)` — takes the
    ADR-012 D2 conceptual source names and returns the visibility tier.
    Tested directly; used by migrations and any code that has already mapped
    RawMessage.source_type → conceptual name.

  - `rawmessage_source_to_conceptual(source_type)` — maps an actual
    RawMessage.source_type value to an ADR-012 D2 conceptual source name.

ADR-012 D2 source → default tier mapping (conceptual names):
  scraped_public_website  → public
  telegram_public_channel → public
  telegram_private_group  → semi_public
  user_submitted_web_form → semi_public
  (empty / manual)        → semi_public

max(public) resolution: if any source maps to 'public', result is 'public'.

ADR-008 D3: unknown source type raises ValueError rather than silently
defaulting; the caller must triage unknown sources.
"""

# Tier ordering: higher index = more public
_TIER_ORDER = ["semi_public", "public"]

# Source → default visibility tier (conceptual ADR-012 D2 source names)
_SOURCE_TIER: dict[str, str] = {
    "scraped_public_website": "public",
    "telegram_public_channel": "public",
    "telegram_private_group": "semi_public",
    "user_submitted_web_form": "semi_public",
}

# RawMessage.source_type → ADR-012 D2 conceptual source name
# ADR-008 D3: unmapped source_type raises in derive_visibility_from_sources.
_RAWMESSAGE_TO_CONCEPTUAL: dict[str, str] = {
    "telegram_bot_forward": "telegram_private_group",
    "telegram_telethon": "telegram_public_channel",
    "email_submission": "user_submitted_web_form",
    "web_form": "user_submitted_web_form",
}


def rawmessage_source_to_conceptual(source_type: str) -> str:
    """Map a RawMessage.source_type to an ADR-012 D2 conceptual source name.

    Raises ValueError for unmapped types (ADR-008 D3).
    """
    if source_type not in _RAWMESSAGE_TO_CONCEPTUAL:
        raise ValueError(
            f"Unknown RawMessage.source_type {source_type!r}. "
            f"Expected one of: {sorted(_RAWMESSAGE_TO_CONCEPTUAL)}. "
            "Cannot derive visibility tier (ADR-008 D3 fail loud)."
        )
    return _RAWMESSAGE_TO_CONCEPTUAL[source_type]


def derive_visibility_from_sources(source_types: list[str]) -> str:
    """
    Return the visibility tier for an event given its list of conceptual
    ADR-012 D2 source type names.

    - Empty list (manual / admin creation): semi_public (ADR-012 D2 table,
      'Manual admin or organizer creation → semi_public' row)
    - Single source: maps directly via _SOURCE_TIER
    - Multiple sources: max(public) wins — returns the most public tier

    Raises ValueError for any unrecognised source_type (ADR-008 D3 fail loud).
    """
    if not source_types:
        return "semi_public"

    tiers = []
    for src in source_types:
        if src not in _SOURCE_TIER:
            raise ValueError(
                f"Unknown source type {src!r}. "
                f"Expected one of: {sorted(_SOURCE_TIER)}. "
                "Cannot derive visibility tier (ADR-008 D3 fail loud)."
            )
        tiers.append(_SOURCE_TIER[src])

    # max(public) resolution: pick the tier with the highest index in _TIER_ORDER
    return max(tiers, key=lambda t: _TIER_ORDER.index(t))
