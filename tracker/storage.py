"""Phase 2: SQLite persistence for chat history.

All SQL lives in this module, behind the Storage class. If we outgrow SQLite
(Postgres, Mongo), this is the only file to replace.
"""

import json
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
    """
    CREATE TABLE foods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        calories_per_100g REAL,
        protein_per_100g REAL,
        fat_per_100g REAL,
        carbs_per_100g REAL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX idx_foods_chat_name ON foods (chat_id, name);
    """,
    """
    CREATE TABLE expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        message_id INTEGER REFERENCES messages(id),
        kind TEXT NOT NULL DEFAULT 'expense' CHECK (kind IN ('expense', 'income')),
        amount REAL NOT NULL,
        currency TEXT,
        description TEXT,
        merchant TEXT,
        category TEXT NOT NULL DEFAULT 'other',
        tags TEXT NOT NULL DEFAULT '[]',
        spent_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_expenses_chat_date ON expenses (chat_id, spent_at, id);
    INSERT INTO expenses (chat_id, message_id, kind, amount, currency,
                          description, category, tags, spent_at, created_at)
    SELECT
        chat_id,
        message_id,
        CASE WHEN json_extract(data, '$.kind') IN ('expense', 'income')
             THEN json_extract(data, '$.kind') ELSE 'expense' END,
        CAST(json_extract(data, '$.amount') AS REAL),
        json_extract(data, '$.currency'),
        json_extract(data, '$.description'),
        CASE WHEN json_extract(data, '$.kind') = 'income'
             THEN 'income' ELSE 'other' END,
        '[]',
        substr(created_at, 1, 10),
        created_at
    FROM entries
    WHERE category = 'finance'
      AND CAST(json_extract(data, '$.amount') AS REAL) > 0;
    """,
    """
    CREATE TABLE expenses_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        message_id INTEGER REFERENCES messages(id),
        kind TEXT NOT NULL DEFAULT 'expense'
            CHECK (kind IN ('expense', 'income', 'refund')),
        amount REAL NOT NULL,
        currency TEXT,
        description TEXT,
        merchant TEXT,
        category TEXT NOT NULL DEFAULT 'other',
        tags TEXT NOT NULL DEFAULT '[]',
        spent_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        refund_of INTEGER REFERENCES expenses(id)
    );
    INSERT INTO expenses_new (id, chat_id, message_id, kind, amount, currency,
                              description, merchant, category, tags, spent_at, created_at)
    SELECT id, chat_id, message_id, kind, amount, currency,
           description, merchant, category, tags, spent_at, created_at
    FROM expenses;
    DROP TABLE expenses;
    ALTER TABLE expenses_new RENAME TO expenses;
    CREATE INDEX idx_expenses_chat_date ON expenses (chat_id, spent_at, id);
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


@dataclass(frozen=True)
class Entry:
    id: int
    chat_id: int
    category: str
    data: str
    created_at: str


@dataclass(frozen=True)
class Expense:
    id: int
    chat_id: int
    kind: str
    amount: float
    currency: str | None
    description: str | None
    merchant: str | None
    category: str
    tags: str  # JSON array
    spent_at: str  # YYYY-MM-DD (local day)
    created_at: str
    refund_of: int | None = None


@dataclass(frozen=True)
class Food:
    name: str
    calories_per_100g: float | None
    protein_per_100g: float | None
    fat_per_100g: float | None
    carbs_per_100g: float | None


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

    def entries_since(self, chat_id: int, category: str, since_iso: str) -> list[Entry]:
        rows = self._conn.execute(
            "SELECT id, chat_id, category, data, created_at FROM entries"
            " WHERE chat_id = ? AND category = ? AND created_at >= ?"
            " ORDER BY id",
            (chat_id, category, since_iso),
        ).fetchall()
        return [
            Entry(
                id=row["id"],
                chat_id=row["chat_id"],
                category=row["category"],
                data=row["data"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def add_expense(
        self,
        *,
        chat_id: int,
        kind: str,
        amount: float,
        category: str,
        spent_at: str,
        currency: str | None = None,
        description: str | None = None,
        merchant: str | None = None,
        tags: list[str] | None = None,
        message_id: int | None = None,
        refund_of: int | None = None,
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO expenses (chat_id, message_id, kind, amount, currency,"
                " description, merchant, category, tags, spent_at, created_at, refund_of)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chat_id,
                    message_id,
                    kind,
                    amount,
                    currency,
                    description,
                    merchant,
                    category,
                    json.dumps(tags or []),
                    spent_at,
                    created_at,
                    refund_of,
                ),
            )
        return cursor.lastrowid

    @staticmethod
    def _expense_from_row(row: sqlite3.Row) -> Expense:
        return Expense(
            id=row["id"],
            chat_id=row["chat_id"],
            kind=row["kind"],
            amount=row["amount"],
            currency=row["currency"],
            description=row["description"],
            merchant=row["merchant"],
            category=row["category"],
            tags=row["tags"],
            spent_at=row["spent_at"],
            created_at=row["created_at"],
            refund_of=row["refund_of"],
        )

    _EXPENSE_COLUMNS = (
        "id, chat_id, kind, amount, currency, description, merchant,"
        " category, tags, spent_at, created_at, refund_of"
    )

    def expenses_since(self, chat_id: int, since_spent_at: str) -> list[Expense]:
        rows = self._conn.execute(
            f"SELECT {self._EXPENSE_COLUMNS} FROM expenses"
            " WHERE chat_id = ? AND spent_at >= ? ORDER BY spent_at, id",
            (chat_id, since_spent_at),
        ).fetchall()
        return [self._expense_from_row(row) for row in rows]

    def recent_expenses(self, chat_id: int, limit: int = 10) -> list[Expense]:
        rows = self._conn.execute(
            f"SELECT {self._EXPENSE_COLUMNS} FROM expenses"
            " WHERE chat_id = ? AND kind = 'expense' ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [self._expense_from_row(row) for row in rows]

    def get_expense(self, chat_id: int, expense_id: int) -> Expense | None:
        row = self._conn.execute(
            f"SELECT {self._EXPENSE_COLUMNS} FROM expenses"
            " WHERE chat_id = ? AND id = ?",
            (chat_id, expense_id),
        ).fetchone()
        return self._expense_from_row(row) if row else None

    def expenses_for_retag(self, include_all: bool = False) -> list[tuple[Expense, str | None]]:
        where = "" if include_all else " WHERE e.category = 'other' AND e.tags = '[]'"
        rows = self._conn.execute(
            "SELECT e.id, e.chat_id, e.kind, e.amount, e.currency, e.description,"
            " e.merchant, e.category, e.tags, e.spent_at, e.created_at, e.refund_of,"
            " m.text AS message"
            " FROM expenses e LEFT JOIN messages m ON m.id = e.message_id"
            f"{where} ORDER BY e.id",
        ).fetchall()
        return [(self._expense_from_row(row), row["message"]) for row in rows]

    def update_expense_classification(
        self, expense_id: int, *, category: str, tags: list[str], merchant: str | None
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE expenses SET category = ?, tags = ?,"
                " merchant = COALESCE(?, merchant) WHERE id = ?",
                (category, json.dumps(tags), merchant, expense_id),
            )

    def upsert_food(
        self,
        *,
        chat_id: int,
        name: str,
        calories_per_100g: float | None = None,
        protein_per_100g: float | None = None,
        fat_per_100g: float | None = None,
        carbs_per_100g: float | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute(
                "INSERT INTO foods (chat_id, name, calories_per_100g, protein_per_100g,"
                " fat_per_100g, carbs_per_100g, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(chat_id, name) DO UPDATE SET"
                " calories_per_100g = COALESCE(excluded.calories_per_100g, foods.calories_per_100g),"
                " protein_per_100g = COALESCE(excluded.protein_per_100g, foods.protein_per_100g),"
                " fat_per_100g = COALESCE(excluded.fat_per_100g, foods.fat_per_100g),"
                " carbs_per_100g = COALESCE(excluded.carbs_per_100g, foods.carbs_per_100g),"
                " updated_at = excluded.updated_at",
                (
                    chat_id,
                    name,
                    calories_per_100g,
                    protein_per_100g,
                    fat_per_100g,
                    carbs_per_100g,
                    now,
                    now,
                ),
            )

    def list_foods(self, chat_id: int) -> list[Food]:
        rows = self._conn.execute(
            "SELECT name, calories_per_100g, protein_per_100g, fat_per_100g,"
            " carbs_per_100g FROM foods WHERE chat_id = ? ORDER BY name",
            (chat_id,),
        ).fetchall()
        return [
            Food(
                name=row["name"],
                calories_per_100g=row["calories_per_100g"],
                protein_per_100g=row["protein_per_100g"],
                fat_per_100g=row["fat_per_100g"],
                carbs_per_100g=row["carbs_per_100g"],
            )
            for row in rows
        ]

    def close(self) -> None:
        self._conn.close()
