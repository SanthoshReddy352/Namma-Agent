"""Phase 7e — user lifecycle hooks (core/hooks.py) + the user-tools surface.

The contract: hooks can observe everything and refuse a tool call, they can
never break a turn, and they cost nothing when nobody has written any.
"""
from __future__ import annotations

import pytest

from namma_agent.core import hooks as hk
from namma_agent.core.tools import ToolRegistry, ToolResult


@pytest.fixture(autouse=True)
def _clean_registry():
    """Every test starts with no hooks loaded and leaves none behind — the
    module registry is process-wide and ToolRegistry.execute reads it."""
    hk.load_hooks(directory="/nonexistent")
    yield
    hk.load_hooks(directory="/nonexistent")


def write_hook(tmp_path, name, body):
    path = tmp_path / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def reg():
    registry = ToolRegistry()
    registry.register("echo", "echo", {"type": "object", "properties": {}},
                      lambda a: ToolResult(ok=True, content="echoed"))
    registry.register("nuke", "delete things", {"type": "object", "properties": {}},
                      lambda a: ToolResult(ok=True, content="nuked"), destructive=True)
    registry.register("boom", "raises", {"type": "object", "properties": {}},
                      lambda a: (_ for _ in ()).throw(RuntimeError("kaboom")))
    return registry


# ── discovery ────────────────────────────────────────────────────────────────

def test_no_hooks_directory_is_fine():
    assert hk.load_hooks(directory="/definitely/not/here") == 0
    assert hk.status()["count"] == 0


def test_loads_a_hook_and_records_its_events(tmp_path):
    write_hook(tmp_path, "audit", "def post_tool(name, args, result):\n    pass\n")
    assert hk.load_hooks(tmp_path) == 1
    loaded = hk.status()["hooks"]
    assert loaded[0]["name"] == "audit"
    assert loaded[0]["events"] == ["post_tool"]


def test_loads_multiple_events_from_one_module(tmp_path):
    write_hook(tmp_path, "many", """
def pre_tool(name, args): return None
def post_tool(name, args, result): pass
def post_turn(session_id, user_text, reply): pass
def on_approval(name, args, approved): pass
""")
    hk.load_hooks(tmp_path)
    assert set(hk.status()["hooks"][0]["events"]) == set(hk.HOOK_NAMES)


def test_underscore_files_are_skipped(tmp_path):
    write_hook(tmp_path, "_helpers", "def pre_tool(name, args): return None\n")
    assert hk.load_hooks(tmp_path) == 0


def test_a_broken_hook_is_skipped_and_reported(tmp_path):
    """A typo in a personal script must not take down the assistant."""
    write_hook(tmp_path, "good", "def post_turn(s, u, r): pass\n")
    write_hook(tmp_path, "broken", "this is not python(((\n")
    assert hk.load_hooks(tmp_path) == 1
    status = hk.status()
    assert [h["name"] for h in status["hooks"]] == ["good"]
    assert status["errors"][0]["name"] == "broken"


def test_a_module_with_no_hook_functions_is_rejected(tmp_path):
    """Almost certainly a mistake — say so instead of loading a silent no-op."""
    write_hook(tmp_path, "empty", "X = 1\n")
    assert hk.load_hooks(tmp_path) == 0
    assert "nothing to hook" in hk.status()["errors"][0]["error"]


def test_reloading_replaces_the_previous_set(tmp_path):
    write_hook(tmp_path, "one", "def post_turn(s, u, r): pass\n")
    hk.load_hooks(tmp_path)
    assert len(hk.registry()) == 1
    hk.load_hooks(directory="/nonexistent")
    assert len(hk.registry()) == 0


# ── pre_tool: the only hook that can change behaviour ────────────────────────

def test_pre_tool_veto_blocks_the_call(tmp_path, reg):
    write_hook(tmp_path, "guard", """
def pre_tool(name, args):
    if name == "nuke":
        return "not on a Friday"
    return None
""")
    hk.load_hooks(tmp_path)

    blocked = reg.execute("nuke", {})
    assert blocked.ok is False
    assert "not on a Friday" in blocked.error
    assert "guard" in blocked.error          # names WHICH hook refused

    assert reg.execute("echo", {}).ok is True   # everything else unaffected


def test_pre_tool_returning_none_allows(tmp_path, reg):
    write_hook(tmp_path, "watch", "def pre_tool(name, args): return None\n")
    hk.load_hooks(tmp_path)
    assert reg.execute("echo", {}).content == "echoed"


def test_pre_tool_empty_string_is_not_a_veto(tmp_path, reg):
    write_hook(tmp_path, "watch", "def pre_tool(name, args): return '   '\n")
    hk.load_hooks(tmp_path)
    assert reg.execute("echo", {}).ok is True


def test_first_veto_wins(tmp_path, reg):
    write_hook(tmp_path, "a_first", "def pre_tool(name, args): return 'first says no'\n")
    write_hook(tmp_path, "b_second", "def pre_tool(name, args): return 'second says no'\n")
    hk.load_hooks(tmp_path)
    assert "first says no" in reg.execute("echo", {}).error


