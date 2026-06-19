"""Persona → system prompt for FRIDAY v2.

Ports the v1 YAML persona idea (kept — it's good): identity/tone/dos/donts live
in ``friday/personas/<id>.yaml`` and compose the system prompt. User facts and a
tool-usage/narration preamble are appended at build time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from friday.core.logger import logger

_PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"

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

MEMORY — you keep durable memory across sessions. Save a single structured fact
with `remember_fact`; save free-form context (ongoing projects, decisions, how the
user likes to work) with `remember_note`; refine the narrative user profile with
`update_user_profile`. To recall, use `recall_facts`, `read_memory`,
`search_conversations`, or `recall_sessions`. Save proactively when you learn
something durable — but never invent facts, and don't announce routine saves.

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

# Pure-conversation preamble for chat mode: no tools, no skills, no actions.
_CHAT_PREAMBLE = """\
You are in CHAT mode: a normal conversation. You have NO tools and take NO
actions — just talk, answer, explain, brainstorm. If something genuinely needs an
action (opening apps, files, web, playing media, running commands), tell the user
to switch to Agent mode for that.
"""


class Persona:
    def __init__(self, data: dict, display_name: Optional[str] = None):
        self.id = data.get("persona_id", "friday_core")
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


def load_persona(persona_id: str = "friday_core", display_name: Optional[str] = None) -> Persona:
    path = _PERSONA_DIR / f"{persona_id}.yaml"
    if not path.exists():
        logger.warning("[persona] %s not found, using minimal default", persona_id)
        return Persona({"persona_id": persona_id}, display_name=display_name)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Persona(data, display_name=display_name)
