import time

import logfire
from asgiref.sync import sync_to_async
from django_q.tasks import async_task
from telegram import Update
from telegram.error import InvalidToken
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from ingestion.models import ApprovedSender, RawMessage, RejectedMessageAttempt

# Rate limiting: in-memory, resets on restart. Acceptable for single-worker -- resets
# on restart, which is fine since the limit is a safety valve, not a billing control.
_rate_buckets: dict[str, list[float]] = {}  # sender_id -> list of timestamps
RATE_LIMIT = 100  # messages per hour per sender


def _is_rate_limited(sender_id: str) -> bool:
    now = time.time()
    window = _rate_buckets.setdefault(sender_id, [])
    _rate_buckets[sender_id] = [t for t in window if now - t < 3600]
    if len(_rate_buckets[sender_id]) >= RATE_LIMIT:
        return True
    _rate_buckets[sender_id].append(now)
    return False


def _bot_enabled() -> bool:
    """DB-backed feature gate via FeatureFlag model (ADR-003 F9, bead kb-8qn.12).

    INGESTION_PAUSED=True  -> bot disabled (returns False; short-circuits handler).
    INGESTION_PAUSED=False -> bot runs normally (returns True).
    Flag missing in DB     -> default=False -> not False = True (bot runs normally).

    Cached 60s TTL; toggle propagates without bot restart within one TTL window."""
    from a_core.models import get_flag

    return not get_flag("INGESTION_PAUSED", default=False)


CONSENT_TEXT_EN = (
    "By forwarding messages to this bot, you confirm you have the right to share "
    "this information and consent to it being used for event listings on Switch Berlin."
)
CONSENT_TEXT_DE = (
    "Mit dem Weiterleiten von Nachrichten an diesen Bot bestätigst du, dass du das "
    "Recht hast, diese Informationen zu teilen, und stimmst ihrer Nutzung für "
    "Veranstaltungslistings auf Switch Berlin zu."
)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 1. Feature flag check (DB-backed; sync_to_async required in async context)
    if not await sync_to_async(_bot_enabled)():
        await update.message.reply_text("Bot is temporarily offline.")
        return

    # 2. Extract sender_id
    sender_id = str(update.effective_user.id)

    # 3. Log receipt
    logfire.info(
        "bot.message_received",
        sender_id=sender_id,
        message_id=str(update.message.message_id) if update.message else "",
        is_text=bool(update.message and update.message.text),
    )

    # 4. Allowlist check
    exists = await sync_to_async(
        ApprovedSender.objects.filter(telegram_user_id=sender_id).exists
    )()
    if not exists:
        message_text = (update.message.text or "")[:500] if update.message else ""
        await sync_to_async(RejectedMessageAttempt.objects.create)(
            telegram_user_id=update.effective_user.id,
            telegram_username=update.effective_user.username or "",
            chat_id=update.message.chat.id if update.message else None,
            message_text=message_text,
        )
        if update.message:
            await update.message.reply_text(
                "This bot only accepts forwards from approved organizers. "
                "To request access, DM @jsnyde0."
            )
        return

    # 5. Non-text message check (only reached by approved senders)
    if update.message and not update.message.text:
        await sync_to_async(RawMessage.objects.create)(
            source_type="telegram_bot_forward",
            sender_id=sender_id,
            channel_id="",
            message_id=str(update.message.message_id) if update.message else "",
            raw_payload=update.message.to_dict(),
            text="",
            extraction_status="skipped",
            extraction_error="non_text_message",
        )
        await update.message.reply_text(
            "Only text messages and text forwards are supported."
        )
        return

    # 6. Rate limit check
    if _is_rate_limited(sender_id):
        await update.message.reply_text(
            "Rate limit reached (100 messages/hour). Please try again later."
        )
        return

    # 7. First-interaction consent
    has_prior = await sync_to_async(
        RawMessage.objects.filter(sender_id=sender_id).exists
    )()
    if not has_prior:
        await update.message.reply_text(CONSENT_TEXT_EN + "\n\n" + CONSENT_TEXT_DE)

    # 8. Dedup check + RawMessage creation
    message_id = str(update.message.message_id) if update.message else ""
    channel_id = (
        str(update.message.forward_from_chat.id)
        if update.message and update.message.forward_from_chat
        else ""
    )
    raw_payload = update.message.to_dict()
    text = update.message.text or ""

    from django.db import IntegrityError

    try:
        raw_message = await sync_to_async(RawMessage.objects.create)(
            source_type="telegram_bot_forward",
            sender_id=sender_id,
            channel_id=channel_id,
            message_id=message_id,
            raw_payload=raw_payload,
            text=text,
        )
    except IntegrityError:
        await update.message.reply_text("Already received this message.")
        return

    # 9. Enqueue extraction task
    await sync_to_async(async_task)(
        "ingestion.tasks.process_raw_message", raw_message.id
    )

    # 10. Acknowledge
    await update.message.reply_text("Received. Will appear in the next review batch.")

    # 11. Log
    logfire.info(
        "bot.message_queued",
        sender_id=sender_id,
        raw_message_id=raw_message.id,
    )


def run_bot(token: str) -> None:
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    _redacted_msg: str | None = None
    try:
        app.run_polling()
    except InvalidToken as exc:
        # Re-raise with token redacted so the full token never lands in docker logs.
        # The original message contains the literal token (e.g.
        # "The token `<token>` was rejected by the server.").
        # Raise *outside* the except block so Python does not auto-set __context__
        # on the new exception — structured telemetry frameworks (logfire, Sentry,
        # structlog) walk __context__ regardless of __suppress_context__, so keeping
        # __context__ would leak the token via that second channel.
        _redacted_msg = str(exc).replace(token, "<redacted>") if token else str(exc)
    else:
        return
    raise InvalidToken(_redacted_msg) from None
