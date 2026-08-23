# Lifelog

Personal tracker for finance, gym sessions, diet and more — driven through a
Telegram chat. An AI parses free-form messages ("spent 250 on lunch",
"bench 4x8 @ 60kg") and files them into the right tracker. Notion sync later.

Built incrementally, one feature at a time — see [ROADMAP.md](ROADMAP.md).

## Current status

**Phase 3 — AI brain.** Free-form messages ("spent 250 on lunch",
"bench 4x8 at 60kg") are sent with recent chat history to a model via
[OpenRouter](https://openrouter.ai) (any model, set `OPENROUTER_MODEL`).
The model classifies the message (finance / gym / diet / note / question),
extracts structured JSON into the `entries` table, and writes the reply the
bot sends back, tagged with `#category`. Without `OPENROUTER_API_KEY` the bot
still runs in echo mode. Storage is SQLite (`data/lifelog.db`), all SQL
isolated in `tracker/storage.py`; `/history` shows the last 20 messages.

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

## Data dashboard

A read-only Streamlit dashboard for browsing everything the bot has stored —
metrics, entries by category, finance spend charts, and the raw message log:

```
uv run streamlit run dashboard.py
```

Opens at http://localhost:8501. Safe to run while the bot is running (the
database is opened in read-only mode).

## Project layout

```
tracker/
  bot.py        # Telegram handlers + entry point
  config.py     # .env loading and validation
  storage.py    # SQLite persistence (all SQL lives here)
  ai.py         # OpenRouter client: classify + extract + reply
  __main__.py   # allows `python -m tracker`
dashboard.py    # Streamlit dashboard over the SQLite data (read-only)
data/           # SQLite database file (gitignored, created on first run)
ROADMAP.md      # phased plan
.env.example    # template for local config (never commit .env)
```
