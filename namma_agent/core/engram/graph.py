"""Engram graph primitives (Phase 10) — entities, relations, schema, ranking.

The knowledge graph is DERIVED from facts: every live fact with a
subject/predicate/object triple contributes one typed, directed relation (or
one entity attribute). The graph is never a second source of truth — it can be
rebuilt from ``memory_items`` at any time (:meth:`MemoryGraph.rebuild`), which
is also how existing data is migrated.

Data model
----------
* **Entity** (``memory_entities``) — ``norm`` is the canonical key (stable id =
  uuid5 of it), ``name`` the display name (most-used surface form; the user's
  own name for the self entity), ``type`` from a small canonical vocabulary
  (anything else is kept as-is, so the schema reflects real data), ``aliases``
  the surface forms seen with counts, ``is_self`` for the user.
* **Alias** (``memory_entity_aliases``) — every lookup key → the entity it
  resolves to. ``source`` is ``auto`` (rebuilt), ``name`` (from a has_name
  fact) or ``manual`` (a user merge — survives rebuilds).
* **Relation** (``memory_relations``) — canonical snake_case ``rel``, ``src`` →
  ``dst`` (direction is meaningful; symmetric predicates are deduped in either
  direction), ``confidence`` (noisy-OR over supporting facts), bi-temporal
  ``valid_from`` / ``created_at`` / ``expired_at`` and ``superseded_by`` (the
  relation that replaced it). One row per live (src, rel, dst); every fact that
  asserts it is a row in ``memory_relation_sources``.
* **Attribute** (``memory_attributes``) — literal values (age, a date, a long
  description) hang off an entity instead of becoming fake nodes. Same
  lifecycle as relations.

Resolution (:func:`canonical_key`, :meth:`MemoryGraph.resolve`)
---------------------------------------------------------------
case/whitespace/article/possessive folding, "Full Name (ACRONYM)" → both keys,
generic suffixes ("Namma Agent project" → "namma agent"), first-person and
"the user" → the self entity, and has_name facts make the user's name an alias
of the self entity (merging a node that was created under that name earlier).

Contradictions
--------------
A new relation on a *functional* predicate (lives_in, studies_at, …) with a
different object supersedes the old one; ``likes`` ⇄ ``dislikes`` on the same
pair supersede each other. Supersession never deletes — the old relation keeps
its row with ``expired_at`` + ``superseded_by`` so time travel still sees it.

Ranking (:meth:`MemoryGraph.ranked`) — documented in PROGRESS.md Phase 10
------------------------------------------------------------------------
``score = 0.45·centrality + 0.30·salience + 0.25·recency`` where
centrality = weighted PageRank over live relations (normalised to the max),
salience = 0.7·max importance of supporting facts + 0.3·min(1, log2(1+mentions)/4),
recency = 0.5 ** (days since the newest supporting fact was seen / half-life).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

GRAPH_VERSION = 2
_NS = uuid.UUID("6f1c2a9e-5b0d-4c3e-9a51-0e7d3b8f4a10")

SELF_NORM = "user"
SELF_KEYS = frozenset({
    "user", "the user", "users", "i", "me", "my", "myself", "mine", "owner",
    "the owner", "user s", "the user s", "the human",
})
# Bare pronouns that never name a resolvable entity on their own.
_UNRESOLVABLE = frozenset({
    "he", "she", "they", "it", "him", "her", "them", "this", "that", "someone",
    "somebody", "something", "we", "us", "you", "your",
})
_ARTICLES = ("the ", "a ", "an ", "my ", "our ", "his ", "her ", "their ", "its ")
# Generic trailing words that don't change WHICH thing is meant.
_GENERIC_SUFFIXES = (
    " programming language", " language", " project", " app", " application",
    " framework", " library", " company", " inc", " ltd", " exam", " city",
)

# Suffixes dropped from the DISPLAY name too ("Namma Agent project" → "Namma
# Agent"); "GATE exam" keeps its word — there it is part of the name.
_DISPLAY_SUFFIXES = (" programming language", " project", " app", " application")

# ── types ──────────────────────────────────────────────────────────────────
CANONICAL_TYPES = ("person", "organization", "place", "project", "technology",
                   "animal", "event", "concept", "product")
_TYPE_SYNONYMS = {
    "people": "person", "human": "person", "individual": "person", "user": "person",
    "family": "person", "family member": "person", "friend": "person",
    "relative": "person", "colleague": "person", "self": "person",
    "company": "organization", "org": "organization", "organisation": "organization",
    "university": "organization", "college": "organization", "school": "organization",
    "institution": "organization", "hospital": "organization", "employer": "organization",
    "team": "organization", "business": "organization", "institute": "organization",
    "city": "place", "country": "place", "location": "place", "state": "place",
    "town": "place", "region": "place", "address": "place", "village": "place",
    "repo": "project", "repository": "project", "application": "project",
    "app": "project", "startup": "project",
    "tool": "technology", "language": "technology", "programming language": "technology",
    "framework": "technology", "library": "technology", "software": "technology",
    "editor": "technology", "database": "technology", "platform": "technology",
    "tech": "technology", "os": "technology", "operating system": "technology",
    "pet": "animal", "dog": "animal", "cat": "animal",
    "exam": "event", "meeting": "event", "deadline": "event", "trip": "event",
    "appointment": "event", "milestone": "event",
    "idea": "concept", "topic": "concept", "subject": "concept", "hobby": "concept",
    "interest": "concept", "skill": "concept", "preference": "concept",
    "setting": "concept", "field": "concept", "activity": "concept",
    "device": "product", "book": "product", "movie": "product", "game": "product",
    "vehicle": "product",
}
_GENERIC_TYPES = frozenset({"", "thing", "entity", "object", "other", "unknown",
                            "concept", "none", "null"})
_TECH_LEXICON = frozenset("""
python java javascript typescript react fastapi django flask rust go golang c c++ cpp
c# csharp kotlin swift ruby php node node.js nodejs vs code vscode visual studio code
docker kubernetes linux windows macos git github gitlab sql sqlite postgres postgresql
mysql mongodb redis pytorch tensorflow electron vite tailwind tailwindcss vue angular
svelte next.js nextjs numpy pandas scikit-learn langchain openai anthropic claude
gemini ollama neovim vim emacs bash powershell html css aws azure gcp firebase
supabase figma jupyter matlab r scala haskell elixir dart flutter unity unreal
""".split()) | {"vs code", "visual studio code", "node.js", "scikit learn"}

# ── predicates ─────────────────────────────────────────────────────────────
_PRED_SYNONYMS = {
    "love": "likes", "loves": "likes", "like": "likes", "enjoys": "likes",
    "enjoy": "likes", "is_fond_of": "likes", "fond_of": "likes",
    "likes_a_lot": "likes", "really_likes": "likes", "is_passionate_about": "likes",
    "hates": "dislikes", "dislike": "dislikes", "does_not_like": "dislikes",
    "doesnt_like": "dislikes", "hate": "dislikes",
    "prefer": "prefers", "favors": "prefers", "favours": "prefers",
    "prefers_using": "prefers",
    "is_building": "works_on", "building": "works_on", "builds": "works_on",
    "build": "works_on", "develops": "works_on", "is_developing": "works_on",
    "working_on": "works_on", "is_working_on": "works_on", "work_on": "works_on",
    "maintains": "works_on", "contributes_to": "works_on",
    "works_for": "works_at", "employed_at": "works_at", "employed_by": "works_at",
    "job_at": "works_at", "work_at": "works_at", "is_employed_at": "works_at",
    "student_at": "studies_at", "attends": "studies_at", "studying_at": "studies_at",
    "is_student_at": "studies_at", "goes_to": "studies_at", "enrolled_at": "studies_at",
    "studies_in": "studies_at", "is_studying_at": "studies_at", "study_at": "studies_at",
    "resides_in": "lives_in", "lives_at": "lives_in", "based_in": "lives_in",
    "living_in": "lives_in", "stays_in": "lives_in", "is_based_in": "lives_in",
    "live_in": "lives_in", "moved_to": "lives_in", "is_living_in": "lives_in",
    "is_from": "from", "hails_from": "from", "comes_from": "from", "native_of": "from",
    "originally_from": "from",
    "built_with": "uses", "uses_tool": "uses", "built_using": "uses",
    "written_in": "uses", "powered_by": "uses", "made_with": "uses", "use": "uses",
    "using": "uses", "is_using": "uses", "depends_on": "uses", "runs_on": "uses",
    "is": "is_a", "is_an": "is_a", "type_of": "is_a", "kind_of": "is_a",
    "job_title": "works_as", "role": "works_as", "is_working_as": "works_as",
    "profession": "works_as", "occupation": "works_as",
    "friends_with": "friend_of", "has_friend": "friend_of", "is_friend_of": "friend_of",
    "collaborates_with": "works_with", "colleague_of": "works_with",
    "coworker_of": "works_with", "teammate_of": "works_with",
    "owns_pet": "has_pet", "pet": "has_pet", "has_dog": "has_pet", "has_cat": "has_pet",
    "meets": "meeting_with", "meeting": "meeting_with", "has_meeting_with": "meeting_with",
    "studying_for": "preparing_for", "prepares_for": "preparing_for",
    "is_preparing_for": "preparing_for",
    "spouse_of": "married_to", "is_married_to": "married_to", "wife_of": "married_to",
    "husband_of": "married_to",
}
# Passive/inverse spellings → (canonical, flip direction).
_PRED_INVERSE = {
    "employs": "works_at", "owned_by": "owns", "used_by": "uses",
    "created_by": "created", "built_by": "works_on", "developed_by": "works_on",
    "pet_of": "has_pet", "sister_of": "has_sister", "brother_of": "has_brother",
    "mother_of": "has_child", "father_of": "has_child", "parent_of": "has_child",
    "attended_by": "studies_at", "home_of": "lives_in",
}
SYMMETRIC = frozenset({"works_with", "friend_of", "married_to", "sibling_of",
                       "knows", "related_to"})
# One live object per subject at a time — a new one supersedes the old.
FUNCTIONAL = frozenset({"lives_in", "studies_at", "born_in", "from", "married_to",
                        "works_as"})
OPPOSITES = {"likes": "dislikes", "dislikes": "likes"}
NAME_PREDICATES = frozenset({"has_name", "name", "name_is", "is_named", "named",
                             "called", "is_called", "goes_by", "known_as", "nickname"})
ATTRIBUTE_PREDICATES = frozenset({
    "age", "birthday", "born_on", "date_of_birth", "dob", "email", "phone",
    "phone_number", "height", "weight", "gender", "pronouns", "blood_type",
    "salary", "gpa", "cgpa", "grade", "year", "timezone", "website", "handle",
    "username", "version",
})
# Range (object type) / domain (subject type) implied by a predicate — used
# only when the model gave no type.
_RANGE = {
    "studies_at": "organization", "works_at": "organization", "lives_in": "place",
    "from": "place", "born_in": "place", "visited": "place", "located_in": "place",
    "works_on": "project", "created": "project", "has_pet": "animal",
    "has_sister": "person", "has_brother": "person", "has_child": "person",
    "has_mother": "person", "has_father": "person", "has_sibling": "person",
    "friend_of": "person", "works_with": "person", "knows": "person",
    "meeting_with": "person", "married_to": "person", "sibling_of": "person",
    "preparing_for": "event", "attending": "event", "uses": "technology",
    "member_of": "organization", "owns": "product", "works_as": "concept",
}
_DOMAIN = {
    "studies_at": "person", "works_at": "person", "lives_in": "person",
    "has_pet": "person", "has_sister": "person", "has_brother": "person",
    "friend_of": "person", "works_with": "person", "married_to": "person",
    "preparing_for": "person", "works_as": "person", "meeting_with": "person",
    "works_on": "person", "likes": "person", "dislikes": "person",
    "prefers": "person", "knows": "person", "has_child": "person",
}

_LITERAL_RE = re.compile(
    r"^(?:[-+]?\d+(?:[.,]\d+)?(?:\s*(?:years?(?:\s+old)?|yrs?|y/o|kg|lbs?|cm|m|km|"
    r"%|ft|inches|hours?|days?|months?|weeks?))?|\d{4}-\d{2}-\d{2}(?:[t ][\d:.]+z?)?|"
    r"(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"\.?(?:\s+\d{1,2})?(?:,?\s+\d{4})?|true|false|yes|no|[^@\s]+@[^@\s]+\.\w+|"
    r"https?://\S+)$", re.IGNORECASE)
_STOP = frozenset("""a an the of and or to for with in on at by from as is are be
only all any some very not no into about than then that this those these""".split())

#: Base confidence of one supporting fact when the model gave none.
SOURCE_CONFIDENCE = {"manual": 0.9, "learning": 0.85, "consolidator": 0.6}
DEFAULT_CONFIDENCE = 0.7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entity_aliases (
    alias   TEXT PRIMARY KEY,
    norm    TEXT NOT NULL,
    source  TEXT DEFAULT 'auto'
);
CREATE TABLE IF NOT EXISTS memory_relation_sources (
    relation_id TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    confidence  REAL DEFAULT 0.7,
    PRIMARY KEY (relation_id, item_id)
);
CREATE TABLE IF NOT EXISTS memory_attributes (
    id         TEXT PRIMARY KEY,
    entity     TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    item_id    TEXT,
    created_at TEXT NOT NULL,
    expired_at TEXT
);
CREATE TABLE IF NOT EXISTS memory_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_mem_rel_sources_item ON memory_relation_sources(item_id);
CREATE INDEX IF NOT EXISTS idx_mem_attr_entity ON memory_attributes(entity);
CREATE INDEX IF NOT EXISTS idx_mem_alias_norm ON memory_entity_aliases(norm);
"""

