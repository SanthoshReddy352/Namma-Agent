"""Engram store — native semantic memory on Namma's existing SQLite file.

Facts live in ``memory_items`` with **bi-temporal validity** (Zep/Graphiti style):
``valid_from``/``valid_to`` track when a fact was true in the world, while
``created_at``/``expired_at`` track when the system knew it. Contradictions never
delete — the resolver *invalidates* the old fact (``expired_at`` + ``superseded_by``)
so history stays queryable and auditable.

Entities + typed relations (``memory_entities`` / ``memory_relations``) form the
knowledge graph the Memory tab renders. At personal-agent scale plain SQLite joins
cover every graph query the agent makes; no graph database is involved.

The store shares the :class:`~namma_agent.core.memory.Database` connection and lock
(one file, one writer) rather than opening a second connection to the same file.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from namma_agent.core.memory import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
    id            TEXT PRIMARY KEY,
    text          TEXT NOT NULL,
    kind          TEXT DEFAULT 'fact',      -- fact | preference | event | insight
    subject       TEXT DEFAULT '',
    predicate     TEXT DEFAULT '',
    object        TEXT DEFAULT '',
    importance    REAL DEFAULT 0.5,
    frequency     INTEGER DEFAULT 1,
    last_seen     TEXT NOT NULL,
    valid_from    TEXT,
    valid_to      TEXT,
    created_at    TEXT NOT NULL,
    expired_at    TEXT,
    superseded_by TEXT,
    source        TEXT DEFAULT '',
    screen_status TEXT DEFAULT 'ok'         -- ok | flagged (injection) | untrusted (sender)
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(text, subject, object);

CREATE TABLE IF NOT EXISTS memory_entities (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    norm       TEXT UNIQUE NOT NULL,
    type       TEXT DEFAULT 'thing',
    summary    TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_relations (
    id         TEXT PRIMARY KEY,
    src        TEXT NOT NULL,
    rel        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    item_id    TEXT,
    valid_from TEXT,
    valid_to   TEXT,
    created_at TEXT NOT NULL,
    expired_at TEXT
);

-- L1 core memory: bounded curated entries, always injected into the prompt.
CREATE TABLE IF NOT EXISTS core_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    block      TEXT NOT NULL,               -- 'user' | 'agent'
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_memory_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    block      TEXT NOT NULL,
    action     TEXT NOT NULL,               -- add | replace | remove | compact
    text       TEXT NOT NULL,
    at         TEXT NOT NULL
);

-- Consolidator report cards ("Last improved 2 h ago: +4 facts, merged 3 …"),
-- persisted so the Memory tab survives a restart.
CREATE TABLE IF NOT EXISTS consolidation_runs (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    reason TEXT DEFAULT '',                  -- manual | idle | daily
    report TEXT DEFAULT '{}'                 -- JSON step counts
);

-- Optional embedding index (design §5 L3): float32 BLOBs, brute-force cosine
-- in-process — the vector channel of fused recall when an embedder is configured.
CREATE TABLE IF NOT EXISTS memory_vectors (
    item_id  TEXT PRIMARY KEY,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL,
    vec      BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_live ON memory_items(expired_at, kind);
CREATE INDEX IF NOT EXISTS idx_memory_relations_src ON memory_relations(src);
CREATE INDEX IF NOT EXISTS idx_memory_relations_dst ON memory_relations(dst);
"""

