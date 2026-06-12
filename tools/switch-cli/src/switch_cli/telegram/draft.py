"""
Telegram multi-destination draft placement for switch-cli.

Decisions:
- D1 (FIRM, ADR-018 D2): draft-only firewall. This module NEVER calls
  sendMessage or any auto-send Telethon method. Placement is exclusively via
  Draft.set_message() → SaveDraftRequest for all destinations (both plain groups
  and forum topics). Verified structurally via AST-parse
  (test_telegram_distribute.py TestASTFirewall) AND behaviorally via mock-not-called
  across all branches.
- D2 (FLEXIBLE, ADR-018 D4 / ADR-008 D3): getDraft-before-saveDraft per destination.
  Pre-existing draft (non-empty) → record skipped-pre-existing-draft, warn, no clobber.
- D3 (FLEXIBLE, ADR-018 D1): forum drafts are placed at the FORUM LEVEL (reply_to=None),
  same as groups. Telegram Desktop does NOT render topic-pinned drafts (top_msg_id) —
  confirmed live 2026-06-12 — so topic-pinning is intentionally NOT used; the intended
  topic is conveyed via the distribute result for the human to route. True per-topic
  pinning is a deferred follow-up.
- D4 (FIRM, ADR-008 D3): --dest not in the postable inventory → fail loud via
  UnknownDestinationError. No silent skip.

Real Telethon Draft API (confirmed from source):
- telethon/tl/custom/draft.py, line 101: Draft.is_empty property
- telethon/tl/custom/draft.py, line 107: Draft.set_message(text, reply_to=0, ...)
  which calls SaveDraftRequest internally.
- client.get_drafts(entity) returns a single Draft when entity is given (line 318).
"""

import warnings

from switch_cli.telegram.enumerate import build_authenticated_client, enumerate_postable_dialogs
from switch_cli.telegram.session import load_telegram_session


class UnknownDestinationError(Exception):
    """
    Raised when a --dest is not found in the postable inventory (ADR-008 D3).
    Fail loud — no silent skip.
    """


def _parse_dest(dest: str) -> tuple[str, int | None]:
    """
    Parse a destination string of the form '<chat_id>' or '<chat_id>:<topic_id>'.

    Returns:
        (chat_id_str, topic_id) where topic_id is None for plain groups/channels.
    """
    if ":" in dest:
        parts = dest.rsplit(":", 1)
        return parts[0], int(parts[1])
    return dest, None


def _resolve_dest(
    dest: str, postable_inventory: list[dict]
) -> dict:
    """
    Resolve a raw --dest string against the postable inventory.

    Returns the matching inventory entry.

    Raises:
        UnknownDestinationError if not found (ADR-008 D3 — fail loud).
    """
    chat_id_str, topic_id = _parse_dest(dest)

    for entry in postable_inventory:
        if entry["chat_id"] == chat_id_str:
            # For plain groups/channels: topic_id must be None
            if topic_id is None and entry.get("topic_id") is None:
                return entry
            # For forum topics: topic_id must match
            if topic_id is not None and entry.get("topic_id") == topic_id:
                return entry

    raise UnknownDestinationError(
        f"Destination '{dest}' (chat_id={chat_id_str!r}, topic_id={topic_id!r}) "
        f"is not in the postable inventory. "
        f"Run `switch-cli telegram sync` to refresh the inventory, "
        f"or check that the --dest value is correct. "
        f"Available destinations: {[e['chat_id'] for e in postable_inventory]}"
    )


