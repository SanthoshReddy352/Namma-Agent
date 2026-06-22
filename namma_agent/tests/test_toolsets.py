"""Tests for the Toolsets system (Phase 3): per-tool enable/disable, toolset
grouping, the disabled-set persisted to config, and the registry honoring it."""
from __future__ import annotations

from namma_agent.core.tools import ToolRegistry, ToolResult


def _reg(disabled=None):
    reg = ToolRegistry(disabled=disabled)
    reg.register("alpha", "first tool", {}, lambda a: "a", category="demo")
    reg.register("beta", "second tool", {}, lambda a: "b", category="demo")
    reg.register("gamma", "third tool", {}, lambda a: "c", category="other",
                 destructive=True)
    return reg


# ── categorization ───────────────────────────────────────────────────────────

def test_default_category():
    reg = ToolRegistry()
    reg.register("x", "d", {}, lambda a: "x")
    assert reg.get("x").category == "general"


def test_categorize_context_manager():
    reg = ToolRegistry()
    with reg.categorize("web"):
        reg.register("web_search", "d", {}, lambda a: "")
        reg.register("web_extract", "d", {}, lambda a: "", category="override")
    reg.register("after", "d", {}, lambda a: "")
    assert reg.get("web_search").category == "web"
    assert reg.get("web_extract").category == "override"  # explicit wins
    assert reg.get("after").category == "general"          # context restored


def test_loaded_tools_grouped_by_module():
    """load_tools tags each tool with the module (toolset) it came from."""
    from namma_agent.tools import load_tools

    reg = load_tools(ToolRegistry())
    assert reg.get("read_file").category == "file_ops"
    assert reg.get("run_shell").category == "shell"
    assert reg.get("web_search").category == "web"


# ── enable / disable ─────────────────────────────────────────────────────────

def test_disabled_excluded_from_definitions():
    reg = _reg(disabled=["beta"])
    assert reg.get("beta").enabled is False
    names = {d["name"] for d in reg.definitions()}
    assert "beta" not in names and {"alpha", "gamma"} <= names


def test_disabled_excluded_with_only_scope():
    reg = _reg(disabled=["alpha"])
    names = {d["name"] for d in reg.definitions(only={"alpha", "beta"})}
    assert names == {"beta"}


def test_execute_refuses_disabled():
    reg = _reg(disabled=["alpha"])
    res = reg.execute("alpha", {})
    assert isinstance(res, ToolResult)
    assert not res.ok and "disabled" in res.error
    # An enabled tool still runs.
    assert reg.execute("beta", {}).ok


def test_set_enabled_roundtrip():
    reg = _reg()
    assert reg.set_enabled("alpha", False).enabled is False
    assert reg.disabled_names() == ["alpha"]
    assert "alpha" not in {d["name"] for d in reg.definitions()}
    reg.set_enabled("alpha", True)
    assert reg.disabled_names() == []
    assert "alpha" in {d["name"] for d in reg.definitions()}


def test_set_enabled_unknown_returns_none():
    assert _reg().set_enabled("nope", False) is None


def test_set_category_enabled():
    reg = _reg()
    changed = reg.set_category_enabled("demo", False)
    assert {t.name for t in changed} == {"alpha", "beta"}
    assert reg.disabled_names() == ["alpha", "beta"]
    assert {d["name"] for d in reg.definitions()} == {"gamma"}
    # And re-enabling the toolset brings them back.
    reg.set_category_enabled("demo", True)
    assert reg.disabled_names() == []


def test_set_category_enabled_unknown():
    assert _reg().set_category_enabled("ghost", False) == []


def test_disabled_names_drops_stale():
    """A persisted disabled name that no longer maps to a tool is pruned."""
    reg = ToolRegistry(disabled=["alpha", "removed-long-ago"])
    reg.register("alpha", "d", {}, lambda a: "")
    assert reg.disabled_names() == ["alpha"]


def test_detail_shape():
    reg = _reg(disabled=["beta"])
    detail = {d["name"]: d for d in reg.detail()}
    assert detail["alpha"]["category"] == "demo"
    assert detail["alpha"]["enabled"] is True
    assert detail["beta"]["enabled"] is False
    assert detail["gamma"]["destructive"] is True


# ── persistence (mirrors the skills persistence test) ────────────────────────

def test_disabled_persists_to_config(tmp_path):
    """disabled_names() written under tools.disabled is honored by a fresh registry."""
    from namma_agent import config as cfgmod

    base = tmp_path / "config.yaml"
    base.write_text("tools: {}\n", encoding="utf-8")

    reg = _reg()
    reg.set_enabled("beta", False)
    cfgmod.update_config({"tools": {"disabled": reg.disabled_names()}}, path=str(base))

    merged = cfgmod.load_config(str(base))
    assert merged["tools"]["disabled"] == ["beta"]
    again = _reg(disabled=merged["tools"]["disabled"])
    assert again.get("beta").enabled is False
    assert "beta" not in {d["name"] for d in again.definitions()}
