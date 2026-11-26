"""Skills marketplace (Phase 5): browse a curated index, or install any Agent
Skills / SKILL.md skill from a URL — with a preview first.

Sources: a GitHub folder (``github.com/o/r/tree/<ref>/<path>``) — fetched whole,
so its references/templates/scripts come along — or a GitHub blob / raw URL /
any https URL of a single ``SKILL.md``.

Safety, because a skill is instructions the model will follow:
* hard limits (60 files, 2 MB total, 512 KB per file, depth 4); paths can't
  escape the skill folder;
* the preview shows the licence, the files, every script, inline-shell lines,
  tools the skill names that this install doesn't have, missing prerequisite
  commands, and a prompt-injection screen of the text;
* installs land DISABLED (the user enables them after reading), with a
  ``.source.json`` sidecar recording where they came from; inline ``!`cmd```
  never runs for installed skills, whatever ``skills.allow_inline_shell`` says.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

MAX_FILES = 60
MAX_TOTAL = 2 * 1024 * 1024
MAX_FILE = 512 * 1024
MAX_DEPTH = 4
_SCRIPT_EXT = {".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".ps1", ".bat", ".cmd", ".rb", ".pl"}
_INDEX_PATH = Path(__file__).resolve().parent.parent / "skills_index.json"
_UA = {"User-Agent": "Namma-Agent-Skills/2.0"}
SOURCE_FILE = ".source.json"

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600


class FetchError(RuntimeError):
    pass


def load_index() -> dict:
    try:
        return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"skills": []}


def _get(url: str, timeout: int = 15, limit: int = MAX_FILE) -> bytes:
    import os
    headers = dict(_UA)
    token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and "api.github.com" in url:
            raise FetchError("GitHub's API rate limit was hit — try again later, or save a "
                             "GITHUB_PERSONAL_ACCESS_TOKEN in the vault") from exc
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"couldn't reach {url}: {getattr(exc, 'reason', exc)}") from exc
    if len(data) > limit:
        raise FetchError(f"{url} is larger than {limit // 1024} KB")
    return data


def parse_source(url: str) -> dict:
    """Classify a skill URL: ``{kind: 'github_dir'|'file', ...}``."""
    url = (url or "").strip()
    if not url.startswith("https://"):
        raise FetchError("use an https:// URL (a GitHub folder or a SKILL.md file)")
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+?)/?$", url)
    if m:
        return {"kind": "github_dir", "owner": m.group(1), "repo": m.group(2),
                "ref": m.group(3), "path": m.group(4)}
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)/SKILL\.md$", url)
    if m:
        return {"kind": "github_dir", "owner": m.group(1), "repo": m.group(2),
                "ref": m.group(3), "path": m.group(4)}
    m = re.match(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)/SKILL\.md$", url)
    if m:
        return {"kind": "github_dir", "owner": m.group(1), "repo": m.group(2),
                "ref": m.group(3), "path": m.group(4)}
    if url.lower().endswith(".md"):
        return {"kind": "file", "url": url}
    raise FetchError("expected a GitHub skill folder (…/tree/<branch>/<path>) or a SKILL.md URL")


def _safe_rel(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or re.match(r"^[A-Za-z]:", parts[0]):
        raise FetchError(f"unsafe path in skill: {rel!r}")
    return "/".join(parts)


def _fetch_github_dir(src: dict) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    base = src["path"].strip("/")

    def walk(path: str, depth: int) -> None:
        nonlocal total
        if depth > MAX_DEPTH:
            return
        api = (f"https://api.github.com/repos/{src['owner']}/{src['repo']}/contents/"
               f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(src['ref'])}")
        listing = json.loads(_get(api, limit=1024 * 1024).decode("utf-8"))
        if isinstance(listing, dict):          # the path is a single file
            listing = [listing]
        for item in listing:
            if item.get("type") == "dir":
                walk(item["path"], depth + 1)
                continue
            if item.get("type") != "file":
                continue
            if len(files) >= MAX_FILES:
                raise FetchError(f"skill has more than {MAX_FILES} files")
            size = int(item.get("size") or 0)
            if size > MAX_FILE:
                continue                          # skip big binaries (fonts, images)
            rel = _safe_rel(item["path"][len(base):] if item["path"].startswith(base) else item["name"])
            data = _get(item["download_url"])
            total += len(data)
            if total > MAX_TOTAL:
                raise FetchError("skill is larger than 2 MB")
            files[rel] = data

    walk(base, 0)
    return files


def fetch(url: str) -> dict[str, bytes]:
    """All files of the skill at ``url`` (``{relative path: bytes}``)."""
    src = parse_source(url)
    if src["kind"] == "github_dir":
        files = _fetch_github_dir(src)
    else:
        files = {"SKILL.md": _get(src["url"])}
    if "SKILL.md" not in files:
        raise FetchError("no SKILL.md at that location")
    return files


def _tool_names_in(body: str) -> set[str]:
    return set(re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)`", body))


def analyse(files: dict[str, bytes], url: str, registry=None, existing: Optional[set] = None) -> dict:
    """The preview: metadata, files, scripts, risks and requirement checks."""
    from namma_agent.core.docscan import scan_text
    from namma_agent.core.skills import parse_frontmatter

    text = files["SKILL.md"].decode("utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    name = str(meta.get("name") or "").strip()
    desc = " ".join(str(meta.get("description") or "").split())
    errors, warnings = [], []
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", name):
        errors.append("frontmatter 'name' is missing or not lowercase-with-hyphens")
    if not desc:
        errors.append("frontmatter 'description' is missing")
    scripts = sorted(p for p in files if Path(p).suffix.lower() in _SCRIPT_EXT)
    inline = re.findall(r"!`([^`\n]+)`", body)
    if scripts:
        warnings.append(f"includes {len(scripts)} script file(s) — read them before enabling")
    if inline:
        warnings.append("contains inline shell (!`…`) — never run for installed skills")
    prereq = (meta.get("prerequisites") or {}) if isinstance(meta.get("prerequisites"), dict) else {}
    missing_cmds = [c for c in (prereq.get("commands") or []) if not shutil.which(str(c))]
    if missing_cmds:
        warnings.append("needs commands not found here: " + ", ".join(missing_cmds))
    unknown_tools: list[str] = []
    if registry is not None:
        known = set(registry.names())
        unknown_tools = sorted(t for t in _tool_names_in(body) if t not in known)
        if unknown_tools:
            warnings.append("names tools this install doesn't have: " + ", ".join(unknown_tools[:12]))
    report = scan_text(" ".join(f.decode("utf-8", "replace") for p, f in files.items()
                                if not p.endswith((".png", ".jpg", ".gif", ".ttf", ".woff"))))
    if report.flagged:
        warnings.append("prompt-injection screen flagged this text: " + "; ".join(report.reasons))
    exists = bool(existing and name.lower() in existing)
    if exists:
        warnings.append(f"a skill named '{name}' is already installed — installing replaces it")
    return {
        "ok": not errors, "url": url, "name": name, "description": desc,
        "license": str(meta.get("license") or ""), "version": str(meta.get("version") or ""),
        "files": [{"path": p, "bytes": len(b)} for p, b in sorted(files.items())],
        "scripts": scripts, "inline_shell": inline[:10], "missing_commands": missing_cmds,
        "unknown_tools": unknown_tools, "screening": report.as_dict(), "exists": exists,
        "errors": errors, "warnings": warnings, "body_preview": body.strip()[:2000],
    }


def preview(url: str, registry=None, existing: Optional[set] = None) -> dict:
    try:
        files = fetch(url)
    except FetchError as exc:
        return {"ok": False, "url": url, "errors": [str(exc)], "warnings": []}
    _cache[url] = (time.time(), files)
    return analyse(files, url, registry, existing)


def install(url: str, user_dir: Path, registry=None, existing: Optional[set] = None,
            overwrite: bool = False) -> dict:
    """Write the skill under ``user_dir/<name>/`` (from the preview's cache when
    fresh) and return the analysis plus ``installed_to``. Caller disables it."""
    cached = _cache.get(url)
    try:
        files = cached[1] if cached and time.time() - cached[0] < _CACHE_TTL else fetch(url)
    except FetchError as exc:
        return {"ok": False, "url": url, "errors": [str(exc)], "warnings": []}
    info = analyse(files, url, registry, existing)
    if not info["ok"]:
        return info
    if info["exists"] and not overwrite:
        return {**info, "ok": False,
                "errors": [f"'{info['name']}' is already installed — confirm to replace it"]}
    target = Path(user_dir).expanduser() / info["name"]
    tmp = target.with_name(target.name + ".installing")
    if tmp.exists():
        shutil.rmtree(tmp)
    for rel, data in files.items():
        dest = tmp / _safe_rel(rel)
        if tmp.resolve() not in dest.resolve().parents:
            raise FetchError(f"unsafe path in skill: {rel!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    (tmp / SOURCE_FILE).write_text(json.dumps({
        "url": url, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "license": info["license"], "files": len(files)}, indent=1), encoding="utf-8")
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    _cache.pop(url, None)
    return {**info, "installed_to": str(target)}
