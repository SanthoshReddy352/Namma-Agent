"""Tests for the skill system (procedural memory ported from hermes-agent)."""
from __future__ import annotations

import os

import pytest

from namma_agent.core.builtins import register_skill_tools
from namma_agent.core.skills import SkillStore, parse_frontmatter
from namma_agent.core.tools import ToolRegistry


def test_parse_frontmatter():
    fm, body = parse_frontmatter("---\nname: x\ndescription: hello\n---\n\n# Body\ntext")
    assert fm["name"] == "x"
    assert fm["description"] == "hello"
    assert "# Body" in body


def test_parse_frontmatter_none():
    fm, body = parse_frontmatter("# no frontmatter\njust text")
    assert fm == {}
    assert body.startswith("# no frontmatter")


def test_bundled_skills_discovered(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    names = {s.name for s in store.all()}
    # Seed skills that ship with Namma Agent.
    assert {"deep-research", "organize-files", "one-three-one-rule"} <= names


def test_render_includes_body(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    body = store.render("deep-research")
    assert body is not None
    assert "Procedure" in body
    assert body.startswith("# Skill: deep-research")


def test_render_unknown(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    assert store.render("does-not-exist") is None


def test_create_and_reload(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    skill = store.create("My Cool Skill", "when to use it", "# Body\nstep 1", category="test")
    assert skill.name == "my-cool-skill"
    assert skill.source == "user"
    assert (tmp_path / "skills" / "my-cool-skill" / "SKILL.md").exists()
    # Survives a reload (round-trips through disk).
    store.reload()
    assert store.get("my-cool-skill") is not None


def test_user_overrides_bundled(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    store.create("deep-research", "overridden", "# Overridden body")
    assert store.get("deep-research").source == "user"
    assert "Overridden body" in store.render("deep-research")


def test_update_skill(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    store.create("temp", "desc", "# Old")
    store.update("temp", body="# New body", description="new desc")
    skill = store.get("temp")
    assert skill.description == "new desc"
    assert "New body" in store.render("temp")


@pytest.mark.skipif(os.name == "nt",
                    reason="inline-shell expansion uses /bin/bash (POSIX only)")
def test_inline_shell_opt_in(tmp_path):
    udir = tmp_path / "skills"
    (udir / "echoer").mkdir(parents=True)
    (udir / "echoer" / "SKILL.md").write_text(
        "---\nname: echoer\ndescription: d\n---\nValue: !`echo HELLO`\n", encoding="utf-8"
    )
    off = SkillStore(user_dir=udir, allow_inline_shell=False)
    assert "!`echo HELLO`" in off.render("echoer")
    on = SkillStore(user_dir=udir, allow_inline_shell=True)
    assert "HELLO" in on.render("echoer")


def test_skill_tools(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    reg = ToolRegistry()
    register_skill_tools(reg, store)
    assert {"list_skills", "use_skill", "create_skill", "update_skill"} <= set(reg.names())

    listed = reg.execute("list_skills", {})
    assert listed.ok and "deep-research" in listed.content

    used = reg.execute("use_skill", {"name": "deep-research"})
    assert used.ok and "Procedure" in used.content

    created = reg.execute("create_skill", {
        "name": "from-tool", "description": "d", "body": "# B",
    })
    assert created.ok
    assert store.get("from-tool") is not None


# ── ported hermes catalog ────────────────────────────────────────────────────

def test_ported_hermes_skills_present(tmp_path):
    """The bulk hermes port landed and loads (category injected from the folder)."""
    store = SkillStore(user_dir=tmp_path / "skills")
    by_name = {s.name: s for s in store.all()}
    assert {"systematic-debugging", "notion", "obsidian"} <= set(by_name)
    assert by_name["notion"].category == "productivity"
    assert by_name["systematic-debugging"].category == "software-development"


# ── prerequisites / support ──────────────────────────────────────────────────

def _mk(udir, name, frontmatter_extra="", body="# Body"):
    d = udir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n{frontmatter_extra}---\n{body}\n", encoding="utf-8")


def test_prerequisites_parsed_and_support(tmp_path):
    udir = tmp_path / "skills"
    _mk(udir, "needs-cli", "prerequisites:\n  commands: [definitely-not-a-real-binary-xyz]\n")
    _mk(udir, "needs-env", "prerequisites:\n  env_vars: [NAMMA_TEST_NOPE_VAR]\n")
    _mk(udir, "plain", "")
    store = SkillStore(user_dir=udir)

    cli = store.get("needs-cli")
    assert cli.requires_commands == ["definitely-not-a-real-binary-xyz"]
    assert not cli.supported and any("command not found" in m for m in cli.missing())

    env = store.get("needs-env")
    assert env.requires_env == ["NAMMA_TEST_NOPE_VAR"]
    assert not env.supported

    assert store.get("plain").supported  # no prerequisites ⇒ always ready


def test_supported_env_present(tmp_path, monkeypatch):
    udir = tmp_path / "skills"
    _mk(udir, "needs-env", "prerequisites:\n  env_vars: [NAMMA_TEST_PRESENT]\n")
    monkeypatch.setenv("NAMMA_TEST_PRESENT", "1")
    store = SkillStore(user_dir=udir)
    assert store.get("needs-env").supported


# ── enable / disable ─────────────────────────────────────────────────────────

def test_disabled_excluded_from_agent_catalog(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills", disabled=["deep-research"])
    assert store.get("deep-research").enabled is False
    assert "deep-research" not in store.catalog_text()
    # Still listed for the UI.
    assert "deep-research" in {s.name for s in store.all()}
    # use_skill / render refuse it.
    assert store.render("deep-research") is None


def test_unsupported_excluded_from_agent_catalog(tmp_path):
    udir = tmp_path / "skills"
    _mk(udir, "needs-cli", "prerequisites:\n  commands: [definitely-not-a-real-binary-xyz]\n")
    store = SkillStore(user_dir=udir)
    assert "needs-cli" not in store.catalog_text()   # missing prereq ⇒ hidden from agent


def test_set_enabled_roundtrip(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills")
    assert store.set_enabled("deep-research", False).enabled is False
    assert store.disabled_names() == ["deep-research"]
    assert "deep-research" not in store.catalog_text()
    store.set_enabled("deep-research", True)
    assert store.disabled_names() == []
    assert "deep-research" in store.catalog_text()


def test_use_skill_refuses_disabled(tmp_path):
    store = SkillStore(user_dir=tmp_path / "skills", disabled=["deep-research"])
    reg = ToolRegistry()
    register_skill_tools(reg, store)
    res = reg.execute("use_skill", {"name": "deep-research"})
    assert not res.ok and "disabled" in res.error
    # And it's absent from the agent's list_skills.
    listed = reg.execute("list_skills", {})
    assert "deep-research" not in listed.content


def test_service_toggle_persists(tmp_path):
    """set_skill_enabled writes skills.disabled to config.local.yaml and the next
    SkillStore built from that config honors it."""
    from namma_agent import config as cfgmod

    base = tmp_path / "config.yaml"
    base.write_text("skills: {}\n", encoding="utf-8")

    store = SkillStore(user_dir=tmp_path / "uskills")
    store.set_enabled("deep-research", False)
    cfgmod.update_config({"skills": {"disabled": store.disabled_names()}}, path=str(base))

    merged = cfgmod.load_config(str(base))
    assert merged["skills"]["disabled"] == ["deep-research"]
    again = SkillStore(user_dir=tmp_path / "uskills",
                       disabled=merged["skills"]["disabled"])
    assert again.get("deep-research").enabled is False
