"""SQLite persistence for sessions and memory.

Provides durable storage that survives process restarts.
Supports both synchronous and async (via aiosqlite) access patterns.
"""
from __future__ import annotations

import json
import sqlite3
import time
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("healthy_agent.persistence")

DEFAULT_DB_PATH = "~/.healthy_agent/store.db"


class SQLiteStore:
    """SQLite-backed persistence for sessions and key-value memory.

    Usage:
        store = SQLiteStore()  # defaults to ~/.healthy_agent/store.db
        store.save_session("abc123", messages=[...], metadata={...})
        session = store.load_session("abc123")
        store.put_memory("abc123", "user_name", "Alice")
        name = store.get_memory("abc123", "user_name")
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_tables()
        logger.info("SQLite store initialized: %s", self._path)

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                metadata TEXT DEFAULT '{}',
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS memory (
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                updated_at REAL NOT NULL,
                PRIMARY KEY (session_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_memory_session
                ON memory(session_id);
        """)
        self._conn.commit()

    # -- Session operations --

    def save_session(
        self,
        session_id: str,
        *,
        messages: list[dict] | None = None,
        metadata: dict | None = None,
        created_at: float | None = None,
    ) -> None:
        """Upsert a session and optionally its messages."""
        now = created_at or time.time()
        self._conn.execute(
            """INSERT INTO sessions (session_id, created_at, metadata)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 metadata = COALESCE(excluded.metadata, sessions.metadata)""",
            (session_id, now, json.dumps(metadata or {})),
        )
        if messages:
            self._conn.executemany(
                """INSERT OR IGNORE INTO messages (session_id, role, content, timestamp)
                   VALUES (?, ?, ?, ?)""",
                [(session_id, m["role"], m["content"], m.get("timestamp", now)) for m in messages],
            )
        self._conn.commit()

    def load_session(self, session_id: str) -> dict | None:
        """Load a session with all its messages."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None

        messages = self._conn.execute(
            "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        return {
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "metadata": json.loads(row["metadata"]),
            "active": bool(row["active"]),
            "messages": [dict(m) for m in messages],
        }

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Append a message to a session."""
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, time.time()),
        )
        self._conn.commit()

    def list_sessions(self, active_only: bool = False) -> list[dict]:
        """List all sessions."""
        query = "SELECT session_id, created_at, metadata, active FROM sessions"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "created_at": r["created_at"],
                "metadata": json.loads(r["metadata"]),
                "active": bool(r["active"]),
            }
            for r in rows
        ]

    def close_session(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET active = 0 WHERE session_id = ?", (session_id,)
        )
        self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        """Delete session and all associated data."""
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM memory WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.commit()

    # -- Memory operations (scoped per session) --

    def put_memory(self, session_id: str, key: str, value: Any, *, tags: list[str] | None = None) -> None:
        """Store a key-value pair for a session."""
        self._conn.execute(
            """INSERT INTO memory (session_id, key, value, tags, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id, key) DO UPDATE SET
                 value = excluded.value,
                 tags = excluded.tags,
                 updated_at = excluded.updated_at""",
            (session_id, key, json.dumps(value), json.dumps(tags or []), time.time()),
        )
        self._conn.commit()

    def get_memory(self, session_id: str, key: str) -> Any | None:
        """Retrieve a value by key for a session."""
        row = self._conn.execute(
            "SELECT value FROM memory WHERE session_id = ? AND key = ?",
            (session_id, key),
        ).fetchone()
        return json.loads(row["value"]) if row else None

    def search_memory(self, session_id: str, tag: str) -> list[dict]:
        """Search memory entries by tag."""
        rows = self._conn.execute(
            "SELECT key, value, tags, updated_at FROM memory WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        results = []
        for r in rows:
            entry_tags = json.loads(r["tags"])
            if tag in entry_tags:
                results.append({
                    "key": r["key"],
                    "value": json.loads(r["value"]),
                    "tags": entry_tags,
                })
        return results

    def all_memory(self, session_id: str) -> dict[str, Any]:
        """Get all memory for a session."""
        rows = self._conn.execute(
            "SELECT key, value FROM memory WHERE session_id = ?", (session_id,),
        ).fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def delete_memory(self, session_id: str, key: str) -> None:
        self._conn.execute(
            "DELETE FROM memory WHERE session_id = ? AND key = ?", (session_id, key),
        )
        self._conn.commit()

    def clear_memory(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM memory WHERE session_id = ?", (session_id,))
        self._conn.commit()

    # -- Lifecycle --

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def stats(self) -> dict:
        """Get store statistics."""
        session_count = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        message_count = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        memory_count = self._conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        return {
            "sessions": session_count,
            "messages": message_count,
            "memory_entries": memory_count,
            "db_path": str(self._path),
        }
