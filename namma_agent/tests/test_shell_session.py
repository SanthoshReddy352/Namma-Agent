"""Persistent shell sessions — cwd/env/state persistence, streaming, recovery.

These tests drive the REAL platform shell (PowerShell on Windows, bash/sh on
POSIX) — fully offline, no API key needed.
"""
from __future__ import annotations

import os
import platform

import pytest

import namma_agent.tools.shell as shell_tool
from namma_agent.core.interactive import set_current_session, set_event_sink
from namma_agent.core.shell_session import PersistentShell, close_all, get_shell
from namma_agent.core.tools import ToolRegistry

WIN = platform.system() == "Windows"


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(str(path).strip()))


@pytest.fixture(scope="module")
def sh():
    shell = PersistentShell("test-shell")
    yield shell
    shell.close()


# -- basics ---------------------------------------------------------------------

def test_echo_roundtrip(sh):
    r = sh.run("echo hello_namma")
    assert r.ok and r.exit_code == 0
    assert "hello_namma" in r.output


def test_nonzero_exit_code(sh):
    r = sh.run("cmd /c exit 3" if WIN else "(exit 3)")
    assert not r.ok and r.exit_code == 3


def test_multiline_command(sh):
    cmd = "$a=1\n$b=2\necho ($a+$b)" if WIN else "a=1\nb=2\necho $((a+b))"
    r = sh.run(cmd)
    assert r.ok and "3" in r.output


# -- the point of a PERSISTENT shell: state carries across calls ------------------

def test_cwd_persists_across_calls(sh, tmp_path):
    r = sh.run(f'cd "{tmp_path}"')
    assert r.ok and _norm(r.cwd) == _norm(tmp_path)
    r2 = sh.run("(Get-Location).Path" if WIN else "pwd")
    assert _norm(tmp_path) in _norm(r2.output)
    assert _norm(sh.cwd) == _norm(tmp_path)


def test_env_and_shell_vars_persist(sh):
    if WIN:
        assert sh.run("$env:NAMMA_TEST_VAR='abc123'; $x=41").ok
        r = sh.run("echo $env:NAMMA_TEST_VAR $x")
    else:
        assert sh.run("export NAMMA_TEST_VAR=abc123; x=41").ok
        r = sh.run("echo $NAMMA_TEST_VAR $x")
    assert "abc123" in r.output and "41" in r.output


# -- streaming --------------------------------------------------------------------

def test_output_streams_to_callback(sh):
    chunks: list[str] = []
    r = sh.run("echo stream_me_please", on_output=chunks.append)
    assert r.ok
    assert "stream_me_please" in "".join(chunks)


# -- recovery ----------------------------------------------------------------------

def test_timeout_kills_and_respawns(sh):
    r = sh.run("Start-Sleep -Seconds 30" if WIN else "sleep 30", timeout=2)
    assert not r.ok and r.timed_out
    r2 = sh.run("echo back_alive")
    assert r2.ok and "back_alive" in r2.output


def test_shell_death_recovers(sh):
    # Kill the shell process itself mid-command — the harshest failure mode.
    r = sh.run("Stop-Process -Id $PID -Force" if WIN else "kill -9 $$")
    assert not r.ok and r.died
    r2 = sh.run("echo revived")
    assert r2.ok and "revived" in r2.output


# -- the run_shell tool on top ------------------------------------------------------

def test_run_shell_tool_streams_and_tracks_cwd(tmp_path):
    events: list[tuple[str, dict]] = []
    set_current_session("shell-tool-test")
    set_event_sink(lambda e, p: events.append((e, p)))
    try:
        reg = ToolRegistry()
        shell_tool.register(reg)

        out = reg.execute("run_shell", {"command": "echo streamed_marker"})
        assert out.ok and "streamed_marker" in out.content
        streamed = "".join(p.get("text", "") for e, p in events if e == "tool_output")
        assert "streamed_marker" in streamed
        assert all(p.get("tool") == "run_shell"
                   for e, p in events if e == "tool_output")

        # cd persists into the next call, and the model is told about the move.
        out2 = reg.execute("run_shell", {"command": f'cd "{tmp_path}"'})
        assert out2.ok and "[cwd is now:" in out2.content
        out3 = reg.execute("run_shell",
                           {"command": "(Get-Location).Path" if WIN else "pwd"})
        assert _norm(tmp_path) in _norm(out3.content.splitlines()[0])
    finally:
        set_current_session(None)
        set_event_sink(None)
        close_all()


def test_get_shell_reuses_per_session():
    try:
        a = get_shell("sess-a")
        assert get_shell("sess-a") is a
        assert get_shell("sess-b") is not a
    finally:
        close_all()


# -- activity steps carry the output (the persisted mini-terminal view) ---------------

def test_record_step_carries_output():
    from namma_agent.core.agent import _record_step

    steps: list[dict] = []
    _record_step(steps, "tool_started", {"tool": "run_shell", "args": {"command": "echo hi"}})
    _record_step(steps, "tool_finished",
                 {"tool": "run_shell", "ok": True, "summary": "hi", "output": "hi\n"})
    assert steps[0]["state"] == "ok"
    assert steps[0]["output"] == "hi\n"


# -- PATH sanitization (Phase 5: stray venv entries shadow python) --------------------

def test_shell_env_strips_stray_venv_entries(monkeypatch):
    import sys as _sys

    from namma_agent.core.shell_session import _shell_env

    exe_dir = os.path.dirname(_sys.executable)
    stray = (r"C:\Users\u\AppData\Local\hermes\hermes-agent\venv\Scripts"
             if os.name == "nt" else "/home/u/.local/hermes/venv/bin")
    keeper = r"C:\Windows\System32" if os.name == "nt" else "/usr/bin"
    monkeypatch.setenv("PATH", os.pathsep.join([stray, keeper]))
    path = _shell_env()["PATH"].split(os.pathsep)
    assert stray not in path            # the stray venv is gone
    assert keeper in path               # normal entries survive
    assert path[0] == exe_dir           # our interpreter resolves first


def test_shell_env_keeps_own_venv_and_dedupes(monkeypatch):
    import sys as _sys

    from namma_agent.core.shell_session import _shell_env

    exe_dir = os.path.dirname(_sys.executable)
    keeper = r"C:\Windows" if os.name == "nt" else "/bin"
    # Our own venv dir already on PATH must not be treated as stray or duplicated.
    monkeypatch.setenv("PATH", os.pathsep.join([keeper, exe_dir]))
    path = _shell_env()["PATH"].split(os.pathsep)
    assert path[0] == exe_dir
    assert path.count(exe_dir) == 1
    assert keeper in path
