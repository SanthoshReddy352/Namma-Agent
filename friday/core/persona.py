"""Persona → system prompt for FRIDAY v2.

Ports the v1 YAML persona idea (kept — it's good): identity/tone/dos/donts live
in ``friday/personas/<id>.yaml`` and compose the system prompt. User facts and a
tool-usage/narration preamble are appended at build time.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from friday.core.logger import logger

# Built-in personas ship inside the package; user-created ones live in the home
# dir so they persist outside the repo and a user persona can override a built-in
# of the same id.
_PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"
_USER_PERSONA_DIR = Path("~/.friday/personas").expanduser()

# Behavioral preamble shared by all personas: how to call tools and narrate.
_AGENT_PREAMBLE = """\
You are a capable desktop agent. You have tools — use them to actually do things
rather than describing what you would do. Never claim a tool succeeded unless you
called it and saw its result. If a tool returns an error, say so plainly — do not
pretend it worked.

TOOL ROUTING — pick the RIGHT tool; do not improvise with the shell:
- To OPEN or LAUNCH anything — an app, a file, a folder, or a URL — ALWAYS call
  `open_app` with the target. NEVER use `run_shell` to open things (no `xdg-open`,
  `gio`, `nohup`, `&`, `start`, or `open`). `open_app` already handles apps, files,
  folders and URLs across platforms.
- To play a video or music, use the `play_youtube` / `play_youtube_music` /
  `open_browser_url` tools — never the shell.
- To create/move/copy/rename/delete files or organise a folder, use the file
  tools (`write_file`, `move_path`, `copy_path`, `delete_path`, `make_dir`,
  `find_files`, `organize_dir`) — never the shell for these.
- `run_shell` is ONLY for running a command whose TEXT OUTPUT you need to read and
  reason about (e.g. `git status`, `df -h`). It is NOT a launcher.
- Make ONE tool call per distinct action. If a tool fails, do not retry the same
  call repeatedly — report the failure and stop.
- When the user clearly wants to end the session (says bye, goodbye, exit, quit,
  close {name}, that's all, I'm done), call `exit_friday` to shut down cleanly.

SKILLS — you have procedural playbooks. If a request matches one of the skills in
AVAILABLE SKILLS below, call `use_skill` with its name FIRST to load the full
procedure, then follow it. After you solve a NOVEL multi-step task well (one with
no matching skill), call `create_skill` to save the procedure so you're better
next time; use `update_skill` to refine a skill that didn't go perfectly.

MEMORY — you keep durable memory across sessions. The moment the user states a
stable fact about themselves — their name, where they live or study, their job or
role, a strong preference, a relationship, a goal, or an ongoing project — call
`remember_fact` to save it (key + value) BEFORE moving on with the task. Save
free-form context (ongoing projects, decisions, how the user likes to work) with
`remember_note`, and refine the narrative user profile with `update_user_profile`.
To recall, use `recall_facts`, `read_memory`, `search_conversations`, or
`recall_sessions`. Save proactively — but never invent facts, and don't announce
routine saves.

When a task may take a moment, say a short, natural spoken line FIRST (in the same
turn as the tool call), e.g. "Sure, let me pull that up." Keep it human and brief
— no preamble like "Of course" or markdown. After tools run, answer directly.
"""

# Formatting rules — the chat UI renders proper markdown, so write clean markdown
# (NOT raw asterisks/hashes the user would see as literal symbols).
_FORMATTING = """\
FORMATTING — your replies are rendered as rich text, so format cleanly:
- For lists, use "- " bullets (or "1." for ordered steps); indent nested items by
  two spaces. Keep related/chained items grouped under one parent bullet.
