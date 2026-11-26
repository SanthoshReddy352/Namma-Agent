"""Phase 10 — memory graph primitives: resolution, relation extraction (mocked
model), schema, ranking, migration and the /api/memory/graph/* surface."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from namma_agent.core.engram import Engram
from namma_agent.core.engram import graph as G
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider


@pytest.fixture()
def store():
    return EngramStore(Database(":memory:"))


def _fact(store, text, s, p, o, **kw):
    """A fact + its graph link, the way the write pipeline stores one."""
    iid = store.add_item(text, subject=s, predicate=p, object=o, **kw)
    store.link_item(iid)
    return iid


def _names(store):
    snap = store.kg.snapshot()
    by_id = {n["id"]: n for n in snap["nodes"]}
    edges = {(by_id[e["src"]]["name"], e["rel"], by_id[e["dst"]]["name"])
             for e in snap["edges"]}
    return by_id, edges


def _load_seed():
    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_memory_graph.py"
    spec = importlib.util.spec_from_file_location("seed_memory_graph", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── pure canonicalisation helpers ────────────────────────────────────────────

@pytest.mark.parametrize("raw,key", [
    ("The User's", "user"), ("  Namma   Agent ", "namma agent"),
    ("my sister", "sister"), ("\"Python\".", "python"), ("dark_mode", "dark mode"),
])
def test_canonical_key_folds_case_articles_possessives(raw, key):
    assert G.canonical_key(raw) == key


def test_match_keys_cover_acronym_and_generic_suffix():
    assert G.match_keys("Kalasalingam Academy of Research and Education (KARE)") == [
        "kalasalingam academy of research and education", "kare"]
    assert G.match_keys("Namma Agent project") == ["namma agent project", "namma agent"]
    assert "python" in G.match_keys("Python programming language")


@pytest.mark.parametrize("raw,canon,flip", [
    ("loves", "likes", False), ("Is Building", "works_on", False),
    ("built_with", "uses", False), ("employs", "works_at", True),
    ("sister_of", "has_sister", True), ("studies_at", "studies_at", False),
    ("wants_github_tool_access", "wants_github_tool_access", False),
])
def test_canonical_predicate_synonyms_and_inverses(raw, canon, flip):
    assert G.canonical_predicate(raw) == (canon, flip)


def test_canonical_type_vocabulary_and_passthrough():
    assert G.canonical_type("University") == "organization"
    assert G.canonical_type("programming language") == "technology"
    assert G.canonical_type("people") == "person"
    assert G.canonical_type("thing") is None and G.canonical_type("") is None
    assert G.canonical_type("Recipe") == "recipe"      # unknown types pass through


def test_literal_and_description_detection():
    for v in ("21", "21 years old", "2027-02-01", "March 3, 2004", "a@b.co", "yes"):
        assert G.is_literal(v), v
    for v in ("Python", "Apollo Hospitals", "GATE exam"):
        assert not G.is_literal(v), v
    assert G.is_description("read-only repositories and issues only")
    assert not G.is_description("Kalasalingam Academy of Research and Education")
    assert not G.is_description("dark mode")


# ── entity resolution ────────────────────────────────────────────────────────

def test_first_person_and_the_user_resolve_to_one_self_entity(store):
    _fact(store, "The user lives in Pune", "the user", "lives_in", "Pune")
    _fact(store, "I like tea", "I", "likes", "tea")
    _fact(store, "User prefers dark mode", "User", "prefers", "dark mode")
    nodes, edges = _names(store)
    selves = [n for n in nodes.values() if n["is_self"]]
    assert len(selves) == 1 and selves[0]["type"] == "person"
    assert {e[0] for e in edges} == {"You"}


def test_has_name_makes_the_name_an_alias_and_merges_an_earlier_node(store):
    # The name node exists BEFORE we learn it is the user's own name.
    _fact(store, "Santhosh studies at KARE", "Santhosh", "studies_at", "KARE")
    _fact(store, "The user likes Python", "user", "likes", "Python")
    _fact(store, "The user's name is Santhosh", "user", "has_name", "Santhosh")
    nodes, edges = _names(store)
    assert "Santhosh" in {n["name"] for n in nodes.values() if n["is_self"]}
    assert not [n for n in nodes.values() if n["name"] == "Santhosh" and not n["is_self"]]
    assert edges == {("Santhosh", "studies_at", "KARE"), ("Santhosh", "likes", "Python")}
    # ...and the name keeps resolving to the user afterwards.
    _fact(store, "Santhosh owns a bike", "santhosh", "owns", "bike")
    nodes, edges = _names(store)
    assert ("Santhosh", "owns", "bike") in edges and len(
        [n for n in nodes.values() if n["is_self"]]) == 1


def test_acronym_suffix_and_case_variants_dedupe(store):
    _fact(store, "a", "user", "studies_at",
          "Kalasalingam Academy of Research and Education (KARE)")
    _fact(store, "b", "Arjun", "studies_at", "KARE")
    _fact(store, "c", "user", "works_on", "Namma Agent project")
    _fact(store, "d", "Arjun", "works_on", "namma agent")
    _fact(store, "e", "user", "likes", "python")
    _fact(store, "f", "Arjun", "likes", "Python")
    nodes, _ = _names(store)
    names = sorted(n["name"] for n in nodes.values())
    assert names == sorted(["You", "Arjun", "Kalasalingam Academy of Research and Education",
                            "Namma Agent", "Python"]), names
    kare = next(n for n in nodes.values() if n["name"].startswith("Kalasalingam"))
    assert "KARE" in kare["aliases"] and kare["type"] == "organization"


def test_pronoun_subjects_never_become_nodes(store):
    res = store.kg.ingest("he", "likes", "cricket")
    assert res["op"] == "skip"
    assert store.kg.snapshot()["nodes"] == []


def test_types_from_model_beat_inference_and_inference_fills_gaps(store):
    _fact(store, "x", "user", "has_pet", "Bruno")               # range → animal
    _fact(store, "y", "user", "uses", "Rust")                   # lexicon → technology
    _fact(store, "z", "user", "likes", "Carnatic music",
          object_type="Hobby")                                  # model → concept
    nodes, _ = _names(store)
    types = {n["name"]: n["type"] for n in nodes.values()}
    assert types["Bruno"] == "animal" and types["Rust"] == "technology"
    assert types["Carnatic music"] == "concept" and types["You"] == "person"


# ── relations: typed, directed, deduplicated, superseded ─────────────────────

def test_literals_and_descriptions_become_attributes_not_nodes(store):
    _fact(store, "21", "user", "age", "21")
    _fact(store, "gh", "user", "wants_github_tool_access",
          "read-only repositories and issues only")
    nodes, edges = _names(store)
    assert edges == set() and len(nodes) == 1
    me = next(iter(nodes.values()))
    assert me["attributes"] == {"age": "21",
                                "wants_github_tool_access": "read-only repositories and issues only"}


def test_restatements_collapse_into_one_relation_with_support(store):
    a = _fact(store, "loves python", "Santhosh", "loves", "Python")
    _fact(store, "likes python a lot", "santhosh", "likes", "python")
    snap = store.kg.snapshot()
    assert len(snap["edges"]) == 1
    e = snap["edges"][0]
    assert e["rel"] == "likes" and e["support"] == 2
    assert e["confidence"] == pytest.approx(1 - 0.3 * 0.3, abs=1e-3)   # noisy-OR
    # One supporting fact going away keeps the relation alive.
    store.invalidate(a)
    snap = store.kg.snapshot()
    assert len(snap["edges"]) == 1 and snap["edges"][0]["support"] == 1


def test_symmetric_relations_dedupe_in_either_direction(store):
    _fact(store, "a", "user", "collaborates_with", "Arjun")
    _fact(store, "b", "Arjun", "works_with", "user")
    snap = store.kg.snapshot()
    assert len(snap["edges"]) == 1 and snap["edges"][0]["symmetric"]


def test_inverse_predicates_are_stored_in_canonical_direction(store):
    _fact(store, "ACME employs Priya", "ACME", "employs", "Priya")
    _, edges = _names(store)
    assert edges == {("Priya", "works_at", "ACME")}


def test_functional_predicate_supersedes_and_retires_the_stale_fact(store):
    old = _fact(store, "lives in Bangalore", "user", "lives_in", "Bangalore")
    new = _fact(store, "lives in Hyderabad", "the user", "lives_in", "Hyderabad")
    _, live = _names(store)
    assert live == {("You", "lives_in", "Hyderabad")}
    full = store.kg.snapshot(include_expired=True)
    gone = next(e for e in full["edges"] if e["expired_at"])
    assert gone["superseded_by"] == next(e["id"] for e in full["edges"] if not e["expired_at"])
    # The resolver missed it; the graph caught it — the stale fact leaves recall.
    assert store.get_item(old)["expired_at"] and store.get_item(old)["superseded_by"] == new
    assert not store.get_item(new)["expired_at"]


def test_likes_and_dislikes_supersede_each_other(store):
    _fact(store, "likes Java", "user", "likes", "Java")
    _fact(store, "dislikes Java", "user", "dislikes", "Java")
    _, live = _names(store)
    assert live == {("You", "dislikes", "Java")}


def test_archive_and_hard_delete_clear_the_live_graph(store):
    a = _fact(store, "meeting", "user", "meeting_with", "Arjun")
    store.archive(a)
    assert store.kg.snapshot()["edges"] == []           # archived = out of the graph
    assert store.kg.snapshot(include_expired=True)["edges"]
    store.hard_delete(a)
    assert store.kg.snapshot(include_expired=True)["edges"] == []
    assert store.kg.snapshot(include_expired=True)["nodes"] == []


def test_approved_pending_fact_reaches_the_graph(store):
    iid = store.add_item("user uses Vim", subject="user", predicate="uses",
                         object="Vim", screen_status="pending")
    store.link_item(iid)                                # pending → no graph yet
    assert store.kg.snapshot()["edges"] == []
    assert store.approve_item(iid)
    _, edges = _names(store)
    assert edges == {("You", "uses", "Vim")}


def test_manual_merge_survives_a_rebuild(store):
    _fact(store, "a", "user", "uses", "VS Code")
    _fact(store, "b", "user", "uses", "Visual Studio Code")
    nodes, _ = _names(store)
    vs = next(n["id"] for n in nodes.values() if n["name"] == "VS Code")
    vsc = next(n["id"] for n in nodes.values() if n["name"] == "Visual Studio Code")
    assert store.kg.merge(vsc, vs)
    store.kg.rebuild()
    _, edges = _names(store)
    assert edges == {("You", "uses", "VS Code")}


# ── relation extraction through the write pipeline (mocked model) ────────────

class _Scripted(Provider):
    name = "scripted"

    def __init__(self, payloads):
        super().__init__(model="the-user-selected-model")
        self._payloads = list(payloads)
        self.calls = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.calls.append(messages)
        return LLMResponse(content=json.dumps(self._payloads.pop(0) if self._payloads else []))


def test_writer_extracts_typed_relations_on_the_selected_model():
    provider = _Scripted([
        [{"text": "Santhosh's sister Priya works at Apollo Hospitals.", "kind": "fact",
          "subject": "Priya", "subject_type": "person", "predicate": "works for",
          "object": "Apollo Hospitals", "object_type": "Hospital", "importance": 0.6}],
    ])
    eng = Engram(Database(":memory:"), config={"database": {"path": ":memory:"}},
                 provider_getter=lambda: provider)
    applied = eng.writer.process("My sister Priya works at Apollo Hospitals")
    assert applied and applied[0]["op"] == "ADD"
    # The extraction call went to the provider getter (the Settings model) and
    # asked for entity types.
    system = provider.calls[0][0]["content"]
    assert "subject_type" in system and '"user"' in system
    nodes, edges = _names(eng.store)
    assert edges == {("Priya", "works_at", "Apollo Hospitals")}
    types = {n["name"]: n["type"] for n in nodes.values()}
    assert types == {"Priya": "person", "Apollo Hospitals": "organization"}
    item = eng.store.list_items()[0]
    assert item["subject_type"] == "person" and item["object_type"] == "Hospital"


def test_writer_without_a_model_writes_no_graph_noise():
    eng = Engram(Database(":memory:"), config={"database": {"path": ":memory:"}},
                 provider_getter=lambda: None)
    eng.writer.process("I live in Pune", explicit=True)    # raw text kept, no triple
    assert eng.store.counts()["items"] == 1
    assert eng.store.kg.snapshot()["nodes"] == []


# ── schema ──────────────────────────────────────────────────────────────────

def test_schema_is_derived_from_actual_types_and_pairs(store):
    _fact(store, "a", "user", "works_on", "Namma Agent", object_type="project")
    _fact(store, "b", "Arjun", "works_on", "Namma Agent")
    _fact(store, "c", "Namma Agent", "built_with", "React")
    _fact(store, "d", "user", "age", "21")
    sch = store.kg.schema()
    types = {t["type"]: t for t in sch["types"]}
    assert types["person"]["count"] == 2 and types["project"]["count"] == 1
    assert "age" in types["person"]["attributes"]
    rels = {r["rel"]: r for r in sch["relations"]}
    assert rels["works_on"]["count"] == 2
    assert rels["works_on"]["pairs"] == [{"source": "person", "target": "project", "count": 2}]
    assert rels["uses"]["pairs"][0] == {"source": "project", "target": "technology", "count": 1}
    assert sch["counts"] == {"types": 3, "relations": 2, "entities": 4, "edges": 3}


# ── ranking ─────────────────────────────────────────────────────────────────

def test_pagerank_hub_outranks_leaves():
    pr = G.pagerank(["hub", "a", "b", "c"],
                    [("hub", "a", 1.0), ("hub", "b", 1.0), ("hub", "c", 1.0)])
    assert pr["hub"] > pr["a"] == pytest.approx(pr["b"])
    assert sum(pr.values()) == pytest.approx(1.0, abs=1e-6)


def test_ranked_combines_centrality_salience_recency(store):
    old = _fact(store, "old hobby", "user", "likes", "Chess", importance=0.3)
    _fact(store, "a", "user", "works_on", "Namma Agent", importance=0.9)
    _fact(store, "b", "Arjun", "works_on", "Namma Agent", importance=0.6)
    _fact(store, "c", "Namma Agent", "uses", "React", importance=0.6)
    _fact(store, "d", "user", "lives_in", "Pune", importance=0.7)
    _fact(store, "e", "user", "likes", "Python", importance=0.7)
    stale = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    store.conn.execute("UPDATE memory_items SET last_seen=? WHERE id=?", (stale, old))
    ranked = store.kg.ranked(half_life_days=30)
    by = {r["name"]: r for r in ranked}
    assert ranked[0]["is_self"]                         # the hub of a personal graph
    assert by["Namma Agent"]["score"] > by["Chess"]["score"]
    assert by["Chess"]["recency"] == pytest.approx(0.5 ** 4, rel=0.05)
    for r in ranked:
        assert 0 <= r["centrality"] <= 1 and 0 <= r["salience"] <= 1 and 0 <= r["recency"] <= 1
        assert r["score"] == pytest.approx(
            0.45 * r["centrality"] + 0.30 * r["salience"] + 0.25 * r["recency"], abs=1e-3)
    assert all(not r["is_self"] for r in store.kg.ranked(include_self=False))


# ── migration of existing (pre-Phase-10) data ────────────────────────────────

def _legacy_rows(db):
    """Write graph rows exactly as the pre-Phase-10 store did: every entity a
    'thing', one relation row per fact, no sources/aliases."""
    st = EngramStore(db)
    st.wipe()
    now = datetime.now(timezone.utc)
    rows = [
        ("user", "has_name", "Santhosh", None), ("Santhosh", "loves", "Python", None),
        ("santhosh", "likes", "python", None), ("the user", "lives_in", "Bangalore", "x"),
        ("I", "lives_in", "Hyderabad", None), ("user", "age", "21", None),
        ("Namma Agent project", "uses", "FastAPI", None),
        ("Santhosh", "is_building", "Namma Agent", None),
    ]
    ents: dict[str, str] = {}
    for i, (s, p, o, expired) in enumerate(rows):
        t = (now - timedelta(days=30 - i)).isoformat()
        iid = f"item-{i}"
        db.conn.execute(
            "INSERT INTO memory_items (id, text, kind, subject, predicate, object, "
            "importance, frequency, last_seen, created_at, expired_at, source, "
            "screen_status) VALUES (?,?,?,?,?,?,0.7,1,?,?,?,'chat','ok')",
            (iid, f"{s} {p} {o}", "fact", s, p, o, t, t,
             (now - timedelta(days=1)).isoformat() if expired else None))
        for name in (s, o):
            norm = " ".join(name.lower().split())
            if norm not in ents:
                ents[norm] = f"ent-{len(ents)}"
                db.conn.execute(
                    "INSERT INTO memory_entities (id, name, norm, type, created_at) "
                    "VALUES (?,?,?,'thing',?)", (ents[norm], name, norm, t))
        db.conn.execute(
            "INSERT INTO memory_relations (id, src, rel, dst, item_id, created_at, "
            "expired_at) VALUES (?,?,?,?,?,?,?)",
            (f"rel-{i}", ents[" ".join(s.lower().split())], p,
             ents[" ".join(o.lower().split())], iid, t,
             (now - timedelta(days=1)).isoformat() if expired else None))
    db.conn.execute("DELETE FROM memory_meta")            # "pre-Phase-10" database
    db.conn.commit()


def test_migration_rebuilds_legacy_graph_on_open():
    db = Database(":memory:")
    _legacy_rows(db)
    assert db.conn.execute("SELECT count(*) FROM memory_entities").fetchone()[0] == 11
    store = EngramStore(db)                               # opening migrates
    nodes, edges = _names(store)
    assert {n["name"] for n in nodes.values()} == {
        "Santhosh", "Python", "Hyderabad", "Namma Agent", "FastAPI"}
    me = next(n for n in nodes.values() if n["is_self"])
    assert me["name"] == "Santhosh" and me["attributes"]["age"] == "21"
    assert edges == {("Santhosh", "likes", "Python"), ("Santhosh", "lives_in", "Hyderabad"),
                     ("Namma Agent", "uses", "FastAPI"), ("Santhosh", "works_on", "Namma Agent")}
    assert all(n["type"] != "thing" for n in nodes.values())
    likes = next(e for e in store.kg.snapshot()["edges"] if e["rel"] == "likes")
    assert likes["support"] == 2
    # Idempotent: a second rebuild gives the same graph; version recorded.
    assert store.kg._version() == G.GRAPH_VERSION
    report = store.kg.rebuild()
    assert report["after"] == {"entities": 5, "relations": 4}
    assert _names(store)[1] == edges


def test_migration_keeps_time_travel_history():
    db = Database(":memory:")
    _legacy_rows(db)
    store = EngramStore(db)
    full = store.kg.snapshot(include_expired=True)
    bang = [e for e in full["edges"] if e["expired_at"]]
    assert bang, "the superseded Bangalore relation is kept as history"
    mid = bang[0]["created_at"]
    then = store.kg.snapshot(as_of=mid)
    names = {n["id"]: n["name"] for n in then["nodes"]}
    assert ("lives_in", "Bangalore") in {(e["rel"], names[e["dst"]]) for e in then["edges"]}


def test_seeded_conversations_build_a_correct_graph():
    """The realistic seed (scripts/seed_memory_graph.py) through the real
    pipeline: the graph the Memory page shows on a scratch instance."""
    seed = _load_seed()
    provider = seed.scripted_provider()
    eng = Engram(Database(":memory:"), config={"database": {"path": ":memory:"}},
                 provider_getter=lambda: provider)
    seed.seed(eng)
    nodes, edges = _names(eng.store)
    names = {n["name"]: n for n in nodes.values()}
    assert set(names) == {
        "Santhosh", "Kalasalingam Academy of Research and Education", "Python",
        "Namma Agent", "FastAPI", "React", "Priya", "Apollo Hospitals", "Java", "Bruno",
        "Arjun", "dark mode", "GATE exam", "Hyderabad"}
    assert names["Santhosh"]["is_self"] and names["Santhosh"]["attributes"]["age"] == "21"
    assert names["Bruno"]["type"] == "animal" and names["Hyderabad"]["type"] == "place"
    assert ("Santhosh", "likes", "Python") in edges
    assert ("Santhosh", "lives_in", "Hyderabad") in edges
    assert not any(e[2] == "Bangalore" for e in edges)
    assert len(edges) == 15
    ranked = eng.store.kg.ranked()
    assert ranked[0]["name"] == "Santhosh"
    assert {t["type"] for t in eng.store.kg.schema()["types"]} == {
        "person", "organization", "place", "project", "technology", "animal",
        "event", "concept"}


# ── service / API surface ────────────────────────────────────────────────────

class _Echo(Provider):
    name = "echo"

    def __init__(self):
        super().__init__(model="echo")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="[]")


@pytest.fixture()
def svc():
    from namma_agent.core.tools import ToolRegistry
    from namma_agent.service import NammaAgentService
    return NammaAgentService(config={"database": {"path": ":memory:"}},
                             provider=_Echo(), registry=ToolRegistry())


def test_api_graph_schema_ranked_entity_search_merge(svc):
    from fastapi.testclient import TestClient

    from namma_agent.server.api import create_app
    st = svc.engram.store
    _fact(st, "Santhosh is building Namma Agent", "user", "works_on", "Namma Agent")
    _fact(st, "Namma Agent uses React", "Namma Agent", "uses", "React")
    _fact(st, "Arjun works on it", "Arjun", "works_on", "Namma Agent")
    _fact(st, "user knows A. Kumar", "user", "knows", "A Kumar")
    _fact(st, "user knows Arjun K", "user", "knows", "Arjun K")
    client = TestClient(create_app(svc))

    g = client.get("/api/memory/graph").json()
    assert g["ok"] and g["counts"] == {"nodes": 6, "edges": 5}
    edge = next(e for e in g["edges"] if e["rel"] == "works_on")
    assert edge["directed"] and edge["relation"] == "works on" and edge["support"] == 1
    assert all("score" in n and "type" in n for n in g["nodes"])

    sch = client.get("/api/memory/graph/schema").json()
    assert {r["rel"] for r in sch["relations"]} == {"works_on", "uses", "knows"}
    ranked = client.get("/api/memory/graph/ranked?limit=3").json()
    assert ranked["weights"] == {"centrality": 0.45, "salience": 0.30, "recency": 0.25}
    assert len(ranked["items"]) == 3

    hits = client.get("/api/memory/graph/search?q=namma").json()
    nid = hits["entities"][0]["id"]
    assert hits["entities"][0]["name"] == "Namma Agent" and hits["facts"]
    hood = client.get(f"/api/memory/graph/entity/{nid}").json()
    assert hood["ok"] and len(hood["edges"]) == 3 and len(hood["facts"]) >= 3
    assert hood["rank"]["name"] == "Namma Agent"
    assert {e["direction"] for e in hood["edges"]} == {"in", "out"}

    nodes = {n["label"]: n["id"] for n in g["nodes"]}
    r = client.post("/api/memory/graph/merge",
                    json={"source": nodes["Arjun K"], "target": nodes["Arjun"]}).json()
    assert r["ok"]
    g2 = client.get("/api/memory/graph").json()
    assert g2["counts"]["nodes"] == 5
    r = client.post(f"/api/memory/graph/entity/{nodes['A Kumar']}",
                    json={"name": "Anil Kumar", "type": "person"}).json()
    assert r["ok"]
    names = {n["label"]: n["type"] for n in client.get("/api/memory/graph").json()["nodes"]}
    assert names["Anil Kumar"] == "person"
    assert client.post("/api/memory/graph/rebuild").json()["ok"]
    assert client.get("/api/memory/graph/entity/nope").json()["ok"] is False