#: Columns the graph adds to the pre-Phase-10 tables.
MIGRATIONS = {
    "memory_entities": {"aliases": "TEXT DEFAULT '{}'", "type_source": "TEXT",
                        "is_self": "INTEGER DEFAULT 0", "updated_at": "TEXT"},
    "memory_relations": {"confidence": "REAL DEFAULT 0.7", "superseded_by": "TEXT"},
    "memory_items": {"subject_type": "TEXT", "object_type": "TEXT"},
}


# ── pure helpers (unit-tested directly) ──────────────────────────────────────

def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip().lower()
    text = text.replace("’", "'").replace("_", " ")
    return " ".join(text.split())


def canonical_key(name: str) -> str:
    """The lookup key for an entity surface form: case/space/article/possessive
    folded. "The User's" → "user"; "  Namma   Agent " → "namma agent"."""
    # "A Kumar" / "A. R. Rahman": a capital initial, not the article "a".
    initial = bool(re.match(r"^\s*(?:A|An)\.?\s+[A-Z]", name or ""))
    key = _fold(name).strip(" \"'`.,;:!?()[]{}")
    if key.endswith("'s"):
        key = key[:-2]
    elif key.endswith("s'"):
        key = key[:-1]
    changed = True
    while changed:
        changed = False
        for art in _ARTICLES:
            if initial and art in ("a ", "an "):
                continue
            if key.startswith(art) and len(key) > len(art):
                key = key[len(art):]
                changed = True
    key = key.replace("'", " ").strip(" -")
    return " ".join(key.split())


def match_keys(name: str) -> list[str]:
    """Every key a surface form may resolve under, most specific first:
    the full key, the acronym in "Name (ACR)", the name without it, and the
    name without a generic suffix."""
    raw = (name or "").strip()
    out: list[str] = []

    def add(k: str) -> None:
        if k and k not in out:
            out.append(k)

    m = re.match(r"^(.*?)\s*\(([^()]{1,40})\)\s*$", raw)
    if m:
        main = canonical_key(m.group(1))
        add(main)
        add(canonical_key(m.group(2)))
    else:
        add(canonical_key(raw))
    for k in list(out):
        for suffix in _GENERIC_SUFFIXES:
            if k.endswith(suffix) and len(k) - len(suffix) >= 2:
                add(k[: -len(suffix)].strip())
    return out