#: Columns added after first release — applied with ALTER TABLE when missing
#: (CREATE TABLE IF NOT EXISTS never upgrades an existing table).
_MIGRATIONS = {
    "memory_items": {"archived_at": "TEXT"},   # decay: out of recall, still browsable
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


class EngramStore:
    """DAO over the engram tables, sharing the app Database's connection/lock."""

    def __init__(self, db: Database):
        self.db = db
        self.conn = db.conn
        self._lock = db._lock
        with self._lock:
            self.conn.executescript(_SCHEMA)
            for table, cols in _MIGRATIONS.items():
                have = {r["name"] for r in
                        self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, decl in cols.items():
                    if col not in have:
                        self.conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            self.conn.commit()

    # -- items ---------------------------------------------------------------

    def add_item(self, text: str, kind: str = "fact", subject: str = "",
                 predicate: str = "", object: str = "", importance: float = 0.5,
                 valid_from: Optional[str] = None, source: str = "",
                 screen_status: str = "ok") -> str:
        item_id = str(uuid.uuid4())
        now = _now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO memory_items (id, text, kind, subject, predicate, object, "
                "importance, frequency, last_seen, valid_from, created_at, source, "
                "screen_status) VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?)",
                (item_id, text.strip(), kind, subject.strip(), predicate.strip(),
                 object.strip(), float(importance), now, valid_from, now, source,
                 screen_status),
            )
            # Flagged items are stored (quarantined) but never indexed for recall.
            if screen_status == "ok":
                self.conn.execute(
                    "INSERT INTO memory_items_fts (rowid, text, subject, object) "
                    "VALUES ((SELECT rowid FROM memory_items WHERE id=?),?,?,?)",
                    (item_id, text.strip(), subject.strip(), object.strip()),
                )
            self.conn.commit()
        return item_id

    def get_item(self, item_id: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM memory_items WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def reinforce(self, item_id: str) -> None:
        """A duplicate observation strengthens the existing memory (NOOP op)."""
        with self._lock:
            self.conn.execute(
                "UPDATE memory_items SET frequency=frequency+1, last_seen=? WHERE id=?",
                (_now(), item_id))
            self.conn.commit()

    def invalidate(self, item_id: str, superseded_by: Optional[str] = None) -> bool:
        """Expire a fact (UPDATE/DELETE ops). Never deletes — the FTS row stays so
        ``include_expired`` searches still find it; live searches filter on
        ``expired_at`` instead."""
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "UPDATE memory_items SET expired_at=?, valid_to=COALESCE(valid_to,?), "
                "superseded_by=? WHERE id=? AND expired_at IS NULL",
                (now, now, superseded_by, item_id))
            self.conn.execute(
                "UPDATE memory_relations SET expired_at=?, valid_to=COALESCE(valid_to,?) "
                "WHERE item_id=? AND expired_at IS NULL", (now, now, item_id))
            self.conn.commit()
        return cur.rowcount > 0

    def search_items(self, query: str, limit: int = 8,
                     include_expired: bool = False) -> list[dict]:
        """BM25 search over live facts (FTS5, LIKE fallback — memory.py pattern)."""
        query = (query or "").strip()
        if not query:
            return []
        live = ("" if include_expired
                else "AND m.expired_at IS NULL AND m.archived_at IS NULL ")
        with self._lock:
            try:
                rows = self.conn.execute(
                    f"SELECT m.* FROM memory_items m "
                    f"JOIN memory_items_fts f ON m.rowid = f.rowid "
                    f"WHERE memory_items_fts MATCH ? {live}ORDER BY rank LIMIT ?",
                    (query, limit)).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query}%"
                rows = self.conn.execute(
                    f"SELECT m.* FROM memory_items m WHERE m.text LIKE ? "
                    f"{live}LIMIT ?", (like, limit)).fetchall()
        return [dict(r) for r in rows]

    def similar_items(self, text: str, limit: int = 8) -> list[dict]:
        """Neighbours for the resolver: OR-match on the candidate's words so a
        rephrased fact still finds the memory it contradicts/duplicates."""
        words = [w for w in "".join(c if c.isalnum() else " " for c in text).split()
                 if len(w) > 2][:12]
        if not words:
            return []
        return self.search_items(" OR ".join(words), limit=limit)

    def list_items(self, kind: Optional[str] = None, include_expired: bool = False,
                   limit: int = 500) -> list[dict]:
        """Live items; ``include_expired`` also returns superseded AND archived."""
        where, params = [], []
        if not include_expired:
            where.append("expired_at IS NULL")
            where.append("archived_at IS NULL")
        if kind:
            where.append("kind=?"); params.append(kind)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM memory_items {clause} ORDER BY last_seen DESC LIMIT ?",
                tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def quarantined_items(self, limit: int = 100) -> list[dict]:
        """Memory items held out of recall by screening: injection-flagged
        ('flagged') and untrusted-sender ('untrusted') writes, newest first —
        the Security tab's memory-quarantine section."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, kind, source, screen_status, created_at "
                "FROM memory_items WHERE screen_status != 'ok' "
                "ORDER BY created_at DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        with self._lock:
            items = self.conn.execute(
                "SELECT count(*) AS c FROM memory_items "
                "WHERE expired_at IS NULL AND archived_at IS NULL").fetchone()["c"]
            entities = self.conn.execute(
                "SELECT count(*) AS c FROM memory_entities").fetchone()["c"]
            relations = self.conn.execute(
                "SELECT count(*) AS c FROM memory_relations WHERE expired_at IS NULL").fetchone()["c"]
        return {"items": int(items), "entities": int(entities), "relations": int(relations)}

    # -- vectors (optional embedding channel) -------------------------------------

    def add_vector(self, item_id: str, model: str, vec: list[float]) -> None:
        from namma_agent.core.engram.embeddings import to_blob
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_vectors (item_id, model, dim, vec) "
                "VALUES (?,?,?,?)", (item_id, model, len(vec), to_blob(vec)))
            self.conn.commit()

    def vector_count(self, model: Optional[str] = None) -> int:
        with self._lock:
            if model:
                row = self.conn.execute(
                    "SELECT count(*) AS c FROM memory_vectors WHERE model=?",
                    (model,)).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT count(*) AS c FROM memory_vectors").fetchone()
        return int(row["c"])

    def items_missing_vectors(self, model: str, limit: int = 200) -> list[dict]:
        """Live, clean items with no embedding yet — the backfill work list."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT m.* FROM memory_items m "
                "LEFT JOIN memory_vectors v ON v.item_id = m.id AND v.model = ? "
                "WHERE v.item_id IS NULL AND m.expired_at IS NULL "
                "AND m.archived_at IS NULL AND m.screen_status = 'ok' LIMIT ?",
                (model, limit)).fetchall()
        return [dict(r) for r in rows]

    def vector_search(self, query_vec: list[float], model: str, limit: int = 8,
                      include_expired: bool = False) -> list[dict]:
        """Brute-force cosine over the stored vectors (personal-agent scale) —
        best matches first, each item dict carrying a ``vscore``."""
        from namma_agent.core.engram.embeddings import cosine, from_blob
        live = ("" if include_expired
                else "AND m.expired_at IS NULL AND m.archived_at IS NULL ")
        with self._lock:
            rows = self.conn.execute(
                f"SELECT m.*, v.vec AS _vec FROM memory_vectors v "
                f"JOIN memory_items m ON m.id = v.item_id "
                f"WHERE v.model = ? {live}", (model,)).fetchall()
        scored = []
        for r in rows:
            d = dict(r)
            score = cosine(query_vec, from_blob(d.pop("_vec")))
            if score > 0:
                d["vscore"] = score
                scored.append(d)
        scored.sort(key=lambda d: d["vscore"], reverse=True)
        return scored[:limit]

    # -- graph -----------------------------------------------------------------

    def upsert_entity(self, name: str, type: str = "thing") -> str:
        norm = _norm(name)
        if not norm:
            return ""
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM memory_entities WHERE norm=?", (norm,)).fetchone()
            if row:
                return row["id"]
            eid = str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO memory_entities (id, name, norm, type, created_at) "
                "VALUES (?,?,?,?,?)", (eid, name.strip(), norm, type, _now()))
            self.conn.commit()
        return eid

    def add_relation(self, src_name: str, rel: str, dst_name: str,
                     item_id: Optional[str] = None,
                     valid_from: Optional[str] = None) -> Optional[str]:
        src, dst = self.upsert_entity(src_name), self.upsert_entity(dst_name)
        rel = _norm(rel).replace(" ", "_")
        if not (src and dst and rel):
            return None
        with self._lock:
            rid = str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO memory_relations (id, src, rel, dst, item_id, valid_from, "
                "created_at) VALUES (?,?,?,?,?,?,?)",
                (rid, src, rel, dst, item_id, valid_from, _now()))
            self.conn.commit()
        return rid

    def entity_items(self, names: list[str], limit: int = 6) -> list[dict]:
        """Live facts attached (via graph edges) to any of the named entities —
        the 1-hop neighbourhood expansion used by recall."""
        norms = [_norm(n) for n in names if _norm(n)]
        if not norms:
            return []
        ph = ",".join("?" * len(norms))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT DISTINCT m.* FROM memory_items m "
                f"JOIN memory_relations r ON r.item_id = m.id "
                f"JOIN memory_entities e ON e.id IN (r.src, r.dst) "
                f"WHERE e.norm IN ({ph}) AND m.expired_at IS NULL "
                f"AND m.archived_at IS NULL "
                f"AND r.expired_at IS NULL ORDER BY m.importance DESC LIMIT ?",
                (*norms, limit)).fetchall()
        return [dict(r) for r in rows]

    def entity_names(self) -> list[str]:
        with self._lock:
            rows = self.conn.execute("SELECT norm FROM memory_entities").fetchall()
        return [r["norm"] for r in rows]

    def graph(self, include_expired: bool = False,
              as_of: Optional[str] = None) -> dict:
        """{nodes, edges} for the Memory tab's force layout.

        ``as_of`` (ISO timestamp) time-travels: only edges/entities the system
        knew at that moment and that had not yet been invalidated — the Memory
        tab's history slider is just this query."""
        params: list = []
        if as_of:
            where = ("WHERE r.created_at <= ? "
                     "AND (r.expired_at IS NULL OR r.expired_at > ?)")
            params = [as_of, as_of]
        else:
            where = "" if include_expired else "WHERE r.expired_at IS NULL"
        with self._lock:
            if as_of:
                nodes = [dict(r) for r in self.conn.execute(
                    "SELECT id, name, type, summary FROM memory_entities "
                    "WHERE created_at <= ?", (as_of,)).fetchall()]
            else:
                nodes = [dict(r) for r in self.conn.execute(
                    "SELECT id, name, type, summary FROM memory_entities").fetchall()]
            edges = [dict(r) for r in self.conn.execute(
                f"SELECT r.src, r.rel, r.dst, r.expired_at FROM memory_relations r "
                f"{where}", tuple(params)).fetchall()]
        return {"nodes": nodes, "edges": edges}

    # -- consolidation helpers ---------------------------------------------------

    def archive(self, item_id: str) -> None:
        """Decay: drop an item out of recall but keep it browsable (reversible —
        unlike invalidate, nothing supersedes it and validity is untouched)."""
        with self._lock:
            self.conn.execute(
                "UPDATE memory_items SET archived_at=? WHERE id=? AND archived_at IS NULL",
                (_now(), item_id))
            self.conn.commit()

    def merge_triple_duplicates(self) -> int:
        """Fold live facts asserting the same (subject, predicate, object) triple
        into one, even when the sentence wording differs. Newest survives with the
        summed frequency; the rest are invalidated (history kept)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, subject, predicate, object, frequency FROM memory_items "
                "WHERE expired_at IS NULL AND archived_at IS NULL "
                "AND subject != '' AND predicate != '' AND object != '' "
                "ORDER BY created_at DESC").fetchall()
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            # snake_case and spaced predicates ("studies_at" / "Studies At")
            # assert the same relation — normalize both to one form.
            key = (_norm(r["subject"]),
                   _norm(r["predicate"].replace("_", " ")),
                   _norm(r["object"]))
            groups.setdefault(key, []).append(dict(r))
        merged = 0
        for dupes in groups.values():
            if len(dupes) < 2:
                continue
            keeper, rest = dupes[0], dupes[1:]
            extra = sum(int(d["frequency"] or 1) for d in rest)
            with self._lock:
                self.conn.execute(
                    "UPDATE memory_items SET frequency=frequency+? WHERE id=?",
                    (extra, keeper["id"]))
                self.conn.commit()
            for d in rest:
                self.invalidate(d["id"], superseded_by=keeper["id"])
                merged += 1
        return merged

    def record_consolidation(self, report: dict, reason: str = "manual") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO consolidation_runs (at, reason, report) VALUES (?,?,?)",
                (_now(), reason, json.dumps(report, ensure_ascii=False)))
            self.conn.commit()

    def latest_consolidation(self) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT at, reason, report FROM consolidation_runs "
                "ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        try:
            report = json.loads(row["report"] or "{}")
        except ValueError:
            report = {}
        return {"at": row["at"], "reason": row["reason"], **report}

    def first_memory_at(self) -> Optional[str]:
        """Earliest fact timestamp — the left edge of the time-travel slider."""
        with self._lock:
            row = self.conn.execute(
                "SELECT MIN(created_at) AS t FROM memory_items").fetchone()
        return row["t"] if row and row["t"] else None

    def merge_exact_duplicates(self) -> int:
        """Fold live facts with identical normalized text into one: the newest
        survives with the summed frequency; the others are invalidated (never
        deleted — bi-temporal history stays queryable). Returns how many were
        folded away."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, frequency, created_at FROM memory_items "
                "WHERE expired_at IS NULL AND archived_at IS NULL "
                "ORDER BY created_at DESC").fetchall()
        groups: dict[str, list[dict]] = {}
        for r in rows:
            key = " ".join(r["text"].lower().split())
            groups.setdefault(key, []).append(dict(r))
        merged = 0
        for dupes in groups.values():
            if len(dupes) < 2:
                continue
            keeper, rest = dupes[0], dupes[1:]
            extra = sum(int(d["frequency"] or 1) for d in rest)
            with self._lock:
                self.conn.execute(
                    "UPDATE memory_items SET frequency=frequency+? WHERE id=?",
                    (extra, keeper["id"]))
                self.conn.commit()
            for d in rest:
                self.invalidate(d["id"], superseded_by=keeper["id"])
                merged += 1
        return merged

    # -- forgetting --------------------------------------------------------------

    def forget_matching(self, query: str, hard: bool = False) -> int:
        """Invalidate (default) or hard-delete every live fact matching a query."""
        hits = self.search_items(query, limit=100)
        for h in hits:
            if hard:
                self.hard_delete(h["id"])
            else:
                self.invalidate(h["id"])
        return len(hits)

    def hard_delete(self, item_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM memory_items_fts WHERE rowid="
                "(SELECT rowid FROM memory_items WHERE id=?)", (item_id,))
            self.conn.execute("DELETE FROM memory_relations WHERE item_id=?", (item_id,))
            self.conn.execute("DELETE FROM memory_vectors WHERE item_id=?", (item_id,))
            self.conn.execute("DELETE FROM memory_items WHERE id=?", (item_id,))
            # Entities exist only as relation endpoints — drop any left orphaned
            # so hard-deleted facts don't leave floating nodes in the graph view.
            self.conn.execute(
                "DELETE FROM memory_entities WHERE id NOT IN "
                "(SELECT src FROM memory_relations UNION SELECT dst FROM memory_relations)")
            self.conn.commit()

    def wipe(self) -> dict:
        """Erase everything (the danger-zone / clear_memory path)."""
        with self._lock:
            n = self.conn.execute("SELECT count(*) AS c FROM memory_items").fetchone()["c"]
            for t in ("memory_items", "memory_items_fts", "memory_entities",
                      "memory_relations", "memory_vectors", "core_memory",
                      "core_memory_history", "consolidation_runs"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()
        return {"items": int(n)}

    # -- core memory (rows; rendering/budgets live in core_memory.py) -------------

    def core_entries(self, block: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, text, updated_at FROM core_memory WHERE block=? ORDER BY id",
                (block,)).fetchall()
        return [dict(r) for r in rows]

    def core_add(self, block: str, text: str) -> int:
        now = _now()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO core_memory (block, text, created_at, updated_at) "
                "VALUES (?,?,?,?)", (block, text.strip(), now, now))
            self.conn.execute(
                "INSERT INTO core_memory_history (block, action, text, at) "
                "VALUES (?,?,?,?)", (block, "add", text.strip(), now))
            self.conn.commit()
        return cur.lastrowid

    def core_update(self, entry_id: int, text: str) -> None:
        now = _now()
        with self._lock:
            self.conn.execute(
                "UPDATE core_memory SET text=?, updated_at=? WHERE id=?",
                (text.strip(), now, entry_id))
            self.conn.execute(
                "INSERT INTO core_memory_history (block, action, text, at) "
                "SELECT block, 'replace', ?, ? FROM core_memory WHERE id=?",
                (text.strip(), now, entry_id))
            self.conn.commit()

    def core_remove(self, entry_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO core_memory_history (block, action, text, at) "
                "SELECT block, 'remove', text, ? FROM core_memory WHERE id=?",
                (_now(), entry_id))
            self.conn.execute("DELETE FROM core_memory WHERE id=?", (entry_id,))
            self.conn.commit()


def dumps_compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
