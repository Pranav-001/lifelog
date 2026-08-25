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
from datetime import datetime, timedelta, timezone

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tracker import finance
from tracker.ai import AIClient
from tracker.config import Settings, load_settings
from tracker.nutrition import enrich_diet
from tracker.storage import Entry, Storage
from tracker.summaries import diet_summary, workout_summary

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
        "I'll understand and log them.\n\n"
        "Commands: /spend, /workout, /diet, /foods, /history",
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


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


async def cmd_foods(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(context.bot_data["settings"], update):
        return
    storage: Storage = context.bot_data["storage"]
    foods = storage.list_foods(update.message.chat_id)
    if not foods:
        await _reply(
            update,
            context,
            "No foods stored yet — tell me e.g. 'oats: 380 kcal, 13g protein, "
            "7g fat, 68g carbs per 100g' and I'll remember it.",
        )
        return

    def n(value: float | None) -> str:
        return f"{value:g}" if value is not None else "?"

    lines = ["🥗 Known foods (per 100g):"]
    lines.extend(
        f"• {f.name} — {n(f.calories_per_100g)} kcal, "
        f"P {n(f.protein_per_100g)} / F {n(f.fat_per_100g)} / C {n(f.carbs_per_100g)}"
        for f in foods
    )
    await _reply(update, context, "\n".join(lines))


def _entries_for(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, category: str, lookback_days: int
) -> list[Entry]:
    storage: Storage = context.bot_data["storage"]
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return storage.entries_since(chat_id, category, since.isoformat(timespec="seconds"))


async def cmd_spend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(context.bot_data["settings"], update):
        return
    storage: Storage = context.bot_data["storage"]
    now = datetime.now().astimezone()
    since = (now.date() - timedelta(days=45)).isoformat()
    rows = storage.expenses_since(update.message.chat_id, since)
    await _reply(update, context, finance.spend_summary(rows, now))


async def cmd_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(context.bot_data["settings"], update):
        return
    entries = _entries_for(context, update.message.chat_id, "gym", lookback_days=365)
    await _reply(update, context, workout_summary(entries, datetime.now().astimezone()))


async def cmd_diet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(context.bot_data["settings"], update):
        return
    entries = _entries_for(context, update.message.chat_id, "diet", lookback_days=2)
    await _reply(update, context, diet_summary(entries, datetime.now().astimezone()))


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
    foods = storage.list_foods(chat_id)
    recent_expenses = storage.recent_expenses(chat_id, limit=10)
    try:
        result = await ai.understand(history, foods, recent_expenses)
    except httpx.HTTPStatusError as e:
        logger.exception("OpenRouter call failed")
        if e.response.status_code == 429:
            await _reply(
                update,
                context,
                "Saved your message, but OpenRouter is rate-limiting us right now. "
                "Free models allow ~20 requests/min and ~50/day — wait a bit and "
                "resend, or set a paid OPENROUTER_MODEL / add credits.",
            )
        else:
            await _reply(
                update,
                context,
                f"Saved your message, but OpenRouter returned an error "
                f"({e.response.status_code}) — it stays in history, resend later.",
            )
        return
    except Exception:
        logger.exception("OpenRouter call failed")
        await _reply(
            update,
            context,
            "Saved your message, but my AI brain is unreachable right now — "
            "it stays in history and you can resend later.",
        )
        return

    data = result.data
    if result.category == "food_info" and isinstance(data, dict):
        name = str(data.get("name") or "").strip().lower()
        if name:
            storage.upsert_food(
                chat_id=chat_id,
                name=name,
                calories_per_100g=_number(data.get("calories_per_100g")),
                protein_per_100g=_number(data.get("protein_per_100g")),
                fat_per_100g=_number(data.get("fat_per_100g")),
                carbs_per_100g=_number(data.get("carbs_per_100g")),
            )
            logger.info("Stored food info: %s", data)
    elif result.category == "diet" and isinstance(data, dict):
        data = enrich_diet(data, {f.name: f for f in foods})

    expense_line: str | None = None
    if result.category == "finance" and isinstance(data, dict):
        parsed = finance.normalize(data, datetime.now().astimezone().date())
        if parsed is not None:
            category = parsed.category
            original = None
            if parsed.kind == "refund" and parsed.refund_of is not None:
                original = storage.get_expense(chat_id, parsed.refund_of)
                if original is not None:
                    category = original.category
            storage.add_expense(
                chat_id=chat_id,
                kind=parsed.kind,
                amount=parsed.amount,
                category=category,
                spent_at=parsed.spent_at.isoformat(),
                currency=parsed.currency,
                description=parsed.description,
                merchant=parsed.merchant,
                tags=parsed.tags,
                message_id=storage.find_message_id(chat_id, update.message.message_id),
                refund_of=original.id if original is not None else None,
            )
            logger.info("Logged expense: %s", parsed)
            expense_line = finance.confirmation_line(parsed)
            if original is not None:
                expense_line += f"  (for: {original.description or original.merchant or f'expense {original.id}'})"

    if result.category is not None and data is not None and expense_line is None:
        storage.save_entry(
            chat_id=chat_id,
            category=result.category,
            data=json.dumps(data, ensure_ascii=False),
            message_id=storage.find_message_id(chat_id, update.message.message_id),
        )
        logger.info("Logged %s entry: %s", result.category, data)

    reply = result.reply
    if result.category == "diet" and isinstance(data, dict) and data.get("computed"):
        reply += (
            f"\n\n📊 {data['calories_estimate']} kcal • P {data['protein_g']}g"
            f" • F {data['fat_g']}g • C {data['carbs_g']}g (from your food data)"
        )
    if expense_line is not None:
        reply += f"\n\n🧾 {expense_line}"
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
    app.add_handler(CommandHandler("spend", cmd_spend))
    app.add_handler(CommandHandler("workout", cmd_workout))
    app.add_handler(CommandHandler("diet", cmd_diet))
    app.add_handler(CommandHandler("foods", cmd_foods))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(handle_error)

    logger.info("Starting bot (long polling)...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        storage.close()


if __name__ == "__main__":
    main()
