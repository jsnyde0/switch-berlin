"""
Track A event collector, Telegram half (sb-7wzb.2, ADR-018 D6).

Reads recent posts from the channels, groups and forum topics on the source
list, through the user's own session, and turns each post into a row for the
Switch RawMessage seam: an album (grouped_id) is one post, and its photos ride
along base64 in raw_payload["images"] so the extractor reads flyers too
(sb-7wzb.4). Photos are downloaded into memory, never to their own files.
They do reach disk inside the rows file that `collect telegram --out` writes;
`collect push` deletes that file after a successful push (unless --keep), and
the server drops the photos after extraction.

READ-ONLY: this module only calls get_dialogs, get_entity, GetForumTopicsRequest
and iter_messages. It never sends, posts, forwards, joins or drafts
(ADR-018 D2 FIRM, D6). Joining a source is the user's manual act.
"""

import base64
from datetime import UTC, datetime, timedelta

from switch_cli.collect import collected_row

PRIVATE_SHAPES = ("telegram_private_channel", "telegram_private_group")


class SourceUnreachable(Exception):
    """The source resolves to no dialog, several dialogs, or no matching topic."""


async def _resolve(client, source: dict, dialogs: list):
    chat = source["chat"]
    if chat.startswith("@"):
        return await client.get_entity(chat)
    chats = [d for d in dialogs if d.is_channel or d.is_group]  # never a person's DM
    hits = [d.entity for d in chats if (d.name or "").lower() == chat.lower()]
    hits = hits or [d.entity for d in chats if chat.lower() in (d.name or "").lower()]
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
    client, sources: list[dict], days: int, include_private: bool, limit: int = 80
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
            posts: dict[int, list] = {}  # album or message id -> its messages, newest first
            async for msg in client.iter_messages(entity, reply_to=topic.id if topic else None, limit=limit):
                if msg.date < cutoff:
                    break
                posts.setdefault(msg.grouped_id or msg.id, []).append(msg)
            got = 0
            for msgs in posts.values():
                msgs = sorted(msgs, key=lambda m: m.id)
                first = msgs[0]
                body = "\n".join((m.message or "").strip() for m in msgs if (m.message or "").strip())
                images = [
                    base64.b64encode(await client.download_media(m, file=bytes)).decode() for m in msgs if m.photo
                ]
                if not body and not images:
                    continue
                posted = first.date.astimezone()
                header = f"Telegram post in {title}, posted {posted.date().isoformat()} ({posted.strftime('%A')})."
                extra = {"images": images} if images else {}
                row = collected_row(
                    src,
                    channel_id,
                    str(first.id),
                    f"{header}\n\n{body}",
                    chat_title=title,
                    posted_at=str(first.date),
                    **extra,
                )
                if username:
                    row["raw_payload"]["url"] = f"https://t.me/{username}/{first.id}"
                row["sender_id"] = str(first.sender_id or "")
                rows.append(row)
                got += 1
            seen = sum(len(m) for m in posts.values())
        except Exception as exc:  # per-source failure is reported, the run continues
            report.append({"source": source["name"], "rows": 0, "error": f"{type(exc).__name__}: {exc}"})
            continue
        report.append({"source": source["name"], "rows": got, "posts_in_window": seen})
    return rows, report
