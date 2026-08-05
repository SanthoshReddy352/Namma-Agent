"""Skill system — procedural memory in the Anthropic *Agent Skills* format.

Ported from NousResearch/hermes-agent (agentskills.io-compatible). A *skill* is a
folder containing a ``SKILL.md`` file:

    ---
    name: deep-research
    description: When the user asks to research a topic in depth, do X, Y, Z…
    platforms: [linux, macos, windows]
    category: research
    metadata:
      hermes:
        tags: [research, web]
    ---
    # Deep Research
    ## When to Use
    ## Procedure
    ## Verification

Skills live under two roots:

  * **bundled** — ``namma_agent/skills/`` (ships with Namma Agent)
  * **user / learned** — ``~/.namma_agent/skills/`` (where ``create_skill`` writes;
    this is the "learning loop": the agent saves a procedure after solving a
    novel multi-step task, and refines it later with ``update_skill``)

The *catalog* (name + one-line description) is injected into the system prompt so
the model knows what's available; calling ``use_skill`` returns the full,
preprocessed body to follow. Preprocessing supports ``${SKILL_DIR}`` /
``${SESSION_ID}`` template vars and inline-shell ``!`cmd``` expansion (capped,
opt-in), matching hermes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from namma_agent.core.logger import logger

# Directories never scanned for skills (VCS / caches / venvs).
_EXCLUDED_DIRS = frozenset({
    ".git", ".github", ".venv", "venv", "node_modules", "site-packages",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".archive",
})

_BUNDLED_DIR = Path(__file__).resolve().parent.parent / "skills"

_PLATFORM = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")

_TEMPLATE_RE = re.compile(r"\$\{(SKILL_DIR|SESSION_ID)\}")
_INLINE_SHELL_RE = re.compile(r"!`([^`\n]+)`")
_INLINE_SHELL_MAX = 4000
_INLINE_SHELL_TIMEOUT = 15

# ── duplicate detection ─────────────────────────────────────────────────────
#
# Every path that writes a skill (self-review proposals, consolidator drafts,
# post-turn capture) used to dedup on the exact slug, so a drafter that renamed
# the same procedure walked straight in and the catalog grew two skills for one
# job — "windows-safe-shell" came back as "robust-windows-shell" (whose own body
# says to refer to the first), "delegate-task-completion" as "Robust Task
# Delegation".
#
# Word overlap alone cannot catch that second pair: measured over the real
# catalog, the best lexical metric separated the known duplicates from unrelated
# skills by 0.03 — noise, not a threshold. Embeddings do separate them (the two
# duplicate pairs scored 0.79 and 0.61 cosine with all-minilm; the closest
# unrelated pair, 0.36), so the semantic channel decides when it is up and a
# deliberately narrow lexical rule covers the offline case.

# Words that appear in nearly every skill description ("Use this when…") and
# would inflate the overlap between two unrelated skills.
_STOPWORDS = frozenset({
    "the", "and", "for", "use", "used", "when", "with", "this", "that", "from",
    "into", "user", "users", "assistant", "skill", "skills", "using", "should",
    "step", "steps", "procedure", "procedures", "task", "tasks", "how", "you",
    "your", "its", "are", "not", "any", "all", "via", "per", "new", "provide",
    "provides", "ensure", "ensures", "proper", "built", "particularly",
    "effectively", "framework", "mechanism", "mechanisms", "improve",
})
# Crude suffix stripping so "command"/"commands" and "delegate"/"delegation"
# compare equal. Not a real stemmer — just enough to stop plurals from splitting
# a word into two tokens.
_SUFFIXES = ("ations", "ation", "tions", "tion", "sions", "sion", "ances",
             "ance", "ences", "ence", "ings", "ing", "ers", "er", "ies", "ied",
             "es", "ed", "ly", "s")

#: Cosine above which two skill blurbs are the same skill. Sits in the middle of
#: the measured gap (duplicates ≥ 0.61, closest unrelated pair 0.36).
SEMANTIC_THRESHOLD = 0.5
#: Offline fallback — BOTH must hold, because with no semantic channel a false
#: positive silently swallows a genuinely new skill.
LEXICAL_NAME_THRESHOLD = 0.5
LEXICAL_DESC_THRESHOLD = 0.3
#: Plain text overlap, used where there is nothing to embed (proposal titles).
DEDUP_THRESHOLD = 0.45


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word


def _tokens(text: str) -> set[str]:
    """Content words of a name/description, for overlap comparison."""
    return {_stem(w) for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower())
            if w not in _STOPWORDS}


def _overlap(a: set[str], b: set[str]) -> float:
    """Overlap coefficient — |a∩b| / |smaller|. Kinder than Jaccard when one
    description is much wordier than the other, which is the normal case."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def texts_overlap(a: str, b: str, threshold: float = DEDUP_THRESHOLD) -> bool:
    """Jaccard overlap of two blurbs. Used for proposal-vs-proposal titles, where
    there is no catalog to embed against."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def lexical_duplicate(name_a: str, desc_a: str, name_b: str, desc_b: str) -> bool:
    """Offline duplicate test: the names must clearly overlap AND the
    descriptions must agree. Requiring both keeps it high-precision — it catches
    the "windows-safe-shell"/"robust-windows-shell" kind of rename and lets a
    merely adjacent skill through rather than suppressing it."""
    return (_overlap(_tokens(name_a), _tokens(name_b)) >= LEXICAL_NAME_THRESHOLD
            and _overlap(_tokens(desc_a), _tokens(desc_b)) >= LEXICAL_DESC_THRESHOLD)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    directory: Path
    platforms: list[str] = field(default_factory=list)
    category: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "bundled"  # bundled | user
    # Prerequisites declared in frontmatter (hermes format): external CLIs the
    # skill drives and env vars it needs. Used to compute `supported`/`missing`.
    requires_commands: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    enabled: bool = True  # set by the store from the persisted disabled-set

    def one_line(self, width: int = 200) -> str:
        desc = " ".join(self.description.split())
        return desc if len(desc) <= width else desc[: width - 1] + "…"

    # -- support / requirements ------------------------------------------------

    def missing(self) -> list[str]:
        """Unmet prerequisites: CLIs not on PATH + env vars not set. Empty ⇒ ready."""
        gaps: list[str] = []
        for cmd in self.requires_commands:
            if not shutil.which(cmd):
                gaps.append(f"`{cmd}` (command not found)")
        for var in self.requires_env:
            if not os.environ.get(var):
                gaps.append(f"${var} (env var not set)")
        return gaps

    @property
    def supported(self) -> bool:
        """True when every declared prerequisite is satisfied on this machine."""
        return not self.missing()

    def requires_text(self) -> list[str]:
        """Human-readable requirement labels for the UI (always shown, met or not)."""
        return [f"`{c}`" for c in self.requires_commands] + [f"${v}" for v in self.requires_env]

    @property
    def is_draft(self) -> bool:
        """A skill the assistant *proposed* — written by the consolidator's
        reflection step or post-turn capture, created disabled and waiting in the
        Skills tab's review queue. Never a self-granted capability."""
        return (self.category.strip().lower() == "draft"
                or "draft" in [t.strip().lower() for t in self.tags])

    def blurb(self) -> str:
        """Name + description — what duplicate detection compares."""
        return f"{self.name} {self.description}"


