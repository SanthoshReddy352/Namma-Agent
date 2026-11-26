"""Phase 9 W3: the backend's hooks for the Electron desktop shell (NAMMA_DESKTOP=1).

Covers the shared contract (``desktop_notify {title, body, action}`` on the event
bus instead of a PowerShell toast), the ``desktop_command`` hand-offs (focus,
update, uninstall), the per-user data dir, ``NAMMA_PORT``, autostart pointing at
the shell, and the websocket accepting the header the shell injects.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from namma_agent import app as launcher
from namma_agent import config
from namma_agent.core import autostart, desktop, notifications, uninstaller, updater
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.server.api import create_app
from namma_agent.service import NammaAgentService


class _Provider(Provider):
    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="hi")


def _service():
    return NammaAgentService(
        config={"persona": "core", "conversation": {}},
        provider=_Provider(),
        registry=ToolRegistry(),
        db=Database(":memory:"),
    )


@pytest.fixture
def events(monkeypatch):
    """Desktop mode with a recording sink; restores the module sink afterwards."""
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    got: list[tuple[str, dict]] = []
    desktop.set_sink(lambda e, p: got.append((e, p)))
    # Never let a test touch the real HKCU notification switches.
    monkeypatch.setattr(notifications, "_windows_toasts_enabled",
                        lambda *a, **k: (True, ""))
    yield got
    desktop.set_sink(None)


@pytest.fixture
def no_spawn(monkeypatch):
    """Fail loudly if anything tries to spawn PowerShell / an uninstaller."""
    calls = []

    def _boom(*a, **k):
        calls.append(a)
        raise AssertionError(f"unexpected subprocess: {a}")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    return calls


# ── mode detection + the sink ───────────────────────────────────────────────

def test_enabled_reads_the_env(monkeypatch):
    monkeypatch.delenv("NAMMA_DESKTOP", raising=False)
    assert desktop.enabled() is False
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("NAMMA_DESKTOP", v)
        assert desktop.enabled() is True
    monkeypatch.setenv("NAMMA_DESKTOP", "0")
    assert desktop.enabled() is False


def test_publish_is_a_noop_outside_desktop_mode(monkeypatch):
    monkeypatch.delenv("NAMMA_DESKTOP", raising=False)
    got = []
    desktop.set_sink(lambda e, p: got.append(e))
    try:
        assert desktop.notify("t", "b") is False
        assert got == []
    finally:
        desktop.set_sink(None)


def test_publish_without_a_sink_reports_false(monkeypatch):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    desktop.set_sink(None)
    assert desktop.command("focus") is False


def test_a_failing_sink_never_raises(monkeypatch):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")

    def _bad(e, p):
        raise RuntimeError("socket gone")

    desktop.set_sink(_bad)
    try:
        assert desktop.notify("t") is False
    finally:
        desktop.set_sink(None)


# ── desktop_notify replaces the PowerShell toast ────────────────────────────

def test_notification_goes_to_the_bus_not_powershell(events, no_spawn):
    assert notifications.send_native_notification("Done", "Your report is ready",
                                                  action="/projects") is True
    assert events == [("desktop_notify", {"title": "Done", "body": "Your report is ready",
                                          "action": "/projects"})]
    assert no_spawn == []


def test_notify_payload_defaults(events):
    desktop.notify("  ", "")
    assert events[-1] == ("desktop_notify", {"title": "Namma Agent", "body": "", "action": None})


def test_status_reports_desktop_and_the_shell_aumid(events, monkeypatch):
    seen = {}

    def _gate(aumid="", app_label=""):
        seen["aumid"] = aumid
        return True, ""

    monkeypatch.setattr(notifications, "_windows_toasts_enabled", _gate)
    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    st = notifications.notification_status()
    assert st == {"available": True, "reason": "", "platform": "desktop"}
    assert seen["aumid"] == "com.namma.agent"


def test_status_honours_a_muted_app(events, monkeypatch, no_spawn):
    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notifications, "_windows_toasts_enabled",
                        lambda *a, **k: (False, "muted"))
    assert notifications.notification_status()["available"] is False
    assert notifications.send_native_notification("x") is False
    assert events == []


def test_status_unavailable_until_the_shell_attaches(monkeypatch):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    monkeypatch.setattr(notifications, "_windows_toasts_enabled", lambda *a, **k: (True, ""))
    desktop.set_sink(None)
    st = notifications.notification_status()
    assert st["available"] is False and "not connected" in st["reason"]


def test_api_notify_reaches_the_ws_event_log(monkeypatch, no_spawn):
    """End to end: /api/notify → desktop_notify on the broadcast → every /ws
    client (the Electron main process subscribes exactly like this)."""
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    monkeypatch.setattr(notifications, "_windows_toasts_enabled", lambda *a, **k: (True, ""))
    svc = _service()
    try:
        assert launcher._attach_desktop(svc) is True
        client = TestClient(create_app(svc))
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            ws.send_json({"type": "resume", "from_seq": hello["seq"], "boot": hello["boot"]})
            r = client.post("/api/notify", json={"title": "Reminder", "body": "Stand up"})
            assert r.json() == {"ok": True, "reason": ""}
            msg = ws.receive_json()
        assert msg["type"] == "desktop_notify"
        assert (msg["title"], msg["body"], msg["action"]) == ("Reminder", "Stand up", None)
    finally:
        desktop.set_sink(None)


def test_attach_is_a_noop_outside_desktop_mode(monkeypatch):
    monkeypatch.delenv("NAMMA_DESKTOP", raising=False)
    assert launcher._attach_desktop(_service()) is False
    assert desktop.has_sink() is False


# ── desktop_command hand-offs ───────────────────────────────────────────────

def test_focus_window_asks_the_shell(events, monkeypatch):
    monkeypatch.setattr(launcher, "_WINDOW", None)
    assert launcher.focus_window() is True
    assert events == [("desktop_command", {"action": "focus"})]


@pytest.fixture
def fresh_update_state():
    desktop.set_update_state({})
    yield
    desktop.set_update_state({})


def test_update_check_and_apply_defer_to_electron_updater(events, no_spawn, monkeypatch,
                                                          fresh_update_state):
    monkeypatch.setattr(updater, "latest_release",
                        lambda *a, **k: pytest.fail("no GitHub call in desktop mode"))
    monkeypatch.setenv("NAMMA_DESKTOP_VERSION", "2.3.2")
    import threading

    # The shell answers an update_check command by reporting electron-updater's
    # result, asynchronously (it really arrives over HTTP from another process).
    def shell(e, p):
        events.append((e, p))
        if e == "desktop_command" and p.get("action") == "update_check":
            def answer():
                desktop.set_update_state({"status": "checking"})
                desktop.set_update_state({"status": "available", "version": "2.3.3"})
            threading.Timer(0.05, answer).start()

    desktop.set_sink(shell)
    chk = updater.check_for_update()
    assert chk["managed_by"] == "desktop"
    assert chk["update_available"] is True
    assert (chk["current"], chk["latest"], chk["status"]) == ("2.3.2", "2.3.3", "available")
    assert chk["html_url"].endswith("/releases/tag/v2.3.3")
    # Once an update is known, a later check answers at once (no new command).
    n = len(events)
    assert updater.check_for_update()["update_available"] is True
    assert len(events) == n
    assert updater.apply_update() == {"started": True, "managed_by": "desktop"}
    assert [p["action"] for _, p in events] == ["update_check", "update_apply"]


def test_update_check_reports_up_to_date_and_times_out_quietly(events, monkeypatch,
                                                               fresh_update_state):
    monkeypatch.setenv("NAMMA_DESKTOP_VERSION", "2.3.2")

    def shell(e, p):
        if p.get("action") == "update_check":
            desktop.set_update_state({"status": "current", "version": "2.3.2"})

    desktop.set_sink(shell)
    chk = updater.check_for_update()
    assert chk["update_available"] is False and chk["status"] == "current"
    # A shell that never answers: the check returns after the timeout, no update.
    desktop.set_update_state({})
    desktop.set_sink(lambda e, p: None)
    chk = updater.check_for_update(timeout=0.2)
    assert chk["update_available"] is False


def test_api_update_state_drives_the_banner(events, monkeypatch, fresh_update_state):
    """The shell POSTs electron-updater's state; /api/update/check (what the web
    UI's banner and Settings → About call) then reports the update."""
    monkeypatch.setenv("NAMMA_DESKTOP_VERSION", "2.3.2")
    client = TestClient(create_app(_service()))
    r = client.post("/api/desktop/update-state",
                    json={"status": "available", "version": "2.4.0", "junk": 1})
    assert r.json() == {"ok": True, "state": {"status": "available", "version": "2.4.0"}}
    chk = client.get("/api/update/check").json()
    assert chk["update_available"] is True and chk["latest"] == "2.4.0"
    assert client.post("/api/update/apply").json()["started"] is True
    assert events[-1] == ("desktop_command", {"action": "update_apply"})


