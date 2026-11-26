"""Phase 3 tests — event bus + model-narrated progress."""
from __future__ import annotations

import time

from namma_agent.core.events import EventBus, fanout
from namma_agent.core.narration import NarrationEngine, humanize_tool

# -- event bus -------------------------------------------------------------

def test_event_bus_pub_sub_and_wildcard():
    bus = EventBus()
    seen, allseen = [], []
    bus.subscribe("tool_started", lambda p: seen.append(p))
    bus.subscribe("*", lambda p: allseen.append(p["type"]))
    bus.publish("tool_started", {"tool": "x"})
    bus.publish("turn_completed", {})
    assert seen == [{"tool": "x"}]
    assert allseen == ["tool_started", "turn_completed"]


def test_fanout_drives_multiple_sinks():
    a, b = [], []
    emit = fanout(lambda e, p: a.append(e), lambda e, p: b.append(e))
    emit("preamble", {})
    assert a == ["preamble"] and b == ["preamble"]


def test_fanout_isolates_failing_sink():
    good = []
    def bad(e, p):
        raise RuntimeError("nope")
    emit = fanout(bad, lambda e, p: good.append(e))
    emit("token", {})  # must not raise
    assert good == ["token"]


# -- narration -------------------------------------------------------------

def test_preamble_is_spoken():
    spoken = []
    n = NarrationEngine(spoken.append)
    n.handle_event("preamble", {"session_id": "s", "text": "Sure, let me check."})
    assert spoken == ["Sure, let me check."]


def test_humanize_tool():
    assert humanize_tool("nmap_scan") == "running the scan"
    assert humanize_tool("browser_navigate") == "loading the page"
    assert humanize_tool("totally_unknown") == "working on that"


def test_progress_phrase_is_context_aware():
    n = NarrationEngine(lambda _t: None)
    assert "scan" in n.phrase_generator("nmap_scan", {}, 0)
    assert n.phrase_generator("web_search", {}, 1)  # second attempt has a line


def test_progress_fires_then_cancelled_on_finish():
    spoken = []
    n = NarrationEngine(spoken.append, progress_delays=(0.02, 5.0))
    n.handle_event("turn_started", {"session_id": "s"})
    n.handle_event("tool_started", {"session_id": "s", "tool": "nmap_scan", "args": {}})
    time.sleep(0.06)  # first delay elapses -> one progress line spoken
    n.handle_event("tool_finished", {"session_id": "s", "tool": "nmap_scan", "ok": True})
    time.sleep(0.05)  # second timer would have fired but was cancelled
    assert len(spoken) == 1
    assert "scan" in spoken[0]


def test_progress_suppressed_after_turn_completed():
    spoken = []
    n = NarrationEngine(spoken.append, progress_delays=(0.02,))
    n.handle_event("turn_started", {"session_id": "s"})
    n.handle_event("tool_started", {"session_id": "s", "tool": "x", "args": {}})
    n.handle_event("turn_completed", {"session_id": "s"})
    time.sleep(0.05)
    assert spoken == []


def test_tool_result_narration_opt_in():
    spoken = []
    n = NarrationEngine(spoken.append, narrate_tool_results=True)
    n.handle_event("tool_finished", {
        "session_id": "s", "tool": "nmap", "ok": True, "summary": "3 ports open\nmore detail",
    })
    assert spoken == ["3 ports open"]


def test_custom_phrase_generator_used():
    spoken = []
    n = NarrationEngine(spoken.append, progress_delays=(0.02,),
                        phrase_generator=lambda t, a, i: f"custom:{t}")
    n.handle_event("turn_started", {"session_id": "s"})
    n.handle_event("tool_started", {"session_id": "s", "tool": "zz", "args": {}})
    time.sleep(0.05)
    assert spoken == ["custom:zz"]
