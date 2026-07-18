"""L1 core memory — small, curated, ALWAYS in the system prompt.

Two bounded blocks (Hermes' MEMORY.md/USER.md pattern):

  * ``user``  — identity, preferences, people, standing instructions (~500 tokens)
  * ``agent`` — environment quirks, conventions, lessons learned      (~800 tokens)

Bounded on purpose: hard caps force curation, and a stable block keeps the system
prompt prefix-cache friendly. Edits go through ``add`` / ``replace`` / ``remove``
(substring matching for replace/remove), every write is injection-screened and
versioned, and each block is mirrored to a plain markdown file under
``data/memory/`` so the user can read and hand-edit their own memory — the mirror
is re-imported on startup when it is newer than the database.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from namma_agent.core.docscan import scan_text
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.logger import logger

#: chars ≈ tokens × 4 — budgets enforced in code, not by convention.
BLOCK_BUDGET_CHARS = {"user": 500 * 4, "agent": 800 * 4}
_MIRROR_NAME = {"user": "USER.md", "agent": "AGENT.md"}
_MIRROR_TITLE = {
    "user": "# USER — who the user is (identity, preferences, standing instructions)",
    "agent": "# AGENT — environment facts, conventions, lessons learned",
}


class CoreMemory:
    def __init__(self, store: EngramStore, data_dir: Optional[Path] = None):
        self.store = store
        self.dir = Path(data_dir) if data_dir else None
        if self.dir is not None:
            self._import_mirrors()

    # -- operations ----------------------------------------------------------

    def add(self, block: str, text: str) -> dict:
        block = self._block(block)
        text = " ".join((text or "").strip().split())
        if not text:
            return {"ok": False, "error": "nothing to remember"}
        report = scan_text(text)
        if report.flagged:
            return {"ok": False, "error": "entry rejected by injection screening: "
                                          + "; ".join(report.reasons)}
        entries = self.store.core_entries(block)
        if any(e["text"].lower() == text.lower() for e in entries):
            return {"ok": True, "note": "already known (exact duplicate skipped)",
                    **self.usage(block)}
        used = sum(len(e["text"]) + 3 for e in entries)
        if used + len(text) > BLOCK_BUDGET_CHARS[block]:
            return {"ok": False, "error":
                    f"core memory '{block}' is full ({self.usage(block)['pct']}%). "
                    f"Replace or remove an entry first (memory_save action=replace/"
                    f"remove), or store this as a regular fact instead."}
        self.store.core_add(block, text)
        self._write_mirror(block)
        return {"ok": True, **self.usage(block)}

    def replace(self, block: str, old_text: str, text: str) -> dict:
        block = self._block(block)
        entry = self._find(block, old_text)
        if entry is None:
            return {"ok": False, "error": f"no '{block}' entry matches {old_text!r}"}
        text = " ".join((text or "").strip().split())
        if not text:
            return {"ok": False, "error": "replacement text is empty (use remove)"}
        report = scan_text(text)
        if report.flagged:
            return {"ok": False, "error": "entry rejected by injection screening: "
                                          + "; ".join(report.reasons)}
        others = sum(len(e["text"]) + 3 for e in self.store.core_entries(block)
                     if e["id"] != entry["id"])
        if others + len(text) > BLOCK_BUDGET_CHARS[block]:
            return {"ok": False, "error": f"replacement would overflow the '{block}' "
                                          f"budget — make it denser"}
        self.store.core_update(entry["id"], text)
        self._write_mirror(block)
        return {"ok": True, **self.usage(block)}

    def remove(self, block: str, old_text: str) -> dict:
        block = self._block(block)
        entry = self._find(block, old_text)
        if entry is None:
            return {"ok": False, "error": f"no '{block}' entry matches {old_text!r}"}
        self.store.core_remove(entry["id"])
        self._write_mirror(block)
        return {"ok": True, **self.usage(block)}

    # -- rendering -------------------------------------------------------------

    def usage(self, block: str) -> dict:
        block = self._block(block)
        used = sum(len(e["text"]) + 3 for e in self.store.core_entries(block))
        budget = BLOCK_BUDGET_CHARS[block]
        return {"block": block, "used_chars": used, "budget_chars": budget,
                "pct": min(100, round(100 * used / budget))}

    def render(self) -> str:
        """The prompt block injected into EVERY turn (chat mode included). Stable
        ordering keeps the prefix cacheable; the usage %% nudges curation."""
        sections = []
        for block, title in (("user", "ABOUT THE USER"), ("agent", "AGENT NOTES")):
            entries = self.store.core_entries(block)
            if not entries:
                continue
            pct = self.usage(block)["pct"]
            body = "\n".join(f"- {e['text']}" for e in entries)
            sections.append(f"{title} (core memory, {pct}% full):\n{body}")
        if not sections:
            return ""
        return ("CORE MEMORY — curated durable memory, always current. Treat as "
                "true unless the user corrects it; when they do, update it with "
                "memory_save.\n" + "\n\n".join(sections))

    # -- mirrors (transparency: memory as readable/editable markdown) -----------

    def _mirror_path(self, block: str) -> Optional[Path]:
        return (self.dir / _MIRROR_NAME[block]) if self.dir is not None else None

    def _write_mirror(self, block: str) -> None:
        p = self._mirror_path(block)
        if p is None:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            lines = [_MIRROR_TITLE[block], ""]
            lines += [f"- {e['text']}" for e in self.store.core_entries(block)]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("[engram] core-memory mirror write failed: %s", exc)

    def _import_mirrors(self) -> None:
        """Hand-edits win: if a mirror file changed after the DB did, its bullet
        lines become the block's entries (screened, budget-truncated)."""
        for block in ("user", "agent"):
            p = self._mirror_path(block)
            if p is None or not p.exists():
                continue
            entries = self.store.core_entries(block)
            newest = max((e["updated_at"] for e in entries), default="")
            try:
                from datetime import datetime, timezone
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
                if newest and mtime <= newest:
                    continue
                lines = [ln[2:].strip() for ln in p.read_text(encoding="utf-8").splitlines()
                         if ln.startswith("- ")]
            except OSError:
                continue
            current = [e["text"] for e in entries]
            if lines == current:
                continue
            for e in entries:
                self.store.core_remove(e["id"])
            used = 0
            for text in lines:
                if scan_text(text).flagged:
                    continue
                if used + len(text) + 3 > BLOCK_BUDGET_CHARS[block]:
                    break
                self.store.core_add(block, text)
                used += len(text) + 3
            logger.info("[engram] imported hand-edited %s mirror (%d entries)",
                        _MIRROR_NAME[block], len(lines))

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _block(block: str) -> str:
        b = (block or "user").strip().lower()
        return b if b in BLOCK_BUDGET_CHARS else "user"

    def _find(self, block: str, needle: str) -> Optional[dict]:
        needle = (needle or "").strip().lower()
        if not needle:
            return None
        for e in self.store.core_entries(block):
            if needle in e["text"].lower():
                return e
        return None
