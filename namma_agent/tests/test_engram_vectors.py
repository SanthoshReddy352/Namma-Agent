"""Engram embeddings — the optional vector channel: store round-trip, fused
recall catching paraphrases, writer auto-embed, consolidation backfill, and
graceful degradation when no embedder is configured. All offline (FakeEmbedder)."""
from __future__ import annotations

import json

from namma_agent.core.engram import Engram
from namma_agent.core.engram.embeddings import Embedder, cosine, from_blob, to_blob
from namma_agent.core.engram.recall import recall
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider


class FakeEmbedder:
    """Deterministic 'meaning' vectors: a fixed lookup, so tests control which
    texts count as semantically similar (no network, no model)."""

    model = "fake-embed"

    def __init__(self, table=None):
        self.table = dict(table or {})
        self.embedded: list[str] = []

    def available(self):
        return True

    def embed(self, texts):
        self.embedded.extend(texts)
        return [self.table.get(t, [0.0, 0.0, 1.0]) for t in texts]


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, payloads):
        super().__init__(model="scripted")
        self._payloads = list(payloads)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        payload = self._payloads.pop(0) if self._payloads else []
        return LLMResponse(content=json.dumps(payload))


# ── primitives ───────────────────────────────────────────────────────────────

def test_blob_roundtrip_and_cosine():
    vec = [0.5, -1.25, 3.0]
    assert from_blob(to_blob(vec)) == vec
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([], [1]) == 0.0


def test_embedder_available_needs_key_or_local(monkeypatch):
    monkeypatch.delenv("X_KEY", raising=False)
    remote = Embedder(base_url="https://api.example.com/v1", model="m",
                      api_key_env="X_KEY")
    assert not remote.available()          # remote endpoint, no key
    monkeypatch.setenv("X_KEY", "sk-123")
    assert remote.available()
    local = Embedder(base_url="http://localhost:1234/v1", model="m")
    assert local.available()               # local endpoints need no key
    assert not Embedder().available()      # unconfigured


# ── store ────────────────────────────────────────────────────────────────────

def test_vector_search_ranks_by_cosine_and_skips_expired():
    store = EngramStore(Database(":memory:"))
    a = store.add_item("likes hiking")
    b = store.add_item("owns a red car")
    store.add_vector(a, "m", [1.0, 0.0])
    store.add_vector(b, "m", [0.6, 0.8])
    hits = store.vector_search([1.0, 0.0], "m", limit=5)
    assert [h["id"] for h in hits] == [a, b]
    store.invalidate(a)
    hits = store.vector_search([1.0, 0.0], "m", limit=5)
    assert [h["id"] for h in hits] == [b]


def test_hard_delete_and_wipe_clean_vectors():
    store = EngramStore(Database(":memory:"))
    a = store.add_item("fact one")
    store.add_vector(a, "m", [1.0])
    store.hard_delete(a)
    assert store.vector_count() == 0
    b = store.add_item("fact two")
    store.add_vector(b, "m", [1.0])
    store.wipe()
    assert store.vector_count() == 0


# ── fused recall ─────────────────────────────────────────────────────────────

def test_recall_finds_paraphrase_via_vectors_only():
    """'my college' shares no keyword with the KARE fact — only the vector
    channel can surface it."""
    db = Database(":memory:")
    store = EngramStore(db)
    kare = store.add_item("Santhosh studies at KARE university")
    fake = FakeEmbedder({
        "Santhosh studies at KARE university": [1.0, 0.0, 0.0],
        "which college do I attend?": [0.95, 0.05, 0.0],
    })
    store.add_vector(kare, fake.model, [1.0, 0.0, 0.0])
    without = recall(store, db, "which college do I attend?")
    assert all("KARE" not in r["text"] for r in without)
    with_vec = recall(store, db, "which college do I attend?", embedder=fake)
    assert any("KARE" in r["text"] for r in with_vec)


# ── writer + engram wiring ───────────────────────────────────────────────────

def _engram(payloads=(), embeddings_cfg=None, embedder=None):
    db = Database(":memory:")
    cfg = {"database": {"path": ":memory:"}}
    if embeddings_cfg:
        cfg["memory"] = {"embeddings": embeddings_cfg}
    provider = ScriptedProvider(payloads)
    eng = Engram(db, config=cfg, provider_getter=lambda: provider)
    if embedder is not None:
        eng.embedder = embedder
        eng.writer.embedder = embedder
    return eng


def test_writer_embeds_new_facts():
    fake = FakeEmbedder()
    eng = _engram(payloads=[[{"text": "Santhosh's dog is Bruno", "kind": "fact",
                              "importance": 0.6}]], embedder=fake)
    eng.writer.process("my dog is called Bruno")
    assert "Santhosh's dog is Bruno" in fake.embedded
    assert eng.store.vector_count(fake.model) == 1


def test_backfill_embeds_missing_vectors():
    fake = FakeEmbedder()
    eng = _engram(embedder=fake)
    eng.store.add_item("fact without a vector")
    eng.store.add_item("another one")
    assert eng._backfill_vectors() == 2
    assert eng.store.vector_count(fake.model) == 2
    assert eng._backfill_vectors() == 0        # nothing left to do


def test_engram_builds_embedder_from_config(monkeypatch):
    monkeypatch.setenv("EMB_KEY", "sk-1")
    eng = _engram(embeddings_cfg={"base_url": "https://api.example.com/v1",
                                  "model": "text-embedding-3-small",
                                  "api_key_env": "EMB_KEY"})
    assert eng.embedder is not None and eng.embedder.available()
    assert eng.status()["embeddings"] is True
    # unconfigured → None, status false, everything still works
    eng2 = _engram()
    assert eng2.embedder is None
    assert eng2.status()["embeddings"] is False
    assert eng2._backfill_vectors() == 0
