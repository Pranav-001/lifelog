"""Phase 1: Telegram connection.

Minimal bot: connects via long polling, handles /start and /ping, and
acknowledges text messages. Later phases plug storage (Phase 2) and the AI
pipeline (Phase 3) into handle_message.
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

logger = logging.getLogger(__name__)


def _is_allowed(settings: Settings, update: Update) -> bool:
    if not settings.allowed_user_ids:
        return True
    user = update.effective_user
    return user is not None and user.id in settings.allowed_user_ids


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    if not _is_allowed(settings, update):
        logger.warning("Ignoring /start from unauthorized user id=%s", user.id if user else "?")
        return
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm your tracker bot.\n\n"
        f"Your Telegram user id is {user.id} — put it in ALLOWED_USER_IDS in .env "
        "so only you can talk to me.\n\n"
        "For now I just acknowledge messages; AI understanding lands in Phase 3."
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not _is_allowed(settings, update):
        return
    await update.message.reply_text("pong")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    if not _is_allowed(settings, update):
        logger.warning("Ignoring message from unauthorized user id=%s", user.id if user else "?")
        return
    text = update.message.text
    logger.info("Message from id=%s: %s", user.id, text)
    await update.message.reply_text(f"Got it 👍 You said: {text}")


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

    app = Application.builder().token(settings.bot_token).build()
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(handle_error)

    logger.info("Starting bot (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
