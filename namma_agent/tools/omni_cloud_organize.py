"""OmniCloud organize tool — powered by OmniCloud REST API.

Automatically organizes loose files in cloud storage root into categorized
folders based on file type and name patterns.

Tools:
  omni_cloud_organize — scan root, categorize files, create folders, move files

Degrades cleanly: if OmniCloud isn't running, returns a clear setup message.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from namma_agent.core.tools import ToolRegistry, ToolResult

# ---------------------------------------------------------------------------
# Configuration (shared with cloud_storage.py)
# ---------------------------------------------------------------------------

OMNICLOUD_BASE_URL = os.environ.get("OMNICLOUD_URL", "http://localhost:8787")
API_PREFIX = f"{OMNICLOUD_BASE_URL}/api"
_TIMEOUT = 30

_NOT_RUNNING_HINT = (
    f"OmniCloud is not reachable at {OMNICLOUD_BASE_URL}. "
    "Make sure it's running: cd C:\\Users\\vamsi\\OmniCloud && docker compose up -d"
)


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _request(
    method: str,
    path: str,
    *,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
) -> tuple[bool, Any, str]:
    url = f"{API_PREFIX}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url = f"{url}?{qs}"

    body = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return True, json.loads(raw), ""
            except (json.JSONDecodeError, ValueError):
                return True, raw, ""
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            err_data = json.loads(raw)
            err_msg = err_data.get("error", raw or str(exc))
        except (json.JSONDecodeError, ValueError):
            err_msg = raw or str(exc)
        return False, None, f"HTTP {exc.code}: {err_msg}"
    except urllib.error.URLError as exc:
        return False, None, f"{_NOT_RUNNING_HINT} ({exc.reason})"
    except Exception as exc:  # noqa: BLE001
        return False, None, f"Request failed: {exc}"


def _get(path: str, **params) -> tuple[bool, Any, str]:
    return _request("GET", path, params=params)


def _post(path: str, data: dict | None = None) -> tuple[bool, Any, str]:
    return _request("POST", path, data=data)


def _patch(path: str, data: dict | None = None) -> tuple[bool, Any, str]:
    return _request("PATCH", path, data=data)


# ---------------------------------------------------------------------------
# Categorization rules
# ---------------------------------------------------------------------------

# Extension -> target folder
_EXT_MAP: dict[str, str] = {
    # Documents
    ".doc": "Documents", ".docx": "Documents", ".odt": "Documents",
    ".txt": "Documents", ".md": "Documents", ".rtf": "Documents",
    ".pdf": "Documents", ".epub": "Documents",
    # Spreadsheets
    ".xls": "Spreadsheets", ".xlsx": "Spreadsheets", ".csv": "Spreadsheets",
    ".ods": "Spreadsheets", ".tsv": "Spreadsheets",
    # Presentations
    ".ppt": "Presentations", ".pptx": "Presentations", ".odp": "Presentations",
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".webp": "Images", ".svg": "Images", ".bmp": "Images", ".ico": "Images",
    ".tiff": "Images", ".heic": "Images",
    # Video
    ".mp4": "Videos", ".mkv": "Videos", ".avi": "Videos", ".mov": "Videos",
    ".wmv": "Videos", ".flv": "Videos", ".webm": "Videos",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".aac": "Audio",
    ".ogg": "Audio", ".m4a": "Audio",
    # Code / Data
    ".py": "Code", ".js": "Code", ".ts": "Code", ".html": "Code",
    ".css": "Code", ".json": "Code", ".xml": "Code", ".yaml": "Code",
    ".yml": "Code", ".sh": "Code", ".sql": "Code",
    # Archives
    ".zip": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".7z": "Archives", ".rar": "Archives",
    # Notebooks
    ".ipynb": "Notebooks",
}

# Name-pattern -> target folder (checked BEFORE extension, case-insensitive)
# Each pattern is a regex matched against the full filename.
_NAME_PATTERNS: list[tuple[str, str]] = [
    # DSA / coding practice files
    (r"dsa|data\s*structur|hard_sol|medium_sol|easy_sol|hard_test|medium_test|easy_test|leetcode|hackerrank|codeforces", "DSA"),
    # Software engineering
    (r"\bse\b|software\s*eng|sdm|srs|use.?case|class.?diagram", "SE"),
    # Notebooks / Colab
    (r"colab|notebook|\.ipynb", "Colab Notebooks"),
    # Business / admin
    (r"business|invoice|customer|registration|billing|waffel|waffle", "Business"),
    # Career / job docs
    (r"cover\s*letter|resume|cv\b|job|career|jp\s*morgan|interview", "Career"),
    # Tube / video content
    (r"tube|video|a001\d+", "Tube"),
    # Projects
    (r"project|proposal|sprint|backlog|orientbell|chatbot|n8n", "Projects"),
    # Academics / lectures
    (r"lecture|unit\s*\d|course|syllabus|assignment|exam|midterm|final", "Academics"),
    # Data / CSV datasets
    (r"^data\d|dataset|sample_data", "Colab Notebooks"),
]

# Files/folders to skip (never move these — they're already organized or are system items)
_SKIP_EXACT: set[str] = {
    "Business", "Colab Notebooks", "DSA", "project", "Projects",
    "sample_data", "SE", "Tube", "Career", "Documents", "Media",
    "Spreadsheets", "Presentations", "Code", "Archives", "Audio",
    "Videos", "Images", "Academics", "Notebooks",
}


def _categorize_file(file: dict) -> str | None:
    """Return the target folder name for a file, or None to skip."""
    name = (file.get("file_name") or file.get("name") or "").strip()
    is_folder = file.get("is_folder", False)

    if not name or name in _SKIP_EXACT:
        return None
    if is_folder:
        return None

    name_lower = name.lower()

    # Check name patterns FIRST (higher priority than extension)
    for pattern, folder in _NAME_PATTERNS:
        if re.search(pattern, name_lower):
            return folder

    # Fall back to extension mapping
    ext = os.path.splitext(name)[1].lower()
    return _EXT_MAP.get(ext)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

def _omni_cloud_organize(args: dict) -> ToolResult:
    """Scan cloud storage root, categorize loose files, create folders, move them.

    Supports dry_run to preview without making changes.
    """
    dry_run = args.get("dry_run", False)
    max_moves = args.get("max_moves", 50)

    # Step 1: List root files
    ok, data, err = _get("/files", path="/")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    files = data.get("data", [])
    if not files:
        return ToolResult(ok=True, content="Root is already clean — no loose files found.", data={"moved": 0})

    # Step 2: Categorize
    moves: list[dict] = []
    skipped: list[str] = []

    for f in files:
        target = _categorize_file(f)
        if target:
            moves.append({
                "id": f.get("id"),
                "name": f.get("file_name") or f.get("name"),
                "target_folder": target,
            })
        else:
            name = f.get("file_name") or f.get("name") or "?"
            skipped.append(name)

    if not moves:
        return ToolResult(
            ok=True,
            content=f"All {len(files)} items are already in folders or are folders. Nothing to organize.",
            data={"moved": 0, "skipped": skipped},
        )

    # Cap at max_moves
    moves = moves[:max_moves]

    if dry_run:
        lines = [f"DRY RUN — would move {len(moves)} file(s):\n"]
        by_folder: dict[str, list[str]] = {}
        for m in moves:
            by_folder.setdefault(m["target_folder"], []).append(m["name"])
        for folder, names in sorted(by_folder.items()):
            lines.append(f"  {folder}/")
            for n in names:
                lines.append(f"    - {n}")
        if skipped:
            lines.append(f"\nWould skip {len(skipped)} item(s): {', '.join(skipped[:10])}")
        return ToolResult(ok=True, content="\n".join(lines), data={"moves": moves, "skipped": skipped})

    # Step 3: Get or create destination folders
    ok, accounts_data, err = _get("/accounts")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    accounts = accounts_data.get("data", [])
    if not accounts:
        return ToolResult(ok=False, content="", error="No cloud accounts connected.")

    # Build folder cache: name -> id (for each account we care about)
    folder_cache: dict[str, str] = {}  # "folder_name" -> folder_id

    # Collect unique target folder names
    target_folders = {m["target_folder"] for m in moves}

    # List root to find existing folders
    ok, root_data, err = _get("/files", path="/")
    if ok:
        for f in root_data.get("data", []):
            if f.get("is_folder") and f.get("file_name") in target_folders:
                folder_cache[f["file_name"]] = f["id"]

    # Create missing folders
    created_folders: list[str] = []
    for folder_name in sorted(target_folders):
        if folder_name not in folder_cache:
            ok, _, err = _post("/files/folders", {"name": folder_name, "virtual_path": "/"})
            if ok:
                created_folders.append(folder_name)
                # Re-list to get the new folder ID
                ok2, root2, _ = _get("/files", path="/")
                if ok2:
                    for f in root2.get("data", []):
                        if f.get("is_folder") and f.get("file_name") == folder_name:
                            folder_cache[folder_name] = f["id"]
                            break

    # Step 4: Move files
    moved_count = 0
    errors: list[str] = []

    for m in moves:
        folder_id = folder_cache.get(m["target_folder"])
        if not folder_id:
            errors.append(f"Could not find/create folder '{m['target_folder']}' for {m['name']}")
            continue

        ok, _, err = _patch(f"/files/{m['id']}", {"parent_id": folder_id})
        if ok:
            moved_count += 1
        else:
            errors.append(f"Failed to move {m['name']}: {err}")

    # Step 5: Build summary
    lines = []
    if created_folders:
        lines.append(f"Created {len(created_folders)} folder(s): {', '.join(created_folders)}")
    lines.append(f"Moved {moved_count}/{len(moves)} file(s) into categorized folders.")
    if errors:
        lines.append(f"\n{len(errors)} error(s):")
        for e in errors[:10]:
            lines.append(f"  - {e}")
    if skipped:
        lines.append(f"\nSkipped {len(skipped)} item(s) (already in folders or are folders).")

    return ToolResult(
        ok=True,
        content="\n".join(lines),
        data={
            "moved": moved_count,
            "total": len(moves),
            "created_folders": created_folders,
            "errors": errors,
            "skipped": skipped,
        },
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry: ToolRegistry) -> None:
    registry.register(
        "omni_cloud_organize",
        (
            "Automatically organize loose files in cloud storage root into "
            "categorized folders (Documents, Images, Videos, Code, etc.) based "
            "on file type and name patterns. Use dry_run=true to preview first."
        ),
        {
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview changes without moving files (default: false)",
                },
                "max_moves": {
                    "type": "integer",
                    "description": "Maximum number of files to move in one run (default: 50)",
                },
            },
        },
        _omni_cloud_organize,
        destructive=True,
    )
