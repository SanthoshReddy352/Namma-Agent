"""Start-on-login (Phase 5 — Windows first-class polish).

One toggle, surfaced in Settings → Behavior, that makes the desktop app launch
when the user signs in:

* **Windows** — a value under ``HKCU\\Software\\Microsoft\\Windows\\
  CurrentVersion\\Run`` (the classic per-user Run key; no admin rights, visible
  and disable-able in Task Manager → Startup apps). The command prefers
  ``pythonw.exe`` so no console window flashes at login.
* **Linux** — an XDG autostart entry (``~/.config/autostart/namma-agent.desktop``).
* **macOS** — not implemented yet; ``status()`` reports ``supported: False``
  honestly instead of pretending.

Everything is best-effort and never raises: a registry/filesystem failure comes
back as ``{"ok": False, "error": ...}`` for the UI to show.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from namma_agent.core.logger import logger

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "NammaAgent"
_DESKTOP_FILE = "namma-agent.desktop"


def launch_command() -> str:
    """The command a login launch runs: this interpreter, windowed, ``-m namma_agent``.

    On Windows, ``pythonw.exe`` (next to the current ``python.exe``) is
    preferred so login doesn't flash a console. Paths are quoted for the
    registry's command-line parsing.
    """
    exe = sys.executable or "python"
    if platform.system() == "Windows":
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.is_file():
            exe = str(pythonw)
    return f'"{exe}" -m namma_agent'


def _autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart"


def supported() -> bool:
    return platform.system() in ("Windows", "Linux")


def enabled() -> bool:
    """Is start-on-login currently registered? Never raises."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, _VALUE_NAME)
            return True
        if system == "Linux":
            return (_autostart_dir() / _DESKTOP_FILE).is_file()
    except OSError:
        return False
    return False


def set_enabled(on: bool) -> dict:
    """Register/unregister the login launch. Returns ``{ok, enabled, error?}``."""
    system = platform.system()
    if not supported():
        return {"ok": False, "enabled": False,
                "error": f"start-on-login is not supported on {system} yet"}
    try:
        if system == "Windows":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                if on:
                    winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ,
                                      launch_command())
                else:
                    try:
                        winreg.DeleteValue(key, _VALUE_NAME)
                    except FileNotFoundError:
                        pass  # already off
        else:  # Linux
            path = _autostart_dir() / _DESKTOP_FILE
            if on:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Namma Agent\n"
                    f"Exec={launch_command()}\n"
                    "X-GNOME-Autostart-enabled=true\n",
                    encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
        logger.info("[autostart] start-on-login %s", "enabled" if on else "disabled")
        return {"ok": True, "enabled": bool(on)}
    except OSError as exc:
        logger.warning("[autostart] toggle failed: %s", exc)
        return {"ok": False, "enabled": enabled(), "error": str(exc)}


def status() -> dict:
    """One payload for the Settings toggle."""
    return {"supported": supported(), "enabled": enabled(),
            "command": launch_command() if supported() else None,
            "platform": platform.system()}
