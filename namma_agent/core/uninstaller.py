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


def apply_uninstall(scope: str = "all") -> dict:
    """Start the detached uninstaller. ``scope`` is 'all' (wipe everything) or
    'keep-data' (back up chats/config first). Returns immediately."""
    scope = "keep-data" if scope == "keep-data" else "all"
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
