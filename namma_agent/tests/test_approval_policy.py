"""Approval policies for unattended turns.

Regression tests for two audit findings (PROGRESS.md, BUG-01 / BUG-02):
  * Auto mode used to replace ANY approval callback with "allow", so routines,
    watchers and /v1 — which explicitly decline destructive tools — ran them.
  * Remote-channel turns passed ``approval=None``, which skipped the
    destructive-tool gate entirely.
"""
from __future__ import annotations

from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, ToolCall
from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.core.trust import (
    allow_all,
    channel_approval,
    decline_all,
    is_decline_all,
    reset_message_trust,
    set_message_trust,
)


def _service(auto_approve: bool, config_extra: dict | None = None):
    from namma_agent.service import NammaAgentService
    from namma_agent.tests.test_server import ScriptedProvider

    reg = ToolRegistry()
    hits = {"ran": 0}

    def danger(_args):
        hits["ran"] += 1
        return ToolResult(ok=True, content="boom")

    reg.register("danger", "d", {"type": "object", "properties": {}}, danger, destructive=True)
    prov = ScriptedProvider([
        LLMResponse(content="", tool_calls=[ToolCall(id="1", name="danger", args={})]),
        LLMResponse(content="done"),
    ])
    config = {"persona": "core", "conversation": {"auto_approve": auto_approve}}
    config.update(config_extra or {})
    svc = NammaAgentService(config=config, provider=prov, registry=reg, db=Database(":memory:"))
    svc.auto_approve = auto_approve
    return svc, hits


def test_decline_all_is_marked_and_allow_all_is_not():
    assert is_decline_all(decline_all)
    assert not is_decline_all(allow_all)
    assert not is_decline_all(lambda *_: False)
    assert not is_decline_all(None)


def test_auto_mode_never_overrides_decline_all():
    svc, hits = _service(auto_approve=True)
    svc.run_turn("do danger", approval=decline_all)
    assert hits["ran"] == 0


def test_routine_turn_declines_destructive_even_in_auto_mode():
    svc, hits = _service(auto_approve=True)
    svc._routine_turn("do danger", None)
    assert hits["ran"] == 0


def test_channel_policy_by_trust_level():
    assert channel_approval("owner") is allow_all
    assert channel_approval("trusted") is decline_all
    assert channel_approval("untrusted") is decline_all
    assert channel_approval("garbage") is decline_all
    opt_in = {"comms": {"trusted_can_run_destructive": True}}
    assert channel_approval("trusted", opt_in) is allow_all
    assert channel_approval("untrusted", opt_in) is decline_all


def test_trusted_channel_turn_declines_destructive():
    svc, hits = _service(auto_approve=False)
    token = set_message_trust("trusted")
    try:
        svc._channel_turn("do danger", None, "agent")
    finally:
        reset_message_trust(token)
    assert hits["ran"] == 0


def test_trusted_channel_turn_declines_even_in_auto_mode():
    svc, hits = _service(auto_approve=True)
    token = set_message_trust("trusted")
    try:
        svc._channel_turn("do danger", None, "agent")
    finally:
        reset_message_trust(token)
    assert hits["ran"] == 0


def test_owner_channel_turn_runs_destructive():
    svc, hits = _service(auto_approve=False)
    token = set_message_trust("owner")
    try:
        svc._channel_turn("do danger", None, "agent")
    finally:
        reset_message_trust(token)
    assert hits["ran"] == 1


def test_trusted_channel_opt_in_runs_destructive():
    svc, hits = _service(auto_approve=False,
                         config_extra={"comms": {"trusted_can_run_destructive": True}})
    token = set_message_trust("trusted")
    try:
        svc._channel_turn("do danger", None, "agent")
    finally:
        reset_message_trust(token)
    assert hits["ran"] == 1
