"""Phase 1 tests for the provider layer.

Cover message/tool translation, registry construction, and the fallback chain —
all without real SDKs or API keys (imports are lazy; translation is pure).
"""
from __future__ import annotations

import pytest

from namma_agent.core.providers import (
    AnthropicProvider,
    LLMResponse,
    OpenAICompatProvider,
    OpenAIProvider,
    Provider,
    ProviderChain,
    ProviderError,
    ToolCall,
    build_provider,
    from_config,
)
from namma_agent.core.providers.google_provider import GoogleProvider


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

class FakeProvider(Provider):
    name = "fake"

    def __init__(self, *, available=True, fail=False, reply="hi", **kw):
        super().__init__(model=kw.pop("model", "fake-model"), **kw)
        self._available = available
        self._fail = fail
        self._reply = reply
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.calls += 1
        if self._fail:
            raise ProviderError("boom")
        if stream and on_token:
            on_token(self._reply)
        return LLMResponse(content=self._reply, provider=self.name, model=self.model)


# --------------------------------------------------------------------------
# OpenAI-style translation
# --------------------------------------------------------------------------

def test_openai_wire_messages_tool_call_and_result():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "scan it"},
        {"role": "assistant", "content": "", "tool_calls": [ToolCall(id="c1", name="nmap", args={"host": "x"})]},
        {"role": "tool", "tool_call_id": "c1", "name": "nmap", "content": "3 ports"},
    ]
    wire = OpenAICompatProvider._to_wire_messages(messages)
    assert wire[0] == {"role": "system", "content": "sys"}
    assert wire[2]["role"] == "assistant"
    assert wire[2]["tool_calls"][0]["id"] == "c1"
    assert wire[2]["tool_calls"][0]["function"]["name"] == "nmap"
    # arguments are JSON-encoded
    assert '"host"' in wire[2]["tool_calls"][0]["function"]["arguments"]
    assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": "3 ports"}


def test_openai_wire_tools_shape():
    tools = [{"name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    wire = OpenAICompatProvider._to_wire_tools(tools)
    assert wire[0]["type"] == "function"
    assert wire[0]["function"]["name"] == "t"
    assert OpenAICompatProvider._to_wire_tools(None) is None


def test_ollama_localhost_needs_no_key():
    p = OpenAICompatProvider(model="llama3.1", base_url="http://localhost:11434/v1")
    assert p._requires_key() is False


# --------------------------------------------------------------------------
# Anthropic translation
# --------------------------------------------------------------------------

def test_anthropic_wire_merges_tool_results_into_user():
    messages = [
        {"role": "assistant", "content": "ok", "tool_calls": [
            ToolCall(id="a1", name="t1", args={}),
            ToolCall(id="a2", name="t2", args={}),
        ]},
        {"role": "tool", "tool_call_id": "a1", "name": "t1", "content": "r1"},
        {"role": "tool", "tool_call_id": "a2", "name": "t2", "content": "r2"},
    ]
    wire = AnthropicProvider._to_wire_messages(messages)
    # assistant content blocks: text + two tool_use
    assert wire[0]["role"] == "assistant"
    types = [b["type"] for b in wire[0]["content"]]
    assert types == ["text", "tool_use", "tool_use"]
    # both tool results merged into ONE user message
    assert len(wire) == 2
    assert wire[1]["role"] == "user"
    assert [b["type"] for b in wire[1]["content"]] == ["tool_result", "tool_result"]
    assert wire[1]["content"][0]["tool_use_id"] == "a1"


def test_anthropic_tools_have_cache_control():
    tools = [{"name": "t", "description": "d", "parameters": {"type": "object"}}]
    wire = AnthropicProvider._to_wire_tools(tools)
    assert wire[-1]["cache_control"] == {"type": "ephemeral"}
    assert wire[0]["input_schema"] == {"type": "object"}


def test_split_system():
    sys_text, convo = Provider.split_system(
        [{"role": "system", "content": "a"}, {"role": "system", "content": "b"}, {"role": "user", "content": "u"}]
    )
    assert sys_text == "a\n\nb"
    assert convo == [{"role": "user", "content": "u"}]


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ptype,cls", [
    ("anthropic", AnthropicProvider),
    ("openai", OpenAIProvider),
    ("google", GoogleProvider),
    ("gemini", GoogleProvider),
    ("openai_compat", OpenAICompatProvider),
    ("opencode", OpenAICompatProvider),
    ("lmstudio", OpenAICompatProvider),
    ("ollama", OpenAICompatProvider),
])
def test_build_provider_types(ptype, cls):
    p = build_provider({"type": ptype, "model": "m"})
    assert isinstance(p, cls)


