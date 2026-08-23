# Lifelog

Personal tracker for finance, gym sessions, diet and more — driven through a
Telegram chat. An AI parses free-form messages ("spent 250 on lunch",
"bench 4x8 @ 60kg") and files them into the right tracker. Notion sync later.

Built incrementally, one feature at a time — see [ROADMAP.md](ROADMAP.md).

## Current status

**Phase 4 — Trackers.** Free-form messages ("spent 250 on lunch",
"bench 4x8 at 60kg") are understood by a model via
[OpenRouter](https://openrouter.ai) (any model, set `OPENROUTER_MODEL`),
classified, and stored as structured entries in SQLite. Summary commands:

- `/spend` — today / week / month totals, category breakdown, recent expenses
- `/workout` — sessions this week, weekly volume, last session detail
- `/diet` — today's meals, estimated calories, protein/fat/carbs
- `/foods` — your personal food database (per-100g macros)
- `/history` — last 20 raw messages

Teach the bot foods ("oats: 380 kcal, 13g protein, 7g fat, 68g carbs per
100g") and it stores them; when a meal mentions known foods with weights,
calories and macros are computed exactly in Python from your data instead
of the model guessing.

Day boundaries use the machine's local timezone. Without
`OPENROUTER_API_KEY` the bot still runs in echo mode.

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
  finance.py    # expense categories, auto-tag validation, /spend text
  summaries.py  # pure functions: /workout, /diet text
  nutrition.py  # deterministic calorie/macro math from the foods table
  __main__.py   # allows `python -m tracker`
dashboard.py    # Streamlit dashboard over the SQLite data (read-only)
data/           # SQLite database file (gitignored, created on first run)
ROADMAP.md      # phased plan
.env.example    # template for local config (never commit .env)
```
