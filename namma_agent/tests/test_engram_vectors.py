"""Engram embeddings — the optional vector channel: store round-trip, fused
recall catching paraphrases, writer auto-embed, consolidation backfill, and
graceful degradation when no embedder is configured. All offline (FakeEmbedder)."""
from __future__ import annotations

import json
import time

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


def test_embedder_rewrites_localhost_to_ipv4():
    """localhost resolves to ::1 first on Windows and local inference servers
    bind IPv4 only, so every call paid a failed-connect penalty (measured
    2154 ms vs 75 ms against the same server) — and the documented config
    example used localhost."""
    assert Embedder(base_url="http://localhost:11434/v1",
                    model="m").base_url == "http://127.0.0.1:11434/v1"
    # An explicit IPv6 literal is a deliberate choice — leave it alone.
    assert Embedder(base_url="http://[::1]:11434/v1",
                    model="m").base_url == "http://[::1]:11434/v1"
    # Remote hosts untouched.
    assert Embedder(base_url="https://api.openai.com/v1",
                    model="m").base_url == "https://api.openai.com/v1"
    # Still counts as local for the no-API-key rule after rewriting.
    assert Embedder(base_url="http://localhost:11434/v1", model="m").available()


def test_embedder_circuit_breaks_after_a_failure():
    """Embeddings ship ON by default, so on a host without Ollama every recall
    would retry a dead endpoint — and an unreachable port is not always cheap
    (a closed loopback port measured 2.05 s at the OS level on Windows). One
    failure must silence the channel for a while."""
    e = Embedder(base_url="http://127.0.0.1:59999/v1", model="m", timeout_s=1)
    assert e.configured() and e.available()
    assert e.embed(["x"]) is None          # endpoint is dead
    assert e.configured()                  # still configured …
    assert not e.available()               # … but the circuit is open
    assert e.last_error


def test_embedder_backoff_grows_then_resets(monkeypatch):
    e = Embedder(base_url="http://127.0.0.1:59999/v1", model="m", timeout_s=1)
    e._note_failure("boom")
    first = e._blocked_until
    e._note_failure("boom")
    assert e._blocked_until - first >= e.COOLDOWN_S      # doubling
    for _ in range(20):
        e._note_failure("boom")
    assert e._blocked_until <= time.monotonic() + e.MAX_COOLDOWN_S + 1   # capped
    e._note_success()
    assert e.available() and e._failures == 0 and not e.last_error


def test_recall_skips_a_broken_embedder_without_calling_it():
    """The cooldown must short-circuit before any network work — recall checks
    available(), so a cooling channel costs zero calls."""
    store = EngramStore(Database(":memory:"))
    store.add_item("Santhosh studies at KARE")
    calls = []

    class _Flaky(Embedder):
        def embed(self, texts):
            calls.append(texts)
            return super().embed(texts)

    e = _Flaky(base_url="http://127.0.0.1:59999/v1", model="m", timeout_s=1)
    for _ in range(5):
        recall(store, Database(":memory:"), "KARE", embedder=e)
    assert len(calls) == 1                 # only the first attempt went out
    assert any("KARE" in r["text"] for r in
               recall(store, Database(":memory:"), "KARE", embedder=e))


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
