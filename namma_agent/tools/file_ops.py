"""File tools — read, write, list, and organise.

Every model-written path is first normalized against the REAL host by
``engram.environment.resolve_path`` (expands ``~``, maps spoken folder names,
fixes POSIX guesses on Windows, rejects nonexistent drives with the actual
layout quoted — so a wrong guess teaches the model the filesystem), then
validated by PathSecurity.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Optional

from namma_agent.core.engram.environment import resolve_path
from namma_agent.core.safety import check_path
from namma_agent.core.tools import ToolRegistry, ToolResult

_MAX_READ = 200_000  # chars
_FIND_CAP = 500      # max paths returned by find_files

# Buckets for organize_dir — extension (lowercased, no dot) → folder name.
_ORGANIZE_BUCKETS = {
    "Images": {"jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "heic", "tiff"},
    "Videos": {"mp4", "mkv", "mov", "avi", "webm", "flv", "wmv", "m4v"},
    "Audio": {"mp3", "wav", "flac", "aac", "ogg", "m4a", "opus"},
    "Documents": {"pdf", "doc", "docx", "txt", "md", "rtf", "odt", "epub"},
    "Spreadsheets": {"xls", "xlsx", "csv", "ods"},
    "Presentations": {"ppt", "pptx", "odp"},
    "Archives": {"zip", "tar", "gz", "bz2", "xz", "7z", "rar"},
    "Code": {"py", "js", "ts", "jsx", "tsx", "c", "cpp", "h", "java", "go", "rs", "sh", "json", "yaml", "yml"},
}


def _checked(raw: str, write: bool = False) -> tuple[str, Optional[str]]:
    """Host-resolve then security-validate a path. Returns ``(path, error)``."""
    path, err = resolve_path(raw)
    if err:
        return path, err
    ok, reason = check_path(path, write=write)
    return path, (None if ok else reason)


def _read_file(args: dict) -> ToolResult:
    path, err = _checked(args.get("path", ""))
    if err:
        return ToolResult(ok=False, content="", error=err)
    p = Path(path).expanduser()
    if not p.is_file():
        return ToolResult(ok=False, content="", error=f"not a file: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")[:_MAX_READ]
    return ToolResult(ok=True, content=text)


def _write_file(args: dict) -> ToolResult:
    path, err = _checked(args.get("path", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args.get("content", ""), encoding="utf-8")
    return ToolResult(ok=True, content=f"Wrote {len(args.get('content', ''))} chars to {path}")


def _list_dir(args: dict) -> ToolResult:
    path, err = _checked(args.get("path", "."))
    if err:
        return ToolResult(ok=False, content="", error=err)
    p = Path(path).expanduser()
    if not p.is_dir():
        return ToolResult(ok=False, content="", error=f"not a directory: {path}")
    entries = []
    for e in sorted(os.scandir(p), key=lambda x: x.name):
        entries.append(f"{'d' if e.is_dir() else 'f'} {e.name}")
    return ToolResult(ok=True, content="\n".join(entries) or "(empty)")


def _bucket_for(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    for bucket, exts in _ORGANIZE_BUCKETS.items():
        if ext in exts:
            return bucket
    return "Other"


def _move_path(args: dict) -> ToolResult:
    # A move both removes the source and creates the dest, so BOTH ends are writes.
    src, err = _checked(args.get("source", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    dst, err = _checked(args.get("dest", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    sp, dp = Path(src).expanduser(), Path(dst).expanduser()
    if not sp.exists():
        return ToolResult(ok=False, content="", error=f"not found: {src}")
    if dp.is_dir():
        dp = dp / sp.name
    dp.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(sp), str(dp))
    return ToolResult(ok=True, content=f"Moved {src} → {dp}")


def _copy_path(args: dict) -> ToolResult:
    # Source is only read; dest is written — so a copy OUT of a system dir is fine,
    # but a copy INTO one is refused.
    src, err = _checked(args.get("source", ""))
    if err:
        return ToolResult(ok=False, content="", error=err)
    dst, err = _checked(args.get("dest", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    sp, dp = Path(src).expanduser(), Path(dst).expanduser()
    if not sp.exists():
        return ToolResult(ok=False, content="", error=f"not found: {src}")
    if sp.is_dir():
        if dp.exists() and dp.is_dir():
            dp = dp / sp.name
        shutil.copytree(str(sp), str(dp))
    else:
        if dp.is_dir():
            dp = dp / sp.name
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(sp), str(dp))
    return ToolResult(ok=True, content=f"Copied {src} → {dp}")


def _delete_path(args: dict) -> ToolResult:
    path, err = _checked(args.get("path", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    p = Path(path).expanduser()
    if not p.exists():
        return ToolResult(ok=False, content="", error=f"not found: {path}")
    if p.is_dir():
        shutil.rmtree(str(p))
        return ToolResult(ok=True, content=f"Deleted folder {path}")
    p.unlink()
    return ToolResult(ok=True, content=f"Deleted {path}")


def _make_dir(args: dict) -> ToolResult:
    path, err = _checked(args.get("path", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    Path(path).expanduser().mkdir(parents=True, exist_ok=True)
    return ToolResult(ok=True, content=f"Created {path}")


def _find_files(args: dict) -> ToolResult:
    pattern = args.get("pattern", "*")
    root, err = _checked(args.get("path", "."))
    if err:
        return ToolResult(ok=False, content="", error=err)
    base = Path(root).expanduser()
    if not base.is_dir():
        return ToolResult(ok=False, content="", error=f"not a directory: {root}")
    matches: list[str] = []
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                matches.append(str(Path(dirpath) / name))
                if len(matches) >= _FIND_CAP:
                    break
        if len(matches) >= _FIND_CAP:
            break
    if not matches:
        return ToolResult(ok=True, content=f"(no files matching {pattern!r} under {root})")
    body = "\n".join(matches)
    return ToolResult(ok=True, content=f"{len(matches)} match(es):\n{body}", data=matches)


def _organize_dir(args: dict) -> ToolResult:
    path, err = _checked(args.get("path", ""), write=True)
    if err:
        return ToolResult(ok=False, content="", error=err)
    base = Path(path).expanduser()
    if not base.is_dir():
        return ToolResult(ok=False, content="", error=f"not a directory: {path}")
    moved: dict[str, int] = {}
    for entry in list(os.scandir(base)):
        if not entry.is_file():
            continue
        bucket = _bucket_for(Path(entry.name).suffix)
        dest_dir = base / bucket
        dest_dir.mkdir(exist_ok=True)
        shutil.move(entry.path, str(dest_dir / entry.name))
        moved[bucket] = moved.get(bucket, 0) + 1
    if not moved:
        return ToolResult(ok=True, content=f"(no loose files to organize in {path})")
    summary = ", ".join(f"{n}→{b}" for b, n in sorted(moved.items()))
    return ToolResult(ok=True, content=f"Organized {path}: {summary}", data=moved)


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

    registry.register("move_path", "Move or rename a file or folder.", {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "path to move/rename"},
            "dest": {"type": "string", "description": "destination path or folder"},
        },
        "required": ["source", "dest"],
    }, _move_path, destructive=True)

    registry.register("copy_path", "Copy a file or folder to a new location.", {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "dest": {"type": "string"},
        },
        "required": ["source", "dest"],
    }, _copy_path)

    registry.register("delete_path", "Delete a file or folder (recursive for folders).", {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }, _delete_path, destructive=True)

    registry.register("make_dir", "Create a directory (parents as needed).", {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }, _make_dir)

    registry.register("find_files", "Recursively find files matching a glob pattern under a directory.", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "root directory to search (default '.')"},
            "pattern": {"type": "string", "description": "glob, e.g. '*.pdf' or 'report*' (default '*')"},
        },
    }, _find_files)

    registry.register("organize_dir", "Sort loose files in a folder into Images/Videos/Documents/… subfolders by type.", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "folder to organize"}},
        "required": ["path"],
    }, _organize_dir, destructive=True)
