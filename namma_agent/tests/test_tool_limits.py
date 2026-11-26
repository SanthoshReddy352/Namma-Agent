"""Provider tool limits + runaway-context guards.

Regression tests for audit findings (PROGRESS.md):
  * BUG-04 — >128 tools (native + a big MCP server such as GitHub's) made every
    OpenAI request fail with "array too long … maximum length 128".
  * BUG-05 — uncapped tool results stayed in context for every later step, and
    find_files walked .venv / node_modules.
"""
from __future__ import annotations

import re

from namma_agent.core.agent import DEFAULT_MAX_TOOLS_PER_REQUEST, Agent, _clip_tool_result
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.mcp.manager import _tool_reg_name

_OPENAI_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _registry(native: int, mcp: int) -> ToolRegistry:
    reg = ToolRegistry()
    schema = {"type": "object", "properties": {}}
    for i in range(native):
        reg.register(f"native_{i}", "n", schema, lambda a: ToolResult(ok=True, content=""))
    with reg.categorize("mcp"):
        for i in range(mcp):
            reg.register(f"mcp_github_tool_{i}", "m", schema,
                         lambda a: ToolResult(ok=True, content=""))
    return reg


def test_cap_keeps_native_tools_and_drops_mcp_first():
    reg = _registry(native=113, mcp=40)
    kept, dropped = reg.cap_definitions(reg.definitions(), 128)
    names = [d["name"] for d in kept]
    assert len(kept) == 128
    assert all(f"native_{i}" in names for i in range(113))
    assert len(dropped) == 25 and all(n.startswith("mcp_") for n in dropped)
    # newest MCP tools are dropped first
    assert "mcp_github_tool_39" in dropped and "mcp_github_tool_0" in names


def test_cap_falls_back_to_dropping_from_the_end_without_mcp():
    reg = _registry(native=130, mcp=0)
    kept, dropped = reg.cap_definitions(reg.definitions(), 128)
    assert len(kept) == 128 and dropped == ["native_128", "native_129"]


def test_cap_is_a_noop_under_the_limit_or_when_disabled():
    reg = _registry(native=10, mcp=5)
    defs = reg.definitions()
    assert reg.cap_definitions(defs, 128) == (defs, [])
    assert reg.cap_definitions(defs, 0) == (defs, [])


class _Capture(Provider):
    name = "cap"

    def __init__(self):
        super().__init__(model="cap")
        self.sent = None

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.sent = [t["name"] for t in (tools or [])]
        return LLMResponse(content="done")


def test_agent_never_sends_more_than_the_cap():
    prov = _Capture()
    reg = _registry(native=113, mcp=40)
    events = []
    agent = Agent(prov, reg, Database(":memory:"), load_persona(),
                  emit=lambda e, p: events.append((e, p)))
    # The hard cap is the backstop when tool search is OFF (Phase 2).
    agent.tool_search_settings = {**agent.tool_search_settings, "mode": "off"}
    assert agent.max_tools_per_request == DEFAULT_MAX_TOOLS_PER_REQUEST == 128
    agent.process_turn("hi", emit=lambda e, p: events.append((e, p)))
    assert prov.sent is not None and len(prov.sent) <= 128
    assert any(e == "tools_trimmed" and len(p["dropped"]) for e, p in events)


def test_tool_search_keeps_requests_small_without_dropping_anything():
    """Default (tool search auto): 153 tools → only core + meta-tools are sent,
    nothing is trimmed, and every tool stays reachable through tool_call."""
    prov = _Capture()
    reg = _registry(native=113, mcp=40)
    events = []
    agent = Agent(prov, reg, Database(":memory:"), load_persona())
    agent.process_turn("hi", emit=lambda e, p: events.append((e, p)))
    assert set(prov.sent) == {"tool_search", "tool_describe", "tool_call"}
    assert not any(e == "tools_trimmed" for e, _ in events)


def test_mcp_tool_names_are_openai_safe_and_unique():
    short = _tool_reg_name("github", "list-issues")
    assert short == "mcp_github_list_issues"
    long_a = _tool_reg_name("github", "a" * 80 + "_first")
    long_b = _tool_reg_name("github", "a" * 80 + "_second")
    for n in (short, long_a, long_b):
        assert _OPENAI_NAME.match(n), n
    assert long_a != long_b
    assert long_a.startswith("mcp_github_")  # disconnect_server matches on this prefix
    assert _OPENAI_NAME.match(_tool_reg_name("s" * 90, "tool"))


def test_clip_spills_full_output_to_a_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path))
    text = "x" * 50_000
    out = _clip_tool_result(text, 24_000)
    assert len(out) < 25_000 and "truncated" in out
    spilled = list((tmp_path / "tool_outputs").glob("*.txt"))
    assert len(spilled) == 1 and spilled[0].read_text(encoding="utf-8") == text
    assert str(spilled[0]) in out
    assert _clip_tool_result("short", 24_000) == "short"


def test_default_config_caps_tool_results_and_steps():
    # The shipped defaults (config.yaml), not a developer's local overlay.
    from pathlib import Path

    import yaml

    import namma_agent
    base = Path(namma_agent.__file__).parent / "config.yaml"
    conv = (yaml.safe_load(base.read_text(encoding="utf-8")) or {}).get("conversation") or {}
    assert int(conv.get("tool_result_max_chars") or 0) > 0
    assert int(conv.get("tool_loop_limit") or 0) > 0


def test_read_file_pages_with_offset(tmp_path):
    from namma_agent.tools.file_ops import register
    reg = ToolRegistry()
    register(reg)
    f = tmp_path / "big.txt"
    f.write_text("abcdefghij" * 10, encoding="utf-8")  # 100 chars
    first = reg.execute("read_file", {"path": str(f), "max_chars": 30})
    assert first.ok and first.content.startswith("a" + "bcdefghij")
    assert "Continue with offset=30" in first.content
    last = reg.execute("read_file", {"path": str(f), "offset": 90})
    assert last.ok and last.content.startswith("abcdefghij") and "End of file" in last.content
    whole = reg.execute("read_file", {"path": str(f)})
    assert whole.content == "abcdefghij" * 10  # small files are untouched


def test_find_files_skips_dependency_trees(tmp_path):
    from namma_agent.tools.file_ops import register
    reg = ToolRegistry()
    register(reg)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("", encoding="utf-8")
    for junk in ("node_modules", ".venv", "__pycache__", ".git"):
        (tmp_path / junk).mkdir()
        (tmp_path / junk / "lib.py").write_text("", encoding="utf-8")
    r = reg.execute("find_files", {"path": str(tmp_path), "pattern": "*.py"})
    assert r.ok and r.data == [str(tmp_path / "src" / "app.py")]
