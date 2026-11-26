"""Phase 2: tool search (core tools + deferred behind tool_search/tool_call),
toolset profiles, and availability-gated (lab / smart-home) tools."""
from __future__ import annotations

import json

from namma_agent.core import tool_search as ts
from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry

_OBJ = {"type": "object", "properties": {}}


class Recorder(Provider):
    name = "rec"

    def __init__(self, responses):
        super().__init__(model="rec")
        self._r = list(responses)
        self.tools_seen: list[list[str]] = []
        self.messages_seen: list[list[dict]] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.tools_seen.append([t["name"] for t in (tools or [])])
        self.messages_seen.append(list(messages))
        return self._r.pop(0) if self._r else LLMResponse(content="done")


def _big_registry(calls: list) -> ToolRegistry:
    reg = ToolRegistry()
    with reg.categorize("file_ops"):
        reg.register("read_file", "Read a file.", _OBJ, lambda a: "file text")
    with reg.categorize("browser"):
        reg.register("play_vinyl", "Play a vinyl record by search query.",
                     {"type": "object", "properties": {"query": {"type": "string"}}},
                     lambda a: calls.append(("play_vinyl", a)) or "playing")
    with reg.categorize("comms"):
        reg.register("send_email", "Send an email message.", _OBJ,
                     lambda a: calls.append(("send_email", a)) or "sent", destructive=True)
    with reg.categorize("misc"):
        for i in range(50):
            reg.register(f"filler_{i}", f"Filler tool number {i}.", _OBJ, lambda a: "x")
    return reg


def _agent(reg, responses):
    return Agent(Recorder(responses), reg, Database(":memory:"), load_persona())


# ── splitting ────────────────────────────────────────────────────────────────

def test_small_registries_are_sent_whole():
    defs = [{"name": f"t{i}", "description": "", "parameters": _OBJ} for i in range(10)]
    sent, deferred = ts.split_tools(defs, ts.search_settings(None))
    assert sent == defs and deferred == []


def test_auto_mode_defers_past_the_threshold_and_keeps_order():
    defs = ([{"name": "read_file", "description": "", "parameters": _OBJ}]
            + [{"name": f"t{i}", "description": "", "parameters": _OBJ} for i in range(60)])
    sent, deferred = ts.split_tools(defs, ts.search_settings(None))
    assert [d["name"] for d in sent] == ["read_file", *ts.META_TOOLS]
    assert len(deferred) == 60


def test_off_and_always_modes():
    defs = [{"name": f"t{i}", "description": "", "parameters": _OBJ} for i in range(60)]
    off = ts.search_settings({"tools": {"search": {"mode": "off"}}})
    assert ts.split_tools(defs, off) == (defs, [])
    small = defs[:5]
    always = ts.search_settings({"tools": {"search": {"mode": "always", "core": ["t0"]}}})
    sent, deferred = ts.split_tools(small, always)
    assert [d["name"] for d in sent] == ["t0", *ts.META_TOOLS] and len(deferred) == 4


def test_settings_are_normalized():
    s = ts.search_settings({"tools": {"search": {"mode": "bogus", "threshold": "x"}}})
    assert s["mode"] == "auto" and s["threshold"] == ts.DEFAULT_THRESHOLD
    assert s["core"] == list(ts.DEFAULT_CORE)


# ── search / describe / unwrap ───────────────────────────────────────────────

def test_search_ranks_by_name_category_and_description_with_schemas():
    deferred = [
        {"name": "play_vinyl", "description": "Play a YouTube video.", "parameters": _OBJ},
        {"name": "send_email", "description": "Send an email message.", "parameters": _OBJ},
        {"name": "add_reminder", "description": "Remind the user later.", "parameters": _OBJ},
    ]
    out = ts.search("vinyl record", deferred, {"play_vinyl": "browser"})
    payload = json.loads(out.split("\n", 1)[1].split("\nAlso")[0])
    assert payload[0]["name"] == "play_vinyl" and "parameters" in payload[0]
    assert ts.search("email", deferred).count("send_email") == 1
    assert "No deferred tool" in ts.search("quantum teleport", deferred)
    exact = ts.search("select:add_reminder", deferred)
    assert '"add_reminder"' in exact and "play_vinyl" not in exact


