"""Checkpoints + rollback (Phase 7b) — undo what a turn did to your files.

The approval gate (Phase 1) asks *before* a destructive tool runs, which only
helps if you can predict the consequence. Rollback is the other half: it lets
you undo a change you already said yes to. An agent that can undo itself is a
stronger trust claim than one that merely asks nicely first.

**How it works.** Before any destructive tool from a write-ish toolset
(``file_ops`` / ``documents`` / ``authoring`` / ``convert`` — the same set that
arms the self-verification nudge) executes, the paths it is about to touch are
extracted from its arguments and snapshotted into
``data/checkpoints/<id>/``. Restoring puts them back.

Three entry kinds cover what the tools actually do:

``file``    the path existed and held content — the bytes are copied out, and
            restore writes them back.
``absent``  the path did not exist — the tool is creating it, so restore
            *deletes* it (undoing a ``write_file`` that created a new file).
``dir``     the path was a directory — its file tree is copied when it fits
            under the size cap (so ``delete_path`` on a folder is undoable);
            when it does not fit, only a manifest of relative paths is kept, and
            restore does what it can: files that were *moved* within the tree
            (the ``organize_dir`` case) are moved back, and anything genuinely
            gone is reported as unrestorable rather than silently skipped.

**Honest limits.** This is a snapshot of *paths named in tool arguments*, not a
filesystem journal. A shell command that rewrites a file is not covered (shell
is deliberately out of ``_WRITE_CATEGORIES``: its output already carries proof,
and snapshotting an arbitrary command's blast radius is not possible from its
arguments). Restoring is itself a write — it can fail on a locked file, and it
reports what it could not do instead of pretending.

Retention is bounded by age and total size (oldest pruned first), so a long
session cannot fill the disk. Everything is ``NAMMA_DATA_DIR``-aware (Phase 6a).
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from namma_agent.core.logger import logger

#: Toolsets whose destructive tools change files on disk. Deliberately the same
#: set the self-verification nudge uses (``core/agent.py:_VERIFY_CATEGORIES``):
#: shell and comms are excluded — their results carry their own proof, and a
#: shell command's targets cannot be read off its arguments.
WRITE_CATEGORIES = frozenset({"file_ops", "documents", "authoring", "convert"})

#: Argument names that carry a filesystem path in the write-ish tools
#: (``write_file.path``, ``move_path.source``/``dest``, ``delete_path.path``,
#: ``organize_dir.path``, ``convert_document.path``…). Matching is by name, not
#: by sniffing every string value — ``write_file.content`` must never be
#: mistaken for a path.
PATH_ARG_NAMES = frozenset({
    "path", "source", "src", "dest", "destination", "target",
    "file", "filename", "file_path", "output", "output_path", "out",
})


@dataclass
class Entry:
    """One saved path inside a checkpoint."""
    path: str            # absolute original path
    kind: str            # "file" | "absent" | "dir"
    stored: str = ""     # blob/dir name inside the checkpoint ("" when nothing saved)
    size: int = 0
    manifest: list[str] = field(default_factory=list)  # dir kind: relative file paths
    truncated: bool = False  # dir kind: too big to copy, manifest only


@dataclass
class Checkpoint:
    id: str
    session_id: str
    tool: str
    created_at: str
    entries: list[Entry] = field(default_factory=list)
    restored_at: str = ""

    def file_count(self) -> int:
        return len(self.entries)

    def summary(self) -> dict:
        """UI-facing row (no absolute-path dump beyond the entries themselves)."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool": self.tool,
            "created_at": self.created_at,
            "restored_at": self.restored_at,
            "entries": [
                {"path": e.path, "kind": e.kind, "size": e.size,
                 "truncated": e.truncated}
                for e in self.entries
            ],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def paths_at_risk(args: dict, schema: Optional[dict] = None) -> list[str]:
    """The filesystem paths a tool call is about to touch, read off its
    arguments by name (see :data:`PATH_ARG_NAMES`).

    ``schema`` (the tool's JSON Schema) narrows it further when available: only
    string-typed properties count, so a tool with an unrelated ``target``
    integer can't produce a bogus path.
    """
    props = ((schema or {}).get("properties") or {})
    out: list[str] = []
    for key, value in (args or {}).items():
        if key not in PATH_ARG_NAMES or not isinstance(value, str):
            continue
        declared = (props.get(key) or {}).get("type")
        if declared and declared != "string":
            continue
        candidate = value.strip()
        if not candidate or "\x00" in candidate:
            continue
        try:
            resolved = Path(candidate).expanduser().resolve()
        except (OSError, ValueError):
            continue
        text = str(resolved)
        if text not in out:
            out.append(text)
    return out


