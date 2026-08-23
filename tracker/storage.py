"""Phase 2: SQLite persistence for chat history.

All SQL lives in this module, behind the Storage class. If we outgrow SQLite
(Postgres, Mongo), this is the only file to replace.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Append-only list of schema scripts. PRAGMA user_version tracks how many have
# been applied, so old databases upgrade automatically on connect.
MIGRATIONS = [
    """
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER,
        direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
        text TEXT NOT NULL,
        telegram_message_id INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_messages_chat ON messages (chat_id, id);
    """,
    """
    CREATE TABLE entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER REFERENCES messages(id),
        chat_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_entries_chat_cat ON entries (chat_id, category, id);
    """,
]


@dataclass(frozen=True)
class Message:
    id: int
    chat_id: int
    user_id: int | None
    direction: str
    text: str
    telegram_message_id: int | None
    created_at: str


class Storage:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @classmethod
    def connect(cls, db_path: str) -> "Storage":
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        storage = cls(conn)
        storage._migrate()
        return storage

    def _migrate(self) -> None:
        (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self._conn.executescript(script)
            self._conn.execute(f"PRAGMA user_version = {number}")
            self._conn.commit()

    def save_message(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        direction: str,
        text: str,
        telegram_message_id: int | None = None,
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO messages"
                " (chat_id, user_id, direction, text, telegram_message_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, direction, text, telegram_message_id, created_at),
            )
        return cursor.lastrowid

    def find_message_id(self, chat_id: int, telegram_message_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM messages WHERE chat_id = ? AND telegram_message_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (chat_id, telegram_message_id),
        ).fetchone()
        return row["id"] if row else None

    def save_entry(
        self,
        *,
        chat_id: int,
        category: str,
        data: str,
        message_id: int | None = None,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute(
                "INSERT INTO entries (message_id, chat_id, category, data, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (message_id, chat_id, category, data, created_at),
            )

    def recent_messages(self, chat_id: int, limit: int = 10) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [
            Message(
                id=row["id"],
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                direction=row["direction"],
                text=row["text"],
                telegram_message_id=row["telegram_message_id"],
                created_at=row["created_at"],
            )
            for row in reversed(rows)
        ]

    def close(self) -> None:
        self._conn.close()
