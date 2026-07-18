"""Self-verification nudge — a turn that wrote files and is about to finalize
without any check after the write gets ONE '[system] verify it' message, then
the loop continues. Shell/comms and non-write tools never trigger it."""
from __future__ import annotations

from namma_agent.core.agent import _VERIFY_NUDGE, Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)
        self.seen_messages: list[list[dict]] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen_messages.append(list(messages))
        return self._responses.pop(0) if self._responses else LLMResponse(content="(exhausted)")


def _registry():
    reg = ToolRegistry()
    reg.register("write_file", "write a file", {"type": "object", "properties": {}},
                 lambda a: "wrote 42 bytes", destructive=True, category="file_ops")
    reg.register("read_file", "read a file", {"type": "object", "properties": {}},
                 lambda a: "the new content", category="file_ops")
    reg.register("send_message", "send a message", {"type": "object", "properties": {}},
                 lambda a: "sent", destructive=True, category="comms")
    return reg


def _agent(responses, **kw):
    db = Database(":memory:")
    agent = Agent(ScriptedProvider(responses), _registry(), db, load_persona(), **kw)
    return agent, db


def _write_call(id="t1"):
    return ToolCall(id=id, name="write_file", args={})


def test_unverified_write_gets_one_nudge():
    agent, _ = _agent([
        LLMResponse(tool_calls=[_write_call()]),
        LLMResponse(content="Done, saved it."),           # unverified draft
        LLMResponse(tool_calls=[ToolCall(id="t2", name="read_file", args={})]),
        LLMResponse(content="Verified — the file has the new content."),
    ])
    result = agent.process_turn("write the file")
    assert result.content == "Verified — the file has the new content."
    assert result.tools_used == ["write_file", "read_file"]
    # The third generate call carries the nudge as the newest user message.
    nudge_call = agent.provider.seen_messages[2]
    assert nudge_call[-1] == {"role": "user", "content": _VERIFY_NUDGE}


def test_nudge_fires_at_most_once():
    """A model that ignores the nudge and answers again is let through."""
    agent, _ = _agent([
        LLMResponse(tool_calls=[_write_call()]),
        LLMResponse(content="Done (unverified)."),
        LLMResponse(content="Still done."),               # ignores the nudge
    ])
    result = agent.process_turn("write the file")
    assert result.content == "Still done."
    assert len(agent.provider.seen_messages) == 3


def test_verified_write_is_not_nudged():
    agent, _ = _agent([
        LLMResponse(tool_calls=[_write_call()]),
        LLMResponse(tool_calls=[ToolCall(id="t2", name="read_file", args={})]),
        LLMResponse(content="Wrote and checked."),
    ])
    result = agent.process_turn("write the file")
    assert result.content == "Wrote and checked."
    assert len(agent.provider.seen_messages) == 3         # no extra round


def test_non_write_destructive_tools_are_exempt():
    """Comms/shell-style destructive tools carry their own proof — no nudge."""
    agent, _ = _agent([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="send_message", args={})]),
        LLMResponse(content="Message sent."),
    ])
    result = agent.process_turn("message them")
    assert result.content == "Message sent."
    assert len(agent.provider.seen_messages) == 2


def test_flag_off_disables_the_nudge():
    agent, _ = _agent([
        LLMResponse(tool_calls=[_write_call()]),
        LLMResponse(content="Done (unverified)."),
    ], verify_after_writes=False)
    result = agent.process_turn("write the file")
    assert result.content == "Done (unverified)."
    assert len(agent.provider.seen_messages) == 2


def test_declined_write_never_arms_the_nudge():
    agent, _ = _agent([
        LLMResponse(tool_calls=[_write_call()]),
        LLMResponse(content="Okay, I won't."),
    ])
    result = agent.process_turn("write it", approval=lambda name, args: False)
    assert result.content == "Okay, I won't."
    assert len(agent.provider.seen_messages) == 2
