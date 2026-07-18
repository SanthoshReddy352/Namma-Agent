"""Small-context (local model) turn shaping: the tool allow-list, the tool-result
cap, and per-model-profile overrides (history window / max_tokens / timeout)."""
from __future__ import annotations

from namma_agent.config import configured_models
from namma_agent.core.agent import Agent, _clip_tool_result
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry, ToolResult


class RecordingProvider(Provider):
    """Scripted responses + records the messages AND tool defs of every call."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)
        self.seen_messages = []
        self.seen_tools = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen_messages.append(list(messages))
        self.seen_tools.append(list(tools or []))
        return self._responses.pop(0)


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    with reg.categorize("file_ops"):
        reg.register("read_file", "read", {"type": "object", "properties": {}}, lambda a: "x")
        reg.register("write_file", "write", {"type": "object", "properties": {}}, lambda a: "x")
    with reg.categorize("web"):
        reg.register("web_search", "search", {"type": "object", "properties": {}}, lambda a: "x")
    with reg.categorize("system"):
        reg.register("update_todos", "todos", {"type": "object", "properties": {}}, lambda a: "x")
    with reg.categorize("memory"):
        reg.register("mcp_cognee_recall", "recall", {"type": "object", "properties": {}}, lambda a: "x")
    return reg


def _agent(responses, registry, **kwargs) -> Agent:
    return Agent(RecordingProvider(responses), registry, Database(":memory:"),
                 load_persona(), **kwargs)


# ── fix 1: the tool allow-list ────────────────────────────────────────────────

def test_global_tool_allow_scopes_definitions():
    """tools.allow mixes toolset (category) names and tool names; only the matching
    tools are exposed to the model."""
    agent = _agent([LLMResponse(content="ok")], _registry(),
                   tool_allow=["file_ops", "web_search"])
    agent.process_turn("hi")
    exposed = {d["name"] for d in agent.provider.seen_tools[0]}
    assert exposed == {"read_file", "write_file", "web_search"}


def test_provider_tool_allow_overrides_global():
    """A model profile's scope (riding the turn's provider) wins over the global
    allow-list — one local brain runs lite while others keep the global scope."""
    agent = _agent([LLMResponse(content="ok")], _registry(), tool_allow=["file_ops"])
    turn_provider = RecordingProvider([LLMResponse(content="ok")])
    turn_provider.tool_allow = ["web"]
    agent.process_turn("hi", provider=turn_provider)
    exposed = {d["name"] for d in turn_provider.seen_tools[0]}
    assert exposed == {"web_search"}


def test_no_allow_list_exposes_everything():
    agent = _agent([LLMResponse(content="ok")], _registry())
    agent.process_turn("hi")
    assert len(agent.provider.seen_tools[0]) == len(_registry())


def test_steering_blocks_follow_actual_exposure():
    """The Cognee / TODO steering blocks are only injected when THIS turn's scoped
    toolset actually exposes those tools — steering the model toward a tool it
    can't call just burns context and invites hallucinated calls."""
    agent = _agent([LLMResponse(content="ok")], _registry(), tool_allow=["file_ops"])
    agent.process_turn("hi")
    system = agent.provider.seen_messages[0][0]["content"]
    assert "COGNEE MEMORY" not in system and "TODO PLAN" not in system

    agent2 = _agent([LLMResponse(content="ok")], _registry(),
                    tool_allow=["memory", "update_todos"])
    agent2.process_turn("hi")
    system2 = agent2.provider.seen_messages[0][0]["content"]
    assert "COGNEE MEMORY" in system2 and "TODO PLAN" in system2


# ── fix 2: the tool-result cap ────────────────────────────────────────────────

def test_tool_result_capped_before_entering_context():
    reg = ToolRegistry()
    big = "A" * 50_000
    reg.register("read_doc", "read", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=big))
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="read_doc", args={})]),
        LLMResponse(content="done"),
    ]
    agent = _agent(responses, reg, tool_result_max_chars=4000)
    agent.process_turn("read it")
    tool_msg = next(m for m in agent.provider.seen_messages[1] if m.get("role") == "tool")
    assert len(tool_msg["content"]) < 4500
    assert "tool result truncated" in tool_msg["content"]
    assert "50000" in tool_msg["content"]  # the model is told the real size