class CheckpointStore:
    """Snapshot/restore store rooted at ``data/checkpoints``."""

    def __init__(self, root: Path | str, *, max_file_mb: int = 32,
                 max_total_mb: int = 512, max_age_days: int = 14,
                 enabled: bool = True):
        # max_file_mb  — the largest single thing (file OR folder tree) copied.
        # max_total_mb — the RETENTION budget for the whole store.
        # Keeping them separate matters: a big folder should degrade to a
        # manifest, not silently evict every other restore point.
        self.root = Path(root)
        self.max_file_bytes = max(0, int(max_file_mb)) * 1024 * 1024
        self.max_total_bytes = max(0, int(max_total_mb)) * 1024 * 1024
        self.max_age_days = max(0, int(max_age_days))
        self.enabled = bool(enabled)

    # -- paths -------------------------------------------------------------

    def _dir(self, checkpoint_id: str) -> Path:
        return self.root / checkpoint_id

    def _manifest_path(self, checkpoint_id: str) -> Path:
        return self._dir(checkpoint_id) / "manifest.json"

    # -- writing -----------------------------------------------------------

    def snapshot(self, session_id: str, tool: str, args: dict,
                 schema: Optional[dict] = None) -> Optional[Checkpoint]:
        """Save the current state of everything ``tool(args)`` may change.

        Returns the :class:`Checkpoint`, or ``None`` when checkpointing is off
        or the call names no paths worth saving. Never raises into the caller —
        a failed snapshot must not block the tool the user approved.
        """
        if not self.enabled:
            return None
        try:
            targets = paths_at_risk(args, schema)
            if not targets:
                return None
            cp = Checkpoint(id=uuid.uuid4().hex[:12], session_id=session_id or "",
                            tool=tool, created_at=_now())
            dest_root = self._dir(cp.id)
            (dest_root / "files").mkdir(parents=True, exist_ok=True)
            for index, target in enumerate(targets):
                entry = self._save_one(Path(target), dest_root, index)
                if entry is not None:
                    cp.entries.append(entry)
            if not cp.entries:
                shutil.rmtree(dest_root, ignore_errors=True)
                return None
            self._write_manifest(cp)
            self.prune()
            logger.info("[checkpoint] %s saved %d path(s) before %s",
                        cp.id, len(cp.entries), tool)
            return cp
        except Exception as exc:  # noqa: BLE001 — never block an approved tool
            logger.warning("[checkpoint] snapshot failed for %s: %s", tool, exc)
            return None

    def _save_one(self, src: Path, dest_root: Path, index: int) -> Optional[Entry]:
        if not src.exists():
            # The tool is creating this path — restore means "delete it again".
            return Entry(path=str(src), kind="absent")

        if src.is_dir():
            manifest = []
            total = 0
            for item in src.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        continue
                    manifest.append(str(item.relative_to(src)))
            entry = Entry(path=str(src), kind="dir", size=total, manifest=manifest)
            if self.max_file_bytes and total > self.max_file_bytes:
                # Too big to copy — keep the manifest so moves within the tree
                # (organize_dir) are still undoable, and say so honestly.
                # NOTE: this is the COPY cap (max_file_mb, "the largest thing
                # we'll duplicate"), not the retention budget (max_total_mb).
                entry.truncated = True
                logger.info("[checkpoint] %s is %.0f MB — manifest only, no copy",
                            src, total / 1024 / 1024)
                return entry
            stored = f"files/{index}"
            shutil.copytree(src, dest_root / stored, dirs_exist_ok=True)
            entry.stored = stored
            return entry

        try:
            size = src.stat().st_size
        except OSError:
            return None
        if self.max_file_bytes and size > self.max_file_bytes:
            logger.info("[checkpoint] %s is %.0f MB — over the per-file cap, not saved",
                        src, size / 1024 / 1024)
            return Entry(path=str(src), kind="file", size=size, truncated=True)
        stored = f"files/{index}{src.suffix}"
        shutil.copy2(src, dest_root / stored)
        return Entry(path=str(src), kind="file", stored=stored, size=size)

    def _write_manifest(self, cp: Checkpoint) -> None:
        self._manifest_path(cp.id).write_text(
            json.dumps(asdict(cp), indent=2), encoding="utf-8")

    # -- reading -----------------------------------------------------------

    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        path = self._manifest_path(checkpoint_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        entries = [Entry(**e) for e in raw.get("entries", [])]
        return Checkpoint(id=raw.get("id", checkpoint_id),
                          session_id=raw.get("session_id", ""),
                          tool=raw.get("tool", ""),
                          created_at=raw.get("created_at", ""),
                          entries=entries,
                          restored_at=raw.get("restored_at", ""))

    def list(self, session_id: str = "", limit: int = 50) -> list[Checkpoint]:
        """Newest first. ``session_id`` filters to one chat."""
        out: list[Checkpoint] = []
        if not self.root.is_dir():
            return out
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            cp = self.load(child.name)
            if cp is None:
                continue
            if session_id and cp.session_id != session_id:
                continue
            out.append(cp)
        out.sort(key=lambda c: c.created_at, reverse=True)
        return out[:limit]

    # -- restoring ---------------------------------------------------------

    def restore(self, checkpoint_id: str) -> dict:
        """Put the snapshotted paths back. Reports exactly what changed and what
        could not be restored — a partial restore is never dressed up as a
        clean one."""
        cp = self.load(checkpoint_id)
        if cp is None:
            return {"ok": False, "error": f"no checkpoint {checkpoint_id!r}"}

        restored: list[str] = []
        deleted: list[str] = []
        failed: list[dict] = []
        root = self._dir(cp.id)

        for entry in cp.entries:
            target = Path(entry.path)
            try:
                if entry.kind == "absent":
                    # The tool created this — undo means remove it again.
                    if target.is_dir():
                        shutil.rmtree(target)
                        deleted.append(str(target))
                    elif target.exists():
                        target.unlink()
                        deleted.append(str(target))
                elif entry.kind == "file":
                    if entry.truncated or not entry.stored:
                        failed.append({"path": str(target),
                                       "why": "was too large to snapshot"})
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(root / entry.stored, target)
                    restored.append(str(target))
                elif entry.kind == "dir":
                    result = self._restore_dir(entry, root)
                    restored.extend(result["restored"])
                    failed.extend(result["failed"])
            except Exception as exc:  # noqa: BLE001 — report, don't abort the rest
                failed.append({"path": str(target), "why": str(exc)})

        cp.restored_at = _now()
        self._write_manifest(cp)
        return {
            "ok": not failed,
            "checkpoint": cp.id,
            "tool": cp.tool,
            "restored": restored,
            "deleted": deleted,
            "failed": failed,
        }

    def _restore_dir(self, entry: Entry, root: Path) -> dict:
        target = Path(entry.path)
        restored: list[str] = []
        failed: list[dict] = []

        if entry.stored and (root / entry.stored).is_dir():
            # Full copy available — put the tree back as it was.
            shutil.copytree(root / entry.stored, target, dirs_exist_ok=True)
            restored.append(str(target))
            return {"restored": restored, "failed": failed}

        # Manifest only. Undo what a manifest CAN undo: files that still exist
        # somewhere under the root but at a different relative path (the
        # organize_dir case — files moved into type subfolders) get moved back.
        if not target.is_dir():
            return {"restored": restored,
                    "failed": [{"path": str(target),
                                "why": "directory is gone and was too large to snapshot"}]}

        current = {}
        for item in target.rglob("*"):
            if item.is_file():
                current.setdefault(item.name, []).append(item)

        for relative in entry.manifest:
            want = target / relative
            if want.exists():
                continue
            candidates = current.get(Path(relative).name) or []
            moved = False
            for candidate in candidates:
                try:
                    want.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(candidate), str(want))
                    restored.append(str(want))
                    moved = True
                    break
                except OSError as exc:
                    failed.append({"path": str(want), "why": str(exc)})
                    moved = True
                    break
            if not moved:
                failed.append({"path": str(want), "why": "file not found under the folder"})
        return {"restored": restored, "failed": failed}

    # -- retention ---------------------------------------------------------

    def delete(self, checkpoint_id: str) -> bool:
        target = self._dir(checkpoint_id)
        if not target.is_dir():
            return False
        shutil.rmtree(target, ignore_errors=True)
        return True

    def total_bytes(self) -> int:
        if not self.root.is_dir():
            return 0
        total = 0
        for item in self.root.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total

    def prune(self) -> list[str]:
        """Drop checkpoints past the age limit, then oldest-first until the
        store fits the size budget. Returns the ids removed."""
        removed: list[str] = []
        entries = sorted(self.list(limit=10_000), key=lambda c: c.created_at)
        if self.max_age_days:
            cutoff = time.time() - self.max_age_days * 86400
            for cp in list(entries):
                try:
                    when = datetime.fromisoformat(cp.created_at).timestamp()
                except ValueError:
                    continue
                if when < cutoff:
                    self.delete(cp.id)
                    removed.append(cp.id)
                    entries.remove(cp)
        if self.max_total_bytes:
            while entries and self.total_bytes() > self.max_total_bytes:
                oldest = entries.pop(0)
                self.delete(oldest.id)
                removed.append(oldest.id)
        if removed:
            logger.info("[checkpoint] pruned %d old checkpoint(s)", len(removed))
        return removed

    def status(self) -> dict:
        """Row for the Status tab / ``background_status()``."""
        items = self.list(limit=10_000)
        return {
            "enabled": self.enabled,
            "count": len(items),
            "total_mb": round(self.total_bytes() / 1024 / 1024, 1),
            "max_total_mb": self.max_total_bytes // 1024 // 1024,
            "max_age_days": self.max_age_days,
            "last": items[0].created_at if items else "",
        }


