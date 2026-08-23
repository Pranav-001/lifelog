# Roadmap

Incremental build — one feature per phase. Each phase is small, shippable, and
tested in the real Telegram chat before moving to the next.

## Phase 0 — Scaffolding ✅
Repo, package layout, config loading, `.env` handling, README.

## Phase 1 — Telegram connection ✅ (current)
- Bot connects via long polling (no server/webhook needed, runs on any machine).
- `/start` and `/ping` commands, plain acknowledgement of any text message.
- User allowlist (`ALLOWED_USER_IDS`) so only you can talk to the bot.

**Done when:** you message the bot from your phone and it replies.

## Phase 2 — Chat history & storage
- SQLite database (single file, zero setup).
- Persist every incoming/outgoing message with timestamp and user id.
- `/history` command to show recent messages.

**Done when:** restarting the bot doesn't lose history and `/history` works.
This is the foundation for AI context and all trackers.

## Phase 3 — AI brain
- Connect to the Claude API.
- Each free-form message is classified (finance / gym / diet / note / question)
  and parsed into structured JSON (amount, exercise, meal, etc.).
- Bot replies naturally, using recent chat history as context.
- Structured output stored alongside the raw message.

**Done when:** "spent 250 on lunch" gets classified as a finance entry with
amount and category extracted, and the bot confirms in natural language.

## Phase 4 — Trackers (one at a time)
### 4a. Finance
- Expense/income entries table, categories.
- `/spend` — today / this week / this month summary.

### 4b. Gym
- Training sessions: exercises, sets, reps, weight.
- `/workout` — last session, weekly volume.

### 4c. Diet
- Meals with rough calorie/macro estimates from the AI.
- `/diet` — today's intake summary.

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