def test_a_raising_pre_tool_does_not_block_the_call(tmp_path, reg):
    """Fail-open on error is deliberate: a buggy hook must not brick the agent.
    An intentional refusal is a returned string, which is unambiguous."""
    write_hook(tmp_path, "buggy", "def pre_tool(name, args): raise ValueError('oops')\n")
    hk.load_hooks(tmp_path)
    assert reg.execute("echo", {}).ok is True


# ── observation hooks ────────────────────────────────────────────────────────

def test_post_tool_sees_the_result(tmp_path, reg):
    write_hook(tmp_path, "rec", """
SEEN = []
def post_tool(name, args, result):
    SEEN.append((name, result.ok, result.content))
""")
    hk.load_hooks(tmp_path)
    reg.execute("echo", {})
    seen = hk.registry()._hooks[0].fns["post_tool"].__globals__["SEEN"]
    assert seen == [("echo", True, "echoed")]


def test_post_tool_also_fires_when_the_tool_raised(tmp_path, reg):
    write_hook(tmp_path, "rec", """
SEEN = []
def post_tool(name, args, result):
    SEEN.append((name, result.ok, result.error))
""")
    hk.load_hooks(tmp_path)
    reg.execute("boom", {})
    seen = hk.registry()._hooks[0].fns["post_tool"].__globals__["SEEN"]
    assert seen[0][0] == "boom" and seen[0][1] is False
    assert "kaboom" in seen[0][2]


def test_a_raising_post_tool_does_not_break_the_result(tmp_path, reg):
    write_hook(tmp_path, "buggy", "def post_tool(name, args, result): raise ValueError('x')\n")
    hk.load_hooks(tmp_path)
    assert reg.execute("echo", {}).content == "echoed"


@pytest.mark.parametrize("approved", [True, False])
def test_on_approval_reports_both_outcomes(tmp_path, approved):
    write_hook(tmp_path, "rec", """
SEEN = []
def on_approval(name, args, approved):
    SEEN.append((name, approved))
""")
    hk.load_hooks(tmp_path)
    registry = ToolRegistry(approval=lambda tool, args: approved)
    registry.register("nuke", "d", {"type": "object", "properties": {}},
                      lambda a: "done", destructive=True)
    registry.execute("nuke", {})
    seen = hk.registry()._hooks[0].fns["on_approval"].__globals__["SEEN"]
    assert seen == [("nuke", approved)]


def test_on_approval_does_not_fire_for_safe_tools(tmp_path, reg):
    write_hook(tmp_path, "rec", """
SEEN = []
def on_approval(name, args, approved): SEEN.append(name)
""")
    hk.load_hooks(tmp_path)
    reg.execute("echo", {})
    assert hk.registry()._hooks[0].fns["on_approval"].__globals__["SEEN"] == []


def test_post_turn_dispatch(tmp_path):
    write_hook(tmp_path, "rec", """
SEEN = []
def post_turn(session_id, user_text, reply): SEEN.append((session_id, user_text, reply))
""")
    hk.load_hooks(tmp_path)
    hk.registry().post_turn("sess1", "hello", "hi there")
    seen = hk.registry()._hooks[0].fns["post_turn"].__globals__["SEEN"]
    assert seen == [("sess1", "hello", "hi there")]


def test_a_raising_post_turn_is_swallowed(tmp_path):
    write_hook(tmp_path, "buggy", "def post_turn(s, u, r): raise RuntimeError('x')\n")
    hk.load_hooks(tmp_path)
    hk.registry().post_turn("s", "u", "r")      # must not raise


# ── zero cost when unused ────────────────────────────────────────────────────

def test_no_hooks_means_no_dispatch_work(reg):
    assert len(hk.registry()) == 0
    assert hk.registry().pre_tool("anything", {}) == ""
    assert hk.registry()._call("post_tool", "x", {}, None) == []
    assert reg.execute("echo", {}).content == "echoed"


# ── user tools (pre-existing machinery, asserted here so it stays) ───────────

def test_user_tools_load_from_the_user_directory(tmp_path, monkeypatch):
    """~/.namma_agent/tools/*.py loading already shipped with create_tool; this
    pins the behaviour Phase 7e depends on."""
    from namma_agent.tools import authoring

    (tmp_path / "my_tool.py").write_text('''
from namma_agent.core.tools import ToolResult

def register(registry):
    registry.register("my_custom", "does a thing", {"type": "object", "properties": {}},
                      lambda args: ToolResult(ok=True, content="custom output"))
''', encoding="utf-8")
    monkeypatch.setattr(authoring, "USER_TOOLS_DIR", tmp_path)

    registry = ToolRegistry()
    assert authoring.load_user_tools(registry) == 1
    assert registry.execute("my_custom", {}).content == "custom output"


def test_a_broken_user_tool_is_skipped(tmp_path, monkeypatch):
    from namma_agent.tools import authoring

    (tmp_path / "bad.py").write_text("syntax ((( error\n", encoding="utf-8")
    (tmp_path / "good.py").write_text('''
def register(registry):
    registry.register("fine", "ok", {"type": "object", "properties": {}}, lambda a: "ok")
''', encoding="utf-8")
    monkeypatch.setattr(authoring, "USER_TOOLS_DIR", tmp_path)

    registry = ToolRegistry()
    assert authoring.load_user_tools(registry) == 1
    assert "fine" in registry