def test_describe_and_unwrap():
    deferred = [{"name": "a", "description": "A.", "parameters": _OBJ}]
    assert '"a"' in ts.describe(["a", "zzz"], deferred) and "zzz" in ts.describe(["a", "zzz"], deferred)
    assert ts.describe(["zzz"], deferred).startswith("ERROR")
    assert ts.unwrap_call({"name": "a", "arguments": '{"x": 1}'}) == ("a", {"x": 1}, "")
    assert ts.unwrap_call({"name": "a"}) == ("a", {}, "")
    assert ts.unwrap_call({"arguments": {}})[2]
    assert ts.unwrap_call({"name": "a", "arguments": "{bad"})[2]


def test_tools_block_groups_by_toolset():
    block = ts.tools_block([{"name": "b"}, {"name": "a"}], {"a": "web", "b": "web"})
    assert "MORE TOOLS" in block and "- web: b, a" in block
    assert ts.tools_block([]) == ""


# ── the agent loop ───────────────────────────────────────────────────────────

def test_agent_sends_core_plus_meta_and_lists_deferred_tools():
    calls: list = []
    agent = _agent(_big_registry(calls), [LLMResponse(content="hi")])
    agent.process_turn("hello")
    sent = agent.provider.tools_seen[0]
    assert sent == ["read_file", *ts.META_TOOLS]
    system = agent.provider.messages_seen[0][0]["content"]
    assert "MORE TOOLS" in system and "play_vinyl" in system


def test_tool_list_is_identical_across_turns_for_caching():
    calls: list = []
    agent = _agent(_big_registry(calls), [LLMResponse(content="a"), LLMResponse(content="b")])
    r = agent.process_turn("one")
    agent.process_turn("two", session_id=r.session_id)
    first, second = agent.provider.messages_seen
    assert agent.provider.tools_seen[0] == agent.provider.tools_seen[1]
    assert first[0]["content"] == second[0]["content"]


def test_search_then_call_runs_the_deferred_tool():
    calls: list = []
    agent = _agent(_big_registry(calls), [
        LLMResponse(content="", tool_calls=[ToolCall(id="1", name="tool_search",
                                                     args={"query": "vinyl"})]),
        LLMResponse(content="", tool_calls=[ToolCall(
            id="2", name="tool_call",
            args={"name": "play_vinyl", "arguments": {"query": "lofi"}})]),
        LLMResponse(content="Playing lofi."),
    ])
    events = []
    res = agent.process_turn("play lofi", emit=lambda e, p: events.append((e, p)))
    assert calls == [("play_vinyl", {"query": "lofi"})]
    assert res.tools_used == ["tool_search", "play_vinyl"]
    # Search result carried the schema back to the model.
    tool_msgs = [m for m in agent.provider.messages_seen[1] if m.get("role") == "tool"]
    assert "play_vinyl" in tool_msgs[-1]["content"]
    # The transcript pairs the result with the tool_call call; events name the real tool.
    final_tool_msgs = [m for m in agent.provider.messages_seen[2] if m.get("role") == "tool"]
    assert final_tool_msgs[-1]["name"] == "tool_call"
    assert ("tool_started", "play_vinyl") in [(e, p.get("tool")) for e, p in events]
    audit = agent.db.recent_audit()
    assert audit[0]["tool"] == "play_vinyl"


def test_tool_call_respects_approval_for_destructive_tools():
    calls: list = []
    agent = _agent(_big_registry(calls), [
        LLMResponse(content="", tool_calls=[ToolCall(
            id="1", name="tool_call", args={"name": "send_email", "arguments": {}})]),
        LLMResponse(content="ok"),
    ])
    asked = []
    agent.process_turn("email bob", approval=lambda n, a: asked.append(n) or False)
    assert asked == ["send_email"] and calls == []
    last_tool = [m for m in agent.provider.messages_seen[1] if m.get("role") == "tool"][-1]
    assert "declined" in last_tool["content"]


def test_tool_call_refuses_tools_outside_the_turn_scope():
    calls: list = []
    reg = _big_registry(calls)
    reg.set_enabled("play_vinyl", False)
    agent = _agent(reg, [
        LLMResponse(content="", tool_calls=[ToolCall(
            id="1", name="tool_call", args={"name": "play_vinyl", "arguments": {}})]),
        LLMResponse(content="ok"),
    ])
    agent.process_turn("play")
    assert calls == []
    last_tool = [m for m in agent.provider.messages_seen[1] if m.get("role") == "tool"][-1]
    assert last_tool["content"].startswith("ERROR") and "tool_search" in last_tool["content"]


