# Lifelog

Personal tracker for finance, gym sessions, diet and more — driven through a
Telegram chat. An AI parses free-form messages ("spent 250 on lunch",
"bench 4x8 @ 60kg") and files them into the right tracker. Notion sync later.

Built incrementally, one feature at a time — see [ROADMAP.md](ROADMAP.md).

## Current status

**Phase 2 — Chat history & storage.** Every text message in both directions is
persisted to a local SQLite file (`data/lifelog.db` by default, configurable
via `DATABASE_PATH`). `/history` shows the last 20 messages. SQLite was chosen
over DuckDB because this workload is many small writes (OLTP), not analytics;
all SQL is isolated in `tracker/storage.py` so a later move to Postgres or
MongoDB only replaces that one module. No AI yet — that's Phase 3.

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
   you can use the bot. Send a few messages, then `/history` to see them back.

## Project layout

```
tracker/
  bot.py        # Telegram handlers + entry point
  config.py     # .env loading and validation
  storage.py    # SQLite persistence (all SQL lives here)
  __main__.py   # allows `python -m tracker`
data/           # SQLite database file (gitignored, created on first run)
ROADMAP.md      # phased plan
.env.example    # template for local config (never commit .env)
```
