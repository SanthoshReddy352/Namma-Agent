"""Pure helpers of the graphical installer (installer/core.py)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from installer import core


def test_repo_slug_is_renamed():
    assert core.REPO == "SanthoshReddy352/Namma-Agent"
    assert core.REPO_URL.endswith("Namma-Agent.git")


def test_default_install_dir_on_desktop():
    d = core.default_install_dir()
    assert d.name == "Namma-Agent"
    assert d.parent.name in ("Desktop", d.parent.name)  # Desktop, or home fallback


# ── install-dir defaulting: instant (no freeze) + redirect-aware ─────────────

def test_desktop_dir_prefers_explorer_registry_on_windows(tmp_path, monkeypatch):
    desk = tmp_path / "OneDrive" / "Desktop"
    monkeypatch.setattr(core, "_is_windows", lambda: True)
    monkeypatch.setattr(core, "_windows_desktop", lambda: desk)
    assert core.desktop_dir() == desk


def test_desktop_dir_onedrive_fallback_when_registry_fails(tmp_path, monkeypatch):
    od = tmp_path / "OneDrive"
    monkeypatch.setattr(core, "_is_windows", lambda: True)
    monkeypatch.setattr(core, "_windows_desktop", lambda: None)
    monkeypatch.setenv("OneDrive", str(od))
    assert core.desktop_dir() == od / "Desktop"


def test_default_install_dir_falls_back_to_localappdata(tmp_path, monkeypatch):
    # No Desktop anywhere → land under %LOCALAPPDATA% (writable), never C:\Users\x root.
    monkeypatch.setattr(core, "_is_windows", lambda: True)
    monkeypatch.setattr(core, "_windows_desktop", lambda: None)
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert core.default_install_dir() == tmp_path / "Namma-Agent"


def test_default_install_dir_does_no_filesystem_probing(monkeypatch):
    # Regression guard: computing the default must NOT call os.access / Path.is_dir —
    # those stall for seconds on an online-only OneDrive Desktop and froze the installer.
    monkeypatch.setattr(core, "_is_windows", lambda: True)
    monkeypatch.setattr(core, "_windows_desktop", lambda: Path(r"D:\Desktop"))

    def _no_access(*_a, **_k):
        raise AssertionError("os.access called on the install-dir hot path")

    def _no_isdir(*_a, **_k):
        raise AssertionError("Path.is_dir called on the install-dir hot path")

    monkeypatch.setattr(core.os, "access", _no_access)
    monkeypatch.setattr(core.Path, "is_dir", _no_isdir)
    assert core.default_install_dir() == Path(r"D:\Desktop") / "Namma-Agent"


def test_prepare_install_dir_wraps_permission_error(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(core.Path, "mkdir", boom)
    with pytest.raises(RuntimeError, match="access denied"):
        core._prepare_install_dir(tmp_path / "x")


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


# ── optional tools (ripgrep + ffmpeg, Hermes parity) ─────────────────────────

def test_optional_tools_have_install_commands():
    assert set(core.OPTIONAL_TOOLS) == {"ripgrep", "ffmpeg"}
    # ripgrep's binary is `rg`, not `ripgrep`.
    assert core._tool_command("ripgrep") == "rg"
    assert core._tool_command("ffmpeg") == "ffmpeg"
    # Each optional tool resolves to a real install command on every OS.
    assert "BurntSushi.ripgrep.MSVC" in core.install_dep_command("ripgrep", "Windows")
    assert "Gyan.FFmpeg" in core.install_dep_command("ffmpeg", "Windows")
    assert core.install_dep_command("ripgrep", "Darwin") == ["brew", "install", "ripgrep"]
    assert core.install_dep_command("ffmpeg", "Darwin") == ["brew", "install", "ffmpeg"]


def test_ensure_optional_tools_never_raises(monkeypatch):
    # Pretend both are missing and no installer exists → it must log, not raise.
    monkeypatch.setattr(core, "_has", lambda _c: False)
    monkeypatch.setattr(core, "install_dep_command", lambda *_a, **_k: None)
    logs: list[str] = []
    core.ensure_optional_tools(logs.append)
    assert any("ripgrep" in l for l in logs) and any("ffmpeg" in l for l in logs)


# ── add the `namma` command to PATH ──────────────────────────────────────────

def test_windows_namma_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_is_windows", lambda: True)
    body = core.windows_namma_cmd(tmp_path)
    assert "@echo off" in body
    assert "-m namma_agent" in body
    assert "%*" in body                  # forwards args (namma --chat / --server)
    assert "pythonw.exe" in body or "python.exe" in body


def test_windows_path_append_ps1(tmp_path):
    bin_dir = tmp_path / "bin"
    ps = core.windows_path_append_ps1(bin_dir)
    assert "'Path','User'" in ps          # persists to the user PATH
    assert str(bin_dir) in ps
    assert "-notcontains" in ps           # idempotent (won't duplicate)


def test_posix_namma_script(tmp_path):
    body = core.posix_namma_script(tmp_path)
    assert body.startswith("#!/usr/bin/env bash")
    assert "-m namma_agent" in body
    assert '"$@"' in body                 # forwards args


def test_install_steps_include_path():
    keys = [k for k, _ in core.INSTALL_STEPS]
    assert "path" in keys


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


# ── Windows Add/Remove-Programs registration (pure) ──────────────────────────

def test_windows_uninstall_registry_ps1(tmp_path):
    ps = core.windows_uninstall_registry_ps1(tmp_path, "9.9.9")
    assert "CurrentVersion\\Uninstall\\NammaAgent" in ps
    assert "DisplayName -Value 'Namma Agent'" in ps
    assert "9.9.9" in ps                              # DisplayVersion
    assert "sparkle.ico" in ps                        # DisplayIcon → blue icon
    assert "uninstall.ps1" in ps and "-Scope all" in ps  # UninstallString
    assert "NoModify" in ps and "NoRepair" in ps


def test_installed_version_reads_version_py(tmp_path):
    pkg = tmp_path / "namma_agent"
    pkg.mkdir()
    (pkg / "version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    assert core._installed_version(tmp_path) == "1.2.3"
    assert core._installed_version(tmp_path / "nope") == ""


# ── uninstaller scripts ship + carry the safety logic ───────────────────────

def test_uninstall_scripts_exist_and_kill_by_cmdline():
    root = Path(core.__file__).resolve().parents[1]
    ps1 = (root / "installers" / "uninstall.ps1").read_text(encoding="utf-8")
    sh = (root / "installers" / "uninstall.sh").read_text(encoding="utf-8")
    # Kill by matching the command line (works despite the bare python.exe name).
    assert "namma_agent" in ps1 and "InstallDir" in ps1
    assert "keep-data" in ps1 and "Uninstall\\NammaAgent" in ps1   # backs up + removes regkey
    assert "namma_agent" in sh and "keep-data" in sh
    # Also tears down the on-PATH `namma` launcher it added.
    assert "'Path', $kept, \"User\"" in ps1 or "SetEnvironmentVariable(\"Path\"" in ps1
    assert ".local/bin/namma" in sh