def display_surface(name: str) -> str:
    """The surface form to show: "Name (ACR)" keeps the long name, articles go."""
    raw = " ".join((name or "").strip().split())
    m = re.match(r"^(.*?)\s*\(([^()]{1,40})\)\s*$", raw)
    if m and m.group(1).strip():
        raw = m.group(1).strip()
    low = raw.lower()
    for art in ("the ", "a ", "an "):
        if low.startswith(art) and len(raw) > len(art):
            # "a dog" loses its article; "A Kumar" (an initial) keeps it.
            if art != "the " and raw[len(art):][:1].isupper():
                break
            raw = raw[len(art):]
            break
    raw = raw.strip(" \"'`.,;:!?")
    low = raw.lower()
    for suffix in _DISPLAY_SUFFIXES:
        if low.endswith(suffix) and len(raw) - len(suffix) >= 2:
            raw = raw[: -len(suffix)].rstrip()
            break
    return raw


def canonical_predicate(pred: str) -> tuple[str, bool]:
    """(canonical snake_case predicate, flip direction?)."""
    key = re.sub(r"[^a-z0-9]+", "_", _fold(pred)).strip("_")
    if not key:
        return "", False
    if key in _PRED_INVERSE:
        return _PRED_INVERSE[key], True
    return _PRED_SYNONYMS.get(key, key), False


def canonical_type(t: Optional[str]) -> Optional[str]:
    """Map a model-given type onto the vocabulary; unknown words pass through
    (lower-case) so the schema reflects the data; generic → None."""
    key = _fold(t or "").strip(" .")
    if key in _GENERIC_TYPES:
        return None
    if key in CANONICAL_TYPES:
        return key
    if key in _TYPE_SYNONYMS:
        return _TYPE_SYNONYMS[key]
    if key.endswith("s") and key[:-1] in CANONICAL_TYPES:
        return key[:-1]
    return key or None


def is_literal(value: str) -> bool:
    """Numbers, dates, durations, booleans, emails, URLs — values, not things."""
    return bool(_LITERAL_RE.match((value or "").strip()))


def is_description(value: str) -> bool:
    """A lower-case clause ("read-only repositories and issues only") rather
    than a name. Title-cased multi-word names stay entities."""
    words = (value or "").split()
    if len(value or "") > 60:
        return True
    if len(words) < 4:
        return False
    content = [w for w in words if w.lower() not in _STOP]
    capped = sum(1 for w in content if w[:1].isupper())
    return capped < max(1, len(content) // 2)


def infer_type(key: str, pred: str = "", role: str = "object") -> str:
    """Best guess when the model gave no type: self → person, a known
    technology, the predicate's range/domain, else concept."""
    if key == SELF_NORM or key in SELF_KEYS:
        return "person"
    if key in _TECH_LEXICON:
        return "technology"
    table = _RANGE if role == "object" else _DOMAIN
    return table.get(pred, "concept")


def _now_default() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(ts: Optional[str], now: datetime) -> float:
    if not ts:
        return 365.0
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return 365.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0.0, (now - t).total_seconds() / 86400.0)


def pagerank(nodes: list[str], edges: list[tuple[str, str, float]],
             damping: float = 0.85, iterations: int = 40) -> dict[str, float]:
    """Weighted PageRank on the UNDIRECTED view of the graph (a hub is central
    whichever way its relations point). Pure python — personal-agent scale."""
    n = len(nodes)
    if not n:
        return {}
    nbrs: dict[str, dict[str, float]] = {v: {} for v in nodes}
    for a, b, w in edges:
        if a in nbrs and b in nbrs and a != b:
            nbrs[a][b] = nbrs[a].get(b, 0.0) + w
            nbrs[b][a] = nbrs[b].get(a, 0.0) + w
    out_w = {v: sum(d.values()) for v, d in nbrs.items()}
    rank = {v: 1.0 / n for v in nodes}
    for _ in range(iterations):
        dangling = sum(rank[v] for v in nodes if out_w[v] == 0)
        new = {}
        for v in nodes:
            s = sum(rank[u] * w / out_w[u] for u, w in nbrs[v].items() if out_w[u])
            new[v] = (1 - damping) / n + damping * (s + dangling / n)
        rank = new
    return rank