def test_provider_result_cap_overrides_global():
    reg = ToolRegistry()
    reg.register("read_doc", "read", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="B" * 10_000))
    agent = _agent([LLMResponse(content="unused")], reg, tool_result_max_chars=0)
    turn_provider = RecordingProvider([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="read_doc", args={})]),
        LLMResponse(content="done"),
    ])
    turn_provider.tool_result_max_chars = 1000
    agent.process_turn("read it", provider=turn_provider)
    tool_msg = next(m for m in turn_provider.seen_messages[1] if m.get("role") == "tool")
    assert len(tool_msg["content"]) < 1300 and "truncated" in tool_msg["content"]


def test_clip_is_a_noop_when_unlimited_or_small():
    assert _clip_tool_result("short", 0) == "short"
    assert _clip_tool_result("short", 100) == "short"
    assert _clip_tool_result("x" * 100, 100) == "x" * 100


# ── fix 3: per-model-profile overrides ────────────────────────────────────────

def test_provider_history_window_override():
    """A profile's max_history_turns (riding the provider) shrinks how much past
    conversation each prompt carries."""
    reg = ToolRegistry()
    agent = _agent([], reg, max_history_turns=12)
    db = agent.db
    sid = agent.new_session()
    for i in range(10):
        db.add_turn(sid, "user", f"q{i}")
        db.add_turn(sid, "assistant", f"a{i}")

    turn_provider = RecordingProvider([LLMResponse(content="ok")])
    turn_provider.max_history_turns = 4
    agent.process_turn("now", session_id=sid, provider=turn_provider)
    msgs = turn_provider.seen_messages[0]
    # system + at most 4 history turns + the new user message
    assert len(msgs) <= 1 + 4 + 1


def test_configured_models_passes_tuning_through():
    cfg = {"models": [{
        "label": "Qwen3 (LM Studio)", "type": "lmstudio", "model": "qwen3-14b",
        "max_tokens": 2048, "timeout_s": 180, "max_history_turns": 4,
        "tool_result_max_chars": 8000, "tools_allow": ["file_ops", "web"],
    }, {
        "label": "Cloud", "provider": "opencode", "model": "big-pickle",
    }]}
    local, cloud = configured_models(cfg)
    assert local["max_tokens"] == 2048 and local["timeout_s"] == 180
    assert local["max_history_turns"] == 4 and local["tool_result_max_chars"] == 8000
    assert local["tools_allow"] == ["file_ops", "web"]
    # profiles without the knobs inherit (0/empty = use globals)
    assert cloud["max_tokens"] == 0 and cloud["tools_allow"] == []


def test_profile_provider_carries_overrides():
    """_build_profile_provider puts the profile's tuning on the Provider: connection
    caps (max_tokens/timeout_s) in the constructor, turn shaping as attributes the
    agent reads per turn."""
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config={"database": {"path": ":memory:"}},
                            registry=ToolRegistry(),
                            provider=RecordingProvider([]),
                            db=Database(":memory:"))
    prof = configured_models({"models": [{
        "label": "Local", "type": "lmstudio", "model": "qwen3-14b",
        "max_tokens": 2048, "timeout_s": 180, "max_history_turns": 4,
        "tool_result_max_chars": 8000, "tools_allow": ["file_ops"],
    }]})[0]
    prov = svc._build_profile_provider(prof)
    assert prov.max_tokens == 2048 and prov.timeout_s == 180
    assert prov.tool_allow == ["file_ops"]
    assert prov.max_history_turns == 4 and prov.tool_result_max_chars == 8000
    # an unadorned profile inherits the base provider tuning and sets no overrides
    plain = svc._build_profile_provider(configured_models(
        {"models": [{"label": "P", "type": "lmstudio", "model": "m"}]})[0])
    assert plain.max_tokens == 8192 and plain.tool_allow == []
