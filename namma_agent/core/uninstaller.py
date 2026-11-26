"""Launch the platform uninstaller, detached, so it can remove the app + its files
after this process exits.

Mirrors :mod:`namma_agent.core.updater`: the in-app "Uninstall" button (Settings →
About → Danger zone) calls :func:`apply_uninstall`, which starts
``installers/uninstall.{ps1,sh}`` in a detached process and returns immediately; the
UI then asks the backend to shut down so the uninstaller can delete the install dir.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from namma_agent.core.logger import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _uninstall_script() -> Path:
    return _REPO_ROOT / "installers" / ("uninstall.ps1" if os.name == "nt" else "uninstall.sh")


def _desktop_uninstall(scope: str) -> dict:
    """Desktop app (``NAMMA_DESKTOP=1``): hand off to the NSIS uninstaller.

    The Electron shell owns it (it knows where ``Uninstall Namma Agent.exe``
    lives and must quit itself so the files unlock), so the request goes out as a
    ``desktop_command``. ``shell_exits`` tells the API not to kill the backend:
    the shell stops it when it quits. If the shell isn't listening, fall back to
    launching the uninstaller it advertised in ``NAMMA_DESKTOP_UNINSTALLER``."""
    from namma_agent.core import desktop

    if desktop.command("uninstall", scope=scope):
        return {"started": True, "scope": scope, "managed_by": "desktop",
                "shell_exits": True}
    exe = os.environ.get("NAMMA_DESKTOP_UNINSTALLER", "").strip()
    if not exe or not Path(exe).is_file():
        return {"started": False, "managed_by": "desktop",
                "error": "the desktop uninstaller was not found"}
    try:
        kwargs = {"close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe], **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[uninstaller] desktop uninstaller failed to launch: %s", exc)
        return {"started": False, "managed_by": "desktop", "error": str(exc)}
    return {"started": True, "scope": scope, "managed_by": "desktop"}


def apply_uninstall(scope: str = "all") -> dict:
    """Start the detached uninstaller. ``scope`` is 'all' (wipe everything) or
    'keep-data' (back up chats/config first). Returns immediately."""
    scope = "keep-data" if scope == "keep-data" else "all"
    from namma_agent.core import desktop

    if desktop.enabled():
        return _desktop_uninstall(scope)
    script = _uninstall_script()
    if not script.exists():
        return {"started": False, "error": f"uninstaller not found: {script}"}
    install_dir = str(_REPO_ROOT)
    try:
        if os.name == "nt":
            # DETACHED_PROCESS so it outlives this app; hidden window.
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                 "-File", str(script), "-InstallDir", install_dir, "-Scope", scope],
                creationflags=DETACHED_PROCESS, close_fds=True)
        else:
            subprocess.Popen(
                ["bash", str(script), "--install-dir", install_dir, "--scope", scope],
                start_new_session=True, close_fds=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[uninstaller] failed to launch: %s", exc)
        return {"started": False, "error": str(exc)}
    logger.info("[uninstaller] started (scope=%s) via %s", scope, script.name)
    return {"started": True, "scope": scope}
