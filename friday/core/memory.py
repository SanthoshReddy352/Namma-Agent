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
    persona     TEXT DEFAULT 'core',
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

-- Standalone FTS5 index over turns (rowid mirrors turns.id; synced in add_turn)
-- for cross-session keyword recall. Backfilled on init if empty.
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(content);

CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    tool_name       TEXT NOT NULL,
    args            TEXT,
    result_summary  TEXT,
    success         INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL
);

-- Projects: named workspaces with their own dedicated (layered) memory.
CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    archived     INTEGER DEFAULT 0
);

-- Learning Room topics. The teacher agent owns a learning path (plan = modules);
-- each module gets its own kind='learning' session (its chat thread). `insights`
-- holds the model's running analysis of the learner (score + analytical prompt).
CREATE TABLE IF NOT EXISTS learning_topics (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,           -- the topic's "overview" session
    title        TEXT NOT NULL,
    depth        TEXT DEFAULT 'solid',
    plan         TEXT,                    -- JSON array of modules [{id,title,summary,status,session_id}]
    progress     TEXT,                    -- JSON {done, total, current_module}
    insights     TEXT,                    -- JSON {understanding, analysis, strengths, gaps}
    status       TEXT DEFAULT 'active',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- Quiz results (feed the insights / understanding score).
CREATE TABLE IF NOT EXISTS learning_quizzes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id     TEXT NOT NULL,
    module_id    TEXT,
    question     TEXT NOT NULL,
    correct      INTEGER DEFAULT 0,       -- 1 if answered correctly
    user_answer  TEXT,
    created_at   TEXT NOT NULL
);

-- Artifacts produced while teaching (diagrams / images / simulations) per topic.
CREATE TABLE IF NOT EXISTS learning_artifacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id     TEXT NOT NULL,
    module_id    TEXT,
    kind         TEXT NOT NULL,           -- 'diagram' | 'image' | 'simulation'
    title        TEXT,
    url          TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Project documents (multi-document RAG): per-file metadata + screening status.
