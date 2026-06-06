"""File tools — read, write, list. All paths go through PathSecurity."""
from __future__ import annotations

import os
from pathlib import Path

from friday.core.safety import check_path
from friday.core.tools import ToolRegistry, ToolResult

_MAX_READ = 200_000  # chars


def _read_file(args: dict) -> ToolResult:
    path = args.get("path", "")
    ok, reason = check_path(path)
    if not ok:
        return ToolResult(ok=False, content="", error=reason)
    p = Path(path).expanduser()
    if not p.is_file():
        return ToolResult(ok=False, content="", error=f"not a file: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")[:_MAX_READ]
    return ToolResult(ok=True, content=text)


def _write_file(args: dict) -> ToolResult:
    path = args.get("path", "")
    ok, reason = check_path(path)
    if not ok:
        return ToolResult(ok=False, content="", error=reason)
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args.get("content", ""), encoding="utf-8")
    return ToolResult(ok=True, content=f"Wrote {len(args.get('content', ''))} chars to {path}")


def _list_dir(args: dict) -> ToolResult:
    path = args.get("path", ".")
    ok, reason = check_path(path)
    if not ok:
        return ToolResult(ok=False, content="", error=reason)
    p = Path(path).expanduser()
    if not p.is_dir():
        return ToolResult(ok=False, content="", error=f"not a directory: {path}")
    entries = []
    for e in sorted(os.scandir(p), key=lambda x: x.name):
        entries.append(f"{'d' if e.is_dir() else 'f'} {e.name}")
    return ToolResult(ok=True, content="\n".join(entries) or "(empty)")


def register(registry: ToolRegistry) -> None:
    registry.register("read_file", "Read a UTF-8 text file and return its contents.", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "absolute or ~ path"}},
        "required": ["path"],
    }, _read_file)

    registry.register("write_file", "Write text to a file (creates/overwrites).", {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }, _write_file, destructive=True)

    registry.register("list_dir", "List entries in a directory.", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "directory path (default '.')"}},
    }, _list_dir)
