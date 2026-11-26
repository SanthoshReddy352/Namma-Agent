"""Seed a scratch Engram memory with a realistic set of conversations.

Phase 10 (memory graph) audit + verification fixture. Each turn below is run
through the REAL write pipeline (``EngramWriter.process``) with a scripted
"model" that replays the kind of output a cloud model returns for that turn:
inconsistent subject spellings ("User", "the user", "I", "Santhosh"), synonym
predicates ("loves"/"likes", "is_building"/"works_on"), objects that are
phrases or literals, a contradiction (moving city) and a restatement. When the
extraction prompt asks for entity types (Phase 10), the scripted model returns
them too, exactly like a model following that prompt would.

Usage (ALWAYS against a scratch data dir — never the real one):

    set NAMMA_DATA_DIR=C:\\path\\to\\scratch
    python scripts/seed_memory_graph.py            # seeds <data dir>/namma_agent.db
    python scripts/seed_memory_graph.py --db X.db  # explicit file

Tests import :func:`seed` and :data:`TURNS` directly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# (days_ago, user_text, extracted candidates). Candidate dicts carry optional
# ``subject_type`` / ``object_type`` — only returned when the prompt asks.
TURNS: list[tuple[int, str, list[dict]]] = [
    (58, "Hi! I'm Santhosh, a B.Tech CSE (AI&ML) student at KARE.", [
        {"text": "The user's name is Santhosh.", "kind": "fact",
         "subject": "user", "predicate": "has_name", "object": "Santhosh",
         "importance": 0.95, "subject_type": "person", "object_type": "person"},
        {"text": "Santhosh studies B.Tech CSE (AI&ML) at KARE.", "kind": "fact",
         "subject": "Santhosh", "predicate": "studies_at",
         "object": "Kalasalingam Academy of Research and Education (KARE)",
         "importance": 0.9, "subject_type": "person", "object_type": "organization"},
    ]),
    (55, "I live in Bangalore with my family.", [
        {"text": "The user lives in Bangalore.", "kind": "fact",
         "subject": "User", "predicate": "lives_in", "object": "Bangalore",
         "importance": 0.7, "subject_type": "person", "object_type": "place"},
    ]),
    (52, "Python is my favourite language, I love it.", [
        {"text": "Santhosh loves Python.", "kind": "preference",
         "subject": "Santhosh", "predicate": "loves", "object": "Python",
         "importance": 0.75, "subject_type": "person", "object_type": "technology"},
    ]),
    (50, "I'm building Namma Agent, a personal AI assistant.", [
        {"text": "Santhosh is building Namma Agent, a personal AI assistant.",
         "kind": "fact", "subject": "Santhosh", "predicate": "is_building",
         "object": "Namma Agent", "importance": 0.85,
         "subject_type": "person", "object_type": "project"},
    ]),
    (49, "Namma Agent's backend is FastAPI and the UI is React.", [
        {"text": "The Namma Agent project uses FastAPI for its backend.",
         "kind": "fact", "subject": "Namma Agent project", "predicate": "uses",
         "object": "FastAPI", "importance": 0.6,
         "subject_type": "project", "object_type": "technology"},
        {"text": "Namma Agent's UI is built with React.", "kind": "fact",
         "subject": "namma agent", "predicate": "built_with", "object": "React",
         "importance": 0.6, "subject_type": "project", "object_type": "technology"},
    ]),
    (45, "My sister Priya is a doctor at Apollo Hospitals.", [
        {"text": "The user's sister is Priya.", "kind": "fact",
         "subject": "the user", "predicate": "has_sister", "object": "Priya",
         "importance": 0.8, "subject_type": "person", "object_type": "person"},
        {"text": "Priya works at Apollo Hospitals.", "kind": "fact",
         "subject": "Priya", "predicate": "works_at", "object": "Apollo Hospitals",
         "importance": 0.6, "subject_type": "person", "object_type": "organization"},
    ]),
    (40, "I really don't like Java, too verbose.", [
        {"text": "Santhosh dislikes Java.", "kind": "preference",
         "subject": "Santhosh", "predicate": "dislikes", "object": "Java",
         "importance": 0.6, "subject_type": "person", "object_type": "technology"},
    ]),
    (36, "I'm 21 and my dog is called Bruno.", [
        {"text": "The user is 21 years old.", "kind": "fact",
         "subject": "user", "predicate": "age", "object": "21",
         "importance": 0.6},
        {"text": "The user has a dog named Bruno.", "kind": "fact",
         "subject": "I", "predicate": "has_pet", "object": "Bruno",
         "importance": 0.6, "subject_type": "person", "object_type": "animal"},
    ]),
    (30, "Arjun and I work on Namma Agent together.", [
        {"text": "The user collaborates with Arjun.", "kind": "fact",
         "subject": "user", "predicate": "collaborates_with", "object": "Arjun",
         "importance": 0.6, "subject_type": "person", "object_type": "person"},
        {"text": "Arjun works on Namma Agent.", "kind": "fact",
         "subject": "Arjun", "predicate": "works_on", "object": "Namma Agent",
         "importance": 0.6, "subject_type": "person", "object_type": "project"},
    ]),
    (25, "Only give the GitHub tool read-only access to repos and issues.", [
        {"text": "The user wants the GitHub tool limited to read-only repositories and issues.",
         "kind": "preference", "subject": "user",
         "predicate": "wants_github_tool_access",
         "object": "read-only repositories and issues only", "importance": 0.7},
    ]),
    (20, "I prefer dark mode everywhere.", [
        {"text": "The user prefers dark mode.", "kind": "preference",
         "subject": "User", "predicate": "prefers", "object": "dark mode",
         "importance": 0.6, "subject_type": "person", "object_type": "concept"},
    ]),
    (14, "I'm preparing for the GATE exam in February 2027.", [
        {"text": "Santhosh is preparing for the GATE exam in February 2027.",
         "kind": "event", "subject": "Santhosh", "predicate": "preparing_for",
         "object": "GATE exam", "importance": 0.7,
         "subject_type": "person", "object_type": "event"},
    ]),
    (9, "Seriously, Python is the best — I like it a lot.", [
        {"text": "Santhosh likes Python a lot.", "kind": "preference",
         "subject": "santhosh", "predicate": "likes", "object": "python",
         "importance": 0.7, "subject_type": "person", "object_type": "technology"},
    ]),
    (4, "We moved — I live in Hyderabad now.", [
        {"text": "The user lives in Hyderabad.", "kind": "fact",
         "subject": "the user", "predicate": "lives_in", "object": "Hyderabad",
         "importance": 0.75, "subject_type": "person", "object_type": "place"},
    ]),
    (2, "Meeting Arjun on Friday to plan the Namma Agent release.", [
        {"text": "The user is meeting Arjun on Friday to plan the Namma Agent release.",
         "kind": "event", "subject": "user", "predicate": "meeting_with",
         "object": "Arjun", "importance": 0.4,
         "subject_type": "person", "object_type": "person"},
    ]),
    # An explicit remember the extractor returns nothing for — stored raw.
    (1, "Remember I prefer step-by-step explanations with code first.", []),
]

# Resolver decisions keyed by a phrase in the candidate text. Anything not
# listed is ADD — what a model does for genuinely new information.
RESOLVE = {
    "lives in Hyderabad": ("UPDATE", "Bangalore"),   # moved city: supersede
    "likes Python a lot": ("ADD", None),             # a model often ADDs a restatement
}


def _payload_for(messages: list[dict]) -> object:
    system = messages[0]["content"]
    user = messages[-1]["content"]
    if "extract durable facts" in system:
        typed = "subject_type" in system
        for _, text, cands in TURNS:
            if text[:2000] in user:
                if typed:
                    return cands
                return [{k: v for k, v in c.items()
                         if k not in ("subject_type", "object_type")} for c in cands]
        return []
    if "NEW candidate" in system or "NEW candidate" in user:
        first = user.splitlines()[0]
        for phrase, (op, target_word) in RESOLVE.items():
            if phrase in first:
                target = None
                if target_word:
                    for line in user.splitlines():
                        if line.startswith("#") and target_word in line:
                            target = int(line[1:line.index(":")])
                            break
                return {"op": op, "target": target, "core": None}
        return {"op": "ADD", "target": None, "core": None}
    return []


def scripted_provider():
    from namma_agent.core.providers.base import LLMResponse, Provider

    class _Scripted(Provider):
        name = "scripted-seed"

        def __init__(self):
            super().__init__(model="scripted-seed")
            self.calls: list[list[dict]] = []

        def is_available(self):
            return True

        def generate(self, messages, tools=None, stream=False, on_token=None,
                     on_thinking=None):
            self.calls.append(messages)
            return LLMResponse(content=json.dumps(_payload_for(messages)))

    return _Scripted()


def seed(engram, now: datetime | None = None) -> dict:
    """Run every turn through ``engram.writer.process`` and back-date the rows
    so recency means something. Returns {"ops": [...], "items": n}."""
    now = now or datetime.now(timezone.utc)
    ops = []
    conn = engram.store.conn
    for days_ago, text, cands in TURNS:
        explicit = not cands
        before = {r[0] for r in conn.execute("SELECT id FROM memory_items")}
        applied = engram.writer.process(text, source="chat", explicit=explicit)
        ops.extend(a["op"] for a in applied)
        stamp = (now - timedelta(days=days_ago)).isoformat()
        new = [r[0] for r in conn.execute("SELECT id FROM memory_items")
               if r[0] not in before]
        with engram.store._lock:
            for iid in new:
                conn.execute("UPDATE memory_items SET created_at=?, last_seen=? "
                             "WHERE id=?", (stamp, stamp, iid))
                for table in ("memory_relations",):
                    conn.execute(f"UPDATE {table} SET created_at=? WHERE item_id=?",
                                 (stamp, iid))
                # Supersedes applied by this turn happened at this turn's time.
                conn.execute("UPDATE memory_items SET expired_at=?, valid_to=? "
                             "WHERE superseded_by=?", (stamp, stamp, iid))
            conn.commit()
    # Entities exist since their first relation.
    with engram.store._lock:
        conn.execute(
            "UPDATE memory_entities SET created_at=COALESCE((SELECT MIN(r.created_at) "
            "FROM memory_relations r WHERE r.src=memory_entities.id "
            "OR r.dst=memory_entities.id), created_at)")
        conn.execute(
            "UPDATE memory_relations SET expired_at=(SELECT m.expired_at FROM "
            "memory_items m WHERE m.id=memory_relations.item_id) WHERE expired_at "
            "IS NOT NULL")
        conn.commit()
    return {"ops": ops, "items": engram.store.counts()["items"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", help="SQLite file (default: $NAMMA_DATA_DIR/namma_agent.db)")
    args = ap.parse_args()
    db_path = args.db
    if not db_path:
        data_dir = os.environ.get("NAMMA_DATA_DIR")
        if not data_dir:
            print("Set NAMMA_DATA_DIR to a SCRATCH folder or pass --db.", file=sys.stderr)
            return 2
        db_path = str(Path(data_dir) / "namma_agent.db")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from namma_agent.core.engram import Engram
    from namma_agent.core.memory import Database

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    provider = scripted_provider()
    eng = Engram(db, config={"database": {"path": db_path}},
                 provider_getter=lambda: provider)
    report = seed(eng)
    print(json.dumps({"db": db_path, **report, **eng.store.counts()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
