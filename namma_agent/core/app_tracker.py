"""Track applications Namma Agent opens, and tell whether they're still running.

Two jobs:
  * record what was launched (``data/opened_apps.json``) so Namma Agent knows what it
    started this session;
  * answer "is <app> running?" so it can re-open a closed app instead of falsely
    claiming it's already open.

Process detection is best-effort and cross-platform-guarded (pgrep/pidof on
Linux/macOS, tasklist on Windows).
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from namma_agent.config import data_dir as _data_dir
_STORE = _data_dir() / "opened_apps.json"


def _aliases(name: str) -> list[str]:
    """Process-name candidates for a launched app (handles common renames)."""
    base = os.path.basename(name).strip().lower()
    base = base[:-8] if base.endswith(".desktop") else base
    cands = {base, base.replace(" ", "-"), base.replace(" ", ""), base.split(".")[-1]}
    extra = {
        "google-chrome": "chrome", "google-chrome-stable": "chrome",
        "code": "code", "vscode": "code", "org.gnome.nautilus": "nautilus",
        "files": "nautilus", "vlc": "vlc",
    }
    if base in extra:
        cands.add(extra[base])
    return [c for c in cands if c]


def is_running(name: str) -> bool:
    """True if a process matching ``name`` (or a known alias) is running."""
    system = platform.system()
    cands = _aliases(name)
    try:
        if system == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=5).stdout.lower()
            return any(c in out for c in cands)
        pgrep = shutil.which("pgrep")
        if pgrep:
            for c in cands:
                if subprocess.run([pgrep, "-fi", c], capture_output=True, timeout=5).returncode == 0:
                    return True
            return False
        # Fallback: scan /proc cmdlines.
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_text(errors="ignore").lower()
            except OSError:
                continue
            if any(c in cmd for c in cands):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


class AppTracker:
    def __init__(self, store: Path = _STORE):
        self.store = store
        self._apps: dict = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            self.store.write_text(json.dumps(self._apps, indent=2), encoding="utf-8")
        except OSError:
            pass

    def record(self, name: str, target: str, pid: int | None = None) -> None:
        self._apps[name.lower()] = {"target": target, "pid": pid, "opened_at": time.time()}
        self._save()

    def running(self) -> list[str]:
        """Names Namma Agent opened that are still running (also prunes dead ones)."""
        alive, changed = [], False
        for name in list(self._apps):
            if is_running(name):
                alive.append(name)
            else:
                self._apps.pop(name, None)
                changed = True
        if changed:
            self._save()
        return alive
