"""Streamlit dashboard for inspecting the lifelog SQLite database.

Read-only: opens the DB in ro mode, so it is safe to run while the bot is
live. Run with: uv run streamlit run dashboard.py
"""

import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "").strip() or "data/lifelog.db"

st.set_page_config(page_title="Lifelog dashboard", page_icon="📒", layout="wide")
st.title("Lifelog dashboard")
st.caption(f"Database: {DB_PATH} (read-only, refreshes every 10s on interaction)")

if not Path(DB_PATH).exists():
    st.warning("No database yet — run the bot and send it a message first.")
    st.stop()


@st.cache_data(ttl=10)
def load_tables(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
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
    finally:
        conn.close()
    for df in (messages, entries):
        if not df.empty:
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
            df["date"] = df["created_at"].dt.date
    return messages, entries


def parse_data(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


messages, entries = load_tables(DB_PATH)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Messages", len(messages))
c2.metric("Entries", len(entries))
c3.metric("Days tracked", messages["date"].nunique() if not messages.empty else 0)
c4.metric("Categories", entries["category"].nunique() if not entries.empty else 0)

tab_entries, tab_finance, tab_messages = st.tabs(["Entries", "Finance", "Messages"])

with tab_entries:
    if entries.empty:
        st.info("No entries yet — the AI stores one per understood message.")
    else:
        categories = sorted(entries["category"].unique())
        selected = st.multiselect("Categories", categories, default=categories)
        view = entries[entries["category"].isin(selected)]
        if not view.empty:
            st.caption("Entries per day")
            st.bar_chart(view.groupby(["date", "category"]).size().unstack(fill_value=0))
        st.dataframe(
            view[["created_at", "category", "message", "data"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_finance:
    fin = entries[entries["category"] == "finance"].copy() if not entries.empty else pd.DataFrame()
    if fin.empty:
        st.info("No finance entries yet — try telling the bot 'spent 250 on lunch'.")
    else:
        parsed = fin["data"].map(parse_data)
        fin["kind"] = parsed.map(lambda d: d.get("kind") or "expense")
        fin["amount"] = pd.to_numeric(parsed.map(lambda d: d.get("amount")), errors="coerce")
        fin["currency"] = parsed.map(lambda d: d.get("currency"))
        fin["description"] = parsed.map(lambda d: d.get("description"))
        expenses = fin[(fin["kind"] != "income") & fin["amount"].notna()]

        today = pd.Timestamp.now(tz="UTC").date()
        week_ago = today - timedelta(days=6)
        c1, c2, c3 = st.columns(3)
        c1.metric("Spent today", f"{expenses[expenses['date'] == today]['amount'].sum():,.0f}")
        c2.metric("Last 7 days", f"{expenses[expenses['date'] >= week_ago]['amount'].sum():,.0f}")
        c3.metric("All time", f"{expenses['amount'].sum():,.0f}")

        if not expenses.empty:
            st.caption("Spend per day")
            st.bar_chart(expenses.groupby("date")["amount"].sum())
        st.dataframe(
            fin[["created_at", "kind", "amount", "currency", "description", "message"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_messages:
    if messages.empty:
        st.info("No messages yet.")
    else:
        direction = st.radio("Direction", ["all", "in", "out"], horizontal=True)
        view = messages if direction == "all" else messages[messages["direction"] == direction]
        st.dataframe(
            view[["created_at", "direction", "text"]],
            use_container_width=True,
            hide_index=True,
        )
