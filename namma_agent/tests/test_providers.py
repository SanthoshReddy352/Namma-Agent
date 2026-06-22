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
