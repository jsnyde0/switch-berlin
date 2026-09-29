"""
Track A event collector, Telegram half (sb-7wzb.2, ADR-018 D6).

Reads recent posts from the channels, groups and forum topics on the source
list, through the user's own session, and turns each post long enough to be an
announcement into a row for the Switch RawMessage seam.

READ-ONLY: this module only calls get_dialogs, get_entity, GetForumTopicsRequest
and iter_messages. It never sends, posts, forwards, joins or drafts
(ADR-018 D2 FIRM, D6). Joining a source is the user's manual act.
"""

from datetime import UTC, datetime, timedelta

from switch_cli.collect import collected_row

PRIVATE_SHAPES = ("telegram_private_channel", "telegram_private_group")


class SourceUnreachable(Exception):
    """The source resolves to no dialog, several dialogs, or no matching topic."""


async def _resolve(client, source: dict, dialogs: list):
    chat = source["chat"]
    if chat.startswith("@"):
        return await client.get_entity(chat)
    hits = [d.entity for d in dialogs if chat.lower() in (d.name or "").lower()]
    if len(hits) != 1:
        raise SourceUnreachable(f"{len(hits)} joined dialogs match title {chat!r}")
    return hits[0]


async def _topic(client, entity, wanted: str):
    from telethon.tl.functions.messages import GetForumTopicsRequest

    result = await client(
        GetForumTopicsRequest(peer=entity, offset_date=None, offset_id=0, offset_topic=0, limit=100, q=None)
    )
    hits = [t for t in result.topics if wanted.lower() in (getattr(t, "title", "") or "").lower()]
    if len(hits) != 1:
        titles = [getattr(t, "title", "") for t in result.topics]
        raise SourceUnreachable(f"{len(hits)} topics match {wanted!r}; topics: {titles}")
    return hits[0]


async def collect_telegram(
    client, sources: list[dict], days: int, include_private: bool, min_chars: int = 120, limit: int = 80
) -> tuple[list[dict], list[dict]]:
    """Rows from every Telegram source for posts of the last `days` days; plus a per-source report."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    dialogs = await client.get_dialogs()
    rows, report = [], []
    for source in sources:
        if source["shape"] == "website":
            continue
        if source["shape"] in PRIVATE_SHAPES and not include_private:
            report.append({"source": source["name"], "rows": 0, "skipped": "private source; run with --private"})
            continue
        try:
            entity = await _resolve(client, source, dialogs)
            title = getattr(entity, "title", "") or source["name"]
            username = getattr(entity, "username", None)
            channel_id = f"@{username}" if username else str(entity.id)
            topic = await _topic(client, entity, source["topic"]) if source.get("topic") else None
            if topic is not None:
                channel_id = f"{channel_id}:{topic.id}"
                title = f"{title} / {topic.title}"
            organizer = source.get("organizer")
            if not organizer and source.get("channel_organizer"):
                organizer = getattr(entity, "title", "")
            src = {**source, "organizer": organizer}
            got = seen = 0
            async for msg in client.iter_messages(entity, reply_to=topic.id if topic else None, limit=limit):
                if msg.date < cutoff:
                    break
                seen += 1
                body = (msg.message or "").strip()
                if len(body) < min_chars:
                    continue
                posted = msg.date.astimezone()
                header = f"Telegram post in {title}, posted {posted.date().isoformat()} ({posted.strftime('%A')})."
                row = collected_row(
                    src, channel_id, str(msg.id), f"{header}\n\n{body}", chat_title=title, posted_at=str(msg.date)
                )
                if username:
                    row["raw_payload"]["url"] = f"https://t.me/{username}/{msg.id}"
                row["sender_id"] = str(msg.sender_id or "")
                rows.append(row)
                got += 1
        except Exception as exc:  # per-source failure is reported, the run continues
            report.append({"source": source["name"], "rows": 0, "error": f"{type(exc).__name__}: {exc}"})
            continue
        report.append({"source": source["name"], "rows": got, "posts_in_window": seen})
    return rows, report
