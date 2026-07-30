"""Cloud storage tools — powered by OmniCloud REST API.

Provides multi-cloud file management (Google Drive, OneDrive, Dropbox, etc.)
through a self-hosted OmniCloud instance running on localhost:8787.

Tools:
  cloud_accounts          — list connected cloud accounts
  cloud_connect           — get OAuth URL to connect a cloud provider
  cloud_list              — list files/folders at a virtual path
  cloud_search            — search files across all connected accounts
  cloud_upload            — upload a local file to cloud storage
  cloud_download          — download a file from cloud to local filesystem
  cloud_mkdir             — create a folder in cloud storage
  cloud_move              — move a file or folder to a different parent folder
  cloud_rename            — rename a file or folder
  cloud_delete            — delete a file or folder
  cloud_star              — star/unstar a file
  cloud_sync              — trigger a manual sync of all accounts
  cloud_health            — check OmniCloud instance status

Degrades cleanly: if OmniCloud isn't running, every tool returns a clear
setup message explaining how to start it.
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from namma_agent.core.tools import ToolRegistry, ToolResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OMNICLOUD_BASE_URL = os.environ.get("OMNICLOUD_URL", "http://localhost:8787")
API_PREFIX = f"{OMNICLOUD_BASE_URL}/api"
_TIMEOUT = 30

_NOT_RUNNING_HINT = (
    f"OmniCloud is not reachable at {OMNICLOUD_BASE_URL}. "
    "Make sure it's running: cd C:\\Users\\vamsi\\OmniCloud && docker compose up -d"
)


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no extra dependencies)
# ---------------------------------------------------------------------------

def _request(
    method: str,
    endpoint: str,
    *,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
) -> tuple[bool, Any, str]:
    """Make an HTTP request to OmniCloud. Returns (ok, parsed_json_or_text, error)."""
    url = f"{API_PREFIX}{endpoint}"
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


def _get(endpoint: str, **params) -> tuple[bool, Any, str]:
    return _request("GET", endpoint, params=params)


def _post(endpoint: str, data: dict | None = None) -> tuple[bool, Any, str]:
    return _request("POST", endpoint, data=data)


def _patch(endpoint: str, data: dict | None = None) -> tuple[bool, Any, str]:
    return _request("PATCH", endpoint, data=data)


def _delete(endpoint: str) -> tuple[bool, Any, str]:
    return _request("DELETE", endpoint)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_size(size_bytes: int | str | None) -> str:
    """Human-readable file size."""
    try:
        n = int(size_bytes)
    except (TypeError, ValueError):
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _format_file_line(f: dict) -> str:
    """One-line summary for a file/folder."""
    is_folder = f.get("is_folder", False)
    icon = "\U0001f4c1" if is_folder else "\U0001f4c4"
    name = f.get("file_name") or f.get("name") or "untitled"
    fid = f.get("id", "")
    provider = f.get("provider", "")
    size = _format_size(f.get("size"))
    size_str = f" ({size})" if size and not is_folder else ""
    starred = " \u2605" if f.get("is_starred") or f.get("starred") else ""
    return f"- {icon} {name}{starred} [{fid}]{size_str} [{provider}]"


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _cloud_health(args: dict) -> ToolResult:
    """Check OmniCloud instance status."""
    ok, data, err = _get("/health")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    status = data.get("status", "unknown")
    mode = data.get("config", {}).get("appMode", "unknown")
    sync = data.get("sync", {})
    last_sync = sync.get("lastRunAt", "never")
    accounts = sync.get("scannedAccounts", 0)

    return ToolResult(
        ok=True,
        content=(
            f"OmniCloud status: {status}\n"
            f"Mode: {mode}\n"
            f"Connected accounts: {accounts}\n"
            f"Last sync: {last_sync}"
        ),
        data=data,
    )


def _cloud_accounts(args: dict) -> ToolResult:
    """List connected cloud storage accounts."""
    ok, data, err = _get("/accounts")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    accounts = data.get("data", [])
    if not accounts:
        return ToolResult(
            ok=True,
            content=(
                "No cloud accounts connected yet. "
                "Use `cloud_connect` with a provider (google_drive, onedrive, dropbox) "
                "to get the OAuth URL and connect one."
            ),
            data={"accounts": []},
        )

    lines = []
    for acc in accounts:
        provider = acc.get("provider", "unknown")
        email = acc.get("email", "unknown")
        status = acc.get("status", "unknown")
        total = _format_size(acc.get("total_space"))
        used = _format_size(acc.get("used_space"))
        free = _format_size(acc.get("free_space"))
        lines.append(
            f"- {provider}: {email} ({status}) — {used} used / {total} total, {free} free"
        )

    return ToolResult(ok=True, content="\n".join(lines), data={"accounts": accounts})


def _cloud_connect(args: dict) -> ToolResult:
    """Get OAuth URL to connect a cloud provider.

    Opens the browser for the user to authorize. Supported providers:
    google_drive, onedrive, dropbox, yandex
    """
    provider = (args.get("provider") or "").strip().lower()
    if not provider:
        return ToolResult(
            ok=False, content="",
            error="'provider' is required. Supported: google_drive, onedrive, dropbox, yandex"
        )

    provider_map = {
        "google_drive": "google",
        "google": "google",
        "onedrive": "onedrive",
        "dropbox": "dropbox",
        "yandex": "yandex",
    }
    api_provider = provider_map.get(provider)
    if not api_provider:
        return ToolResult(
            ok=False, content="",
            error=f"Unknown provider '{provider}'. Supported: google_drive, onedrive, dropbox, yandex"
        )

    ok, data, err = _get(f"/accounts/{api_provider}/connect")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    connect_data = data.get("data", data)
    auth_url = connect_data.get("authorizationUrl", "")
    state = connect_data.get("state", "")

    return ToolResult(
        ok=True,
        content=(
            f"Open this URL in your browser to connect {provider}:\n\n{auth_url}\n\n"
            f"After authorizing, you'll be redirected to complete the connection. "
            f"Once done, run `cloud_accounts` to verify."
        ),
        data={"authorization_url": auth_url, "state": state, "provider": provider},
    )


def _cloud_list(args: dict) -> ToolResult:
    """List files/folders at a virtual path or by account."""
    path = (args.get("path") or "/").strip()
    starred = args.get("starred", False)
    recent = args.get("recent", False)
    shared = args.get("shared", False)
    search_query = (args.get("search") or "").strip()

    params = {}
    if search_query:
        params["search"] = search_query
    elif starred:
        params["starred"] = "1"
    elif recent:
        params["recent"] = "1"
    elif shared:
        params["shared"] = "1"
    else:
        params["path"] = path

    # Use _request directly to avoid collision with _get's endpoint param
    ok, data, err = _request("GET", "/files", params=params)
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    files = data.get("data", [])
    if not files:
        label = f" in '{path}'" if not any([starred, recent, shared, search_query]) else ""
        return ToolResult(ok=True, content=f"No files found{label}.", data={"files": []})

    lines = [f"Found {len(files)} item(s):\n"]
    for f in files:
        lines.append(_format_file_line(f))

    return ToolResult(ok=True, content="\n".join(lines), data={"files": files})


def _cloud_search(args: dict) -> ToolResult:
    """Search files across all connected cloud accounts."""
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="'query' is required")

    max_results = args.get("max", 20)
    ok, data, err = _get("/files", search=query, limit=str(max_results))
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    files = data.get("data", [])
    if not files:
        return ToolResult(ok=True, content=f"No files matching '{query}'.", data={"files": []})

    lines = [f"Found {len(files)} result(s) for '{query}':\n"]
    for f in files:
        lines.append(_format_file_line(f))

    return ToolResult(ok=True, content="\n".join(lines), data={"files": files})


def _cloud_upload(args: dict) -> ToolResult:
    """Upload a local file to cloud storage.

    Two-step process: initiate upload session, then stream the file.
    """
    local_path = (args.get("local_path") or "").strip()
    if not local_path:
        return ToolResult(ok=False, content="", error="'local_path' is required")
    if not os.path.isfile(local_path):
        return ToolResult(ok=False, content="", error=f"File not found: {local_path}")

    virtual_path = (args.get("virtual_path") or "/").strip()
    name = (args.get("name") or "").strip() or os.path.basename(local_path)
    file_size = os.path.getsize(local_path)
    mime_type = _guess_mime(name)

    # Step 1: initiate upload session
    init_payload = {
        "file_name": name,
        "size": file_size,
        "mime_type": mime_type,
        "virtual_path": virtual_path,
    }
    ok, data, err = _post("/uploads/initiate", init_payload)
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    session = data.get("data", {})
    upload_id = session.get("upload_id")
    session_token = session.get("session_token")
    target = session.get("target_account", {})

    if not upload_id or not session_token:
        return ToolResult(ok=False, content="", error="Failed to create upload session")

    # Step 2: stream file content
    try:
        with open(local_path, "rb") as fh:
            file_data = fh.read()
    except OSError as exc:
        return ToolResult(ok=False, content="", error=f"Failed to read file: {exc}")

    upload_url = f"{API_PREFIX}/uploads/{upload_id}/stream"
    headers = {
        "Content-Type": mime_type,
        "X-Upload-Token": session_token,
        "X-File-Name": name,
    }
    req = urllib.request.Request(upload_url, data=file_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return ToolResult(ok=False, content="", error=f"Upload failed (HTTP {exc.code}): {raw}")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"Upload failed: {exc}")

    metadata = resp_data.get("data", resp_data)
    return ToolResult(
        ok=True,
        content=(
            f"Uploaded '{name}' ({_format_size(file_size)}) to {target.get('provider', 'cloud')} "
            f"({target.get('email', 'unknown')})."
        ),
        data={"name": name, "size": file_size, "target_account": target, "metadata": metadata},
    )


def _cloud_download(args: dict) -> ToolResult:
    """Download a file from cloud storage to local filesystem."""
    file_id = (args.get("file_id") or "").strip()
    if not file_id:
        return ToolResult(ok=False, content="", error="'file_id' is required")

    dest = (args.get("dest") or "").strip() or "."

    # Get file details first to know the filename
    ok, detail_data, err = _get(f"/files/{file_id}")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    file_info = detail_data.get("data", {})
    file_name = file_info.get("file_name") or file_info.get("name") or file_id
    is_folder = file_info.get("is_folder", False)

    if is_folder:
        return ToolResult(ok=False, content="", error="Cannot download a folder directly. Download individual files instead.")

    # Build destination path
    if os.path.isdir(dest):
        dest_path = os.path.join(dest, file_name)
    else:
        dest_path = dest

    # Download via streaming
    download_url = f"{API_PREFIX}/files/{file_id}/download"
    req = urllib.request.Request(download_url)

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(dest_path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
    except urllib.error.HTTPError as exc:
        return ToolResult(ok=False, content="", error=f"Download failed (HTTP {exc.code})")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"Download failed: {exc}")

    size = os.path.getsize(dest_path) if os.path.isfile(dest_path) else 0
    return ToolResult(
        ok=True,
        content=f"Downloaded '{file_name}' ({_format_size(size)}) to {dest_path}",
        data={"file_id": file_id, "path": dest_path, "size": size},
    )


def _cloud_mkdir(args: dict) -> ToolResult:
    """Create a folder in cloud storage."""
    name = (args.get("name") or "").strip()
    if not name:
        return ToolResult(ok=False, content="", error="'name' is required")

    virtual_path = (args.get("virtual_path") or "/").strip()

    ok, data, err = _post("/files/folders", {"name": name, "virtual_path": virtual_path})
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    return ToolResult(
        ok=True,
        content=f"Created folder '{name}' at {virtual_path}",
        data={"name": name, "virtual_path": virtual_path},
    )


def _cloud_move(args: dict) -> ToolResult:
    """Move a file or folder to a different parent folder in cloud storage."""
    file_id = (args.get("file_id") or "").strip()
    parent_id = (args.get("parent_id") or "").strip()
    if not file_id:
        return ToolResult(ok=False, content="", error="'file_id' is required")
    if not parent_id:
        return ToolResult(ok=False, content="", error="'parent_id' is required (the destination folder ID)")

    ok, data, err = _patch(f"/files/{file_id}", {"parent_id": parent_id})
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    return ToolResult(
        ok=True,
        content=f"Moved file {file_id} to folder {parent_id}",
        data={"file_id": file_id, "parent_id": parent_id},
    )


def _cloud_rename(args: dict) -> ToolResult:
    """Rename a file or folder in cloud storage."""
    file_id = (args.get("file_id") or "").strip()
    name = (args.get("name") or "").strip()
    if not file_id:
        return ToolResult(ok=False, content="", error="'file_id' is required")
    if not name:
        return ToolResult(ok=False, content="", error="'name' (new name) is required")

    ok, data, err = _patch(f"/files/{file_id}/rename", {"name": name})
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    return ToolResult(
        ok=True,
        content=f"Renamed file {file_id} to '{name}'",
        data={"file_id": file_id, "new_name": name},
    )


def _cloud_delete(args: dict) -> ToolResult:
    """Delete a file or folder from cloud storage."""
    file_id = (args.get("file_id") or "").strip()
    if not file_id:
        return ToolResult(ok=False, content="", error="'file_id' is required")

    ok, data, err = _delete(f"/files/{file_id}")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    return ToolResult(
        ok=True,
        content=f"Deleted file {file_id}",
        data={"file_id": file_id, "deleted": True},
    )


def _cloud_star(args: dict) -> ToolResult:
    """Star or unstar a file in cloud storage."""
    file_id = (args.get("file_id") or "").strip()
    if not file_id:
        return ToolResult(ok=False, content="", error="'file_id' is required")

    is_starred = args.get("is_starred", True)

    ok, data, err = _patch(f"/files/{file_id}/star", {"is_starred": is_starred})
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    action = "Starred" if is_starred else "Unstarred"
    return ToolResult(
        ok=True,
        content=f"{action} file {file_id}",
        data={"file_id": file_id, "is_starred": is_starred},
    )


def _cloud_sync(args: dict) -> ToolResult:
    """Trigger a manual sync of all connected cloud accounts."""
    ok, data, err = _post("/sync/run")
    if not ok:
        return ToolResult(ok=False, content="", error=err)

    report = data.get("data", data)
    scanned = report.get("scannedAccounts", 0)
    changes = report.get("changesDetected", 0)

    return ToolResult(
        ok=True,
        content=f"Sync complete. Scanned {scanned} account(s), {changes} change(s) detected.",
        data=report,
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".json": "application/json", ".xml": "application/xml",
    ".zip": "application/zip", ".tar": "application/x-tar",
    ".gz": "application/gzip", ".mp4": "video/mp4",
    ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".py": "text/x-python", ".js": "text/javascript",
    ".html": "text/html", ".css": "text/css",
}


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return _MIME_MAP.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry: ToolRegistry) -> None:
    # --- read-only tools ---
    registry.register(
        "cloud_health",
        "Check OmniCloud instance status and configuration.",
        {"type": "object", "properties": {}},
        _cloud_health,
    )

    registry.register(
        "cloud_accounts",
        "List all connected cloud storage accounts (Google Drive, OneDrive, Dropbox, etc.).",
        {"type": "object", "properties": {}},
        _cloud_accounts,
    )

    registry.register(
        "cloud_connect",
        "Get the OAuth URL to connect a new cloud provider. Opens the browser for authorization.",
        {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "cloud provider to connect: google_drive, onedrive, dropbox, yandex",
                },
            },
            "required": ["provider"],
        },
        _cloud_connect,
    )

    registry.register(
        "cloud_list",
        "List files/folders in cloud storage at a virtual path, or show starred/recent/shared items.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "virtual path to list (default: /)"},
                "starred": {"type": "boolean", "description": "list starred files instead"},
                "recent": {"type": "boolean", "description": "list recent files instead"},
                "shared": {"type": "boolean", "description": "list files shared with me"},
                "search": {"type": "string", "description": "search query to filter results"},
            },
        },
        _cloud_list,
    )

    registry.register(
        "cloud_search",
        "Search files by name or keyword across all connected cloud accounts.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search term or filename"},
                "max": {"type": "integer", "description": "max results (default 20)"},
            },
            "required": ["query"],
        },
        _cloud_search,
    )

    # --- destructive tools ---
    registry.register(
        "cloud_upload",
        "Upload a local file to cloud storage (auto-selects best account by free space).",
        {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "absolute path to the local file"},
                "virtual_path": {"type": "string", "description": "destination path in cloud (default: /)"},
                "name": {"type": "string", "description": "display name in cloud (defaults to filename)"},
            },
            "required": ["local_path"],
        },
        _cloud_upload,
        destructive=True,
    )

    registry.register(
        "cloud_download",
        "Download a file from cloud storage to the local filesystem.",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "cloud file ID"},
                "dest": {"type": "string", "description": "local destination path or folder (default: current dir)"},
            },
            "required": ["file_id"],
        },
        _cloud_download,
        destructive=True,
    )

    registry.register(
        "cloud_mkdir",
        "Create a folder in cloud storage.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "folder name"},
                "virtual_path": {"type": "string", "description": "parent path (default: /)"},
            },
            "required": ["name"],
        },
        _cloud_mkdir,
        destructive=True,
    )

    registry.register(
        "cloud_move",
        "Move a file or folder to a different parent folder in cloud storage.",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "file/folder ID to move"},
                "parent_id": {"type": "string", "description": "destination folder ID"},
            },
            "required": ["file_id", "parent_id"],
        },
        _cloud_move,
        destructive=True,
    )

    registry.register(
        "cloud_rename",
        "Rename a file or folder in cloud storage.",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "file/folder ID to rename"},
                "name": {"type": "string", "description": "new name"},
            },
            "required": ["file_id", "name"],
        },
        _cloud_rename,
        destructive=True,
    )

    registry.register(
        "cloud_delete",
        "Delete a file or folder from cloud storage. This is permanent.",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "file/folder ID to delete"},
            },
            "required": ["file_id"],
        },
        _cloud_delete,
        destructive=True,
    )

    registry.register(
        "cloud_star",
        "Star or unstar a file in cloud storage.",
        {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "file ID to star/unstar"},
                "is_starred": {"type": "boolean", "description": "true to star, false to unstar (default: true)"},
            },
            "required": ["file_id"],
        },
        _cloud_star,
        destructive=True,
    )

    registry.register(
        "cloud_sync",
        "Trigger a manual sync of all connected cloud accounts.",
        {"type": "object", "properties": {}},
        _cloud_sync,
        destructive=True,
    )
