"""The Electron desktop shell's side of the backend (Phase 9 W3).

The desktop app (``desktop/`` — Electron) starts this backend as a child process
with ``NAMMA_DESKTOP=1``. In that mode a few things that the backend used to do
itself belong to the shell instead, because the shell owns the window, the app
identity (AUMID ``com.namma.agent``), the installer and the updater:

* **notifications** — instead of spawning a PowerShell toast, the backend emits
  ``desktop_notify {title, body, action}`` on the event bus; the Electron main
  process (subscribed over ``/ws``) shows a native ``Notification`` under the
  app's own name and icon;
* **window focus, update, uninstall** — emitted as ``desktop_command {action, …}``
  for the shell to carry out (focus the window, run electron-updater, launch the
  NSIS uninstaller);
* **state** — :func:`default_data_dir` is the per-user app-data folder rather than
  the CWD-relative ``data/`` (the shell normally passes ``NAMMA_DATA_DIR``
  explicitly; this is the fallback).

The event sink is registered by the launcher (``app.py``) once the service exists
(``service.broadcast.publish``). Everything here is best-effort and never raises.
"""
from __future__ import annotations

import os
import platform
import threading
from pathlib import Path
from typing import Callable, Optional

from namma_agent.core.logger import logger

#: The Windows AppUserModelID the desktop app (and its installer's Start-menu
#: shortcut) carry — toasts are attributed to it.
APP_ID = "com.namma.agent"
#: The folder name under the platform app-data root (Electron's productName).
APP_DIR_NAME = "Namma Agent"

_TRUTHY = {"1", "true", "yes", "on"}

Sink = Callable[[str, dict], None]
_sink: Optional[Sink] = None
_lock = threading.Lock()


def enabled() -> bool:
    """True when this backend runs under the Electron desktop shell."""
    return os.environ.get("NAMMA_DESKTOP", "").strip().lower() in _TRUTHY


def default_data_dir() -> Path:
    """The per-user app-data folder the desktop app keeps its state in.

    Windows ``%APPDATA%\\Namma Agent\\data``, macOS
    ``~/Library/Application Support/Namma Agent/data``, Linux
    ``$XDG_CONFIG_HOME/Namma Agent/data`` — i.e. ``data`` inside Electron's
    ``app.getPath("userData")``, which is what the shell passes explicitly.
    """
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / APP_DIR_NAME / "data"


def set_sink(sink: Optional[Sink]) -> None:
    """Register (or clear, with None) where desktop events are published —
    normally ``service.broadcast.publish``, which reaches every ``/ws`` client,
    the Electron main process included."""
    global _sink
    with _lock:
        _sink = sink


def has_sink() -> bool:
    return _sink is not None


def publish(event_type: str, payload: dict) -> bool:
    """Emit one desktop event. False when not in desktop mode, no sink is
    registered, or the sink failed — callers then use their non-desktop path."""
    if not enabled():
        return False
    with _lock:
        sink = _sink
    if sink is None:
        return False
    try:
        sink(event_type, dict(payload))
        return True
    except Exception as exc:  # noqa: BLE001 — never break the caller
        logger.debug("[desktop] publishing %s failed: %s", event_type, exc)
        return False


def notify(title: str, body: str = "", action: Optional[str] = None) -> bool:
    """Ask the shell to show a native notification. ``action`` is the in-app
    route (e.g. ``/`` or ``/settings/notifications``) a click opens; None just
    brings the window forward."""
    return publish("desktop_notify", {
        "title": (title or "").strip() or "Namma Agent",
        "body": (body or "").strip(),
        "action": action or None,
    })


def command(action: str, **params) -> bool:
    """Ask the shell to do something only it can (``focus``, ``update_check``,
    ``update_apply``, ``uninstall``)."""
    return publish("desktop_command", {"action": action, **params})


def _wait_for_exit_windows(pid: int) -> bool:
    """Block until process ``pid`` exits (True), or False if it can't be watched."""
    import ctypes

    SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        kernel32.WaitForSingleObject(handle, INFINITE)
        return True
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def start_parent_watchdog(on_exit: Callable[[], None],
                          pid: Optional[int] = None,
                          poll: float = 2.0) -> bool:
    """Exit with the shell: when the Electron process (``NAMMA_DESKTOP_PARENT_PID``)
    dies without stopping us (a crash, a kill from Task Manager), call ``on_exit``
    so the backend never lingers holding the port, the DB and the Telegram poller.
    Returns whether a watchdog started. Daemon thread; never raises."""
    if pid is None:
        raw = os.environ.get("NAMMA_DESKTOP_PARENT_PID", "").strip()
        pid = int(raw) if raw.isdigit() else None
    if not pid or pid == os.getpid():
        return False

    def _watch() -> None:
        try:
            if os.name == "nt":
                if not _wait_for_exit_windows(pid):
                    return
            else:
                import time
                while _pid_alive_posix(pid):
                    time.sleep(poll)
            logger.warning("[desktop] shell process %s exited; stopping the backend", pid)
            on_exit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[desktop] parent watchdog failed: %s", exc)

    threading.Thread(target=_watch, name="desktop-parent-watchdog", daemon=True).start()
    return True


# ── updates (electron-updater state, reported by the shell) ─────────────────
# The shell owns updates; it POSTs electron-updater's state here whenever it
# changes (/api/desktop/update-state), so the web UI's existing update banner and
# Settings → About can show "Update available" and drive "Update now".
_update_state: dict = {}
_update_seq = 0
_update_cond = threading.Condition()


def set_update_state(state: dict) -> dict:
    """Record the shell's latest updater state (``status``: checking | current |
    available | downloading | ready | error | unsupported, plus ``version``,
    ``progress``, ``error``). Wakes anyone waiting in :func:`wait_update_state`."""
    global _update_seq
    clean = {k: state.get(k) for k in ("status", "version", "progress", "error", "current")
             if state.get(k) is not None}
    with _update_cond:
        _update_state.clear()
        _update_state.update(clean)
        _update_seq += 1
        _update_cond.notify_all()
    return dict(clean)


def update_state() -> dict:
    with _update_cond:
        return dict(_update_state)


def wait_update_state(after_seq: int, timeout: float) -> dict:
    """Block up to ``timeout`` s for a state newer than ``after_seq`` whose check
    has finished (not ``checking``). Returns whatever is known by then."""
    import time

    deadline = time.monotonic() + max(0.0, timeout)
    with _update_cond:
        while True:
            done = _update_seq > after_seq and _update_state.get("status") not in (None, "checking")
            left = deadline - time.monotonic()
            if done or left <= 0:
                return dict(_update_state)
            _update_cond.wait(left)


def update_seq() -> int:
    with _update_cond:
        return _update_seq


def info() -> dict:
    """What the backend knows about the shell, for ``/api/desktop`` style
    reporting and diagnostics."""
    return {
        "desktop": enabled(),
        "app_id": APP_ID,
        "bus_ready": has_sink(),
        "exe": os.environ.get("NAMMA_DESKTOP_EXE", ""),
        "version": os.environ.get("NAMMA_DESKTOP_VERSION", ""),
    }