def test_update_state_endpoint_is_desktop_only(monkeypatch):
    monkeypatch.delenv("NAMMA_DESKTOP", raising=False)
    client = TestClient(create_app(_service()))
    assert client.post("/api/desktop/update-state", json={"status": "x"}).status_code == 404


def test_update_apply_without_the_shell_does_not_run_the_git_script(monkeypatch, no_spawn):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    desktop.set_sink(None)
    res = updater.apply_update()
    assert res["started"] is False and res["managed_by"] == "desktop"


def test_uninstall_hands_off_to_the_shell(events, no_spawn):
    res = uninstaller.apply_uninstall("keep-data")
    assert res == {"started": True, "scope": "keep-data", "managed_by": "desktop",
                   "shell_exits": True}
    assert events == [("desktop_command", {"action": "uninstall", "scope": "keep-data"})]


def test_api_uninstall_does_not_kill_the_backend_under_the_shell(events, monkeypatch, no_spawn):
    svc = _service()
    stopped = []
    monkeypatch.setattr(svc, "shutdown", lambda *a, **k: stopped.append(1))
    client = TestClient(create_app(svc))
    r = client.post("/api/uninstall", json={"scope": "all"})
    assert r.json()["started"] is True
    import time
    time.sleep(1.3)  # the non-desktop path shuts down after 1 s
    assert stopped == []


