"""System info tool — read-only host facts."""
from __future__ import annotations

import platform
import shutil

from friday.core.tools import ToolRegistry, ToolResult


def _system_info(_args: dict) -> ToolResult:
    info = {
        "os": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hostname": platform.node(),
    }
    try:
        total, used, free = shutil.disk_usage("/")
        info["disk_free_gb"] = round(free / 1e9, 1)
    except Exception:  # noqa: BLE001
        pass
    lines = "\n".join(f"{k}: {v}" for k, v in info.items())
    return ToolResult(ok=True, content=lines, data=info)


def register(registry: ToolRegistry) -> None:
    registry.register("system_info", "Get basic information about the host system.", {
        "type": "object", "properties": {},
    }, _system_info)
