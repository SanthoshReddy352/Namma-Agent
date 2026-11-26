"""Behaviour fixes from live gpt-4.1-mini runs (2026-11-25): sub-agents must be
reachable without tool search, /skill commands load a skill, and the persona
teaches tables, resourcefulness and real delegation."""
from __future__ import annotations

from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.tool_search import DEFAULT_CORE
from namma_agent.core.tools import ToolRegistry


class _Skill:
    def __init__(self, name, enabled=True):
        self.name, self.enabled = name, enabled


class _Store:
    def __init__(self):
        self.skills = {"deep-research": _Skill("deep-research"), "off": _Skill("off", False)}

    def get(self, name):
        return self.skills.get(name)

    def render(self, name, session_id=None):
        return f"# Skill: {name}\n1. fan out with delegate_task"

    def catalog_text(self):
        return ""


def _agent():
    return Agent(None, ToolRegistry(), Database(":memory:"), load_persona(), skills=_Store())


def test_delegation_tools_are_always_sent():
    assert {"delegate_task", "background_task"} <= set(DEFAULT_CORE)


def test_slash_skill_loads_the_procedure_into_the_turn():
    a = _agent()
    ctx = a._with_turn_context("/deep-research vector databases", False)
    assert "SKILL INVOKED" in ctx and "fan out with delegate_task" in ctx
    assert ctx.endswith("/deep-research vector databases")


def test_unknown_or_disabled_slash_is_just_text():
    a = _agent()
    assert "SKILL INVOKED" not in a._with_turn_context("/nope do it", False)
    assert "SKILL INVOKED" not in a._with_turn_context("/off do it", False)
    assert "SKILL INVOKED" not in a._with_turn_context("use /deep-research later", False)
    assert "SKILL INVOKED" not in a._with_turn_context("/deep-research x", True)   # chat mode


def test_persona_teaches_tables_resourcefulness_and_real_delegation():
    sp = load_persona().system_prompt()
    assert "markdown table" in sp
    assert "BE RESOURCEFUL" in sp and "Never answer \"I can't\"" in sp
    assert "CALL `delegate_task`" in sp and "Never pretend to spawn sub-agents" in sp
    assert "numbers (bar / line / pie) are NOT Mermaid" in sp
