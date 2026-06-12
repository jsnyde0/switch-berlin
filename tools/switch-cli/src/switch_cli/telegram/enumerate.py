"""
Telegram dialog enumeration with can-post filter + forum-topic expansion.

Decisions:
- D1 (FLEXIBLE, ADR-018 D1): can-post filter — classify by postability, not chat type.
  Exclude broadcast-only subscriptions; include private no-username groups;
  expand forum groups to per-topic (group_id, topic_id, topic_title) rows.
  The forum group itself is NOT a postable destination.
- D2 (FIRM, ADR-018 D4): payload is metadata-only — no content, no access_hash,
  no session. This module never emits those fields.
- ADR-008 D3: fail loud on bad dialog data / missing session.

The CANONICAL_DIALOG_TYPES set PINS the four type strings that the server's
TelegramDialogType enum defines. This module cannot import the Django enum
(separate subproject), so we mirror the four strings here and pin them with a
test (divergence would produce 422s from the ingest verb).

Single-resolution-point: the server's TelegramDialogType in syndication/models.py
is authoritative. CANONICAL_DIALOG_TYPES here must match it exactly.
"""

from telethon import TelegramClient
from telethon.sessions import StringSession

from switch_cli.telegram.session import load_telegram_session

# ---------------------------------------------------------------------------
# Canonical type vocabulary — mirrors server TelegramDialogType enum
# (kb-ru55.2 D1a single-resolution-point: channel/group/supergroup/forum_topic)
# DO NOT add forum_group — only forum TOPICS are postable destinations.
# ---------------------------------------------------------------------------

CANONICAL_DIALOG_TYPES = {"channel", "group", "supergroup", "forum_topic"}

# ---------------------------------------------------------------------------
# Server-vocabulary postability tiers — mirrors syndication/models.py postability
# field (kb-ru55.2). Must be kept in sync; divergence causes 422s from ingest verb.
# Single-resolution-point: the server model's help_text documents these tiers.
# ---------------------------------------------------------------------------
SERVER_POSTABILITY_VOCABULARY = {"bot", "agent", "public"}

# MTProto sync via user session reaches every dialog through the agent/saveDraft
# path → honest tier is "agent". Whether a destination is ALSO bot-reachable or
# public (deep-link) is refined server-side by kb-sbhs D4 (Switch bot admin presence
# + username presence). Do NOT compute those tiers here.
POSTABILITY_TIER = "agent"


class NoSessionError(Exception):
    """
    Raised when no session file exists and sync is attempted.
    (ADR-008 D3: fail loud — tell the user to run `connect` first.)
    """


async def _get_forum_topics(client, entity) -> list:
    """
    Fetch forum topics for a forum group entity.

    Separated as its own function so it can be easily mocked in tests.
    Uses GetForumTopicsRequest from Telethon messages functions.
    """
    from telethon.tl.functions.messages import GetForumTopicsRequest

    result = await client(
        GetForumTopicsRequest(
            peer=entity,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
            q=None,
        )
    )
    return result.topics


def _is_broadcast_subscription(entity) -> bool:
    """
    Return True if the dialog is a broadcast channel the user can only READ
    (cannot post to).

    Broadcast channels are excluded unless:
    - entity.creator is True (user owns the channel), or
    - entity.admin_rights is not None AND admin_rights.post_messages is truthy
      (user has admin rights with explicit post permission).

    ADR-018 D1: classify by POSTABILITY.
    """
    is_broadcast = getattr(entity, "broadcast", False)
    if not is_broadcast:
        return False
    creator = getattr(entity, "creator", False)
    admin_rights = getattr(entity, "admin_rights", None)
    # User can post if they are the creator, or if they have admin rights AND
    # admin_rights.post_messages is truthy. post_messages=None/False means the
    # admin cannot post (e.g. ban_users-only admin) → must EXCLUDE.
    can_post = creator or (admin_rights is not None and bool(getattr(admin_rights, "post_messages", False)))
    return not can_post


def _is_forum(entity) -> bool:
    """Return True if the entity is a forum group (forum=True attribute)."""
    try:
        return bool(getattr(entity, "forum", False))
    except (AttributeError, TypeError):
        return False