def store_config(cfg: Optional[dict] = None) -> dict:
    """Parse the ``checkpoints`` config block (missing/partial → defaults)."""
    raw = (cfg or {}).get("checkpoints") or {}
    out = {"enabled": True, "max_file_mb": 32, "max_total_mb": 512, "max_age_days": 14}
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    for key in ("max_file_mb", "max_total_mb", "max_age_days"):
        try:
            out[key] = max(0, int(raw.get(key, out[key])))
        except (TypeError, ValueError):
            pass  # malformed value keeps the default
    return out


def build_store(config: Optional[dict] = None, root: Optional[Path] = None) -> CheckpointStore:
    """The store the service wires in (``data/checkpoints``, NAMMA_DATA_DIR-aware)."""
    from namma_agent.config import data_dir

    opts = store_config(config)
    return CheckpointStore(root or (data_dir() / "checkpoints"), **opts)


# ── model-facing tools ───────────────────────────────────────────────────────

def _describe(cp: Checkpoint) -> str:
    when = (cp.created_at or "").replace("T", " ")[:16]
    paths = ", ".join(Path(e.path).name for e in cp.entries[:4])
    more = f" +{len(cp.entries) - 4} more" if len(cp.entries) > 4 else ""
    return f"{cp.id} · {cp.tool} · {when} · {paths}{more}"


