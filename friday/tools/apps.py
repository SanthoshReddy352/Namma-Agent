"""App launcher tool — open a desktop application or file (cross-platform)."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

from friday.core.tools import ToolRegistry, ToolResult


def _open_app(args: dict) -> ToolResult:
    target = args.get("target", "").strip()
    if not target:
        return ToolResult(ok=False, content="", error="no target given")
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", target])
        else:
            opener = shutil.which("xdg-open") or shutil.which("gio")
            if shutil.which(target):  # it's an executable name
                subprocess.Popen([target], start_new_session=True)
            elif opener:
                subprocess.Popen([opener, target], start_new_session=True)
            else:
                return ToolResult(ok=False, content="", error="no opener (xdg-open) and not an executable")
        return ToolResult(ok=True, content=f"Opened {target}")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))


def register(registry: ToolRegistry) -> None:
    registry.register("open_app", "Open a desktop application, file, or URL.", {
        "type": "object",
        "properties": {"target": {"type": "string", "description": "app name, file path, or URL"}},
        "required": ["target"],
    }, _open_app)
