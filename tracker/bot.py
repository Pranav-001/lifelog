"""Phase 3: Telegram connection + chat history + AI understanding.

Incoming text is recorded once by log_incoming, which runs in handler
group -1 before any routing. Outgoing text is recorded by replying through
_reply() instead of reply_text() directly. handle_message sends recent
history to the model via OpenRouter, stores the structured entry, and sends
back the model's natural-language reply. Without OPENROUTER_API_KEY the bot
falls back to Phase 2 echo behaviour.
"""

import json
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tracker.ai import AIClient
from tracker.config import Settings, load_settings
from tracker.storage import Storage

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
HISTORY_LINE_CHARS = 64
CONTEXT_MESSAGES = 12


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
        "Tell me things like 'spent 250 on lunch' or 'bench 4x8 at 60kg' and "
        "I'll understand and log them. /history shows recent messages.",
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
    chat_id = update.message.chat_id
    logger.info("Message from id=%s: %s", user.id, text)

    ai: AIClient | None = context.bot_data.get("ai")
    if ai is None:
        await _reply(
            update,
            context,
            f"Got it 👍 Saved. You said: {text}\n\n"
            "(AI is off — set OPENROUTER_API_KEY in .env to enable understanding.)",
        )
        return

    storage: Storage = context.bot_data["storage"]
    await update.message.chat.send_action(ChatAction.TYPING)
    # recent_messages already includes this message — log_incoming ran first
    history = storage.recent_messages(chat_id, limit=CONTEXT_MESSAGES)
    try:
        result = await ai.understand(history)
    except Exception:
        logger.exception("OpenRouter call failed")
        await _reply(
            update,
            context,
            "Saved your message, but my AI brain is unreachable right now — "
            "it stays in history and you can resend later.",
        )
        return

    if result.category is not None and result.data is not None:
        storage.save_entry(
            chat_id=chat_id,
            category=result.category,
            data=json.dumps(result.data, ensure_ascii=False),
            message_id=storage.find_message_id(chat_id, update.message.message_id),
        )
        logger.info("Logged %s entry: %s", result.category, result.data)

    reply = result.reply
    if result.category is not None:
        reply = f"{reply}\n#{result.category}"
    await _reply(update, context, reply)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error while processing update: %s", update, exc_info=context.error)


async def _post_shutdown(app: Application) -> None:
    ai: AIClient | None = app.bot_data.get("ai")
    if ai is not None:
        await ai.close()


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

    ai: AIClient | None = None
    if settings.openrouter_api_key:
        ai = AIClient(settings.openrouter_api_key, settings.openrouter_model)
        logger.info("AI enabled via OpenRouter, model=%s", settings.openrouter_model)
    else:
        logger.warning("OPENROUTER_API_KEY is empty — running without AI (echo mode).")

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["storage"] = storage
    app.bot_data["ai"] = ai

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