async def _place_draft(
    client,
    entry: dict,
    message: str,
) -> dict:
    """
    Place a draft for a single destination via the getDraft → saveDraft mechanism.

    D1 (FIRM, ADR-018 D2): NEVER calls send_message or any auto-send method.
    D2 (ADR-008 D3): pre-existing draft → skip with skipped-pre-existing-draft, no clobber.
    D3 (FLEXIBLE, ADR-018 D1): forum drafts placed at the FORUM LEVEL (reply_to=None),
    same as groups. Telegram Desktop does NOT render topic-pinned drafts (top_msg_id set)
    — confirmed live 2026-06-12 — so topic-pinning is intentionally NOT used; the intended
    topic is conveyed via the distribute result for the human to route. True per-topic
    pinning is a deferred follow-up.

    Returns a dict with keys: chat_id, topic_id, status.
    """
    chat_id_str = entry["chat_id"]
    topic_id = entry.get("topic_id")

    # Resolve the entity from the chat_id
    # Telethon requires the peer as an integer or resolvable entity
    chat_id_int = int(chat_id_str)

    # getDraft first (D2)
    # client.get_drafts(entity) returns a single Draft when entity is given
    draft = await client.get_drafts(chat_id_int)

    # Pre-existing draft check (D2 / ADR-008 D3 warn-don't-clobber)
    if not draft.is_empty:
        warnings.warn(
            f"Skipping chat_id={chat_id_str} (topic_id={topic_id}): "
            f"pre-existing draft detected, not clobbering. "
            f"Clear the draft manually if you want to place a new one.",
            stacklevel=2,
        )
        return {
            "chat_id": chat_id_str,
            "topic_id": topic_id,
            "status": "skipped-pre-existing-draft",
        }

    # saveDraft (D1 FIRM: Draft.set_message → SaveDraftRequest — no send path)
    # Same path for both plain groups and forum topics (reply_to=None for both).
    # Forum-level draft (no reply_to) is visible in Telegram Desktop; topic-pinned
    # drafts (top_msg_id set) are NOT rendered by Telegram Desktop — confirmed live
    # 2026-06-12 (ADR-018 D1, D3 FLEXIBLE). Per-topic pinning is a deferred follow-up.
    await draft.set_message(text=message)

    return {
        "chat_id": chat_id_str,
        "topic_id": topic_id,
        "status": "placed",
    }


async def distribute(
    client,
    message: str,
    dests: list[str],
    postable_inventory: list[dict],
) -> list[dict]:
    """
    Multi-destination draft placement.

    Builds a placement set from --dest values resolved against the postable
    inventory, then for each destination: getDraft → if empty, saveDraft; if
    pre-existing, record skipped-pre-existing-draft and warn (no clobber).

    Args:
        client: authenticated Telethon TelegramClient.
        message: the draft body text to place.
        dests: list of destination strings ('<chat_id>' or '<chat_id>:<topic_id>').
        postable_inventory: flat list from enumerate_postable_dialogs.

    Returns:
        List of per-destination result dicts with keys: chat_id, topic_id, status.
        status is 'placed' or 'skipped-pre-existing-draft'.

    Raises:
        UnknownDestinationError if any --dest is not in the inventory (ADR-008 D3).

    D1 (FIRM, ADR-018 D2): never calls send_message or any auto-send variant.
    """
    # Validate ALL destinations before placing any draft (fail-fast, ADR-008 D3)
    resolved_entries = []
    for dest in dests:
        entry = _resolve_dest(dest, postable_inventory)
        resolved_entries.append(entry)

    # Place drafts for each resolved destination
    results = []
    for entry in resolved_entries:
        result = await _place_draft(client=client, entry=entry, message=message)
        results.append(result)

    return results


async def run_distribute(
    api_id: int,
    api_hash: str,
    config_dir: str,
    message: str,
    dests: list[str],
) -> list[dict]:
    """
    Entry point for the `telegram distribute` CLI command.

    1. Load session string — fail loud if missing (ADR-008 D3).
    2. Build an authenticated Telethon client.
    3. Enumerate the live postable inventory.
    4. Call distribute() to place drafts.
    5. Return the placement results.

    Raises:
        NoSessionError if no session file found.
        SessionCorruptError if session file is corrupt.
        UnknownDestinationError if any --dest is not in the postable inventory.
    """
    from switch_cli.telegram.enumerate import NoSessionError

    session_string = load_telegram_session(config_dir=config_dir)
    if session_string is None:
        raise NoSessionError(
            "No Telegram session found. Run `switch-cli telegram connect` first to authenticate."
        )

    client = build_authenticated_client(api_id=api_id, api_hash=api_hash, session_string=session_string)
    async with client:
        postable_inventory = await enumerate_postable_dialogs(client)
        return await distribute(
            client=client,
            message=message,
            dests=dests,
            postable_inventory=postable_inventory,
        )