-- status: 'ready' (indexed, retrievable) | 'flagged' (indexed, quarantined out of
-- retrieval until trusted) | 'trusted' (user overrode a flag) | 'error'.
CREATE TABLE IF NOT EXISTS project_documents (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    name         TEXT NOT NULL,
    path         TEXT NOT NULL,
    bytes        INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'ready',
    flag_reasons TEXT,                    -- JSON array of screening hits
    chunk_count  INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_documents ON project_documents(project_id);

-- Retrieval chunks: structure-aware slices of each document, indexed for BM25
-- keyword retrieval (doc_chunks_fts rowid mirrors doc_chunks.id).
CREATE TABLE IF NOT EXISTS doc_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    section     TEXT DEFAULT '',
    content     TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(content, section);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc ON doc_chunks(doc_id, position);

-- Dedicated memory for a project or learning topic (scope_type + scope_id).
CREATE TABLE IF NOT EXISTS scope_memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type   TEXT NOT NULL,           -- 'project' | 'learning'
    scope_id     TEXT NOT NULL,
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS scope_memory_fts USING fts5(content);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit(tool_name);
CREATE INDEX IF NOT EXISTS idx_scope_memory ON scope_memory(scope_type, scope_id);
"""

# Columns added to `sessions` after its original release (v2). Applied idempotently
# on every open so older databases pick them up (sqlite errors if already present).
_SESSION_MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN title TEXT",
    "ALTER TABLE sessions ADD COLUMN project_id TEXT",
    "ALTER TABLE sessions ADD COLUMN kind TEXT DEFAULT 'chat'",
    "ALTER TABLE sessions ADD COLUMN meta TEXT",
    # The model profile id this session is bound to (model switching = new session).
    "ALTER TABLE sessions ADD COLUMN model TEXT",
    "ALTER TABLE learning_topics ADD COLUMN insights TEXT",
    "ALTER TABLE learning_topics ADD COLUMN preferences TEXT",
    # Full quiz payloads (not just question + right/wrong) so the dashboard can
    # show options/answer/explanation, and answered cards survive a reload.
    "ALTER TABLE learning_quizzes ADD COLUMN quiz_uid TEXT",
    "ALTER TABLE learning_quizzes ADD COLUMN options TEXT",
    "ALTER TABLE learning_quizzes ADD COLUMN answer_index INTEGER",
    "ALTER TABLE learning_quizzes ADD COLUMN picked_index INTEGER",
    "ALTER TABLE learning_quizzes ADD COLUMN explanation TEXT",
    # Per-turn stats (time-to-first-token + token count) so they persist across
    # reloads, shown in the message footer. JSON: {"ttft": float, "tokens": int}.
    "ALTER TABLE turns ADD COLUMN meta TEXT",
]


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
            self._migrate_sessions()
            self._backfill_turns_fts()

    def _migrate_sessions(self) -> None:
        """Add post-release `sessions` columns idempotently (projects/learning)."""
        for stmt in _SESSION_MIGRATIONS:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        # Index on the newly-added project_id (created after the column exists).
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id)")
        self.conn.commit()

    def _backfill_turns_fts(self) -> None:
        """Populate turns_fts from existing turns the first time it appears
        (e.g. on a database created before the index existed)."""
        n_fts = self.conn.execute("SELECT count(*) AS c FROM turns_fts").fetchone()["c"]
        n_turns = self.conn.execute("SELECT count(*) AS c FROM turns").fetchone()["c"]
        if n_fts == 0 and n_turns > 0:
            rows = self.conn.execute("SELECT id, content FROM turns").fetchall()
            self.conn.executemany(
                "INSERT INTO turns_fts (rowid, content) VALUES (?,?)",
                [(r["id"], r["content"]) for r in rows],
            )
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- sessions ----------------------------------------------------------

    def create_session(self, persona: str = "core",
                        model: Optional[str] = None) -> str:
        sid = str(uuid.uuid4())
        now = _now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions (id, created_at, updated_at, persona, model) "
                "VALUES (?,?,?,?,?)",
                (sid, now, now, persona, model or None),
            )
            self.conn.commit()
        return sid

    def set_session_model(self, session_id: str, model: Optional[str]) -> None:
        """Bind a session to a model profile id (its 'brain' for every turn)."""
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET model=? WHERE id=?", (model or None, session_id)
            )
            self.conn.commit()

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id)
            )
            self.conn.commit()

    # -- turns -------------------------------------------------------------

    def add_turn(self, session_id: str, role: str, content: str,
                 tools_used: Optional[list[str]] = None,
                 meta: Optional[dict] = None) -> None:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO turns (session_id, role, content, tools_used, meta, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (session_id, role, content, json.dumps(tools_used or []),
                 json.dumps(meta) if meta else None, _now()),
            )
            # Only real conversation enters the search index — UI-only turns
            # (persisted quiz cards) would surface as JSON noise in recall.
            if role in ("user", "assistant"):
                self.conn.execute(
                    "INSERT INTO turns_fts (rowid, content) VALUES (?,?)",
                    (cur.lastrowid, content),
                )
            self.conn.commit()
        self.touch_session(session_id)

    def recent_turns(self, session_id: str, limit: int = 12) -> list[dict]:
        """Return the last ``limit`` turns in chronological order. Only real
        conversation roles — UI-only turns (e.g. persisted 'quiz' cards) never
        enter the model's message history."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT role, content FROM turns WHERE session_id=? "
                "AND role IN ('user','assistant') ORDER BY id DESC LIMIT ?",
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

    def search_turns(self, query: str, limit: int = 10,
                     project_id: Optional[str] = None) -> list[dict]:
        """Cross-session keyword search over turns (FTS5, LIKE fallback). Pass
        ``project_id`` to search only the chats filed in one project."""
        query = (query or "").strip()
        if not query:
            return []
        scope_join, scope_where, scope_params = "", "", []
        if project_id:
            scope_join = "JOIN sessions s ON s.id = t.session_id "
            scope_where = "AND s.project_id=? "
            scope_params = [project_id]
        with self._lock:
            try:
                rows = self.conn.execute(
                    "SELECT t.session_id, t.role, t.content, t.created_at FROM turns t "
                    "JOIN turns_fts ON t.id = turns_fts.rowid "
                    f"{scope_join}"
                    f"WHERE turns_fts MATCH ? {scope_where}ORDER BY rank LIMIT ?",
                    (query, *scope_params, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query}%"
                rows = self.conn.execute(
                    "SELECT t.session_id, t.role, t.content, t.created_at FROM turns t "
                    f"{scope_join}"
                    f"WHERE t.content LIKE ? AND t.role IN ('user','assistant') "
                    f"{scope_where}ORDER BY t.id DESC LIMIT ?",
                    (like, *scope_params, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    # -- session summaries (cross-session recall) --------------------------

    def count_turns(self, session_id: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT count(*) AS c FROM turns WHERE session_id=?", (session_id,)
            ).fetchone()
        return int(row["c"])

    def session_turns(self, session_id: str, limit: int = 200) -> list[dict]:
        """All turns for a session in chronological order (for summarization and the
        UI history). Carries persisted per-turn stats (`meta`) and `tools_used` so a
        reloaded chat shows the same footer (time-to-first-token, tokens, tools used)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT role, content, tools_used, meta, created_at FROM turns "
                "WHERE session_id=? ORDER BY id LIMIT ?",
                (session_id, limit),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                tools = json.loads(r["tools_used"]) if r["tools_used"] else []
            except (ValueError, TypeError):
                tools = []
            try:
                meta = json.loads(r["meta"]) if r["meta"] else None
            except (ValueError, TypeError):
                meta = None
            out.append({"role": r["role"], "content": r["content"], "tools_used": tools,
                        "meta": meta, "created_at": r["created_at"]})
        return out

    def set_session_summary(self, session_id: str, summary: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET summary=?, updated_at=? WHERE id=?",
                (summary, _now(), session_id),
            )
            self.conn.commit()

    def get_session_summary(self, session_id: str) -> Optional[str]:
        with self._lock:
            row = self.conn.execute(
                "SELECT summary FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        return row["summary"] if row and row["summary"] else None

    def unsummarized_sessions(self, exclude: Optional[str] = None,
                              project_id: Optional[str] = None) -> list[str]:
        """Session ids that have turns but no summary yet (oldest first). Pass
        ``project_id`` to restrict to one project's chats."""
        where = ["(s.summary IS NULL OR s.summary='')",
                 "EXISTS (SELECT 1 FROM turns t WHERE t.session_id=s.id)"]
        params: list = []
        if project_id:
            where.append("s.project_id=?")
            params.append(project_id)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT s.id FROM sessions s WHERE {' AND '.join(where)} ORDER BY s.created_at",
                tuple(params),
            ).fetchall()
        return [r["id"] for r in rows if r["id"] != exclude]

    def list_sessions(self, limit: int = 50, project_id: Optional[str] = None,
                      include_learning: bool = False) -> list[dict]:
        """Recent chat sessions for the sidebar: id, timestamps, a title (custom
        rename else first user message), summary, project_id. Learning-Room
        sessions are excluded unless ``include_learning``; pass ``project_id`` to
        list only one project's chats (use the sentinel ``""`` for unfiled chats)."""
        where = ["EXISTS (SELECT 1 FROM turns t WHERE t.session_id=s.id)"]
        params: list = []
        if not include_learning:
            where.append("(s.kind IS NULL OR s.kind='chat')")
        if project_id is not None:
            if project_id == "":
                where.append("(s.project_id IS NULL OR s.project_id='')")
            else:
                where.append("s.project_id=?")
                params.append(project_id)
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(
                "SELECT s.id, s.created_at, s.updated_at, s.summary, s.project_id, s.model, s.title AS custom_title, "
                "(SELECT t.content FROM turns t WHERE t.session_id=s.id AND t.role='user' "
                " ORDER BY t.id LIMIT 1) AS first_msg "
                "FROM sessions s "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY s.updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            custom = (d.pop("custom_title", None) or "").strip()
            first = (d.pop("first_msg", None) or "").strip()
            title = custom or first
            d["title"] = (title[:60] + "…") if len(title) > 60 else (title or "New chat")
            out.append(d)
        return out

    # -- session metadata (rename / project / scope lookup) ----------------

    def get_session(self, session_id: str) -> Optional[dict]:
        """Row for a session: kind/project_id/title/meta (for scoped prompts)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT id, created_at, updated_at, persona, summary, title, project_id, kind, meta, model "
                "FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def rename_session(self, session_id: str, title: str) -> bool:
        title = (title or "").strip()[:120]
        with self._lock:
            cur = self.conn.execute(
                "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                (title or None, _now(), session_id),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def set_auto_title(self, session_id: str, title: str) -> bool:
        """Set a model-generated title, but only if the user hasn't named the chat
        (preserves manual renames). Returns True if it actually set one."""
        title = (title or "").strip()[:80]
        if not title:
            return False
        with self._lock:
            cur = self.conn.execute(
                "UPDATE sessions SET title=? WHERE id=? AND (title IS NULL OR title='')",
                (title, session_id),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def set_session_project(self, session_id: str, project_id: Optional[str]) -> bool:
        """File a chat into a project (or unfile with ``None``/``''``)."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE sessions SET project_id=?, updated_at=? WHERE id=?",
                (project_id or None, _now(), session_id),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def create_session_in(self, project_id: Optional[str] = None, kind: str = "chat",
                          persona: str = "core") -> str:
        """Create a session pre-attached to a project and/or with a kind."""
        sid = str(uuid.uuid4())
        now = _now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions (id, created_at, updated_at, persona, project_id, kind) "
                "VALUES (?,?,?,?,?,?)",
                (sid, now, now, persona, project_id or None, kind),
            )
            self.conn.commit()
        return sid

    # -- projects ----------------------------------------------------------

    def create_project(self, name: str, description: str = "") -> dict:
        pid = str(uuid.uuid4())
        now = _now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO projects (id, name, description, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (pid, name.strip() or "Untitled project", description.strip(), now, now),
            )
            self.conn.commit()
        return self.get_project(pid)

    def get_project(self, project_id: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, name, description, created_at, updated_at, archived "
                "FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT p.id, p.name, p.description, p.created_at, p.updated_at, p.archived, "
                "(SELECT count(*) FROM sessions s WHERE s.project_id=p.id) AS chat_count "
                "FROM projects p WHERE p.archived=0 ORDER BY p.updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_project(self, project_id: str, name: Optional[str] = None,
                       description: Optional[str] = None) -> Optional[dict]:
        sets, params = [], []
        if name is not None:
            sets.append("name=?"); params.append(name.strip() or "Untitled project")
        if description is not None:
            sets.append("description=?"); params.append(description.strip())
        if not sets:
            return self.get_project(project_id)
        sets.append("updated_at=?"); params.append(_now())
        params.append(project_id)
        with self._lock:
            self.conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", tuple(params))
            self.conn.commit()
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        """Delete a project; its chats are unfiled (kept), its memory and document
        index removed (the caller owns deleting the files on disk)."""
        with self._lock:
            self.conn.execute("UPDATE sessions SET project_id=NULL WHERE project_id=?", (project_id,))
            self._delete_scope_memory("project", project_id)
            ids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM doc_chunks WHERE project_id=?", (project_id,)).fetchall()]
            self.conn.executemany("DELETE FROM doc_chunks_fts WHERE rowid=?", [(i,) for i in ids])
            self.conn.execute("DELETE FROM doc_chunks WHERE project_id=?", (project_id,))
            self.conn.execute("DELETE FROM project_documents WHERE project_id=?", (project_id,))
            cur = self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self.conn.commit()
        return cur.rowcount > 0

    # -- project documents (multi-document RAG) -----------------------------

    @staticmethod
    def _doc_row(r) -> dict:
        d = dict(r)
        d["flag_reasons"] = json.loads(d["flag_reasons"]) if d.get("flag_reasons") else []
        return d

    def add_project_document(self, project_id: str, name: str, path: str, size: int,
                             status: str = "ready",
                             flag_reasons: Optional[list] = None) -> dict:
        doc_id = str(uuid.uuid4())
        with self._lock:
            self.conn.execute(
                "INSERT INTO project_documents (id, project_id, name, path, bytes, status, "
                "flag_reasons, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, project_id, name, path, size, status,
                 json.dumps(flag_reasons or []), _now()),
            )
            self.conn.commit()
        return self.get_project_document(doc_id)

    def get_project_document(self, doc_id: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM project_documents WHERE id=?", (doc_id,)).fetchone()
        return self._doc_row(row) if row else None

    def list_project_documents(self, project_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM project_documents WHERE project_id=? ORDER BY created_at",
                (project_id,)).fetchall()
        return [self._doc_row(r) for r in rows]

    def count_project_documents(self, project_id: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT count(*) AS c FROM project_documents WHERE project_id=?",
                (project_id,)).fetchone()
        return int(row["c"])

    def set_document_status(self, doc_id: str, status: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE project_documents SET status=? WHERE id=?", (status, doc_id))
            self.conn.commit()
        return cur.rowcount > 0

    def delete_project_document(self, doc_id: str) -> bool:
        with self._lock:
            ids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM doc_chunks WHERE doc_id=?", (doc_id,)).fetchall()]
            self.conn.executemany("DELETE FROM doc_chunks_fts WHERE rowid=?", [(i,) for i in ids])
            self.conn.execute("DELETE FROM doc_chunks WHERE doc_id=?", (doc_id,))
            cur = self.conn.execute("DELETE FROM project_documents WHERE id=?", (doc_id,))
            self.conn.commit()
        return cur.rowcount > 0

    def replace_doc_chunks(self, doc_id: str, project_id: str, chunks: list[dict]) -> int:
        """(Re)index a document's chunks; keeps the FTS mirror in sync and stores
        the chunk count on the document row."""
        with self._lock:
            ids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM doc_chunks WHERE doc_id=?", (doc_id,)).fetchall()]
            self.conn.executemany("DELETE FROM doc_chunks_fts WHERE rowid=?", [(i,) for i in ids])
            self.conn.execute("DELETE FROM doc_chunks WHERE doc_id=?", (doc_id,))
            for ch in chunks:
                cur = self.conn.execute(
                    "INSERT INTO doc_chunks (doc_id, project_id, position, section, content) "
                    "VALUES (?,?,?,?,?)",
                    (doc_id, project_id, int(ch.get("position", 0)),
                     (ch.get("section") or "")[:200], ch.get("content") or ""),
                )
                self.conn.execute(
                    "INSERT INTO doc_chunks_fts (rowid, content, section) VALUES (?,?,?)",
                    (cur.lastrowid, ch.get("content") or "", (ch.get("section") or "")[:200]),
                )
            self.conn.execute(
                "UPDATE project_documents SET chunk_count=? WHERE id=?", (len(chunks), doc_id))
            self.conn.commit()
        return len(chunks)

    def search_doc_chunks(self, project_id: str, query: str, limit: int = 18,
                          include_flagged: bool = False) -> list[dict]:
        """BM25-ranked chunk search within one project's retrievable documents.
        Flagged documents are quarantined out unless ``include_flagged``."""
        query = (query or "").strip()
        if not query:
            return []
        statuses = ("ready", "trusted", "flagged") if include_flagged else ("ready", "trusted")
        ph = ",".join("?" * len(statuses))
        with self._lock:
            try:
                rows = self.conn.execute(
                    f"SELECT c.id, c.doc_id, c.position, c.section, c.content, d.name AS doc_name, "
                    f"bm25(doc_chunks_fts) AS score "
                    f"FROM doc_chunks c "
                    f"JOIN doc_chunks_fts ON c.id = doc_chunks_fts.rowid "
                    f"JOIN project_documents d ON d.id = c.doc_id "
                    f"WHERE doc_chunks_fts MATCH ? AND c.project_id=? AND d.status IN ({ph}) "
                    f"ORDER BY score LIMIT ?",
                    (query, project_id, *statuses, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query}%"
                rows = self.conn.execute(
                    f"SELECT c.id, c.doc_id, c.position, c.section, c.content, d.name AS doc_name, "
                    f"0.0 AS score FROM doc_chunks c "
                    f"JOIN project_documents d ON d.id = c.doc_id "
                    f"WHERE c.content LIKE ? AND c.project_id=? AND d.status IN ({ph}) LIMIT ?",
                    (like, project_id, *statuses, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def doc_chunks_at(self, doc_id: str, positions: list[int]) -> list[dict]:
        """Fetch specific chunk positions of one document (neighbour stitching)."""
        if not positions:
            return []
        ph = ",".join("?" * len(positions))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT id, doc_id, position, section, content FROM doc_chunks "
                f"WHERE doc_id=? AND position IN ({ph}) ORDER BY position",
                (doc_id, *positions)).fetchall()
        return [dict(r) for r in rows]

    # -- scope memory (project / learning dedicated memory) ----------------

    def add_scope_memory(self, scope_type: str, scope_id: str, content: str) -> int:
        content = (content or "").strip()
        if not content:
            return 0
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO scope_memory (scope_type, scope_id, content, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (scope_type, scope_id, content, now, now),
            )
            self.conn.execute(
                "INSERT INTO scope_memory_fts (rowid, content) VALUES (?,?)",
                (cur.lastrowid, content),
            )
            self.conn.commit()
        return cur.lastrowid

    def list_scope_memory(self, scope_type: str, scope_id: str, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, content, created_at, updated_at FROM scope_memory "
                "WHERE scope_type=? AND scope_id=? ORDER BY id LIMIT ?",
                (scope_type, scope_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_scope_memory_entry(self, entry_id: int) -> bool:
        with self._lock:
            self.conn.execute("DELETE FROM scope_memory_fts WHERE rowid=?", (entry_id,))
            cur = self.conn.execute("DELETE FROM scope_memory WHERE id=?", (entry_id,))
            self.conn.commit()
        return cur.rowcount > 0

    def _delete_scope_memory(self, scope_type: str, scope_id: str) -> None:
        ids = [r["id"] for r in self.conn.execute(
            "SELECT id FROM scope_memory WHERE scope_type=? AND scope_id=?",
            (scope_type, scope_id)).fetchall()]
        self.conn.executemany("DELETE FROM scope_memory_fts WHERE rowid=?", [(i,) for i in ids])
        self.conn.execute("DELETE FROM scope_memory WHERE scope_type=? AND scope_id=?",
                          (scope_type, scope_id))

    # -- learning topics (the teacher agent) -------------------------------

    @staticmethod
    def _topic_row(r) -> dict:
        d = dict(r)
        for k in ("plan", "progress", "insights", "preferences"):
            d[k] = json.loads(d[k]) if d.get(k) else (None if k == "insights" else [])
        return d

    def create_learning_topic(self, title: str, depth: str = "solid") -> dict:
        tid = str(uuid.uuid4())
        now = _now()
        overview = self.create_session_in(kind="learning")
        with self._lock:
            self.conn.execute(
                "INSERT INTO learning_topics (id, session_id, title, depth, plan, progress, "
                "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (tid, overview, title.strip() or "Untitled topic", depth,
                 json.dumps([]), json.dumps({"done": 0, "total": 0, "current_module": None}),
                 "active", now, now),
            )
            self.conn.commit()
        return self.get_learning_topic(tid)

    def get_learning_topic(self, topic_id: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM learning_topics WHERE id=?", (topic_id,)).fetchone()
        return self._topic_row(row) if row else None

    def get_topic_by_session(self, session_id: str) -> Optional[dict]:
        """Resolve the topic owning a session — either its overview session or any
        module session (module.session_id stored inside the plan)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM learning_topics WHERE session_id=?", (session_id,)).fetchone()
            if row:
                return self._topic_row(row)
            rows = self.conn.execute("SELECT * FROM learning_topics").fetchall()
        for r in rows:
            t = self._topic_row(r)
            for m in (t.get("plan") or []):
                if m.get("session_id") == session_id:
                    return t
        return None

    def list_learning_topics(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM learning_topics ORDER BY updated_at DESC").fetchall()
        return [self._topic_row(r) for r in rows]

    def _save_topic_fields(self, topic_id: str, **fields) -> Optional[dict]:
        sets, params = [], []
        for k, v in fields.items():
            sets.append(f"{k}=?")
            params.append(json.dumps(v) if k in ("plan", "progress", "insights",
                                                 "preferences") else v)
        sets.append("updated_at=?"); params.append(_now())
        params.append(topic_id)
        with self._lock:
            self.conn.execute(
                f"UPDATE learning_topics SET {', '.join(sets)} WHERE id=?", tuple(params))
            self.conn.commit()
        return self.get_learning_topic(topic_id)

    def set_learning_plan(self, topic_id: str, modules: list[dict]) -> Optional[dict]:
        """Store/replace the module list, preserving any existing module session_ids
        by id so re-planning doesn't orphan threads. Recomputes progress."""
        existing = {m["id"]: m for m in (self.get_learning_topic(topic_id) or {}).get("plan", [])}
        norm = []
        for i, m in enumerate(modules):
            mid = m.get("id") or f"m{i+1}"
            prev = existing.get(mid, {})
            norm.append({
                "id": mid,
                "title": (m.get("title") or f"Module {i+1}").strip(),
                "summary": (m.get("summary") or "").strip(),
                "status": m.get("status") or prev.get("status") or ("current" if i == 0 else "todo"),
                "session_id": prev.get("session_id"),
            })
        progress = {
            "done": sum(1 for m in norm if m["status"] == "done"),
            "total": len(norm),
            "current_module": next((m["id"] for m in norm if m["status"] == "current"), None),
        }
        return self._save_topic_fields(topic_id, plan=norm, progress=progress)

    def module_session(self, topic_id: str, module_id: str) -> Optional[str]:
        """Return (creating if needed) the chat session for one module."""
        topic = self.get_learning_topic(topic_id)
        if not topic:
            return None
        plan = topic.get("plan") or []
        for m in plan:
            if m["id"] == module_id:
                if not m.get("session_id"):
                    m["session_id"] = self.create_session_in(kind="learning")
                    self._save_topic_fields(topic_id, plan=plan)
                return m["session_id"]
        return None

    def repoint_learning_session(self, old_session_id: str,
                                 new_session_id: str) -> Optional[dict]:
        """Move a learning thread (the path overview OR a module) onto a new session
        id — used when switching the model mid-topic: the new session carries a recap
        of the old one, so the learner continues instead of cold-starting. Returns the
        owning topic, or None if the old session isn't a learning thread."""
        topic = self.get_topic_by_session(old_session_id)
        if not topic:
            return None
        if topic.get("session_id") == old_session_id:  # the path/overview thread
            return self._save_topic_fields(topic["id"], session_id=new_session_id)
        plan = topic.get("plan") or []
        changed = False
        for m in plan:
            if m.get("session_id") == old_session_id:
                m["session_id"] = new_session_id
                changed = True
        return self._save_topic_fields(topic["id"], plan=plan) if changed else topic

    def mark_module(self, topic_id: str, module_id: str, status: str = "done") -> Optional[dict]:
        topic = self.get_learning_topic(topic_id)
        if not topic:
            return None
        plan = topic.get("plan") or []
        ids = [m["id"] for m in plan]
        for m in plan:
            if m["id"] == module_id:
                m["status"] = status
        # advance: first non-done module becomes 'current'
        if status == "done":
            nxt = next((m for m in plan if m["status"] not in ("done",)), None)
            for m in plan:
                if m["status"] == "current" and m["id"] != (nxt or {}).get("id"):
                    m["status"] = "todo"
            if nxt:
                nxt["status"] = "current"
        progress = {
            "done": sum(1 for m in plan if m["status"] == "done"),
            "total": len(plan),
            "current_module": next((m["id"] for m in plan if m["status"] == "current"), None),
        }
        return self._save_topic_fields(topic_id, plan=plan, progress=progress)

    def add_teaching_preference(self, topic_id: str, instruction: str) -> Optional[dict]:
        """Append a standing teaching preference (applied in every module chat)."""
        instruction = (instruction or "").strip()
        topic = self.get_learning_topic(topic_id)
        if not topic or not instruction:
            return topic
        prefs = topic.get("preferences") or []
        if instruction not in prefs:
            prefs.append(instruction)
        return self._save_topic_fields(topic_id, preferences=prefs)

    def remove_teaching_preference(self, topic_id: str, index: int) -> Optional[dict]:
        topic = self.get_learning_topic(topic_id)
        if not topic:
            return None
        prefs = topic.get("preferences") or []
        if 0 <= index < len(prefs):
            prefs.pop(index)
        return self._save_topic_fields(topic_id, preferences=prefs)

    def set_learning_insights(self, topic_id: str, insights: dict) -> Optional[dict]:
        cur = (self.get_learning_topic(topic_id) or {}).get("insights") or {}
        cur.update({k: v for k, v in insights.items() if v is not None})
        return self._save_topic_fields(topic_id, insights=cur)

    def record_quiz(self, topic_id: str, question: str, correct: bool,
                    module_id: Optional[str] = None, user_answer: str = "",
                    quiz_uid: str = "", options: Optional[list] = None,
                    answer_index: Optional[int] = None,
                    picked_index: Optional[int] = None, explanation: str = "") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO learning_quizzes (topic_id, module_id, question, correct, "
                "user_answer, quiz_uid, options, answer_index, picked_index, explanation, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (topic_id, module_id, question, int(bool(correct)), user_answer,
                 quiz_uid, json.dumps(options) if options is not None else None,
                 answer_index, picked_index, explanation, _now()),
            )
            self.conn.commit()

    def get_quiz_result(self, quiz_uid: str) -> Optional[dict]:
        """The recorded answer for one posed quiz (restores answered cards)."""
        if not quiz_uid:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT correct, user_answer, picked_index FROM learning_quizzes "
                "WHERE quiz_uid=? ORDER BY id DESC LIMIT 1", (quiz_uid,)
            ).fetchone()
        return dict(row) if row else None

    def record_artifact(self, topic_id: str, kind: str, url: str,
                        title: str = "", module_id: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO learning_artifacts (topic_id, module_id, kind, title, url, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (topic_id, module_id, kind, title, url, _now()),
            )
            self.conn.commit()

    def topic_insights(self, topic_id: str) -> dict:
        """Aggregate insights for the dashboard: quiz stats, artifacts, the model's
        running analysis, and an overall understanding score."""
        topic = self.get_learning_topic(topic_id)
        if not topic:
            return {}
        with self._lock:
            quizzes = [dict(r) for r in self.conn.execute(
                "SELECT question, correct, user_answer, module_id, created_at, "
                "options, answer_index, picked_index, explanation "
                "FROM learning_quizzes WHERE topic_id=? ORDER BY id", (topic_id,)).fetchall()]
            artifacts = [dict(r) for r in self.conn.execute(
                "SELECT kind, title, url, module_id, created_at "
                "FROM learning_artifacts WHERE topic_id=? ORDER BY id", (topic_id,)).fetchall()]
        for q in quizzes:
            q["options"] = json.loads(q["options"]) if q.get("options") else []
        n = len(quizzes)
        n_correct = sum(q["correct"] for q in quizzes)
        quiz_score = round(100 * n_correct / n) if n else None
        info = topic.get("insights") or {}
        return {
            "understanding": info.get("understanding", quiz_score),
            "analysis": info.get("analysis", ""),
            "strengths": info.get("strengths", []),
            "gaps": info.get("gaps", []),
            "quiz": {"total": n, "correct": n_correct, "score": quiz_score, "items": quizzes},
            "artifacts": artifacts,
            "progress": topic.get("progress") or {},
        }

    def delete_learning_topic(self, topic_id: str) -> bool:
        topic = self.get_learning_topic(topic_id)
        if not topic:
            return False
        sessions = [topic["session_id"]] + [
            m["session_id"] for m in (topic.get("plan") or []) if m.get("session_id")]
        with self._lock:
            for sid in sessions:
                ids = [r["id"] for r in self.conn.execute(
                    "SELECT id FROM turns WHERE session_id=?", (sid,)).fetchall()]
                self.conn.executemany("DELETE FROM turns_fts WHERE rowid=?", [(i,) for i in ids])
                self.conn.execute("DELETE FROM turns WHERE session_id=?", (sid,))
                self.conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.conn.execute("DELETE FROM learning_quizzes WHERE topic_id=?", (topic_id,))
            self.conn.execute("DELETE FROM learning_artifacts WHERE topic_id=?", (topic_id,))
            self._delete_scope_memory("learning", topic_id)
            self.conn.execute("DELETE FROM learning_topics WHERE id=?", (topic_id,))
            self.conn.commit()
        return True

    def search_sessions(self, query: str, limit: int = 5) -> list[dict]:
        """Search past session summaries (LIKE over the curated summary text)."""
        query = (query or "").strip()
        like = f"%{query}%"
        with self._lock:
            if query:
                rows = self.conn.execute(
                    "SELECT id, created_at, summary FROM sessions "
                    "WHERE summary IS NOT NULL AND summary != '' AND summary LIKE ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (like, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT id, created_at, summary FROM sessions "
                    "WHERE summary IS NOT NULL AND summary != '' "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # -- cleanup -----------------------------------------------------------

    def clear_facts(self) -> int:
        with self._lock:
            n = self.conn.execute("SELECT count(*) AS c FROM facts").fetchone()["c"]
            self.conn.execute("DELETE FROM facts")
            self.conn.execute("DELETE FROM facts_fts")
            self.conn.commit()
        return int(n)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            ids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM turns WHERE session_id=?", (session_id,)).fetchall()]
            self.conn.executemany("DELETE FROM turns_fts WHERE rowid=?", [(i,) for i in ids])
            self.conn.execute("DELETE FROM turns WHERE session_id=?", (session_id,))
            cur = self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self.conn.commit()
        return cur.rowcount > 0

    def clear_conversations(self) -> int:
        with self._lock:
            n = self.conn.execute("SELECT count(*) AS c FROM turns").fetchone()["c"]
            self.conn.execute("DELETE FROM turns")
            self.conn.execute("DELETE FROM turns_fts")
            self.conn.execute("DELETE FROM sessions")
            self.conn.commit()
        return int(n)

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