class MemoryGraph:
    """Graph primitives over the engram tables (shares the store's connection
    and lock). Built by :class:`~namma_agent.core.engram.store.EngramStore`."""

    def __init__(self, store, now: Callable[[], str] = _now_default):
        self.store = store
        self.conn = store.conn
        self._lock = store._lock
        self._now = now
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()
        if self._version() < GRAPH_VERSION:
            self.rebuild()

    # -- meta -------------------------------------------------------------------

    def _version(self) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM memory_meta WHERE key='graph_version'").fetchone()
        try:
            return int(row["value"]) if row else 0
        except (TypeError, ValueError):
            return 0

    def _set_version(self, v: int) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_meta (key, value) VALUES ('graph_version', ?)",
                (str(v),))
            self.conn.commit()

    def _locked_name(self, norm: str) -> Optional[str]:
        """A display name the user chose (rename / merge) — survives rebuilds."""
        with self._lock:
            row = self.conn.execute("SELECT value FROM memory_meta WHERE key=?",
                                    (f"name:{norm}",)).fetchone()
        return row["value"] if row else None

    def _lock_name(self, norm: str, name: str) -> None:
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO memory_meta (key, value) VALUES (?,?)",
                              (f"name:{norm}", name))

    # -- entities ---------------------------------------------------------------

    @staticmethod
    def entity_id(norm: str) -> str:
        return str(uuid.uuid5(_NS, norm))

    def lookup(self, name: str) -> Optional[str]:
        """The canonical norm a surface form resolves to, or None (no create)."""
        keys = match_keys(name)
        if not keys:
            return None
        if keys[0] in SELF_KEYS:
            return SELF_NORM
        with self._lock:
            for k in keys:
                row = self.conn.execute(
                    "SELECT norm FROM memory_entity_aliases WHERE alias=?", (k,)).fetchone()
                if row:
                    return row["norm"]
                row = self.conn.execute(
                    "SELECT norm FROM memory_entities WHERE norm=?", (k,)).fetchone()
                if row:
                    return row["norm"]
        return None

    def resolve(self, name: str, type: Optional[str] = None, *, pred: str = "",
                role: str = "object", type_source: str = "model",
                at: Optional[str] = None) -> Optional[str]:
        """Resolve a surface form to an entity id, creating it when new.
        Returns None for bare pronouns / empty names."""
        keys = match_keys(name)
        if not keys or keys[0] in _UNRESOLVABLE:
            return None
        at = at or self._now()
        norm = self.lookup(name)
        surface = display_surface(name)
        new_type = canonical_type(type)
        tsrc = type_source if new_type else "inferred"
        if norm is None:
            norm = keys[0]
            if not new_type:
                new_type = infer_type(norm, pred, role)
        is_self = norm == SELF_NORM
        if is_self:
            new_type, tsrc = "person", "self"
        eid = self.entity_id(norm)
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM memory_entities WHERE norm=?", (norm,)).fetchone()
            if row is None:
                aliases = {} if is_self else {surface: 1}
                self.conn.execute(
                    "INSERT INTO memory_entities (id, name, norm, type, summary, "
                    "created_at, aliases, type_source, is_self, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (eid, "You" if is_self else (self._locked_name(norm) or surface), norm,
                     new_type or infer_type(norm, pred, role), "", at,
                     json.dumps(aliases, ensure_ascii=False), tsrc,
                     1 if is_self else 0, at))
            else:
                eid = row["id"]
                self._touch_entity(dict(row), surface, new_type, tsrc, at)
            for k in keys:
                if k in SELF_KEYS and not is_self:
                    continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO memory_entity_aliases (alias, norm, source) "
                    "VALUES (?,?,'auto')", (k, norm))
            self.conn.commit()
        return eid

    def _touch_entity(self, row: dict, surface: str, new_type: Optional[str],
                      tsrc: str, at: str) -> None:
        """Count a surface sighting, re-pick the display name, upgrade the type
        (lock held by caller)."""
        try:
            aliases = json.loads(row.get("aliases") or "{}") or {}
        except ValueError:
            aliases = {}
        if row.get("is_self"):
            name = row["name"]
        else:
            if surface and canonical_key(surface) not in SELF_KEYS:
                aliases[surface] = int(aliases.get(surface, 0)) + 1
            name = (self._locked_name(row["norm"]) or _pick_name(aliases)
                    or row["name"])
        etype, esrc = row.get("type") or "concept", row.get("type_source") or "inferred"
        if new_type and not row.get("is_self"):
            if etype in _GENERIC_TYPES or (esrc == "inferred" and tsrc == "model"):
                etype, esrc = new_type, tsrc
        self.conn.execute(
            "UPDATE memory_entities SET name=?, aliases=?, type=?, type_source=?, "
            "updated_at=? WHERE id=?",
            (name, json.dumps(aliases, ensure_ascii=False), etype, esrc, at, row["id"]))

    def add_alias(self, entity_id: str, alias: str, source: str = "name") -> None:
        """Make ``alias`` resolve to ``entity_id``; an entity that already
        lives under that key is merged in (e.g. a node first created as
        "Santhosh" before we learned that is the user's name)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT norm FROM memory_entities WHERE id=?", (entity_id,)).fetchone()
        if not row:
            return
        target = row["norm"]
        for k in match_keys(alias)[:1]:
            if k in SELF_KEYS or k in _UNRESOLVABLE:
                continue
            other = self.lookup(alias)
            if other and other != target:
                self.merge(self.entity_id_for_norm(other), entity_id, source=source)
            with self._lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO memory_entity_aliases (alias, norm, source) "
                    "VALUES (?,?,?)", (k, target, source))
                self.conn.commit()

    def entity_id_for_norm(self, norm: str) -> str:
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM memory_entities WHERE norm=?", (norm,)).fetchone()
        return row["id"] if row else self.entity_id(norm)

    def merge(self, src_id: str, into_id: str, source: str = "manual") -> bool:
        """Fold entity ``src_id`` into ``into_id``: relations, attributes,
        aliases and surface counts move; duplicate relations collapse."""
        if not src_id or src_id == into_id:
            return False
        with self._lock:
            a = self.conn.execute("SELECT * FROM memory_entities WHERE id=?",
                                  (src_id,)).fetchone()
            b = self.conn.execute("SELECT * FROM memory_entities WHERE id=?",
                                  (into_id,)).fetchone()
            if not a or not b:
                return False
            a, b = dict(a), dict(b)
            self.conn.execute("UPDATE memory_relations SET src=? WHERE src=?",
                              (into_id, src_id))
            self.conn.execute("UPDATE memory_relations SET dst=? WHERE dst=?",
                              (into_id, src_id))
            # A merge can turn "Santhosh -works_with-> user" into a self-loop.
            self.conn.execute(
                "DELETE FROM memory_relation_sources WHERE relation_id IN "
                "(SELECT id FROM memory_relations WHERE src=dst)")
            self.conn.execute("DELETE FROM memory_relations WHERE src=dst")
            self.conn.execute("UPDATE memory_attributes SET entity=? WHERE entity=?",
                              (into_id, src_id))
            keep_source = "manual" if source == "manual" else None
            self.conn.execute(
                "UPDATE memory_entity_aliases SET norm=?" +
                (", source='manual'" if keep_source else "") + " WHERE norm=?",
                (b["norm"], a["norm"]))
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_entity_aliases (alias, norm, source) "
                "VALUES (?,?,?)", (a["norm"], b["norm"], source))
            try:
                sa = json.loads(a.get("aliases") or "{}") or {}
                sb = json.loads(b.get("aliases") or "{}") or {}
            except ValueError:
                sa, sb = {}, {}
            for k, v in sa.items():
                sb[k] = int(sb.get(k, 0)) + int(v)
            if b.get("is_self"):
                name = b["name"]
            elif source == "manual":
                # The user picked the target: its name stays, through rebuilds.
                name = b["name"]
                self._lock_name(b["norm"], name)
            else:
                name = self._locked_name(b["norm"]) or _pick_name(sb) or b["name"]
            etype = b["type"]
            if (etype in _GENERIC_TYPES and a["type"] not in _GENERIC_TYPES) or (
                    b.get("type_source") == "inferred" and a.get("type_source") == "model"):
                etype = a["type"]
            if b.get("is_self"):
                etype = "person"
            self.conn.execute(
                "UPDATE memory_entities SET name=?, aliases=?, type=?, created_at=?, "
                "updated_at=? WHERE id=?",
                (name, json.dumps(sb, ensure_ascii=False), etype,
                 min(a["created_at"], b["created_at"]), self._now(), into_id))
            self.conn.execute("DELETE FROM memory_entities WHERE id=?", (src_id,))
            self.conn.commit()
        self._collapse_duplicate_relations()
        return True

    def rename(self, entity_id: str, name: str) -> bool:
        name = " ".join((name or "").split())
        if not name:
            return False
        with self._lock:
            cur = self.conn.execute(
                "UPDATE memory_entities SET name=?, updated_at=? WHERE id=?",
                (name, self._now(), entity_id))
            row = self.conn.execute("SELECT norm FROM memory_entities WHERE id=?",
                                    (entity_id,)).fetchone()
            if row:
                self.conn.execute(
                    "INSERT OR REPLACE INTO memory_entity_aliases (alias, norm, source) "
                    "VALUES (?,?,'manual')", (canonical_key(name), row["norm"]))
                self._lock_name(row["norm"], name)
            self.conn.commit()
        return cur.rowcount > 0

    def set_type(self, entity_id: str, type: str) -> bool:
        t = canonical_type(type)
        if not t:
            return False
        with self._lock:
            cur = self.conn.execute(
                "UPDATE memory_entities SET type=?, type_source='manual', updated_at=? "
                "WHERE id=? AND COALESCE(is_self,0)=0", (t, self._now(), entity_id))
            self.conn.commit()
        return cur.rowcount > 0

    # -- relations ----------------------------------------------------------------

    def ingest(self, subject: str, predicate: str, obj: str, *,
               item_id: Optional[str] = None, subject_type: Optional[str] = None,
               object_type: Optional[str] = None, confidence: Optional[float] = None,
               source: str = "", at: Optional[str] = None,
               valid_from: Optional[str] = None) -> dict:
        """Turn one triple into graph structure. Returns what happened:
        ``{"op": "relation"|"attribute"|"alias"|"skip", ...}``."""
        at = at or self._now()
        pred, flip = canonical_predicate(predicate)
        subject, obj = (subject or "").strip(), (obj or "").strip()
        if not (subject and obj and pred):
            return {"op": "skip", "reason": "incomplete triple"}
        if flip:
            subject, obj = obj, subject
            subject_type, object_type = object_type, subject_type
        conf = float(confidence) if isinstance(confidence, (int, float)) else \
            SOURCE_CONFIDENCE.get(source, DEFAULT_CONFIDENCE)
        conf = max(0.05, min(0.99, conf))

        src = self.resolve(subject, subject_type, pred=pred, role="subject", at=at)
        if not src:
            return {"op": "skip", "reason": "unresolvable subject"}

        if pred in NAME_PREDICATES:
            self.add_alias(src, obj, source="name")
            self._set_attribute(src, "name", display_surface(obj), item_id, at)
            if self._is_self(src):
                with self._lock:
                    self.conn.execute(
                        "UPDATE memory_entities SET name=?, updated_at=? WHERE id=?",
                        (display_surface(obj), at, src))
                    self.conn.commit()
            return {"op": "alias", "entity": src, "alias": obj}

        obj_key = canonical_key(obj)
        if (pred in ATTRIBUTE_PREDICATES or is_literal(obj) or is_description(obj)
                or not obj_key or obj_key in _UNRESOLVABLE):
            aid = self._set_attribute(src, pred, obj, item_id, at)
            return {"op": "attribute", "entity": src, "key": pred, "id": aid}

        dst = self.resolve(obj, object_type, pred=pred, role="object", at=at)
        if not dst or dst == src:
            return {"op": "skip", "reason": "self-loop"}
        rid = self._add_relation(src, pred, dst, item_id=item_id, confidence=conf,
                                 at=at, valid_from=valid_from)
        return {"op": "relation", "id": rid, "src": src, "rel": pred, "dst": dst}

    def _is_self(self, entity_id: str) -> bool:
        with self._lock:
            row = self.conn.execute("SELECT is_self FROM memory_entities WHERE id=?",
                                    (entity_id,)).fetchone()
        return bool(row and row["is_self"])

    def _add_relation(self, src: str, rel: str, dst: str, *, item_id: Optional[str],
                      confidence: float, at: str,
                      valid_from: Optional[str] = None) -> str:
        with self._lock:
            if rel in SYMMETRIC:
                row = self.conn.execute(
                    "SELECT id FROM memory_relations WHERE rel=? AND expired_at IS NULL "
                    "AND ((src=? AND dst=?) OR (src=? AND dst=?))",
                    (rel, src, dst, dst, src)).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT id FROM memory_relations WHERE rel=? AND src=? AND dst=? "
                    "AND expired_at IS NULL", (rel, src, dst)).fetchone()
            if row:
                rid = row["id"]
            else:
                rid = str(uuid.uuid4())
                self.conn.execute(
                    "INSERT INTO memory_relations (id, src, rel, dst, item_id, valid_from, "
                    "created_at, confidence) VALUES (?,?,?,?,?,?,?,?)",
                    (rid, src, rel, dst, item_id, valid_from or at, at, confidence))
            if item_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO memory_relation_sources (relation_id, item_id, "
                    "confidence) VALUES (?,?,?)", (rid, item_id, confidence))
            self._refresh_confidence(rid)
            # Contradictions: a functional predicate keeps one live object per
            # subject; likes/dislikes on the same pair replace each other.
            losers = []
            if rel in FUNCTIONAL:
                losers += [r["id"] for r in self.conn.execute(
                    "SELECT id FROM memory_relations WHERE src=? AND rel=? AND dst!=? "
                    "AND expired_at IS NULL AND id!=?", (src, rel, dst, rid))]
            if rel in OPPOSITES:
                losers += [r["id"] for r in self.conn.execute(
                    "SELECT id FROM memory_relations WHERE src=? AND rel=? AND dst=? "
                    "AND expired_at IS NULL", (src, OPPOSITES[rel], dst))]
            for lid in losers:
                self.conn.execute(
                    "UPDATE memory_relations SET expired_at=?, valid_to=COALESCE(valid_to,?), "
                    "superseded_by=? WHERE id=?", (at, at, rid, lid))
            self.conn.commit()
        for lid in losers:
            self._supersede_lone_facts(lid, item_id, at)
        return rid

    def _supersede_lone_facts(self, relation_id: str, new_item: Optional[str],
                              at: str) -> None:
        """A fact whose ONLY graph content was the superseded relation is the
        same contradiction the resolver should have caught — invalidate it
        too (history kept) so recall stops serving the stale value."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT s.item_id FROM memory_relation_sources s JOIN memory_items m "
                "ON m.id = s.item_id WHERE s.relation_id=? AND m.expired_at IS NULL",
                (relation_id,)).fetchall()
            for r in rows:
                iid = r["item_id"]
                others = self.conn.execute(
                    "SELECT count(*) AS c FROM memory_relation_sources s JOIN "
                    "memory_relations r ON r.id = s.relation_id WHERE s.item_id=? "
                    "AND r.expired_at IS NULL", (iid,)).fetchone()["c"]
                if others == 0 and iid != new_item:
                    self.conn.execute(
                        "UPDATE memory_items SET expired_at=?, valid_to=COALESCE(valid_to,?), "
                        "superseded_by=? WHERE id=? AND expired_at IS NULL",
                        (at, at, new_item, iid))
            self.conn.commit()

    def _refresh_confidence(self, rid: str) -> None:
        """Noisy-OR over the supporting facts (lock held by caller)."""
        rows = self.conn.execute(
            "SELECT confidence FROM memory_relation_sources WHERE relation_id=?",
            (rid,)).fetchall()
        if not rows:
            return
        miss = 1.0
        for r in rows:
            miss *= 1.0 - float(r["confidence"] or DEFAULT_CONFIDENCE)
        self.conn.execute("UPDATE memory_relations SET confidence=? WHERE id=?",
                          (round(min(0.99, 1.0 - miss), 3), rid))

    def _set_attribute(self, entity: str, key: str, value: str,
                       item_id: Optional[str], at: str) -> str:
        value = " ".join(str(value).split())[:300]
        with self._lock:
            # One live value per key — a new value expires the old one.
            self.conn.execute(
                "UPDATE memory_attributes SET expired_at=? WHERE entity=? AND key=? "
                "AND expired_at IS NULL AND value != ?", (at, entity, key, value))
            row = self.conn.execute(
                "SELECT id FROM memory_attributes WHERE entity=? AND key=? AND value=? "
                "AND expired_at IS NULL", (entity, key, value)).fetchone()
            if row:
                aid = row["id"]
            else:
                aid = str(uuid.uuid4())
                self.conn.execute(
                    "INSERT INTO memory_attributes (id, entity, key, value, item_id, "
                    "created_at) VALUES (?,?,?,?,?,?)",
                    (aid, entity, key, value, item_id, at))
            self.conn.commit()
        return aid

    def _collapse_duplicate_relations(self) -> None:
        """After a merge two live rows may assert the same (src, rel, dst)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, src, rel, dst, created_at FROM memory_relations "
                "WHERE expired_at IS NULL ORDER BY created_at").fetchall()
            seen: dict[tuple, str] = {}
            for r in rows:
                a, b = r["src"], r["dst"]
                key = (r["rel"], *sorted((a, b))) if r["rel"] in SYMMETRIC else (
                    r["rel"], a, b)
                if key not in seen:
                    seen[key] = r["id"]
                    continue
                keep = seen[key]
                self.conn.execute(
                    "INSERT OR IGNORE INTO memory_relation_sources (relation_id, item_id, "
                    "confidence) SELECT ?, item_id, confidence FROM "
                    "memory_relation_sources WHERE relation_id=?", (keep, r["id"]))
                self.conn.execute("DELETE FROM memory_relation_sources WHERE relation_id=?",
                                  (r["id"],))
                self.conn.execute("DELETE FROM memory_relations WHERE id=?", (r["id"],))
                self._refresh_confidence(keep)
            self.conn.commit()

    # -- lifecycle (called by the store when a fact changes) -----------------------

    def item_gone(self, item_id: str, superseded_by: Optional[str] = None,
                  at: Optional[str] = None) -> None:
        """A fact was invalidated/archived: relations it alone supported expire
        (pointing at the replacing fact's relation when there is one) and its
        attributes expire."""
        at = at or self._now()
        with self._lock:
            rel_ids = [r["relation_id"] for r in self.conn.execute(
                "SELECT relation_id FROM memory_relation_sources WHERE item_id=?",
                (item_id,))]
            legacy = [r["id"] for r in self.conn.execute(
                "SELECT id FROM memory_relations WHERE item_id=? AND expired_at IS NULL",
                (item_id,))]
            replacement = None
            if superseded_by:
                row = self.conn.execute(
                    "SELECT relation_id FROM memory_relation_sources WHERE item_id=? "
                    "LIMIT 1", (superseded_by,)).fetchone()
                replacement = row["relation_id"] if row else None
            for rid in dict.fromkeys(rel_ids + legacy):
                live = self.conn.execute(
                    "SELECT count(*) AS c FROM memory_relation_sources s JOIN memory_items m "
                    "ON m.id = s.item_id WHERE s.relation_id=? AND s.item_id != ? "
                    "AND m.expired_at IS NULL AND m.archived_at IS NULL "
                    "AND m.screen_status='ok'", (rid, item_id)).fetchone()["c"]
                if live:
                    self._refresh_confidence(rid)
                    continue
                self.conn.execute(
                    "UPDATE memory_relations SET expired_at=?, valid_to=COALESCE(valid_to,?), "
                    "superseded_by=COALESCE(superseded_by, ?) WHERE id=? "
                    "AND expired_at IS NULL", (at, at, replacement, rid))
            self.conn.execute(
                "UPDATE memory_attributes SET expired_at=? WHERE item_id=? "
                "AND expired_at IS NULL", (at, item_id))
            self.conn.commit()

    def item_deleted(self, item_id: str) -> None:
        """Hard delete: drop the fact's sources; relations with no source left
        go, then orphaned entities."""
        with self._lock:
            rel_ids = [r["relation_id"] for r in self.conn.execute(
                "SELECT relation_id FROM memory_relation_sources WHERE item_id=?",
                (item_id,))]
            self.conn.execute("DELETE FROM memory_relation_sources WHERE item_id=?",
                              (item_id,))
            for rid in rel_ids:
                left = self.conn.execute(
                    "SELECT count(*) AS c FROM memory_relation_sources WHERE relation_id=?",
                    (rid,)).fetchone()["c"]
                if left:
                    self._refresh_confidence(rid)
                else:
                    self.conn.execute("DELETE FROM memory_relations WHERE id=?", (rid,))
            self.conn.execute("DELETE FROM memory_relations WHERE item_id=? AND id NOT IN "
                              "(SELECT relation_id FROM memory_relation_sources)", (item_id,))
            self.conn.execute("DELETE FROM memory_attributes WHERE item_id=?", (item_id,))
            self._gc_orphans()
            self.conn.commit()

    def _gc_orphans(self) -> None:
        """Entities with no relation and no attribute left (lock held)."""
        self.conn.execute(
            "DELETE FROM memory_entities WHERE id NOT IN "
            "(SELECT src FROM memory_relations UNION SELECT dst FROM memory_relations "
            "UNION SELECT entity FROM memory_attributes)")
        self.conn.execute(
            "DELETE FROM memory_entity_aliases WHERE source != 'manual' AND norm NOT IN "
            "(SELECT norm FROM memory_entities)")

    def wipe(self) -> None:
        with self._lock:
            for t in ("memory_entity_aliases", "memory_relation_sources",
                      "memory_attributes"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()

    # -- migration ----------------------------------------------------------------

    def rebuild(self) -> dict:
        """Re-derive the whole graph from the facts, chronologically, so every
        existing relation goes through resolution/typing/supersession and time
        travel keeps working. Idempotent; manual aliases/merges survive.
        This IS the migration for pre-Phase-10 data."""
        with self._lock:
            items = [dict(r) for r in self.conn.execute(
                "SELECT * FROM memory_items WHERE screen_status='ok' "
                "ORDER BY created_at").fetchall()]
            item_ids = {i["id"] for i in items}
            # Relations that never had a fact behind them (direct API use, the
            # Cognee import) — re-derived from their own endpoint names.
            orphan_rels = [dict(r) for r in self.conn.execute(
                "SELECT r.rel, r.created_at, r.expired_at, r.item_id, s.name AS sname, "
                "s.type AS stype, d.name AS dname, d.type AS dtype FROM memory_relations r "
                "JOIN memory_entities s ON s.id=r.src JOIN memory_entities d ON d.id=r.dst"
            ).fetchall()]
            orphan_rels = [r for r in orphan_rels if not r["item_id"]
                           or r["item_id"] not in item_ids]
            lone = [dict(r) for r in self.conn.execute(
                "SELECT name, type, created_at FROM memory_entities e WHERE NOT EXISTS "
                "(SELECT 1 FROM memory_relations r WHERE r.src=e.id OR r.dst=e.id)"
            ).fetchall()]
            before = {
                "entities": self.conn.execute(
                    "SELECT count(*) AS c FROM memory_entities").fetchone()["c"],
                "relations": self.conn.execute(
                    "SELECT count(*) AS c FROM memory_relations WHERE expired_at IS NULL"
                ).fetchone()["c"],
            }
            for t in ("memory_relations", "memory_relation_sources", "memory_attributes",
                      "memory_entities"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.execute("DELETE FROM memory_entity_aliases WHERE source != 'manual'")
            self.conn.commit()

        events: list[tuple[str, int, str, dict]] = []
        for it in items:
            if it.get("subject") and it.get("predicate") and it.get("object"):
                events.append((it["created_at"], 0, "add", it))
                gone = it.get("expired_at") or it.get("archived_at")
                if gone:
                    events.append((gone, 1, "gone", it))
        for r in orphan_rels:
            events.append((r["created_at"], 0, "rel", r))
            if r.get("expired_at"):
                events.append((r["expired_at"], 1, "relgone", r))
        events.sort(key=lambda e: (e[0] or "", e[1]))
        live_ids = {i["id"] for i in items if not i.get("expired_at")}
        for at, _, kind, data in events:
            if kind == "add":
                self.ingest(data["subject"], data["predicate"], data["object"],
                            item_id=data["id"], subject_type=data.get("subject_type"),
                            object_type=data.get("object_type"), source=data.get("source", ""),
                            at=at, valid_from=data.get("valid_from"))
            elif kind == "gone":
                self.item_gone(data["id"], superseded_by=data.get("superseded_by"), at=at)
            elif kind == "rel":
                res = self.ingest(data["sname"], data["rel"], data["dname"],
                                  subject_type=data.get("stype"),
                                  object_type=data.get("dtype"), at=at)
                data["_rid"] = res.get("id")
            elif kind == "relgone" and data.get("_rid"):
                with self._lock:
                    self.conn.execute(
                        "UPDATE memory_relations SET expired_at=?, valid_to=COALESCE(valid_to,?) "
                        "WHERE id=? AND expired_at IS NULL", (at, at, data["_rid"]))
                    self.conn.commit()
        for e in lone:
            self.resolve(e["name"], e.get("type"), at=e.get("created_at"))
        # Replay may supersede a still-live fact (functional contradiction the
        # resolver missed) — that's intended; report it.
        with self._lock:
            newly_expired = sum(
                1 for r in self.conn.execute(
                    "SELECT id FROM memory_items WHERE expired_at IS NOT NULL")
                if r["id"] in live_ids)
        self._set_version(GRAPH_VERSION)
        after = self.counts()
        return {"before": before, "after": after, "facts_superseded": newly_expired}

    # -- read side ----------------------------------------------------------------

    def counts(self) -> dict:
        with self._lock:
            ents = self.conn.execute(
                "SELECT count(*) AS c FROM memory_entities e WHERE COALESCE(is_self,0)=1 "
                "OR EXISTS (SELECT 1 FROM memory_relations r WHERE r.expired_at IS NULL "
                "AND (r.src=e.id OR r.dst=e.id)) OR EXISTS (SELECT 1 FROM "
                "memory_attributes a WHERE a.entity=e.id AND a.expired_at IS NULL)"
            ).fetchone()["c"]
            rels = self.conn.execute(
                "SELECT count(*) AS c FROM memory_relations WHERE expired_at IS NULL"
            ).fetchone()["c"]
        return {"entities": int(ents), "relations": int(rels)}

    def snapshot(self, include_expired: bool = False,
                 as_of: Optional[str] = None, all_entities: bool = False) -> dict:
        """Nodes + edges (+ attributes) for the graph view. Live view: only
        entities that still have a live relation/attribute (or are the user);
        ``all_entities`` also lists entity rows with nothing live (the store's
        raw view). ``as_of`` time-travels on the bi-temporal stamps."""
        with self._lock:
            ents = [dict(r) for r in self.conn.execute(
                "SELECT * FROM memory_entities").fetchall()]
            rels = [dict(r) for r in self.conn.execute(
                "SELECT * FROM memory_relations").fetchall()]
            attrs = [dict(r) for r in self.conn.execute(
                "SELECT * FROM memory_attributes").fetchall()]
            alias_keys: dict[str, list[str]] = {}
            for r in self.conn.execute("SELECT alias, norm FROM memory_entity_aliases"):
                alias_keys.setdefault(r["norm"], []).append(r["alias"])
            support = {r["relation_id"]: r["c"] for r in self.conn.execute(
                "SELECT s.relation_id, count(*) AS c FROM memory_relation_sources s "
                "JOIN memory_items m ON m.id=s.item_id WHERE m.expired_at IS NULL "
                "AND m.archived_at IS NULL GROUP BY s.relation_id")}

        def alive(row: dict) -> bool:
            if as_of:
                return row["created_at"] <= as_of and (
                    not row.get("expired_at") or row["expired_at"] > as_of)
            return include_expired or not row.get("expired_at")

        rels = [r for r in rels if alive(r)]
        attrs = [a for a in attrs if alive(a)]
        used = {r["src"] for r in rels} | {r["dst"] for r in rels} | {
            a["entity"] for a in attrs}
        if as_of:
            ents = [e for e in ents if e["created_at"] <= as_of and e["id"] in used]
        else:
            ents = [e for e in ents if all_entities or e["id"] in used or e.get("is_self")]
        by_entity: dict[str, dict] = {}
        for a in sorted(attrs, key=lambda a: a["created_at"]):
            by_entity.setdefault(a["entity"], {})[a["key"]] = a["value"]
        nodes = []
        for e in ents:
            try:
                surfaces = json.loads(e.get("aliases") or "{}") or {}
            except ValueError:
                surfaces = {}
            nodes.append({
                "id": e["id"], "name": e["name"], "norm": e["norm"],
                "type": e.get("type") or "concept", "summary": e.get("summary") or "",
                "aliases": _alias_list(e, surfaces, alias_keys.get(e["norm"], [])),
                "attributes": by_entity.get(e["id"], {}),
                "is_self": bool(e.get("is_self")), "created_at": e["created_at"],
            })
        ids = {n["id"] for n in nodes}
        edges = [{
            "id": r["id"], "src": r["src"], "rel": r["rel"], "dst": r["dst"],
            "item_id": r.get("item_id"), "confidence": r.get("confidence"),
            "valid_from": r.get("valid_from"), "created_at": r["created_at"],
            "expired_at": r.get("expired_at"), "superseded_by": r.get("superseded_by"),
            "symmetric": r["rel"] in SYMMETRIC, "support": support.get(r["id"], 0),
        } for r in rels if r["src"] in ids and r["dst"] in ids]
        return {"nodes": nodes, "edges": edges}

    def schema(self) -> dict:
        """The schema DERIVED from the live graph: entity types with counts and
        attribute keys; relation types with counts and the (source type →
        target type) pairs they actually connect."""
        snap = self.snapshot()
        type_of = {n["id"]: n["type"] for n in snap["nodes"]}
        types: dict[str, dict] = {}
        for n in snap["nodes"]:
            t = types.setdefault(n["type"], {"type": n["type"], "count": 0,
                                             "attributes": set(), "examples": []})
            t["count"] += 1
            t["attributes"].update(n["attributes"].keys())
            if len(t["examples"]) < 4:
                t["examples"].append(n["name"])
        rels: dict[str, dict] = {}
        for e in snap["edges"]:
            r = rels.setdefault(e["rel"], {"rel": e["rel"], "label": e["rel"].replace("_", " "),
                                           "count": 0, "pairs": {},
                                           "symmetric": e["rel"] in SYMMETRIC,
                                           "functional": e["rel"] in FUNCTIONAL})
            r["count"] += 1
            pair = (type_of.get(e["src"], "?"), type_of.get(e["dst"], "?"))
            r["pairs"][pair] = r["pairs"].get(pair, 0) + 1
        return {
            "types": sorted(({**t, "attributes": sorted(t["attributes"])}
                             for t in types.values()), key=lambda t: -t["count"]),
            "relations": sorted(({**r, "pairs": [
                {"source": a, "target": b, "count": c}
                for (a, b), c in sorted(r["pairs"].items(), key=lambda kv: -kv[1])]}
                for r in rels.values()), key=lambda r: (-r["count"], r["rel"])),
            "counts": {"types": len(types), "relations": len(rels),
                       "entities": len(snap["nodes"]), "edges": len(snap["edges"])},
        }

    def ranked(self, limit: int = 50, half_life_days: float = 30.0,
               include_self: bool = True) -> list[dict]:
        """Entities by importance — see the module docstring for the formula.
        Every component is returned so the UI can show WHY."""
        snap = self.snapshot()
        nodes = snap["nodes"]
        if not nodes:
            return []
        ids = [n["id"] for n in nodes]
        pr = pagerank(ids, [(e["src"], e["dst"],
                             max(1, e["support"]) * float(e["confidence"] or 0.7))
                            for e in snap["edges"]])
        top = max(pr.values()) or 1.0
        facts = self._entity_fact_stats()
        now = datetime.now(timezone.utc)
        degree: dict[str, int] = {}
        for e in snap["edges"]:
            degree[e["src"]] = degree.get(e["src"], 0) + 1
            degree[e["dst"]] = degree.get(e["dst"], 0) + 1
        out = []
        for n in nodes:
            if n["is_self"] and not include_self:
                continue
            st = facts.get(n["id"], {})
            centrality = pr.get(n["id"], 0.0) / top
            mentions = int(st.get("mentions", 0))
            salience = 0.7 * float(st.get("importance", 0.0)) + 0.3 * min(
                1.0, math.log2(1 + mentions) / 4)
            days = _days_since(st.get("last_seen"), now)
            recency = 0.5 ** (days / max(0.1, half_life_days))
            score = 0.45 * centrality + 0.30 * salience + 0.25 * recency
            out.append({
                "id": n["id"], "name": n["name"], "type": n["type"],
                "is_self": n["is_self"], "score": round(score, 4),
                "centrality": round(centrality, 4), "salience": round(salience, 4),
                "recency": round(recency, 4), "degree": degree.get(n["id"], 0),
                "facts": int(st.get("facts", 0)), "mentions": mentions,
                "last_seen": st.get("last_seen"),
            })
        out.sort(key=lambda r: (-r["score"], r["name"].lower()))
        return out[: max(1, int(limit))]

    def _entity_fact_stats(self) -> dict[str, dict]:
        """Per entity: live supporting facts, max importance, summed frequency,
        newest last_seen — via relation sources and attributes."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT e.id AS eid, m.id AS mid, m.importance, m.frequency, m.last_seen "
                "FROM memory_entities e JOIN memory_relations r ON r.expired_at IS NULL "
                "AND (r.src=e.id OR r.dst=e.id) JOIN memory_relation_sources s ON "
                "s.relation_id=r.id JOIN memory_items m ON m.id=s.item_id "
                "WHERE m.expired_at IS NULL AND m.archived_at IS NULL "
                "UNION SELECT a.entity AS eid, m.id AS mid, m.importance, m.frequency, "
                "m.last_seen FROM memory_attributes a JOIN memory_items m ON "
                "m.id=a.item_id WHERE a.expired_at IS NULL AND m.expired_at IS NULL"
            ).fetchall()
        stats: dict[str, dict] = {}
        seen: set = set()
        for r in rows:
            if (r["eid"], r["mid"]) in seen:
                continue
            seen.add((r["eid"], r["mid"]))
            s = stats.setdefault(r["eid"], {"facts": 0, "importance": 0.0,
                                            "mentions": 0, "last_seen": None})
            s["facts"] += 1
            s["importance"] = max(s["importance"], float(r["importance"] or 0))
            s["mentions"] += int(r["frequency"] or 1)
            if r["last_seen"] and (not s["last_seen"] or r["last_seen"] > s["last_seen"]):
                s["last_seen"] = r["last_seen"]
        return stats

    def neighbourhood(self, entity_id: str, include_expired: bool = True,
                      fact_limit: int = 30) -> Optional[dict]:
        """One entity in focus: its attributes, aliases, incident relations
        (superseded ones too, flagged) and the facts behind them — plus facts
        that merely mention it by name."""
        snap = self.snapshot(include_expired=True)
        node = next((n for n in snap["nodes"] if n["id"] == entity_id), None)
        if node is None:
            with self._lock:
                row = self.conn.execute("SELECT * FROM memory_entities WHERE id=?",
                                        (entity_id,)).fetchone()
            if not row:
                return None
            node = {"id": row["id"], "name": row["name"], "type": row["type"],
                    "aliases": [], "attributes": {}, "is_self": bool(row["is_self"])}
        names = {n["id"]: n for n in snap["nodes"]}
        edges = []
        for e in snap["edges"]:
            if entity_id not in (e["src"], e["dst"]):
                continue
            if e["expired_at"] and not include_expired:
                continue
            outgoing = e["src"] == entity_id
            other = names.get(e["dst"] if outgoing else e["src"], {})
            edges.append({**e, "direction": "out" if outgoing else "in",
                          "other": {"id": other.get("id"), "name": other.get("name"),
                                    "type": other.get("type")}})
        edges.sort(key=lambda e: (bool(e["expired_at"]), e["rel"]))
        rel_ids = [e["id"] for e in edges]
        with self._lock:
            facts: dict[str, dict] = {}
            if rel_ids:
                ph = ",".join("?" * len(rel_ids))
                for r in self.conn.execute(
                        f"SELECT m.*, s.relation_id FROM memory_relation_sources s JOIN "
                        f"memory_items m ON m.id=s.item_id WHERE s.relation_id IN ({ph})",
                        rel_ids):
                    d = dict(r)
                    facts.setdefault(d["id"], {**_fact_view(d), "relations": []})[
                        "relations"].append(d["relation_id"])
            for r in self.conn.execute(
                    "SELECT m.* FROM memory_attributes a JOIN memory_items m ON "
                    "m.id=a.item_id WHERE a.entity=?", (entity_id,)):
                d = dict(r)
                facts.setdefault(d["id"], {**_fact_view(d), "relations": []})
            attr_hist = [dict(r) for r in self.conn.execute(
                "SELECT key, value, created_at, expired_at, item_id FROM memory_attributes "
                "WHERE entity=? ORDER BY created_at", (entity_id,))]
        # Facts that mention the entity by any of its names (raw remembers that
        # never got a triple still belong here).
        terms = [node["name"]] + list(node.get("aliases") or [])
        if not node.get("is_self"):
            for t in terms[:4]:
                if len(t) < 3:
                    continue
                for m in self.store.search_items(f'"{t}"', limit=8, include_expired=True):
                    if m["id"] not in facts:
                        facts[m["id"]] = {**_fact_view(m), "relations": [], "mention": True}
        ordered = sorted(facts.values(), key=lambda f: (bool(f["expired"]),
                                                        f.get("mention", False),
                                                        -(f["importance"] or 0)))
        return {"entity": node, "edges": edges, "facts": ordered[:fact_limit],
                "attribute_history": attr_hist,
                "neighbours": sorted({e["other"]["id"] for e in edges if e["other"]["id"]
                                      and not e["expired_at"]})}

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Entities whose name or any alias contains the query (prefix matches
        first), with their type."""
        q = canonical_key(query)
        if not q:
            return []
        snap = self.snapshot()
        with self._lock:
            alias_rows = self.conn.execute(
                "SELECT alias, norm FROM memory_entity_aliases WHERE alias LIKE ?",
                (f"%{q}%",)).fetchall()
        hit_norms = {r["norm"]: r["alias"] for r in alias_rows}
        out = []
        for n in snap["nodes"]:
            names = [n["name"]] + n["aliases"]
            keys = [canonical_key(x) for x in names]
            match = next((k for k in keys if q in k), None) or hit_norms.get(n["norm"])
            if not match:
                continue
            rank = 0 if any(k.startswith(q) for k in keys) else 1
            out.append((rank, len(n["name"]), {"id": n["id"], "name": n["name"],
                                               "type": n["type"], "match": match,
                                               "is_self": n["is_self"]}))
        out.sort(key=lambda t: (t[0], t[1]))
        return [o[2] for o in out[:limit]]

    def items_for(self, names: list[str], limit: int = 6) -> list[dict]:
        """Live facts attached to any of the named entities (recall's graph
        expansion)."""
        norms = {n for n in (self.lookup(x) for x in names) if n}
        if not norms:
            return []
        ids = [self.entity_id_for_norm(n) for n in norms]
        ph = ",".join("?" * len(ids))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT DISTINCT m.* FROM memory_items m "
                f"JOIN memory_relation_sources s ON s.item_id = m.id "
                f"JOIN memory_relations r ON r.id = s.relation_id "
                f"WHERE (r.src IN ({ph}) OR r.dst IN ({ph})) AND m.expired_at IS NULL "
                f"AND m.archived_at IS NULL AND r.expired_at IS NULL "
                f"ORDER BY m.importance DESC LIMIT ?", (*ids, *ids, limit)).fetchall()
        return [dict(r) for r in rows]

    def mention_keys(self) -> list[str]:
        """Names/aliases recall may spot in a query (the self entity excluded —
        "I"/"my" in every question would pull in the whole hub)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT alias FROM memory_entity_aliases WHERE norm != ? "
                "UNION SELECT norm FROM memory_entities WHERE COALESCE(is_self,0)=0",
                (SELF_NORM,)).fetchall()
        return [r[0] for r in rows if r[0]]


