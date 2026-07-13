"""The four Cognee memory-lifecycle ops behind the Memory tab — focus on the
**improve** op (session buffer → consolidate → cognify), which the cognee-mcp image
has no direct tool for. Offline: the cognee MCP client is faked.
"""
from __future__ import annotations

import pytest

from namma_agent.service import NammaAgentService


class FakeCogneeClient:
    def __init__(self):
        self.calls = []        # (tool, args)

    def call_tool(self, tool, args, timeout=None):
        self.calls.append((tool, dict(args or {})))
        return f"{tool}: ok"

    def list_tools(self):
        return [{"name": n} for n in ("remember", "recall", "forget")]


@pytest.fixture
def svc(monkeypatch):
    s = NammaAgentService.__new__(NammaAgentService)   # skip heavy __init__
    client = FakeCogneeClient()
    s._cognee_client = lambda: client
    s._fake = client
    return s


def test_session_remember_buffers_for_consolidation(svc):
    r = svc.cognee_remember("I love Python", permanent=False)
    assert r["ok"] and r["pending_consolidation"] == 1
    # stored to the session cache (fast, no graph build)
    tool, args = svc._fake.calls[-1]
    assert tool == "remember" and args.get("session_id") == "namma_ui"
    assert svc.cognee_pending() == 1


def test_permanent_remember_does_not_buffer(svc):
    r = svc.cognee_remember("I am building Namma Agent", permanent=True)
    assert r["ok"] and svc.cognee_pending() == 0
    tool, args = svc._fake.calls[-1]
    assert tool == "remember" and "session_id" not in args   # straight to cognify


def test_consolidate_promotes_buffer_to_graph_then_clears(svc):
    svc.cognee_remember("fact one", permanent=False)
    svc.cognee_remember("fact two", permanent=False)
    assert svc.cognee_pending() == 2

    out = svc.cognee_consolidate()
    assert out["ok"] and out["consolidated"] == 2 and out["pending_consolidation"] == 0
    # each buffered note was cognified permanently (no session_id this time)
    permanent_calls = [a for (t, a) in svc._fake.calls if t == "remember" and "session_id" not in a]
    assert {c["data"] for c in permanent_calls} == {"fact one", "fact two"}
    assert svc.cognee_pending() == 0   # buffer cleared


def test_consolidate_with_nothing_pending_is_friendly(svc):
    out = svc.cognee_consolidate()
    assert out["ok"] and out["consolidated"] == 0
    assert "Nothing pending" in out["content"]


def test_remember_rejects_empty(svc):
    out = svc.cognee_remember("   ", permanent=False)
    assert out["ok"] is False and svc.cognee_pending() == 0


def test_consolidate_offline_errors_cleanly():
    s = NammaAgentService.__new__(NammaAgentService)
    s._cognee_client = lambda: None
    out = s.cognee_consolidate()
    assert out["ok"] is False and "not connected" in out["error"]


def _svc_with_disk_buffer(tmp_path):
    """A bare service whose pending-consolidation buffer persists under tmp_path."""
    s = NammaAgentService.__new__(NammaAgentService)
    s._cognee_client = lambda: FakeCogneeClient()
    s.config = {"database": {"path": str(tmp_path / "namma_agent.db")}}
    return s


def test_session_buffer_survives_restart(tmp_path):
    # Buffered session memories must not vanish on an app restart — they'd
    # silently drop out of the Consolidate queue and never reach the graph.
    first = _svc_with_disk_buffer(tmp_path)
    first.cognee_remember("fact before restart", permanent=False)
    assert first.cognee_pending() == 1

    reborn = _svc_with_disk_buffer(tmp_path)      # fresh process, same data dir
    assert reborn.cognee_pending() == 1
    out = reborn.cognee_consolidate()
    assert out["ok"] and out["consolidated"] == 1

    third = _svc_with_disk_buffer(tmp_path)       # consolidation also persisted
    assert third.cognee_pending() == 0


