"""Shell tool — run a command (destructive; approval-gated)."""
from __future__ import annotations

import subprocess

from friday.core.tools import ToolRegistry, ToolResult

_TIMEOUT = 60


def _run_shell(args: dict) -> ToolResult:
    cmd = args.get("command", "").strip()
    if not cmd:
        return ToolResult(ok=False, content="", error="empty command")
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, content="", error=f"timed out after {_TIMEOUT}s")
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip()[:20_000] or "(no output)"
    return ToolResult(ok=proc.returncode == 0, content=out,
                      error="" if proc.returncode == 0 else f"exit {proc.returncode}: {out[:300]}")


def register(registry: ToolRegistry) -> None:
    registry.register("run_shell", "Run a shell command and return stdout/stderr.", {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "the shell command to run"}},
        "required": ["command"],
    }, _run_shell, destructive=True)
