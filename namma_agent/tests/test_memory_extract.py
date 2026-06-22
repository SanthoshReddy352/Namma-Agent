"""Deterministic post-turn memory capture: the heuristic gate, fact upsert,
dedup, forget, and end-to-end recall via the agent's fact injection."""
from __future__ import annotations

import json

from namma_agent.core.memory import Database
from namma_agent.core.memory_extract import MemoryExtractor
from namma_agent.core.providers.base import LLMResponse


class FakeProvider:
    """A provider that returns a canned JSON payload and records every call."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls = 0

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.calls += 1
        return LLMResponse(content=json.dumps(self._payload))


def _db() -> Database:
    return Database(":memory:")


def test_heuristic_gates_out_task_turns():
    assert not MemoryExtractor.looks_personal("play any song on youtube")
    assert not MemoryExtractor.looks_personal("what's the weather tomorrow?")
    assert MemoryExtractor.looks_personal("my name is Santhosh")
    assert MemoryExtractor.looks_personal("I'm a CSE student at KARE")
    assert MemoryExtractor.looks_personal("I prefer dark mode")


def test_capture_saves_durable_facts():
    db = _db()
    provider = FakeProvider({"facts": [
        {"key": "name", "value": "Santhosh Reddy", "category": "identity"},
        {"key": "branch", "value": "CSE", "category": "study"},
    ], "forget": []})
    ext = MemoryExtractor(db)

    saved = ext.capture(provider, "My name is Santhosh Reddy and I'm in CSE.")

    assert {s["key"] for s in saved} == {"name", "branch"}
    assert db.get_fact("name") == "Santhosh Reddy"
    assert db.get_fact("branch") == "CSE"


def test_non_personal_turn_makes_no_llm_call():
    db = _db()
    provider = FakeProvider({"facts": [], "forget": []})
    ext = MemoryExtractor(db)

    saved = ext.capture(provider, "open youtube and play a song")

    assert saved == []
    assert provider.calls == 0  # gated out before any model call


def test_unchanged_value_is_not_rewritten():
    db = _db()
    db.save_fact("name", "Santhosh Reddy", category="identity")
    provider = FakeProvider({"facts": [
        {"key": "name", "value": "Santhosh Reddy", "category": "identity"},
    ], "forget": []})
    ext = MemoryExtractor(db)

    saved = ext.capture(provider, "Just so you know, my name is Santhosh Reddy.")

    assert saved == []  # identical value → skipped
    assert db.get_fact("name") == "Santhosh Reddy"


def test_forget_deletes_a_fact():
    db = _db()
    db.save_fact("location", "Chennai")
    provider = FakeProvider({"facts": [], "forget": ["location"]})
    ext = MemoryExtractor(db)

    ext.capture(provider, "Actually, forget that I live in Chennai.")

    assert db.get_fact("location") is None


def test_disabled_extractor_does_nothing():
    db = _db()
    provider = FakeProvider({"facts": [{"key": "name", "value": "X"}], "forget": []})
    ext = MemoryExtractor(db, enabled=False)

    assert ext.capture(provider, "my name is X") == []
    assert provider.calls == 0


def test_captured_fact_reaches_a_fresh_session_prompt():
    """The whole point: a fact captured in one turn is injected into the system
    prompt of a brand-new session (cross-session recall)."""
    from namma_agent.core.persona import load_persona

    db = _db()
    provider = FakeProvider({"facts": [
        {"key": "name", "value": "Santhosh Reddy", "category": "identity"},
    ], "forget": []})
    MemoryExtractor(db).capture(provider, "my name is Santhosh Reddy")

    # A fresh session builds its system prompt from db.all_facts() — exactly what
    # Agent._build_messages does on the first turn of a new session.
    prompt = load_persona("core").system_prompt(facts=db.all_facts())
    assert "Santhosh Reddy" in prompt
