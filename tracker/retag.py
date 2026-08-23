"""Maintenance: auto-categorize and auto-tag existing expenses.

Sends expenses that are still uncategorized (category 'other' with no tags)
to the model in one batch, validates the response against the taxonomy, and
writes back category, tags and merchant.

Run:  uv run python -m tracker.retag        (only uncategorized rows)
      uv run python -m tracker.retag --all  (re-classify everything)
"""

import asyncio
import json
import logging
import sys

from tracker.ai import AIClient, _extract_json
from tracker.config import load_settings
from tracker.finance import CATEGORIES
from tracker.storage import Storage

logger = logging.getLogger(__name__)

PROMPT = """\
You are cleaning up a personal expense database.

For each expense below, decide:
- category: exactly one of {categories}. For kind "income" use "income".
- tags: 0-3 short lowercase cross-cutting labels (e.g. "office", "trip-goa",
  "friends", "monthly") that add context beyond the category.
- merchant: the shop/service name if identifiable, else null.

Expenses:
{expenses}

Respond with ONLY this JSON, no markdown fences:
{{"expenses": [{{"id": number, "category": "...", "tags": ["..."], "merchant": "..." or null}}]}}
"""


def _clean_tags(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(t).strip().lower().replace(" ", "-") for t in raw if str(t).strip()][:3]


async def run(include_all: bool) -> None:
    settings = load_settings()
    if not settings.openrouter_api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set — the retagger needs the model.")

    storage = Storage.connect(settings.db_path)
    ai = AIClient(settings.openrouter_api_key, settings.openrouter_model)
    try:
        targets = storage.expenses_for_retag(include_all)
        if not targets:
            print("Nothing to retag — all expenses already have a category or tags.")
            return

        payload = [
            {
                "id": expense.id,
                "kind": expense.kind,
                "amount": expense.amount,
                "spent_at": expense.spent_at,
                "description": expense.description,
                "merchant": expense.merchant,
                "original_message": message,
            }
            for expense, message in targets
        ]
        prompt = PROMPT.replace("{categories}", ", ".join(CATEGORIES)).replace(
            "{expenses}", json.dumps(payload, ensure_ascii=False, indent=2)
        )
        print(f"Classifying {len(targets)} expense(s) with {settings.openrouter_model}...")
        content = await ai.complete([{"role": "user", "content": prompt}])
        results = _extract_json(content).get("expenses", [])

        by_id = {expense.id: expense for expense, _ in targets}
        updated = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            expense = by_id.get(item.get("id"))
            if expense is None:
                continue
            category = str(item.get("category") or "").strip().lower()
            if expense.kind == "income":
                category = "income"
            elif category not in CATEGORIES:
                logger.warning("Expense %s: invalid category %r, keeping %r", expense.id, category, expense.category)
                category = expense.category
            tags = _clean_tags(item.get("tags"))
            merchant = str(item.get("merchant") or "").strip() or None
            storage.update_expense_classification(
                expense.id, category=category, tags=tags, merchant=merchant
            )
            updated += 1
            tag_text = " ".join(f"#{t}" for t in tags) or "(no tags)"
            print(
                f"  id {expense.id}: {expense.category} -> {category}  {tag_text}"
                + (f"  merchant: {merchant}" if merchant else "")
                + f"  | {expense.description or ''}"
            )
        print(f"Updated {updated} of {len(targets)} expense(s).")
    finally:
        await ai.close()
        storage.close()


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run("--all" in sys.argv[1:]))


if __name__ == "__main__":
    main()
