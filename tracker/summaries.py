"""Phase 4: tracker summaries computed from stored entries.

Pure functions: they take entries plus 'now' and return reply text, so they
are unit-testable without Telegram or the database. Day boundaries use the
timezone carried by 'now' (the bot passes local time); created_at is UTC.
"""

import json
from datetime import date, datetime, timedelta

from tracker.storage import Entry


def _data(entry: Entry) -> dict:
    try:
        parsed = json.loads(entry.data)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def _local_date(entry: Entry, now: datetime) -> date:
    return datetime.fromisoformat(entry.created_at).astimezone(now.tzinfo).date()


def spend_summary(entries: list[Entry], now: datetime) -> str:
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    expenses: list[tuple[date, float, str]] = []
    income_this_month = 0.0
    for entry in entries:
        data = _data(entry)
        amount = data.get("amount")
        if not isinstance(amount, (int, float)):
            continue
        day = _local_date(entry, now)
        if data.get("kind") == "income":
            if day >= month_start:
                income_this_month += amount
            continue
        expenses.append((day, float(amount), str(data.get("description") or "?")))

    if not expenses and not income_this_month:
        return "No finance entries yet — tell me things like 'spent 250 on lunch'."

    def total(since: date) -> float:
        return sum(amount for day, amount, _ in expenses if day >= since)

    lines = [
        "💸 Spending",
        f"Today: {total(today):,.0f}",
        f"This week: {total(week_start):,.0f}",
        f"This month: {total(month_start):,.0f}",
    ]
    if income_this_month:
        lines.append(f"Income this month: {income_this_month:,.0f}")
    recent = [x for x in expenses if x[0] >= today - timedelta(days=6)][-5:]
    if recent:
        lines.append("")
        lines.append("Recent:")
        lines.extend(
            f"• {day.strftime('%d %b')} — {amount:,.0f} {desc}"
            for day, amount, desc in recent
        )
    return "\n".join(lines)


def workout_summary(entries: list[Entry], now: datetime) -> str:
    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    sessions: dict[date, list[dict]] = {}
    for entry in entries:
        data = _data(entry)
        exercises = data.get("exercises")
        if not isinstance(exercises, list):
            continue
        day = _local_date(entry, now)
        sessions.setdefault(day, []).extend(x for x in exercises if isinstance(x, dict))

    if not sessions:
        return "No gym entries yet — tell me things like 'bench 4x8 at 60kg'."

    week_days = [d for d in sessions if d >= week_start]
    volume = 0.0
    for day in week_days:
        for x in sessions[day]:
            sets, reps, weight = x.get("sets"), x.get("reps"), x.get("weight_kg")
            if all(isinstance(v, (int, float)) for v in (sets, reps, weight)):
                volume += sets * reps * weight

    def fmt(x: dict) -> str:
        name = x.get("name") or "exercise"
        parts = []
        sets, reps, weight = x.get("sets"), x.get("reps"), x.get("weight_kg")
        if sets and reps:
            parts.append(f"{sets}x{reps}")
        elif reps:
            parts.append(f"{reps} reps")
        if weight:
            parts.append(f"@ {weight}kg")
        return f"• {name}" + (f" — {' '.join(parts)}" if parts else "")

    last_day = max(sessions)
    lines = ["🏋️ Gym", f"Sessions this week: {len(week_days)}"]
    if volume:
        lines.append(f"Weekly volume: {volume:,.0f} kg (sets × reps × weight)")
    lines.append("")
    lines.append(f"Last session ({last_day.strftime('%d %b')}):")
    lines.extend(fmt(x) for x in sessions[last_day])
    return "\n".join(lines)


def _item_label(item) -> str:
    if isinstance(item, dict):
        name = str(item.get("name") or "food")
        grams = item.get("grams")
        if isinstance(grams, (int, float)):
            return f"{name} ({grams:g}g)"
        return name
    return str(item)


def diet_summary(entries: list[Entry], now: datetime) -> str:
    today = now.date()
    meals: list[tuple[str, list[str]]] = []
    calories = protein = fat = carbs = 0.0
    has_calories = has_macros = False
    for entry in entries:
        if _local_date(entry, now) != today:
            continue
        data = _data(entry)
        items = data.get("items")
        labels = [_item_label(i) for i in items] if isinstance(items, list) else []
        meals.append((str(data.get("meal") or "meal"), labels))
        if isinstance(data.get("calories_estimate"), (int, float)):
            calories += data["calories_estimate"]
            has_calories = True
        p, ft, cb = (data.get(k) for k in ("protein_g", "fat_g", "carbs_g"))
        if isinstance(p, (int, float)):
            protein += p
            has_macros = True
        if isinstance(ft, (int, float)):
            fat += ft
            has_macros = True
        if isinstance(cb, (int, float)):
            carbs += cb
            has_macros = True

    if not meals:
        return "No diet entries today — tell me what you ate!"

    lines = ["🍽️ Today's food"]
    lines.extend(f"• {meal}: {', '.join(items) if items else '—'}" for meal, items in meals)
    if has_calories or has_macros:
        lines.append("")
    if has_calories:
        lines.append(f"Estimated calories: {calories:,.0f} kcal")
    if has_macros:
        lines.append(f"Protein {protein:,.0f}g • Fat {fat:,.0f}g • Carbs {carbs:,.0f}g")
    return "\n".join(lines)
