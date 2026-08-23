"""Phase 2: Telegram connection + persistent chat history.

Incoming text is recorded once by log_incoming, which runs in handler
group -1 before any routing. Outgoing text is recorded by replying through
_reply() instead of reply_text() directly. Phase 3 plugs the AI pipeline
into handle_message.
"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tracker.config import Settings, load_settings
from tracker.storage import Storage

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
HISTORY_LINE_CHARS = 64


def _is_allowed(settings: Settings, update: Update) -> bool:
    if not settings.allowed_user_ids:
        return True
    user = update.effective_user
    return user is not None and user.id in settings.allowed_user_ids


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    storage: Storage = context.bot_data["storage"]
    sent = await update.message.reply_text(text)
    storage.save_message(
        chat_id=sent.chat_id,
        user_id=context.bot.id,
        direction="out",
        text=text,
        telegram_message_id=sent.message_id,
    )


async def log_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    message = update.message
    if message is None or message.text is None or not _is_allowed(settings, update):
        return
    storage: Storage = context.bot_data["storage"]
    storage.save_message(
        chat_id=message.chat_id,
        user_id=update.effective_user.id if update.effective_user else None,
        direction="in",
        text=message.text,
        telegram_message_id=message.message_id,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    if not _is_allowed(settings, update):
        logger.warning("Ignoring /start from unauthorized user id=%s", user.id if user else "?")
        return
    await _reply(
        update,
        context,
        f"Hi {user.first_name}! I'm your tracker bot.\n\n"
        f"Your Telegram user id is {user.id} — put it in ALLOWED_USER_IDS in .env "
        "so only you can talk to me.\n\n"
        "I now remember everything you send — try /history. "
        "AI understanding lands in Phase 3.",
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not _is_allowed(settings, update):
        return
    await _reply(update, context, "pong")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not _is_allowed(settings, update):
        return
    storage: Storage = context.bot_data["storage"]
    messages = storage.recent_messages(update.message.chat_id, limit=HISTORY_LIMIT)
    if not messages:
        await _reply(update, context, "No history yet — send me something first.")
        return
    lines = []
    for m in messages:
        who = "you" if m.direction == "in" else "bot"
        stamp = m.created_at[5:16].replace("T", " ")
        text = m.text.replace("\n", " ")
        if len(text) > HISTORY_LINE_CHARS:
            text = text[: HISTORY_LINE_CHARS - 1] + "…"
        lines.append(f"{stamp} {who}: {text}")
    await _reply(update, context, f"Last {len(messages)} messages (UTC):\n" + "\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    if not _is_allowed(settings, update):
        logger.warning("Ignoring message from unauthorized user id=%s", user.id if user else "?")
        return
    text = update.message.text
    logger.info("Message from id=%s: %s", user.id, text)
    await _reply(update, context, f"Got it 👍 Saved. You said: {text}")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error while processing update: %s", update, exc_info=context.error)


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings()
    if not settings.allowed_user_ids:
        logger.warning("ALLOWED_USER_IDS is empty — the bot will answer anyone who finds it.")

    storage = Storage.connect(settings.db_path)
    logger.info("Database ready at %s", settings.db_path)

    app = Application.builder().token(settings.bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["storage"] = storage

    app.add_handler(MessageHandler(filters.TEXT, log_incoming), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(handle_error)

    logger.info("Starting bot (long polling)...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        storage.close()


if __name__ == "__main__":
    main()