def test_build_provider_unknown_raises():
    with pytest.raises(ValueError):
        build_provider({"type": "nope", "model": "m"})


def test_ollama_type_default_base_url():
    p = build_provider({"type": "ollama", "model": "llama3.1"})
    assert p.base_url == "http://localhost:11434/v1"


def test_from_config_single_vs_chain():
    single = from_config({"provider": {"type": "openai", "model": "m"}})
    assert not isinstance(single, ProviderChain)

    chain = from_config({"provider": {
        "type": "anthropic", "model": "m",
        "fallback": [{"type": "openai", "model": "m2"}],
    }})
    assert isinstance(chain, ProviderChain)
    assert chain.active.name == "anthropic"


# --------------------------------------------------------------------------
# Fallback chain behavior
# --------------------------------------------------------------------------

def test_chain_skips_unavailable_then_succeeds():
    down = FakeProvider(available=False)
    up = FakeProvider(available=True, reply="from-up")
    chain = ProviderChain([down, up])
    resp = chain.generate([{"role": "user", "content": "hi"}])
    assert resp.content == "from-up"
    assert down.calls == 0 and up.calls == 1


def test_chain_advances_on_error():
    bad = FakeProvider(available=True, fail=True)
    good = FakeProvider(available=True, reply="ok")
    chain = ProviderChain([bad, good])
    resp = chain.generate([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert bad.calls == 1 and good.calls == 1


def test_chain_all_fail_raises():
    chain = ProviderChain([FakeProvider(available=True, fail=True), FakeProvider(available=False)])
    with pytest.raises(ProviderError):
        chain.generate([{"role": "user", "content": "hi"}])


def test_chain_streams_through_callback():
    got = []
    chain = ProviderChain([FakeProvider(available=True, reply="streamed")])
    chain.generate([{"role": "user", "content": "hi"}], stream=True, on_token=got.append)
    assert got == ["streamed"]


# --------------------------------------------------------------------------
# OpenAI parameter adaptation (max_completion_tokens & temperature)
# --------------------------------------------------------------------------

def test_openai_reasoning_and_completion_tokens_hints():
    # OpenAI provider defaults to max_completion_tokens
    prov_openai = OpenAIProvider(model="gpt-4o")
    assert prov_openai._prefers_max_completion_tokens() is True
    assert prov_openai._is_reasoning_model() is False

    # Reasoning models require max_completion_tokens and drop temperature
    for m in ("o1-preview", "o1-mini", "o3-2025-04-16", "o4-mini-2025-04-16"):
        p = OpenAICompatProvider(model=m)
        assert p._is_reasoning_model() is True
        assert p._prefers_max_completion_tokens() is True

    # Next-gen GPT-5/6 models require max_completion_tokens
    for m in ("gpt-5.4-mini", "gpt-6.1-sol"):
        p = OpenAICompatProvider(model=m)
        assert p._prefers_max_completion_tokens() is True

    # Third-party local models retain max_tokens
    local_p = OpenAICompatProvider(model="llama3.1", base_url="http://localhost:11434/v1")
    assert local_p._prefers_max_completion_tokens() is False
    assert local_p._is_reasoning_model() is False


def test_openai_generate_adaptive_parameter_repair(monkeypatch):
    calls = []

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    if "max_tokens" in kwargs:
                        raise RuntimeError("Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.")
                    
                    class DummyChoice:
                        message = type("Msg", (), {"content": "recovered", "tool_calls": None, "reasoning_content": ""})()
                        finish_reason = "stop"
                    
                    return type("Resp", (), {"choices": [DummyChoice()], "usage": None})()

    prov = OpenAICompatProvider(model="custom-model", base_url="http://custom/v1")
    monkeypatch.setattr(prov, "_client", lambda: DummyClient())

    resp = prov.generate([{"role": "user", "content": "hi"}])
    assert resp.content == "recovered"
    # First call had max_tokens; second call adapted to max_completion_tokens
    assert "max_tokens" in calls[0]
    assert "max_completion_tokens" in calls[1]


def test_openai_reasoning_effort_none_for_gpt56_tools(monkeypatch):
    p = OpenAICompatProvider(model="gpt-5.6-terra")
    assert p._requires_reasoning_effort_none_for_tools() is True

    calls = []

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    class DummyChoice:
                        message = type("Msg", (), {"content": "tool-ready", "tool_calls": None, "reasoning_content": ""})()
                        finish_reason = "stop"
                    return type("Resp", (), {"choices": [DummyChoice()], "usage": None})()

    monkeypatch.setattr(p, "_client", lambda: DummyClient())

    # Pure chat has no reasoning_effort injected
    p.generate([{"role": "user", "content": "hi"}], tools=None)
    assert "reasoning_effort" not in calls[0]

    # Tool calls automatically include reasoning_effort="none"
    p.generate([{"role": "user", "content": "call it"}], tools=[{"name": "t", "parameters": {}}])
    assert calls[1].get("reasoning_effort") == "none"


def test_openai_adaptive_reasoning_effort_repair(monkeypatch):
    calls = []

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    if kwargs.get("reasoning_effort") != "none":
                        raise RuntimeError(
                            "Function tools with reasoning_effort are not supported for gpt-5.6-terra in /v1/chat/completions. "
                            "To use function tools, use /v1/responses or set reasoning_effort to 'none'."
                        )
                    class DummyChoice:
                        message = type("Msg", (), {"content": "ok", "tool_calls": None, "reasoning_content": ""})()
                        finish_reason = "stop"
                    return type("Resp", (), {"choices": [DummyChoice()], "usage": None})()

    # Generic model where proactive didn't fire, but server rejects with error
    p = OpenAICompatProvider(model="custom-hybrid-model")
    monkeypatch.setattr(p, "_client", lambda: DummyClient())

    resp = p.generate([{"role": "user", "content": "hi"}], tools=[{"name": "t", "parameters": {}}])
    assert resp.content == "ok"
    assert "reasoning_effort" not in calls[0]
    assert calls[1].get("reasoning_effort") == "none"


def test_openai_temperature_restricted_for_gpt56(monkeypatch):
    p = OpenAICompatProvider(model="gpt-5.6-terra", temperature=0.3)
    assert p._is_temperature_restricted_model() is True

    calls = []

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    class DummyChoice:
                        message = type("Msg", (), {"content": "title", "tool_calls": None, "reasoning_content": ""})()
                        finish_reason = "stop"
                    return type("Resp", (), {"choices": [DummyChoice()], "usage": None})()

    monkeypatch.setattr(p, "_client", lambda: DummyClient())

    p.generate([{"role": "user", "content": "summarize"}])
    # Temperature 0.3 is proactively excluded so OpenAI doesn't 400
    assert "temperature" not in calls[0]


def test_openai_adaptive_temperature_unsupported_value_repair(monkeypatch):
    calls = []

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    if "temperature" in kwargs:
                        raise RuntimeError(
                            "Unsupported value: 'temperature' does not support 0.3 with this model. Only the default (1) value is supported."
                        )
                    class DummyChoice:
                        message = type("Msg", (), {"content": "ok", "tool_calls": None, "reasoning_content": ""})()
                        finish_reason = "stop"
                    return type("Resp", (), {"choices": [DummyChoice()], "usage": None})()

    p = OpenAICompatProvider(model="some-model", temperature=0.3)
    monkeypatch.setattr(p, "_client", lambda: DummyClient())

    resp = p.generate([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]