def register_checkpoint_tools(registry, store: CheckpointStore,
                              session_getter=None) -> None:
    """``list_checkpoints`` / ``rollback`` — "undo what you just did to my files"
    as a chat action. ``session_getter()`` returns the current session id so a
    bare ``rollback`` undoes THIS chat's last change, not some other chat's."""
    from namma_agent.core.tools import ToolResult

    def _current_session() -> str:
        try:
            return session_getter() if session_getter else ""
        except Exception:  # noqa: BLE001
            return ""

    def _list(args: dict) -> ToolResult:
        limit = max(1, min(int(args.get("limit") or 10), 50))
        scope = "" if args.get("all_chats") else _current_session()
        items = store.list(session_id=scope, limit=limit)
        if not items:
            return ToolResult(ok=True, content=(
                "No file checkpoints — nothing has been changed that I can undo."))
        lines = ["Restore points (newest first):"]
        lines += [f"  {_describe(cp)}" + (" · already restored" if cp.restored_at else "")
                  for cp in items]
        return ToolResult(ok=True, content="\n".join(lines),
                          data=[cp.summary() for cp in items])

    def _rollback(args: dict) -> ToolResult:
        checkpoint_id = (args.get("id") or "").strip()
        if not checkpoint_id:
            # No id given: undo the most recent change in THIS chat.
            recent = store.list(session_id=_current_session(), limit=1)
            if not recent:
                return ToolResult(ok=False, content="",
                                  error="nothing to undo in this chat")
            checkpoint_id = recent[0].id
        report = store.restore(checkpoint_id)
        if report.get("error"):
            return ToolResult(ok=False, content="", error=report["error"])
        parts = []
        if report["restored"]:
            parts.append(f"restored {len(report['restored'])} path(s)")
        if report["deleted"]:
            parts.append(f"removed {len(report['deleted'])} newly-created path(s)")
        if report["failed"]:
            parts.append(f"COULD NOT restore {len(report['failed'])}: " + "; ".join(
                f"{Path(f['path']).name} ({f['why']})" for f in report["failed"][:3]))
        summary = f"Rolled back {report['tool']} ({checkpoint_id}): " + (
            "; ".join(parts) or "nothing needed changing")
        return ToolResult(ok=report["ok"], content=summary,
                          error="" if report["ok"] else summary, data=report)

    registry.register(
        "list_checkpoints",
        ("List restore points — snapshots taken automatically before tools changed "
         "files this chat. Use before rollback so the user can pick one."),
        {"type": "object",
         "properties": {
             "limit": {"type": "integer", "description": "how many (1-50, default 10)"},
             "all_chats": {"type": "boolean",
                           "description": "include other chats' restore points"},
         }},
        _list)

    registry.register(
        "rollback",
        ("Undo a file change: restore the files as they were before a tool ran. "
         "With no id, undoes the most recent change in this chat. Use when the "
         "user says the change was wrong, or asks to undo/revert it."),
        {"type": "object",
         "properties": {"id": {"type": "string",
                               "description": "checkpoint id from list_checkpoints "
                                              "(omit for the most recent change)"}}},
        _rollback, destructive=True)
