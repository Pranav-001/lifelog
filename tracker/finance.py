"""Finance tracking module.

Design notes (from common tracker practice):
- Categories are purpose-based and deliberately coarse — one per expense.
- Tags are the cross-cutting second layer (trip-goa, office, family).
- The model proposes category/tags/date; this module validates everything.
- spent_at is the local day the money moved, not the logging timestamp.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from tracker.storage import Expense

CATEGORIES = [
    "groceries",
    "dining",
    "transport",
    "housing",
    "utilities",
    "subscriptions",
    "health",
    "fitness",
    "shopping",
    "entertainment",
    "travel",
    "education",
    "personal-care",
    "gifts",
    "fees",
    "other",
]


@dataclass(frozen=True)
class ParsedExpense:
    kind: str
    amount: float
    currency: str | None
    description: str | None
    merchant: str | None
    category: str
    tags: list[str]
    spent_at: date


def normalize(data: dict, today: date) -> ParsedExpense | None:
    amount = data.get("amount")
    if not isinstance(amount, (int, float)) or amount <= 0:
        return None

    kind = data.get("kind") if data.get("kind") in ("expense", "income") else "expense"

    category = str(data.get("category") or "").strip().lower()
    if kind == "income":
        category = "income"
    elif category not in CATEGORIES:
        category = "other"

    raw_tags = data.get("tags")
    tags = []
    if isinstance(raw_tags, list):
        tags = [str(t).strip().lower().replace(" ", "-") for t in raw_tags if str(t).strip()][:3]

    spent_at = today
    raw_date = data.get("date")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            parsed = date.fromisoformat(raw_date.strip())
            if parsed <= today:  # models occasionally hallucinate future dates
                spent_at = parsed
        except ValueError:
            pass

    def text(key: str) -> str | None:
        value = str(data.get(key) or "").strip()
        return value or None

    return ParsedExpense(
        kind=kind,
        amount=float(amount),
        currency=text("currency"),
        description=text("description"),
        merchant=text("merchant"),
        category=category,
        tags=tags,
        spent_at=spent_at,
    )


def confirmation_line(e: ParsedExpense) -> str:
    amount = f"{e.amount:,.0f}" + (f" {e.currency}" if e.currency else "")
    line = " • ".join([amount, e.category, e.spent_at.strftime("%d %b")])
    if e.tags:
        line += "  " + " ".join(f"#{t}" for t in e.tags)
    return line


def _tags_of(row: Expense) -> list[str]:
    try:
        tags = json.loads(row.tags)
        return [str(t) for t in tags] if isinstance(tags, list) else []
    except (TypeError, ValueError):
        return []


def spend_summary(rows: list[Expense], now: datetime) -> str:
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    expenses: list[tuple[date, Expense]] = []
    income_this_month = 0.0
    for row in rows:
        try:
            day = date.fromisoformat(row.spent_at)
        except (TypeError, ValueError):
            continue
        if row.kind == "income":
            if day >= month_start:
                income_this_month += row.amount
            continue
        expenses.append((day, row))

    if not expenses and not income_this_month:
        return "No expenses logged yet — tell me things like 'spent 250 on lunch yesterday'."

    def total(since: date) -> float:
        return sum(row.amount for day, row in expenses if day >= since)

    lines = [
        "💸 Spending",
        f"Today: {total(today):,.0f}",
        f"This week: {total(week_start):,.0f}",
        f"This month: {total(month_start):,.0f}",
    ]
    if income_this_month:
        lines.append(f"Income this month: {income_this_month:,.0f}")

    by_category: dict[str, float] = {}
    for day, row in expenses:
        if day >= month_start:
            by_category[row.category] = by_category.get(row.category, 0.0) + row.amount
    if by_category:
        lines.append("")
        lines.append("By category (this month):")
        for category, amount in sorted(by_category.items(), key=lambda kv: -kv[1])[:6]:
            lines.append(f"• {category} — {amount:,.0f}")

    recent = sorted(expenses, key=lambda pair: (pair[0], pair[1].id))[-5:]
    if recent:
        lines.append("")
        lines.append("Recent:")
        for day, row in recent:
            what = row.description or row.merchant or ""
            tags = "".join(f" #{t}" for t in _tags_of(row))
            lines.append(
                f"• {day.strftime('%d %b')} — {row.amount:,.0f} {what} ({row.category}){tags}"
            )
    return "\n".join(lines)
