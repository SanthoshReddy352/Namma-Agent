"""Single-database memory for FRIDAY v2.

One SQLite file replaces v1's 8 stores + ChromaDB + Mem0. Four tables:

  * ``sessions`` — conversation sessions
  * ``turns``    — per-role messages (user/assistant) = conversation history
  * ``facts``    — key/value facts about the user (+ ``facts_fts`` FTS5 search)
  * ``audit``    — tool execution log

The model's context window handles relevance; FTS5 covers keyword recall. No
embeddings, no vector DB, no separate stores.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    persona     TEXT DEFAULT 'friday_core',
    summary     TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,            -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    tools_used  TEXT,                     -- JSON array of tool names
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT UNIQUE NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT DEFAULT 'general',
    confidence  REAL DEFAULT 1.0,
    updated_at  TEXT NOT NULL
);

-- Standalone FTS5 index (rowid mirrors facts.id; synced manually in save_fact).
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(key, value);

CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    tool_name       TEXT NOT NULL,
    args            TEXT,
    result_summary  TEXT,
    success         INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit(tool_name);
"""


class Database:
    """Thread-safe single-connection SQLite store."""

    def __init__(self, path: str = "data/friday.db"):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- sessions ----------------------------------------------------------

    def create_session(self, persona: str = "friday_core") -> str:
        sid = str(uuid.uuid4())
        now = _now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions (id, created_at, updated_at, persona) VALUES (?,?,?,?)",
                (sid, now, now, persona),
            )
            self.conn.commit()
        return sid

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id)
            )
            self.conn.commit()

    # -- turns -------------------------------------------------------------

    def add_turn(self, session_id: str, role: str, content: str,
                 tools_used: Optional[list[str]] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO turns (session_id, role, content, tools_used, created_at) "
                "VALUES (?,?,?,?,?)",
                (session_id, role, content, json.dumps(tools_used or []), _now()),
            )
            self.conn.commit()
        self.touch_session(session_id)

    def recent_turns(self, session_id: str, limit: int = 12) -> list[dict]:
        """Return the last ``limit`` turns in chronological order."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT role, content FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # -- facts -------------------------------------------------------------

    def save_fact(self, key: str, value: str, category: str = "general") -> None:
        key = key.strip().lower()
        with self._lock:
            self.conn.execute(
                "INSERT INTO facts (key, value, category, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "category=excluded.category, updated_at=excluded.updated_at",
                (key, value, category, _now()),
            )
            row = self.conn.execute("SELECT id FROM facts WHERE key=?", (key,)).fetchone()
            # Keep the FTS mirror in sync.
            self.conn.execute("DELETE FROM facts_fts WHERE rowid=?", (row["id"],))
            self.conn.execute(
                "INSERT INTO facts_fts (rowid, key, value) VALUES (?,?,?)",
                (row["id"], key, value),
            )
            self.conn.commit()

    def get_fact(self, key: str) -> Optional[str]:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM facts WHERE key=?", (key.strip().lower(),)
            ).fetchone()
        return row["value"] if row else None

    def all_facts(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT key, value, category FROM facts ORDER BY key"
            ).fetchall()
        return [dict(r) for r in rows]

    def search_facts(self, query: str, limit: int = 10) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        with self._lock:
            try:
                rows = self.conn.execute(
                    "SELECT f.key, f.value, f.category FROM facts f "
                    "JOIN facts_fts ON f.id = facts_fts.rowid "
                    "WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # FTS rejects some punctuation; fall back to LIKE.
                like = f"%{query}%"
                rows = self.conn.execute(
                    "SELECT key, value, category FROM facts "
                    "WHERE key LIKE ? OR value LIKE ? LIMIT ?",
                    (like, like, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_fact(self, key: str) -> bool:
        key = (key or "").strip().lower()
        with self._lock:
            row = self.conn.execute("SELECT id FROM facts WHERE key=?", (key,)).fetchone()
            if row is None:
                return False
            self.conn.execute("DELETE FROM facts_fts WHERE rowid=?", (row["id"],))
            self.conn.execute("DELETE FROM facts WHERE id=?", (row["id"],))
            self.conn.commit()
        return True

    def search_turns(self, query: str, limit: int = 10) -> list[dict]:
        """Keyword search across stored conversation turns (LIKE; cross-session)."""
        query = (query or "").strip()
        if not query:
            return []
        like = f"%{query}%"
        with self._lock:
            rows = self.conn.execute(
                "SELECT session_id, role, content, created_at FROM turns "
                "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (like, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- audit -------------------------------------------------------------

    def log_audit(self, session_id: Optional[str], tool_name: str, args: dict,
                  result_summary: str, success: bool = True) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit (session_id, tool_name, args, result_summary, success, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (session_id, tool_name, json.dumps(args, default=str),
                 result_summary[:500], int(success), _now()),
            )
            self.conn.commit()
