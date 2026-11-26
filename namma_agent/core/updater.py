"""Update checking + applying for an installed Namma Agent.

The app ships as source (a git clone or an unpacked release) run from a project
``.venv``, so an "update" is: fetch the new source, reinstall any changed
dependencies, and rebuild the web UI. That work is done by the platform update
script (``installers/update.ps1`` / ``installers/update.sh``) — this module:

  * reports the installed version (``current_version``),
  * asks GitHub for the latest released version (``check_for_update``), and
  * launches the update script detached so it can replace files while the app
    exits and then relaunches (``apply_update``).

Network/path failures are returned as data, never raised — a failed update check
must never break a running app.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from namma_agent.core.logger import logger
from namma_agent.version import __version__

#: owner/repo the updates are published from (matches the git remote).
DEFAULT_REPO = "SanthoshReddy352/Namma-Agent"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def current_version() -> str:
    return __version__


def parse_version(v: str) -> tuple[int, int, int]:
    """Lenient semver parse: 'v2.3.1' / '2.3' / 'release-2.3.1' → (2,3,1)."""
    nums = [int(n) for n in re.findall(r"\d+", str(v or ""))][:3]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def _http_json(url: str, timeout: float) -> object:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Namma-Agent-Updater",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_release(repo: str = DEFAULT_REPO, timeout: float = 6.0) -> dict | None:
    """Latest published release (falls back to the newest tag). None if unreachable."""
    try:
        d = _http_json(f"https://api.github.com/repos/{repo}/releases/latest", timeout)
        if isinstance(d, dict) and d.get("tag_name"):
            return {"version": str(d["tag_name"]).lstrip("vV"), "tag": d["tag_name"],
                    "html_url": d.get("html_url"), "notes": d.get("body") or "",
                    "published_at": d.get("published_at")}
    except Exception as exc:  # noqa: BLE001 — no releases yet / offline / rate-limited
        logger.debug("[updater] releases/latest failed: %s", exc)
    try:
        tags = _http_json(f"https://api.github.com/repos/{repo}/tags", timeout)
        if isinstance(tags, list) and tags:
            name = str(tags[0].get("name") or "")
            return {"version": name.lstrip("vV"), "tag": name,
                    "html_url": f"https://github.com/{repo}/releases", "notes": "",
                    "published_at": None}
    except Exception as exc:  # noqa: BLE001
        logger.debug("[updater] tags failed: %s", exc)
    return None


def check_for_update(repo: str = DEFAULT_REPO, timeout: float = 6.0) -> dict:
    """Compare the installed version to the latest published one.

    Under the desktop app (``NAMMA_DESKTOP=1``) the Electron shell owns updates
    (electron-updater): the check is forwarded to it as a ``desktop_command`` and
    the answer says ``managed_by: "desktop"`` — the shell reports progress with
    its own native UI. The version comparison is still returned for display."""
    from namma_agent.core import desktop

    if desktop.enabled():
        forwarded = desktop.command("update_check")
        cur = current_version()
        return {"current": cur, "latest": None, "update_available": False,
                "managed_by": "desktop", "forwarded": forwarded,
                "desktop_version": os.environ.get("NAMMA_DESKTOP_VERSION", "")}
    cur = current_version()
    latest = latest_release(repo, timeout)
    if not latest or not latest.get("version"):
        return {"current": cur, "latest": None, "update_available": False,
                "error": "could not reach the update server"}
    available = parse_version(latest["version"]) > parse_version(cur)
    return {"current": cur, "latest": latest["version"], "update_available": available,
            "html_url": latest.get("html_url"), "notes": latest.get("notes", ""),
            "published_at": latest.get("published_at")}


def _update_script() -> Path:
    return _REPO_ROOT / "installers" / ("update.ps1" if os.name == "nt" else "update.sh")


def apply_update() -> dict:
    """Launch the platform update script **detached** so it can update files and
    relaunch the app after this process exits. Returns immediately.

    Desktop installs never run the git-pull script (it assumes a source checkout,
    a ``.venv`` and port 8000): the request is handed to the Electron shell,
    which downloads and installs the new NSIS build with electron-updater."""
    from namma_agent.core import desktop

    if desktop.enabled():
        if desktop.command("update_apply"):
            return {"started": True, "managed_by": "desktop"}
        return {"started": False, "managed_by": "desktop",
                "error": "the desktop app is not connected"}
    script = _update_script()
    if not script.exists():
        return {"started": False, "error": f"updater script not found: {script}"}
    try:
        if os.name == "nt":
            CREATE_NEW_CONSOLE = 0x00000010
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), "-Relaunch"],
                cwd=str(_REPO_ROOT), creationflags=CREATE_NEW_CONSOLE,
                close_fds=True)
        else:
            subprocess.Popen(
                ["bash", str(script), "--relaunch"],
                cwd=str(_REPO_ROOT), start_new_session=True, close_fds=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[updater] failed to launch update script: %s", exc)
        return {"started": False, "error": str(exc)}
    logger.info("[updater] update started via %s — app will relaunch", script.name)
    return {"started": True, "script": str(script)}