def test_untrusted_turns_cannot_reach_destructive_tools_via_tool_call():
    from namma_agent.core.trust import reset_message_trust, set_message_trust

    calls: list = []
    agent = _agent(_big_registry(calls), [
        LLMResponse(content="", tool_calls=[ToolCall(
            id="1", name="tool_call", args={"name": "send_email", "arguments": {}})]),
        LLMResponse(content="ok"),
    ])
    token = set_message_trust("untrusted")
    try:
        agent.process_turn("email everyone")
    finally:
        reset_message_trust(token)
    assert calls == []
    system = agent.provider.messages_seen[0][0]["content"]
    assert "send_email" not in system


# ── profiles ─────────────────────────────────────────────────────────────────

def test_profile_scopes_toolsets_and_explicit_allow_wins():
    calls: list = []
    reg = _big_registry(calls)
    agent = _agent(reg, [LLMResponse(content="a"), LLMResponse(content="b")])
    agent.tool_profile = "minimal"
    names = {d["name"] for d in agent._tool_defs_for(agent.new_session())}
    assert "read_file" in names and "play_vinyl" not in names and "send_email" not in names
    agent.tool_allow = ["browser"]
    names = {d["name"] for d in agent._tool_defs_for(agent.new_session())}
    assert names == {"play_vinyl"}


def test_profiles_catalogue():
    ids = [p["id"] for p in ts.profiles_list()]
    assert ids == ["general", "productivity", "code", "research", "minimal"]
    assert ts.profile_categories("general") is None
    assert "shell" in ts.profile_categories("code")
    assert ts.profile_categories("nonsense") is None


# ── availability-gated tools ─────────────────────────────────────────────────

def test_unavailable_tools_are_hidden_from_the_model_but_listed():
    reg = ToolRegistry()
    state = {"on": False}
    reg.register("scan", "Scan.", _OBJ, lambda a: "x",
                 requires=lambda: "" if state["on"] else "needs lab_mode")
    assert reg.definitions() == []
    assert reg.detail()[0]["unavailable"] == "needs lab_mode"
    state["on"] = True
    assert [d["name"] for d in reg.definitions()] == ["scan"]


def test_lab_and_smart_home_tools_hidden_without_config(monkeypatch):
    from namma_agent.tools import security, smart_home
    from namma_agent.tools import load_tools

    monkeypatch.setattr(security, "_cfg", lambda: {"lab_mode": False})
    monkeypatch.setattr(smart_home, "_cfg", lambda: {})
    reg = load_tools(ToolRegistry())
    names = {d["name"] for d in reg.definitions()}
    assert not names & {"port_scan", "ping_sweep", "dir_enum", "dns_enum"}
    assert not names & {"ha_turn_on", "ha_turn_off", "ha_get_state", "ha_set_temperature"}
    assert "port_scan" in reg            # still registered (Toolsets tab, clear errors)
    monkeypatch.setattr(security, "_cfg", lambda: {"lab_mode": True})
    assert "port_scan" in {d["name"] for d in reg.definitions()}


# ── service wiring ───────────────────────────────────────────────────────────

def test_service_applies_profile_and_search_settings(monkeypatch):
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(
        config={"persona": "core", "conversation": {},
                "tools": {"profile": "research", "search": {"mode": "off"}}},
        provider=Recorder([]), registry=ToolRegistry(), db=Database(":memory:"))
    assert svc.agent.tool_profile == "research"
    assert svc.agent.tool_search_settings["mode"] == "off"
    over = svc.tools_overview()
    assert over["profile"] == "research" and len(over["profiles"]) == 5
    import namma_agent.config as cfg
    monkeypatch.setattr(cfg, "update_config", lambda updates, path=None: {
        **svc.config, "tools": {**svc.config.get("tools", {}), **updates["tools"]}})
    assert svc.set_tool_profile("code")["profile"] == "code"
    assert svc.agent.tool_profile == "code"
    assert not svc.set_tool_profile("nope")["ok"]
    assert svc.set_tool_search("always")["search"]["mode"] == "always"