def test_uninstall_falls_back_to_the_advertised_nsis_exe(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    desktop.set_sink(None)
    exe = tmp_path / "Uninstall Namma Agent.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("NAMMA_DESKTOP_UNINSTALLER", str(exe))
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **k: launched.append(args))
    res = uninstaller.apply_uninstall("all")
    assert res["started"] is True and launched == [[str(exe)]]


def test_uninstall_without_shell_or_exe_reports_an_error(monkeypatch, no_spawn):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    monkeypatch.delenv("NAMMA_DESKTOP_UNINSTALLER", raising=False)
    desktop.set_sink(None)
    res = uninstaller.apply_uninstall("all")
    assert res["started"] is False and "not found" in res["error"]


# ── state location, port, autostart, websocket auth ─────────────────────────

def test_data_dir_defaults_to_app_data_under_the_shell(monkeypatch, tmp_path):
    monkeypatch.delenv("NAMMA_DATA_DIR", raising=False)
    monkeypatch.delenv("NAMMA_DESKTOP", raising=False)
    assert config.data_dir() == Path("data")
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = config.data_dir()
    assert d.parts[-2:] == ("Namma Agent", "data")
    monkeypatch.delenv("NAMMA_ENV_FILE", raising=False)
    assert config.env_file() == d / ".env"   # .env (and the user overlay) follow
    # An explicit NAMMA_DATA_DIR (what the shell passes) always wins.
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path / "x"))
    assert config.data_dir() == tmp_path / "x"


def test_namma_port_overrides_config(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("NAMMA_HOST", raising=False)
    monkeypatch.setenv("NAMMA_PORT", "47811")
    assert config.server_bind({"server": {"port": 9000}}) == ("127.0.0.1", 47811)
    monkeypatch.delenv("NAMMA_PORT")
    assert config.server_bind({"server": {"port": 9000}})[1] == 9000


def test_autostart_launches_the_shell_hidden(monkeypatch):
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    monkeypatch.setenv("NAMMA_DESKTOP_EXE", r"C:\Apps\Namma Agent\Namma Agent.exe")
    assert autostart.launch_command() == r'"C:\Apps\Namma Agent\Namma Agent.exe" --hidden'
    monkeypatch.delenv("NAMMA_DESKTOP")
    assert "-m namma_agent" in autostart.launch_command()


def test_ws_accepts_the_token_header_the_shell_injects(monkeypatch):
    monkeypatch.setenv("NAMMA_AUTH_TOKEN", "per-launch-secret")
    client = TestClient(create_app(_service()))
    with client.websocket_connect("/ws", headers={"X-Namma-Token": "per-launch-secret"}) as ws:
        assert ws.receive_json()["type"] == "hello"
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"X-Namma-Token": "wrong"}) as ws:
            ws.receive_json()
    assert client.get("/api/version", headers={"X-Namma-Token": "per-launch-secret"}).status_code == 200
    assert client.get("/api/version").status_code == 401


def test_parent_watchdog_stops_the_backend_when_the_shell_dies(monkeypatch):
    import sys
    import threading

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    fired = threading.Event()
    assert desktop.start_parent_watchdog(fired.set, pid=child.pid, poll=0.1) is True
    child.wait(timeout=10)
    assert fired.wait(timeout=10)


def test_parent_watchdog_needs_a_pid(monkeypatch):
    import os
    monkeypatch.delenv("NAMMA_DESKTOP_PARENT_PID", raising=False)
    assert desktop.start_parent_watchdog(lambda: None) is False
    assert desktop.start_parent_watchdog(lambda: None, pid=os.getpid()) is False


def test_whatsapp_qr_session_lives_in_the_desktop_data_dir(monkeypatch, tmp_path):
    from namma_agent.comms import whatsapp_qr
    monkeypatch.setenv("NAMMA_WHATSAPP_SESSION", str(tmp_path / "pinned.sqlite3"))
    assert whatsapp_qr.session_db_path() == tmp_path / "pinned.sqlite3"   # the override wins
    monkeypatch.delenv("NAMMA_WHATSAPP_SESSION")
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NAMMA_DESKTOP", "1")
    assert whatsapp_qr.session_db_path() == tmp_path / "data" / "whatsapp_qr.sqlite3"
    monkeypatch.delenv("NAMMA_DESKTOP")
    assert whatsapp_qr.session_db_path().parent.name == ".namma_agent"