def _classify_type(entity) -> str:
    """
    Classify a postable dialog entity into one of the canonical type strings.

    Returns one of: channel, group, supergroup, forum_topic.
    (forum_topic rows are produced by expansion; this function returns supergroup
    for megagroup entities, group for plain groups, channel for channels.)
    """
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
        return "supergroup"
    return "group"


async def enumerate_postable_dialogs(
    client,
    config_dir: str = None,
    check_session: bool = False,
) -> list[dict]:
    """
    Enumerate the account's dialogs and return a flat list of postable destinations.

    Can-post filter (ADR-018 D1 / bead D1):
    - broadcast channel the user only subscribes to → EXCLUDE
    - own/admin channel → INCLUDE as type=channel
    - plain group, no-username group → INCLUDE as type=group
    - megagroup/supergroup → INCLUDE as type=supergroup
    - forum group → expand into one row per topic (type=forum_topic, topic_id=<id>)
      The forum GROUP itself is NOT included as a postable destination.

    Args:
        client: authenticated Telethon TelegramClient (or None if check_session=True)
        config_dir: path to check for session file (used when check_session=True)
        check_session: if True, raise NoSessionError when no session file exists
                       (ADR-008 D3 — fail loud, tell user to run connect first)

    Returns:
        list of dicts with keys: chat_id, title, type, topic_id, postability
        (metadata-only — ADR-018 D4 / bead D2 FIRM)

    Raises:
        NoSessionError if check_session=True and no session file found.
    """
    if check_session:
        if config_dir is None:
            raise ValueError("config_dir required when check_session=True")
        session = load_telegram_session(config_dir=config_dir)
        if session is None:
            raise NoSessionError("No Telegram session found. Run `switch-cli telegram connect` first to authenticate.")

    dialogs = await client.get_dialogs()
    inventory: list[dict] = []

    for dialog in dialogs:
        entity = dialog.entity

        # Exclude broadcast-only subscriptions (cannot post)
        if _is_broadcast_subscription(entity):
            continue

        # Forum groups → expand into per-topic rows
        if _is_forum(entity):
            topics = await _get_forum_topics(client, entity)
            for topic in topics:
                inventory.append(
                    {
                        "chat_id": str(dialog.id),
                        "title": topic.title,
                        "type": "forum_topic",
                        "topic_id": topic.id,
                        "postability": POSTABILITY_TIER,
                    }
                )
            # The forum group itself is NOT a postable destination — skip
            continue

        # Plain channel (admin/owner) or group/supergroup → include
        dialog_type = _classify_type(entity)
        inventory.append(
            {
                "chat_id": str(dialog.id),
                "title": dialog.name,
                "type": dialog_type,
                "topic_id": None,
                "postability": POSTABILITY_TIER,
            }
        )

    return inventory


def build_authenticated_client(api_id: int, api_hash: str, session_string: str) -> TelegramClient:
    """
    Build a Telethon TelegramClient using the stored StringSession.

    The session_string is read from the local config file — it is NEVER
    sent to any server (ADR-018 D4 / D2 FIRM).
    """
    return TelegramClient(StringSession(session_string), api_id, api_hash)


async def run_sync(api_id: int, api_hash: str, config_dir: str) -> list[dict]:
    """
    Synchronous entry point for the `telegram sync` CLI command.

    1. Load session string from config dir — fail loud if missing (ADR-008 D3).
    2. Build an authenticated Telethon client.
    3. Enumerate postable dialogs.
    4. Return the flat inventory list (metadata-only).

    Raises:
        NoSessionError if no session file found (ADR-008 D3).
        SessionCorruptError if session file is corrupt (ADR-008 D3).
    """
    session_string = load_telegram_session(config_dir=config_dir)
    if session_string is None:
        raise NoSessionError("No Telegram session found. Run `switch-cli telegram connect` first to authenticate.")

    client = build_authenticated_client(api_id=api_id, api_hash=api_hash, session_string=session_string)
    async with client:
        return await enumerate_postable_dialogs(client)
