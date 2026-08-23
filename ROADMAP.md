# Roadmap

Incremental build — one feature per phase. Each phase is small, shippable, and
tested in the real Telegram chat before moving to the next.

## Phase 0 — Scaffolding ✅
Repo, package layout, config loading, `.env` handling, README.

## Phase 1 — Telegram connection ✅
- Bot connects via long polling (no server/webhook needed, runs on any machine).
- `/start` and `/ping` commands, plain acknowledgement of any text message.
- User allowlist (`ALLOWED_USER_IDS`) so only you can talk to the bot.

**Done when:** you message the bot from your phone and it replies.

## Phase 2 — Chat history & storage ✅
- SQLite database (stdlib `sqlite3`, single file under `data/`, zero setup).
  Chosen over DuckDB: this is an OLTP workload (many small inserts), DuckDB
  is an OLAP engine. All SQL isolated in `tracker/storage.py` behind a small
  `Storage` interface, so a future move to Postgres/Mongo swaps one module.
- Persist every incoming/outgoing text message with timestamp and user id.
- Versioned migrations via `PRAGMA user_version` — later phases add tables
  by appending to the `MIGRATIONS` list.
- `/history` command shows the last 20 messages.

**Done when:** restarting the bot doesn't lose history and `/history` works.
This is the foundation for AI context and all trackers.

## Phase 3 — AI brain ✅
- Connect via OpenRouter (model-agnostic; pick with `OPENROUTER_MODEL`).
- Each free-form message is classified (finance / gym / diet / note / question)
  and parsed into structured JSON (amount, exercise, meal, etc.).
- Bot replies naturally, using recent chat history as context.
- Structured output stored in the `entries` table, linked to the raw message.
- Graceful degradation: echo mode without an API key, apology reply if the
  API call fails (message still saved to history).

**Done when:** "spent 250 on lunch" gets classified as a finance entry with
amount and category extracted, and the bot confirms in natural language.

## Phase 4 — Trackers ✅ (current)
Summaries are computed from the `entries` table the AI already fills — no
separate per-tracker tables needed yet. Logic lives in `tracker/summaries.py`
as pure functions; day boundaries use local time (storage is UTC).

### 4a. Finance (revamped as its own module)
- Dedicated `expenses` table (migration v4, old JSON entries backfilled):
  kind, amount, currency, description, merchant, purpose-based category,
  tags, and `spent_at` — the day the money moved ("yesterday" works),
  separate from the logging timestamp.
- Fixed category taxonomy in `tracker/finance.py`, injected into the AI
  prompt so the model can only pick valid categories; auto-tagging with
  0-3 cross-cutting tags (trip, office...); everything validated in Python.
- `/spend` — today / week / month totals, income, category breakdown,
  recent expenses with dates and tags.

### 4b. Gym
- `/workout` — sessions this week, weekly volume (sets × reps × weight),
  last session detail.

### 4c. Diet
- `/diet` — today's meals with calories and protein/fat/carbs totals.

### 4d. Food database
- `foods` table: per-100g calories/protein/fat/carbs, taught in chat via the
  new `food_info` category ("oats: 380 kcal, 13g protein... per 100g").
- Known foods are injected into the AI prompt; when all meal items match
  with grams, totals are computed deterministically in `tracker/nutrition.py`
  (model does language, Python does math).
- `/foods` lists the stored foods.

**Done when:** each tracker logs from free-form messages and its summary
command answers correctly.

## Phase 5 — Summaries & insights
- Scheduled daily/weekly digest pushed to you (Telegram JobQueue).
- Trends: spend vs last month, workout streaks, calorie averages.

## Phase 6 — Notion sync
- Push entries into Notion databases (one database per tracker).
- One-way (bot → Notion) first; reconcile/two-way later if needed.

## Phase 7 — Nice-to-haves (pick as needed)
- Voice notes → transcription → same AI pipeline.
- Photos (meal pics, gym machine screens) via vision.
- Edit/undo last entry.
- Charts sent as images.
- Deployment: Docker + a small VPS / Raspberry Pi, switch polling → webhook.
- Database backups.