def _pick_name(surfaces: dict) -> str:
    """Most-used surface form; ties → has capitals, then shorter."""
    if not surfaces:
        return ""
    # Longer wins a tie: the full name over its acronym ("Kalasalingam …" over
    # "KARE"), "Santhosh Reddy" over "Santhosh".
    return sorted(surfaces.items(),
                  key=lambda kv: (-int(kv[1]), not any(c.isupper() for c in kv[0]),
                                  -len(kv[0])))[0][0]


def _alias_list(entity: dict, surfaces: dict, keys: list[str]) -> list[str]:
    """Other names an entity goes by: surface forms (as written) plus lookup
    keys no surface already covers (an acronym shows upper-case). Case-only
    variants of the display name are not aliases."""
    name_key = canonical_key(entity["name"])
    out: dict[str, str] = {}
    for s in surfaces:
        k = canonical_key(s)
        if k != name_key and k not in out:
            out[k] = s
    for k in keys:
        if k == name_key or k in out or k == entity["norm"] == name_key:
            continue
        if k in SELF_KEYS:
            continue
        out[k] = k.upper() if len(k) <= 5 and " " not in k else k
    return sorted(out.values(), key=str.lower)


def _fact_view(m: dict) -> dict:
    return {"id": m["id"], "text": m["text"], "kind": m.get("kind"),
            "importance": m.get("importance"), "frequency": m.get("frequency"),
            "created_at": m.get("created_at"), "last_seen": m.get("last_seen"),
            "source": m.get("source"), "expired": bool(m.get("expired_at")),
            "archived": bool(m.get("archived_at")),
            "superseded_by": m.get("superseded_by")}
