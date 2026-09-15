"""
State store for deduplication so re-running the bot doesn't spam Slack/Discord
with issues you were already told about.

Supports both:
1. JSON-backed state (default: state.json) with atomic writes.
2. SQLite-backed state (e.g. state.db) for larger volume and concurrent access.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_STATE_PATH = "state.json"


class SQLiteStateStore:
    """SQLite-backed deduplication store for high issue volume."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS issue_state (
                    issue_key TEXT PRIMARY KEY,
                    first_seen TEXT NOT NULL,
                    last_notified TEXT NOT NULL
                )
                """
            )

    def get(self, key: str, default=None) -> dict | None:
        cursor = self.conn.execute(
            "SELECT first_seen, last_notified FROM issue_state WHERE issue_key = ?",
            (key,),
        )
        row = cursor.fetchone()
        if row is None:
            return default
        return {"first_seen": row["first_seen"], "last_notified": row["last_notified"]}

    def setdefault(self, key: str, default: dict) -> dict:
        existing = self.get(key)
        if existing is not None:
            return existing
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO issue_state (issue_key, first_seen, last_notified) VALUES (?, ?, ?)",
                (key, default.get("first_seen"), default.get("last_notified")),
            )
        return self.get(key) or default

    def mark_notified(self, key: str) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO issue_state (issue_key, first_seen, last_notified)
                VALUES (?, ?, ?)
                ON CONFLICT(issue_key) DO UPDATE SET last_notified = excluded.last_notified
                """,
                (key, now, now),
            )

    def count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM issue_state")
        return cursor.fetchone()[0]

    def migrate_from_json(self, json_path: str) -> int:
        """Migrates records from a state.json file into SQLite."""
        if not os.path.exists(json_path):
            return 0
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        migrated = 0
        with self.conn:
            for key, entry in data.items():
                first_seen = entry.get("first_seen")
                last_notified = entry.get("last_notified") or first_seen
                if first_seen:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO issue_state (issue_key, first_seen, last_notified) VALUES (?, ?, ?)",
                        (key, first_seen, last_notified),
                    )
                    migrated += 1
        return migrated

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def is_sqlite_path(path: str) -> bool:
    return path.endswith((".db", ".sqlite", ".sqlite3"))


def load_state(path: str = DEFAULT_STATE_PATH, auto_migrate: bool = True):
    if is_sqlite_path(path):
        store = SQLiteStateStore(path)
        # If database is freshly initialized, try migrating from state.json if present
        if auto_migrate and path in ("state.db", "state.sqlite") and store.count() == 0 and os.path.exists(DEFAULT_STATE_PATH):
            store.migrate_from_json(DEFAULT_STATE_PATH)
        return store

    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state, path: str = DEFAULT_STATE_PATH) -> None:
    if isinstance(state, SQLiteStateStore):
        state.commit()
        return

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def should_notify(state, key: str, renotify_after_days: int) -> bool:
    entry = state.get(key)
    if entry is None:
        return True
    if renotify_after_days <= 0:
        return False
    last = datetime.fromisoformat(entry["last_notified"].replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
    return age_days >= renotify_after_days


def mark_notified(state, key: str) -> None:
    if isinstance(state, SQLiteStateStore):
        state.mark_notified(key)
        return

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entry = state.setdefault(key, {"first_seen": now})
    entry["last_notified"] = now
