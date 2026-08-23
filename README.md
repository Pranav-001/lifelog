# Lifelog

Personal tracker for finance, gym sessions, diet and more — driven through a
Telegram chat. An AI parses free-form messages ("spent 250 on lunch",
"bench 4x8 @ 60kg") and files them into the right tracker. Notion sync later.

Built incrementally, one feature at a time — see [ROADMAP.md](ROADMAP.md).

## Current status

**Phase 1 — Telegram connection.** The bot connects via long polling, replies
to `/start` and `/ping`, and acknowledges any text message. No AI or storage yet.

## Setup

1. **Create the bot**: in Telegram, message [@BotFather](https://t.me/BotFather),
   send `/newbot`, follow the prompts, and copy the token it gives you.
2. **Configure**: copy `.env.example` to `.env` and paste the token into
   `TELEGRAM_BOT_TOKEN`.
3. **Install** (needs [uv](https://docs.astral.sh/uv/)):

   ```
   uv sync
   ```

4. **Run**:

   ```
   uv run lifelog
   ```

5. **Test**: message your bot on Telegram. `/start` replies with your Telegram
   user id — put that id into `ALLOWED_USER_IDS` in `.env` and restart so only
   you can use the bot.

## Project layout

```
tracker/
  bot.py        # Telegram handlers + entry point
  config.py     # .env loading and validation
  __main__.py   # allows `python -m tracker`
ROADMAP.md      # phased plan
.env.example    # template for local config (never commit .env)
```
