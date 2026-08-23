"""Streamlit dashboard for the lifelog SQLite database.

Charts read via a read-only connection; the Edit tab writes back (updates,
inserts, deletes) in short transactions with a busy timeout, so it is safe
to run while the bot is live (WAL: many readers + one writer).
Run with: uv run streamlit run dashboard.py
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from tracker.finance import CATEGORIES as EXPENSE_CATEGORIES

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "").strip() or "data/lifelog.db"
CATEGORIES = ["finance", "gym", "diet", "food_info", "note", "question", "other"]
EXPENSE_CATEGORY_OPTIONS = EXPENSE_CATEGORIES + ["income"]

st.set_page_config(page_title="Lifelog dashboard", page_icon="📒", layout="wide")
st.title("Lifelog dashboard")

if not Path(DB_PATH).exists():
    st.warning("No database yet — run the bot and send it a message first.")
    st.stop()


@st.cache_data(ttl=10)
def load_tables(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        messages = pd.read_sql_query(
            "SELECT id, chat_id, user_id, direction, text, created_at"
            " FROM messages ORDER BY id DESC",
            conn,
        )
        entries = pd.read_sql_query(
            "SELECT e.id, e.chat_id, e.category, e.data, e.created_at,"
            " m.text AS message"
            " FROM entries e LEFT JOIN messages m ON m.id = e.message_id"
            " ORDER BY e.id DESC",
            conn,
        )
        foods = pd.read_sql_query(
            "SELECT id, chat_id, name, calories_per_100g, protein_per_100g,"
            " fat_per_100g, carbs_per_100g FROM foods ORDER BY name",
            conn,
        )
        expenses = pd.read_sql_query(
            "SELECT id, chat_id, kind, amount, currency, description, merchant,"
            " category, tags, spent_at FROM expenses ORDER BY spent_at DESC, id DESC",
            conn,
        )
    finally:
        conn.close()
    for df in (messages, entries):
        if not df.empty:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
            df["date"] = df["created_at"].dt.tz_convert(LOCAL_TZ).dt.date
    if not expenses.empty:
        expenses["spent_at"] = pd.to_datetime(expenses["spent_at"]).dt.date
    return messages, entries, foods, expenses


def write_many(statements: list[tuple[str, tuple]]) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout = 3000")
        with conn:
            for sql, params in statements:
                conn.execute(sql, params)
    finally:
        conn.close()


def parse_json(raw) -> dict:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def num(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def opt(value):
    return None if value is None or pd.isna(value) else float(value)


LOCAL_TZ = datetime.now().astimezone().tzinfo
TODAY = datetime.now(LOCAL_TZ).date()

messages, entries, foods, expenses = load_tables(DB_PATH)

with st.sidebar:
    st.caption(f"Database: {DB_PATH}")
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Messages", len(messages))
c2.metric("Entries", len(entries))
c3.metric("Known foods", len(foods))
c4.metric("Days tracked", messages["date"].nunique() if not messages.empty else 0)

tab_overview, tab_finance, tab_nutrition, tab_gym, tab_edit = st.tabs(
    ["Overview", "Finance", "Nutrition", "Gym", "Edit"]
)

with tab_overview:
    if entries.empty:
        st.info("No entries yet — the AI stores one per understood message.")
    else:
        chart_df = entries.copy()
        chart_df["date"] = pd.to_datetime(chart_df["date"])
        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("count():Q", title="entries"),
                color=alt.Color("category:N", title=None),
                tooltip=["date:T", "category:N", "count():Q"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption("Latest entries")
        st.dataframe(
            entries[["created_at", "category", "message", "data"]].head(15),
            use_container_width=True,
            hide_index=True,
        )

with tab_finance:
    if expenses.empty:
        st.info("No expenses yet — try telling the bot 'spent 250 on lunch'.")
    else:
        exp = expenses[expenses["kind"] != "income"].copy()
        exp["date"] = exp["spent_at"]

        def spent(day_from, day_to=None):
            sel = exp[exp["date"] >= day_from]
            if day_to is not None:
                sel = sel[sel["date"] <= day_to]
            return sel["amount"].sum()

        yesterday = TODAY - timedelta(days=1)
        month_start = TODAY.replace(day=1)
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Spent today",
            f"{spent(TODAY):,.0f}",
            delta=f"{spent(TODAY) - spent(yesterday, yesterday):+,.0f} vs yesterday",
            delta_color="inverse",
        )
        c2.metric("Last 7 days", f"{spent(TODAY - timedelta(days=6)):,.0f}")
        c3.metric("This month", f"{spent(month_start):,.0f}")

        month = exp[exp["date"] >= month_start]
        if not month.empty:
            daily = month.groupby("date", as_index=False)["amount"].sum()
            daily["date"] = pd.to_datetime(daily["date"])
            daily = daily.sort_values("date")
            daily["cumulative"] = daily["amount"].cumsum()
            bars = (
                alt.Chart(daily)
                .mark_bar(color="#4c78a8")
                .encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y("amount:Q", title="daily spend"),
                    tooltip=["date:T", "amount:Q"],
                )
            )
            line = (
                alt.Chart(daily)
                .mark_line(point=True, color="#e45756")
                .encode(
                    x="date:T",
                    y=alt.Y("cumulative:Q", title="cumulative"),
                    tooltip=["date:T", "cumulative:Q"],
                )
            )
            st.caption("This month: daily spend (bars) and cumulative (line)")
            st.altair_chart(
                alt.layer(bars, line).resolve_scale(y="independent").properties(height=280),
                use_container_width=True,
            )
            by_cat = (
                month.groupby("category", as_index=False)["amount"]
                .sum()
                .sort_values("amount", ascending=False)
            )
            cat_chart = (
                alt.Chart(by_cat)
                .mark_bar(color="#4c78a8")
                .encode(
                    x=alt.X("amount:Q", title="spend"),
                    y=alt.Y("category:N", sort="-x", title=None),
                    tooltip=["category:N", "amount:Q"],
                )
                .properties(height=220, title="This month by category")
            )
            st.altair_chart(cat_chart, use_container_width=True)
        st.dataframe(
            expenses[["spent_at", "kind", "amount", "category", "tags", "description", "merchant"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_nutrition:
    diet = entries[entries["category"] == "diet"].copy() if not entries.empty else pd.DataFrame()
    if diet.empty:
        st.info("No diet entries yet — tell the bot what you ate.")
    else:
        parsed = diet["data"].map(parse_json)
        for col, key in [
            ("calories", "calories_estimate"),
            ("protein", "protein_g"),
            ("fat", "fat_g"),
            ("carbs", "carbs_g"),
        ]:
            diet[col] = parsed.map(lambda d, k=key: num(d.get(k)))

        today_df = diet[diet["date"] == TODAY]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Calories today", f"{today_df['calories'].sum():,.0f} kcal")
        c2.metric("Protein", f"{today_df['protein'].sum():,.0f} g")
        c3.metric("Fat", f"{today_df['fat'].sum():,.0f} g")
        c4.metric("Carbs", f"{today_df['carbs'].sum():,.0f} g")

        recent = diet[diet["date"] >= TODAY - timedelta(days=13)]
        if not recent.empty:
            daily = recent.groupby("date", as_index=False)[
                ["calories", "protein", "fat", "carbs"]
            ].sum()
            daily["date"] = pd.to_datetime(daily["date"])
            cal_chart = (
                alt.Chart(daily)
                .mark_bar(color="#f58518")
                .encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y("calories:Q", title="kcal"),
                    tooltip=["date:T", "calories:Q"],
                )
                .properties(height=220, title="Calories per day (last 14 days)")
            )
            macros = daily.melt(
                id_vars="date",
                value_vars=["protein", "fat", "carbs"],
                var_name="macro",
                value_name="grams",
            )
            macro_chart = (
                alt.Chart(macros)
                .mark_bar()
                .encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y("grams:Q", title="g"),
                    color=alt.Color("macro:N", title=None),
                    tooltip=["date:T", "macro:N", "grams:Q"],
                )
                .properties(height=220, title="Macros per day")
            )
            col_a, col_b = st.columns(2)
            col_a.altair_chart(cal_chart, use_container_width=True)
            col_b.altair_chart(macro_chart, use_container_width=True)
        st.dataframe(
            diet[["created_at", "message", "calories", "protein", "fat", "carbs", "data"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_gym:
    gym = entries[entries["category"] == "gym"].copy() if not entries.empty else pd.DataFrame()
    if gym.empty:
        st.info("No gym entries yet — tell the bot 'bench 4x8 at 60kg'.")
    else:
        rows = []
        for _, r in gym.iterrows():
            for x in parse_json(r["data"]).get("exercises") or []:
                if isinstance(x, dict):
                    sets, reps, weight = (num(x.get(k)) for k in ("sets", "reps", "weight_kg"))
                    rows.append(
                        {
                            "date": r["date"],
                            "exercise": str(x.get("name") or "exercise"),
                            "volume": sets * reps * weight,
                        }
                    )
        ex = pd.DataFrame(rows)
        week_start = TODAY - timedelta(days=TODAY.weekday())
        c1, c2 = st.columns(2)
        c1.metric("Sessions this week", ex[ex["date"] >= week_start]["date"].nunique())
        c2.metric("Volume this week", f"{ex[ex['date'] >= week_start]['volume'].sum():,.0f} kg")

        daily = ex.groupby("date", as_index=False)["volume"].sum()
        daily["date"] = pd.to_datetime(daily["date"])
        vol_chart = (
            alt.Chart(daily)
            .mark_bar(color="#54a24b")
            .encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("volume:Q", title="kg"),
                tooltip=["date:T", "volume:Q"],
            )
            .properties(height=220, title="Training volume per day")
        )
        freq = ex.groupby("exercise", as_index=False).size().sort_values("size", ascending=False)
        freq_chart = (
            alt.Chart(freq.head(12))
            .mark_bar(color="#72b7b2")
            .encode(
                x=alt.X("size:Q", title="times logged"),
                y=alt.Y("exercise:N", sort="-x", title=None),
                tooltip=["exercise:N", "size:Q"],
            )
            .properties(height=220, title="Most logged exercises")
        )
        col_a, col_b = st.columns(2)
        col_a.altair_chart(vol_chart, use_container_width=True)
        col_b.altair_chart(freq_chart, use_container_width=True)
        st.dataframe(
            gym[["created_at", "message", "data"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_edit:
    st.caption(
        "Edit cells, tick delete, then press the save button of that section. "
        "Changes write straight to the SQLite file."
    )

    st.subheader("Entries")
    if entries.empty:
        st.info("Nothing to edit yet.")
    else:
        entry_grid = entries[["id", "created_at", "category", "data", "message"]].head(200).copy()
        entry_grid.insert(0, "delete", False)
        edited_entries = st.data_editor(
            entry_grid,
            column_config={
                "delete": st.column_config.CheckboxColumn("delete"),
                "category": st.column_config.SelectboxColumn("category", options=CATEGORIES),
                "data": st.column_config.TextColumn("data (JSON)", width="large"),
            },
            disabled=["id", "created_at", "message"],
            hide_index=True,
            key="entries_editor",
        )
        if st.button("💾 Save entry changes"):
            original = entry_grid.set_index("id")
            statements, errors = [], []
            for _, row in edited_entries.iterrows():
                rid = int(row["id"])
                if row["delete"]:
                    statements.append(("DELETE FROM entries WHERE id = ?", (rid,)))
                    continue
                before = original.loc[rid]
                if row["category"] != before["category"] or row["data"] != before["data"]:
                    try:
                        json.loads(row["data"])
                    except (TypeError, ValueError):
                        errors.append(f"Entry {rid}: data is not valid JSON — skipped.")
                        continue
                    statements.append(
                        (
                            "UPDATE entries SET category = ?, data = ? WHERE id = ?",
                            (row["category"], row["data"], rid),
                        )
                    )
            for message in errors:
                st.error(message)
            if statements:
                write_many(statements)
                st.success(f"Applied {len(statements)} change(s).")
                st.cache_data.clear()
                st.rerun()
            elif not errors:
                st.info("No changes to save.")

    st.subheader("Expenses")
    if expenses.empty:
        st.info("No expenses yet.")
    else:
        exp_grid = expenses[
            ["id", "spent_at", "kind", "amount", "category", "tags", "description", "merchant"]
        ].head(200).copy()
        exp_grid.insert(0, "delete", False)
        edited_exp = st.data_editor(
            exp_grid,
            column_config={
                "delete": st.column_config.CheckboxColumn("delete"),
                "spent_at": st.column_config.DateColumn("spent on"),
                "kind": st.column_config.SelectboxColumn("kind", options=["expense", "income"]),
                "amount": st.column_config.NumberColumn("amount", min_value=0.0),
                "category": st.column_config.SelectboxColumn(
                    "category", options=EXPENSE_CATEGORY_OPTIONS
                ),
                "tags": st.column_config.TextColumn('tags (JSON, e.g. ["office"])'),
            },
            disabled=["id"],
            hide_index=True,
            key="expenses_editor",
        )
        if st.button("💾 Save expense changes"):
            original = exp_grid.set_index("id")
            statements, errors = [], []
            editable = ["spent_at", "kind", "amount", "category", "tags", "description", "merchant"]
            for _, row in edited_exp.iterrows():
                rid = int(row["id"])
                if row["delete"]:
                    statements.append(("DELETE FROM expenses WHERE id = ?", (rid,)))
                    continue
                before = original.loc[rid]
                if all(row[c] == before[c] for c in editable):
                    continue
                try:
                    tags = json.loads(row["tags"] or "[]")
                    assert isinstance(tags, list)
                except (TypeError, ValueError, AssertionError):
                    errors.append(f"Expense {rid}: tags must be a JSON list — skipped.")
                    continue
                if pd.isna(row["amount"]) or row["amount"] <= 0:
                    errors.append(f"Expense {rid}: amount must be positive — skipped.")
                    continue
                statements.append(
                    (
                        "UPDATE expenses SET spent_at = ?, kind = ?, amount = ?,"
                        " category = ?, tags = ?, description = ?, merchant = ?"
                        " WHERE id = ?",
                        (
                            str(row["spent_at"]),
                            row["kind"],
                            float(row["amount"]),
                            row["category"],
                            json.dumps([str(t) for t in tags]),
                            row["description"] or None,
                            row["merchant"] or None,
                            rid,
                        ),
                    )
                )
            for message in errors:
                st.error(message)
            if statements:
                write_many(statements)
                st.success(f"Applied {len(statements)} change(s).")
                st.cache_data.clear()
                st.rerun()
            elif not errors:
                st.info("No changes to save.")

    st.subheader("Foods")
    chat_ids = sorted(
        set(messages["chat_id"].tolist()) | set(foods["chat_id"].tolist())
    ) or [0]
    default_chat = st.selectbox("chat_id for new foods", chat_ids)
    foods_grid = foods.copy()
    edited_foods = st.data_editor(
        foods_grid,
        num_rows="dynamic",
        disabled=["id", "chat_id"],
        hide_index=True,
        key="foods_editor",
    )
    if st.button("💾 Save food changes"):
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        statements = []
        kept_ids = set()
        for _, row in edited_foods.iterrows():
            name = str(row["name"] or "").strip().lower()
            values = (
                opt(row["calories_per_100g"]),
                opt(row["protein_per_100g"]),
                opt(row["fat_per_100g"]),
                opt(row["carbs_per_100g"]),
            )
            if pd.isna(row["id"]):
                if name:
                    statements.append(
                        (
                            "INSERT INTO foods (chat_id, name, calories_per_100g,"
                            " protein_per_100g, fat_per_100g, carbs_per_100g,"
                            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                            " ON CONFLICT(chat_id, name) DO UPDATE SET"
                            " calories_per_100g = excluded.calories_per_100g,"
                            " protein_per_100g = excluded.protein_per_100g,"
                            " fat_per_100g = excluded.fat_per_100g,"
                            " carbs_per_100g = excluded.carbs_per_100g,"
                            " updated_at = excluded.updated_at",
                            (default_chat, name, *values, now_iso, now_iso),
                        )
                    )
            else:
                rid = int(row["id"])
                kept_ids.add(rid)
                statements.append(
                    (
                        "UPDATE foods SET name = ?, calories_per_100g = ?,"
                        " protein_per_100g = ?, fat_per_100g = ?, carbs_per_100g = ?,"
                        " updated_at = ? WHERE id = ?",
                        (name, *values, now_iso, rid),
                    )
                )
        for rid in set(foods_grid["id"].astype(int)) - kept_ids:
            statements.append(("DELETE FROM foods WHERE id = ?", (rid,)))
        if statements:
            write_many(statements)
            st.success(f"Applied {len(statements)} change(s).")
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("No changes to save.")

    st.subheader("Messages")
    if messages.empty:
        st.info("Nothing to edit yet.")
    else:
        msg_grid = messages[["id", "created_at", "direction", "text"]].head(200).copy()
        msg_grid.insert(0, "delete", False)
        edited_msgs = st.data_editor(
            msg_grid,
            column_config={
                "delete": st.column_config.CheckboxColumn("delete"),
                "text": st.column_config.TextColumn("text", width="large"),
            },
            disabled=["id", "created_at", "direction"],
            hide_index=True,
            key="messages_editor",
        )
        if st.button("💾 Save message changes"):
            original = msg_grid.set_index("id")
            statements = []
            for _, row in edited_msgs.iterrows():
                rid = int(row["id"])
                if row["delete"]:
                    statements.append(("DELETE FROM messages WHERE id = ?", (rid,)))
                elif row["text"] != original.loc[rid, "text"]:
                    statements.append(
                        ("UPDATE messages SET text = ? WHERE id = ?", (row["text"], rid))
                    )
            if statements:
                write_many(statements)
                st.success(f"Applied {len(statements)} change(s).")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No changes to save.")
