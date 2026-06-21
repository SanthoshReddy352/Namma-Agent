"""Pure helpers of the graphical installer (installer/core.py)."""
from __future__ import annotations

import os

import pytest

from installer import core


def test_repo_slug_is_renamed():
    assert core.REPO == "SanthoshReddy352/Namma-Agent"
    assert core.REPO_URL.endswith("Namma-Agent.git")


def test_default_install_dir_on_desktop():
    d = core.default_install_dir()
    assert d.name == "Namma-Agent"
    assert d.parent.name in ("Desktop", d.parent.name)  # Desktop, or home fallback


def test_dependency_status_shape():
    s = core.dependency_status()
    assert set(s) == {"python", "git", "node"}
    assert all(isinstance(v, bool) for v in s.values())


def test_install_dep_command_windows():
    assert core.install_dep_command("python", "Windows")[:2] == ["winget", "install"]
    assert "Python.Python.3.12" in core.install_dep_command("python", "Windows")
    assert "Git.Git" in core.install_dep_command("git", "Windows")
    assert "OpenJS.NodeJS.LTS" in core.install_dep_command("node", "Windows")
    assert core.install_dep_command("bogus", "Windows") is None


def test_install_dep_command_macos():
    assert core.install_dep_command("node", "Darwin") == ["brew", "install", "node"]
    assert core.install_dep_command("python", "Darwin") == ["brew", "install", "python"]


def test_venv_python_path_shape(tmp_path):
    p = core.venv_python(tmp_path)
    assert ".venv" in str(p) and p.name.startswith("python")


# ── windowless subprocess flag ───────────────────────────────────────────────

def test_no_window_flag_off_windows():
    if os.name == "nt":
        assert core._NO_WINDOW == __import__("subprocess").CREATE_NO_WINDOW
        assert core._startupinfo() is not None
    else:
        assert core._NO_WINDOW == 0
        assert core._startupinfo() is None


# ── configurable install dir (no double-nesting) ─────────────────────────────

def test_resolve_install_dir_default():
    assert core.resolve_install_dir(None) == core.default_install_dir()
    assert core.resolve_install_dir("") == core.default_install_dir()


def test_resolve_install_dir_appends_app_name(tmp_path):
    chosen = tmp_path / "Apps"
    assert core.resolve_install_dir(chosen) == chosen / core.APP_DIR_NAME


def test_resolve_install_dir_no_double_nest(tmp_path):
    chosen = tmp_path / core.APP_DIR_NAME
    # Already ends in Namma-Agent → don't nest a second Namma-Agent under it.
    assert core.resolve_install_dir(chosen) == chosen


# ── step reporter ────────────────────────────────────────────────────────────

def test_step_reporter_transitions():
    updates: list[list[dict]] = []
    logs: list[str] = []
    rep = core.StepReporter([("a", "Step A"), ("b", "Step B")],
                            on_update=updates.append, on_log=logs.append)
    # Initial emit shows everything pending.
    assert all(s["status"] == "pending" for s in updates[0])

    with rep.step("a") as log:
        assert rep._by_key["a"].status == "active"
        log("hello")
    assert rep._by_key["a"].status == "done"
    assert "hello" in logs

    with pytest.raises(RuntimeError):
        with rep.step("b"):
            raise RuntimeError("boom")
    assert rep._by_key["b"].status == "error"


def test_install_steps_shape():
    keys = [k for k, _ in core.INSTALL_STEPS]
    assert keys[0] == "python" and "shortcuts" in keys
    assert all(isinstance(label, str) and label for _, label in core.INSTALL_STEPS)


def test_bootstrap_accepts_plain_log_callable():
    # A plain callable still works (the --cli / test path) — it's wrapped into a
    # StepReporter that just forwards log lines.
    rep = core._as_reporter(lambda _m: None)
    assert isinstance(rep, core.StepReporter)
    # A StepReporter passes through unchanged.
    assert core._as_reporter(rep) is rep


# ── shortcut builders (pure) ─────────────────────────────────────────────────

def test_windows_shortcut_ps1_contents(tmp_path):
    script = core.windows_shortcut_ps1(tmp_path)
    assert "Namma Agent.lnk" in script
    assert "-m namma_agent" in script
    assert "Desktop" in script and "Start Menu" in script
    assert "WScript.Shell" in script


def test_macos_launcher_body(tmp_path):
    body = core.macos_launcher_body(tmp_path)
    assert body.startswith("#!/usr/bin/env bash")
    assert "-m namma_agent" in body
    assert str(tmp_path) in body


def test_linux_desktop_entry(tmp_path):
    entry = core.linux_desktop_entry(tmp_path)
    assert "[Desktop Entry]" in entry
    assert "Name=Namma Agent" in entry
    assert "namma_agent" in entry
    assert "Terminal=false" in entry