- Use **bold** only for genuine emphasis and `code` for commands, paths, and code.
- Never emit stray, unmatched "*" or "#"/"###" characters, and never use markdown
  headings (#) in a normal reply. Don't show literal asterisks as decoration.
- Prefer short paragraphs and tight lists over walls of text. Use fenced code
  blocks (```) for multi-line code or terminal output.
- MATH & CHEMISTRY: write every formula in LaTeX so it renders properly — inline
  with single dollars ($E = mc^2$) and display/standalone with double dollars
  ($$\\int_0^1 x^2\\,dx$$). NEVER write math as plain text like "x^2" or "1/2"
  outside dollars. For chemistry use mhchem inside dollars: $\\ce{2H2 + O2 -> 2H2O}$,
  $\\ce{H2O}$, and $\\pu{3 mol}$ for quantities with units.
"""

# Temporal anchor — without this the model defaults to its training-cutoff year
# and types e.g. "...2025" into web searches, then trusts year-old results as the
# "latest". Recomputed every turn so the assistant always lives in the present.
def _temporal_block(now: Optional[datetime] = None) -> str:
    now = now or datetime.now().astimezone()
    tz = now.tzname() or ""
    stamp = now.strftime("%A, %d %B %Y, %H:%M")
    return (
        "CURRENT DATE & TIME — this is the present moment; treat it as ground truth:\n"
        f"  {stamp}{(' ' + tz) if tz else ''}.\n"
        "Your training data has a knowledge cutoff in the PAST, but the real world has "
        "moved on since then. You live in the present, not at your cutoff.\n"
        "- When the user asks about anything current — \"latest\", \"recent\", \"news\", "
        "\"today\", \"now\", \"what's new\" — anchor to the date above. Use the CURRENT "
        "year/month in web searches; never hard-code your training-cutoff year.\n"
        "- Always check the publication date of what a search returns. NEVER present "
        "months- or years-old information as if it were current.\n"
        "- If the freshest source you can find is still old, say so plainly rather than "
        "implying it is up to date."
    )


# Pure-conversation preamble for chat mode: no tools, no skills, no actions.
_CHAT_PREAMBLE = """\
You are in CHAT mode: a normal conversation. You have NO tools and take NO
actions — just talk, answer, explain, brainstorm. If something genuinely needs an
action (opening apps, files, web, playing media, running commands), tell the user
to switch to Agent mode for that.
"""


class Persona:
    def __init__(self, data: dict, display_name: Optional[str] = None):
        self.id = data.get("persona_id", "core")
        # The assistant's display name comes from config (single source of truth);
        # the persona YAML's `name` is only a fallback when none is provided.
        self.name = (display_name or data.get("name") or "FRIDAY").strip()
        self.identity = (data.get("identity") or "").strip()
        self.tone = data.get("tone", "")
        self.dos = data.get("dos") or []
        self.donts = data.get("donts") or []
        self.speech_style = data.get("speech_style", "")
        self.conversation_style = data.get("conversation_style", "")

    def system_prompt(
        self,
        facts: Optional[list[dict]] = None,
        skills_catalog: str = "",
        memory_block: str = "",
        nudge: str = "",
        chat_mode: bool = False,
    ) -> str:
        parts: list[str] = [self.identity or f"You are {self.name}."]
        # Anchor every turn to the real present so the assistant doesn't default to
        # its training-cutoff year when searching/answering about current events.
        parts.append(_temporal_block())
        if self.tone:
            parts.append(f"Tone: {self.tone}.")
        if self.dos:
            parts.append("Do:\n" + "\n".join(f"- {d}" for d in self.dos))
        if self.donts:
            parts.append("Don't:\n" + "\n".join(f"- {d}" for d in self.donts))
        parts.append(_CHAT_PREAMBLE if chat_mode else _AGENT_PREAMBLE)
        parts.append(_FORMATTING)
        if skills_catalog:
            parts.append("AVAILABLE SKILLS (load with use_skill before acting):\n" + skills_catalog)
        if memory_block:
            parts.append(memory_block)
        if facts:
            fact_lines = "\n".join(f"- {f['key']}: {f['value']}" for f in facts)
            parts.append(
                "USER_FACTS (these describe the USER, not you):\n" + fact_lines
            )
        if nudge:
            parts.append(nudge)
        prompt = "\n\n".join(p for p in parts if p).strip()
        # `{name}` placeholders (in persona YAML identity + the shared preamble)
        # resolve to the configured display name — rename in one place.
        return prompt.replace("{name}", self.name)


def _persona_dirs() -> list[Path]:
    """Search order: user personas (writable, override) then the built-ins."""
    return [_USER_PERSONA_DIR, _PERSONA_DIR]


def _persona_path(persona_id: str) -> Optional[Path]:
    for directory in _persona_dirs():
        candidate = directory / f"{persona_id}.yaml"
        if candidate.exists():
            return candidate
    return None


def load_persona(persona_id: str = "core", display_name: Optional[str] = None) -> Persona:
    path = _persona_path(persona_id)
    if path is None:
        logger.warning("[persona] %s not found, using minimal default", persona_id)
        return Persona({"persona_id": persona_id}, display_name=display_name)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("persona_id", persona_id)
    return Persona(data, display_name=display_name)


def slugify_persona_id(name: str) -> str:
    """A filesystem-safe persona id derived from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "persona"


def _identity_line(identity: str, display_name: str) -> str:
    """First sentence of an identity, name-substituted — the dropdown subtitle."""
    text = (identity or "").replace("{name}", display_name)
    text = " ".join(text.split())  # collapse newlines/whitespace
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0] if text else ""
    return first[:160]


def list_personas(display_name: str = "FRIDAY") -> list[dict]:
    """Every available persona (user + built-in) with a one-line identity, for the
    Settings dropdown. A user persona overrides a built-in sharing its id; the
    ``source`` field marks which ones the user can edit/delete."""
    out: list[dict] = []
    seen: set[str] = set()
    for directory in _persona_dirs():
        if not directory.exists():
            continue
        source = "user" if directory == _USER_PERSONA_DIR else "builtin"
        for path in sorted(directory.glob("*.yaml")):
            pid = path.stem
            if pid in seen:
                continue
            seen.add(pid)
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001 — skip an unreadable persona file
                continue
            raw_name = (data.get("name") or pid).strip()
            out.append({
                "id": pid,
                "name": raw_name.replace("{name}", display_name),
                "identity_line": _identity_line(data.get("identity", ""), display_name),
                "tone": (data.get("tone") or "").strip(),
                "source": source,
            })
    return out


def get_persona_spec(persona_id: str) -> Optional[dict]:
    """The full editable spec of one persona (identity, tone, dos, donts), for the
    Settings editor / 'view all instructions'. Returns None if it doesn't exist."""
    path = _persona_path(persona_id)
    if path is None:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        data = {}
    source = "user" if path.parent == _USER_PERSONA_DIR else "builtin"
    return {
        "id": persona_id,
        "name": (data.get("name") or persona_id).strip(),
        "identity": (data.get("identity") or "").strip(),
        "tone": (data.get("tone") or "").strip(),
        "dos": [str(x).strip() for x in (data.get("dos") or []) if str(x).strip()],
        "donts": [str(x).strip() for x in (data.get("donts") or []) if str(x).strip()],
        "source": source,
    }


# Fields a user persona may carry (mirrors the built-in YAML shape).
def save_persona(spec: dict) -> dict:
    """Write a user persona YAML to ``~/.friday/personas`` and return ``{id, name}``.

    ``spec`` needs at least ``name`` + ``identity``; ``tone`` and the ``dos`` /
    ``donts`` lists are optional (lists may also arrive as newline-separated text
    from the UI). The id is an explicit ``id`` or a slug of the name.
    """
    name = (spec.get("name") or "").strip()
    identity = (spec.get("identity") or "").strip()
    if not name or not identity:
        raise ValueError("a persona needs a name and an identity")

    pid = (spec.get("id") or "").strip() or slugify_persona_id(name)
    data: dict = {"persona_id": pid, "name": name, "identity": identity}
    for field in ("tone", "speech_style", "conversation_style"):
        value = str(spec.get(field) or "").strip()
        if value:
            data[field] = value
    for field in ("dos", "donts"):
        items = spec.get(field)
        if isinstance(items, str):
            items = [ln.strip("-•* \t") for ln in items.splitlines()]
        items = [str(x).strip() for x in (items or []) if str(x).strip()]
        if items:
            data[field] = items

    _USER_PERSONA_DIR.mkdir(parents=True, exist_ok=True)
    path = _USER_PERSONA_DIR / f"{pid}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logger.info("[persona] saved user persona %s", pid)
    return {"id": pid, "name": name}


def delete_user_persona(persona_id: str) -> bool:
    """Delete a user persona file (built-ins are never touched). Returns success."""
    path = _USER_PERSONA_DIR / f"{persona_id}.yaml"
    if path.exists():
        path.unlink()
        logger.info("[persona] deleted user persona %s", persona_id)
        return True
    return False