# ── Frontmatter parsing (ported from hermes skill_utils.parse_frontmatter) ──

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split ``---`` YAML frontmatter from the markdown body."""
    if not content.startswith("---"):
        return {}, content
    end = re.search(r"\n---\s*\n", content[3:])
    if not end:
        return {}, content
    raw = content[3 : end.start() + 3]
    body = content[end.end() + 3 :]
    try:
        parsed = yaml.safe_load(raw)
        return (parsed if isinstance(parsed, dict) else {}), body
    except Exception:  # noqa: BLE001 — tolerate malformed YAML
        fm: dict = {}
        for line in raw.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        return fm, body


# ── Preprocessing (template vars + inline shell) ────────────────────────────

def _substitute_vars(text: str, skill_dir: Path, session_id: Optional[str]) -> str:
    def repl(m: re.Match) -> str:
        tok = m.group(1)
        if tok == "SKILL_DIR":
            return str(skill_dir)
        if tok == "SESSION_ID" and session_id:
            return str(session_id)
        return m.group(0)
    return _TEMPLATE_RE.sub(repl, text)


def _expand_inline_shell(text: str, cwd: Path) -> str:
    if "!`" not in text:
        return text

    def repl(m: re.Match) -> str:
        cmd = m.group(1).strip()
        if not cmd:
            return ""
        try:
            proc = subprocess.run(
                ["bash", "-c", cmd], cwd=str(cwd), capture_output=True, text=True,
                timeout=_INLINE_SHELL_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired:
            return f"[inline-shell timeout: {cmd}]"
        except Exception as exc:  # noqa: BLE001
            return f"[inline-shell error: {exc}]"
        out = (proc.stdout or "").rstrip("\n") or (proc.stderr or "").rstrip("\n")
        return out[:_INLINE_SHELL_MAX] + ("…[truncated]" if len(out) > _INLINE_SHELL_MAX else "")

    return _INLINE_SHELL_RE.sub(repl, text)


# ── Store ───────────────────────────────────────────────────────────────────

class SkillStore:
    """Discovers, renders, and authors skills across bundled + user roots."""

    def __init__(
        self,
        user_dir: Optional[Path] = None,
        *,
        allow_inline_shell: bool = False,
        extra_dirs: Optional[list[Path]] = None,
        disabled: Optional[list[str]] = None,
        embedder=None,
    ):
        self.user_dir = Path(user_dir or "~/.namma_agent/skills").expanduser()
        self.allow_inline_shell = allow_inline_shell
        # Optional Engram embedder — the semantic half of duplicate detection.
        # None (or an unreachable endpoint) degrades to the lexical rule.
        self._embedder = embedder
        # Names the user turned off in the Skills tab — excluded from the agent's
        # catalog and refused by use_skill, but still listed in the UI so they can
        # be re-enabled. Persisted by the caller (config.local.yaml: skills.disabled).
        self._disabled: set[str] = {str(n).strip().lower() for n in (disabled or [])}
        # Later roots win on name collisions, so user/learned skills override bundled.
        self._roots: list[Path] = [_BUNDLED_DIR, *(extra_dirs or []), self.user_dir]
        self._skills: dict[str, Skill] = {}
        self.reload()

    # -- discovery ---------------------------------------------------------

    def reload(self) -> None:
        found: dict[str, Skill] = {}
        for root in self._roots:
            if not root.exists():
                continue
            source = "user" if root == self.user_dir else "bundled"
            for md in root.rglob("SKILL.md"):
                if any(part in _EXCLUDED_DIRS for part in md.parts):
                    continue
                skill = self._load_one(md, source)
                if skill and self._for_this_platform(skill):
                    skill.enabled = skill.name.strip().lower() not in self._disabled
                    found[skill.name] = skill
        self._skills = found
        logger.debug("[skills] discovered %d skill(s)", len(found))

    @staticmethod
    def _for_this_platform(skill: Skill) -> bool:
        return not skill.platforms or _PLATFORM in skill.platforms

    def _load_one(self, md: Path, source: str) -> Optional[Skill]:
        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("[skills] cannot read %s: %s", md, exc)
            return None
        fm, body = parse_frontmatter(content)
        name = str(fm.get("name") or md.parent.name).strip()
        if not name:
            return None
        meta = fm.get("metadata") or {}
        hermes = (meta.get("hermes") or {}) if isinstance(meta, dict) else {}
        tags = hermes.get("tags") or fm.get("tags") or []
        platforms = fm.get("platforms") or []
        prereq = fm.get("prerequisites") or {}
        cmds = prereq.get("commands") if isinstance(prereq, dict) else []
        envs = prereq.get("env_vars") if isinstance(prereq, dict) else []
        return Skill(
            name=name,
            description=str(fm.get("description") or "").strip(),
            body=body.strip(),
            directory=md.parent,
            platforms=[str(p).lower() for p in platforms] if isinstance(platforms, list) else [],
            category=str(fm.get("category") or "").strip(),
            tags=[str(t) for t in tags] if isinstance(tags, list) else [],
            source=source,
            requires_commands=[str(c) for c in cmds] if isinstance(cmds, list) else [],
            requires_env=[str(v) for v in envs] if isinstance(envs, list) else [],
        )

    # -- access ------------------------------------------------------------

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name) or self._skills.get(name.strip().lower())

    def drafts(self) -> list[Skill]:
        """Proposed-but-not-approved skills — the Skills tab's review queue."""
        return [s for s in self.all() if s.is_draft]

    def _semantic_match(self, blurb: str, candidates: list[Skill],
                        threshold: float) -> tuple[Optional[Skill], bool]:
        """``(best match or None, whether the embedding channel answered)``.

        The second flag matters: "no match" and "embeddings are down" must not
        look the same to the caller, or a dead Ollama would silently turn
        duplicate detection off."""
        emb = self._embedder
        if emb is None or not emb.available():
            return None, False
        vecs = emb.embed([blurb] + [s.blurb() for s in candidates])
        if not vecs or len(vecs) != len(candidates) + 1:
            return None, False
        from namma_agent.core.engram.embeddings import cosine

        best, best_score = None, 0.0
        for skill, vec in zip(candidates, vecs[1:]):
            score = cosine(vecs[0], vec)
            if score > best_score:
                best, best_score = skill, score
        return (best if best_score >= threshold else None), True

    def find_similar(self, name: str, description: str = "",
                     threshold: float = SEMANTIC_THRESHOLD) -> Optional[Skill]:
        """The existing skill that already covers this name/description, if any.

        Every path that creates a skill (self-review proposals, consolidator
        drafts, post-turn capture) checks here first. Exact slug, then meaning,
        then — only when there is no embedding channel — word overlap."""
        exact = self.get(self._slug(name))
        if exact is not None:
            return exact
        candidates = self.all()
        if not candidates:
            return None
        hit, decided = self._semantic_match(f"{name} {description}".strip(),
                                            candidates, threshold)
        if decided:
            return hit          # the semantic channel answered; trust it
        for skill in candidates:
            if lexical_duplicate(name, description, skill.name, skill.description):
                return skill
        return None

    def catalog_text(self, limit: int = 250) -> str:
        """Skill catalog for the agent's system prompt. Only skills the user has
        left **enabled** and whose prerequisites are **satisfied** here are shown —
        no point advertising a Notion skill when ``$NOTION_API_KEY`` isn't set."""
        skills = [s for s in self.all() if s.enabled and s.supported][:limit]
        if not skills:
            return ""
        lines = [f"- {s.name}: {s.one_line(160)}" for s in skills]
        return "\n".join(lines)

    def set_enabled(self, name: str, enabled: bool) -> Optional[Skill]:
        """Turn a skill on/off in memory and return it. Persistence (the
        ``skills.disabled`` list in config) is the caller's job."""
        skill = self.get(name)
        if not skill:
            return None
        key = skill.name.strip().lower()
        if enabled:
            self._disabled.discard(key)
        else:
            self._disabled.add(key)
        skill.enabled = enabled
        return skill

    def disabled_names(self) -> list[str]:
        """The current disabled-set, sorted — what the caller persists to config."""
        return sorted(self._disabled)

    def render(self, name: str, session_id: Optional[str] = None) -> Optional[str]:
        skill = self.get(name)
        if not skill or not skill.enabled:
            return None
        text = _substitute_vars(skill.body, skill.directory, session_id)
        if self.allow_inline_shell:
            text = _expand_inline_shell(text, skill.directory)
        header = f"# Skill: {skill.name}\n"
        return header + text

    # -- authoring (the learning loop) -------------------------------------

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
        return slug or "skill"

    def create(
        self, name: str, description: str, body: str,
        category: str = "", tags: Optional[list[str]] = None,
    ) -> Skill:
        slug = self._slug(name)
        skill_dir = self.user_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        fm = {
            "name": slug,
            "description": description.strip(),
            "platforms": ["linux", "macos", "windows"],
            "version": "1.0.0",
            "category": category.strip() or "general",
            "metadata": {"hermes": {"tags": tags or []}},
        }
        front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
        md = f"---\n{front}\n---\n\n{body.strip()}\n"
        (skill_dir / "SKILL.md").write_text(md, encoding="utf-8")
        self.reload()
        return self._skills[slug]

    def delete(self, name: str) -> tuple[bool, str]:
        """Remove a LEARNED skill from disk (the review queue's "discard").

        Bundled skills ship with the app and are only ever turned off, never
        deleted — a user who discards one could not get it back."""
        skill = self.get(name)
        if skill is None:
            return False, f"no skill named {name!r}"
        if skill.source != "user":
            return False, (f"{skill.name!r} is a bundled skill — turn it off "
                           "instead of deleting it")
        try:
            shutil.rmtree(skill.directory)
        except OSError as exc:
            return False, f"could not delete {skill.name!r}: {exc}"
        # Drop it from the disabled-set too (drafts live there): a later skill of
        # the same name must not come back silently switched off.
        self._disabled.discard(skill.name.strip().lower())
        self.reload()
        return True, f"deleted skill {skill.name!r}"

    def update(self, name: str, body: Optional[str] = None,
               description: Optional[str] = None) -> Optional[Skill]:
        skill = self.get(name)
        if not skill:
            return None
        md_path = skill.directory / "SKILL.md"
        content = md_path.read_text(encoding="utf-8", errors="replace")
        fm, old_body = parse_frontmatter(content)
        if description is not None:
            fm["description"] = description.strip()
        new_body = (body if body is not None else old_body).strip()
        front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
        md_path.write_text(f"---\n{front}\n---\n\n{new_body}\n", encoding="utf-8")
        self.reload()
        return self.get(skill.name)
