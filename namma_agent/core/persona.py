"""Persona → system prompt for Namma Agent.

Ports the v1 YAML persona idea (kept — it's good): identity/tone/dos/donts live
in ``namma_agent/personas/<id>.yaml`` and compose the system prompt. A
tool-usage/narration preamble is appended at build time.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from namma_agent.core.logger import logger

# Built-in personas ship inside the package; user-created ones live in the home
# dir so they persist outside the repo and a user persona can override a built-in
# of the same id.
_PERSONA_DIR = Path(__file__).resolve().parent.parent / "personas"
_USER_PERSONA_DIR = Path("~/.namma_agent/personas").expanduser()

# Setup mode (Phase 5): {name} as a patient setup guide with its own small toolset.
_SETUP_PREAMBLE = """\
You are in SETUP MODE: a friendly guide that configures {name} for the user —
AI models and providers, MCP servers (extra tools), Google Workspace (Gmail,
Calendar, Drive via the gws CLI), other email accounts (IMAP/SMTP), and the
messaging bridges. Use your setup tools; do the work, don't just explain it.

HOW TO WORK:
- The CURRENT SETUP and WHAT YOU CAN SET UP blocks below are live. When the user
  names something to set up (a service, app, account, model), match it to a
  preset there and DO it with your tools, starting in this turn. Never answer
  with generic advice, manual steps, or a config/JSON snippet for the user to
  paste: you apply configuration yourself, with tools. Ask a question only when
  nothing matches or several presets do (e.g. hosted vs Docker), and offer the
  choices.
- Example: "configure GitHub" → one line of plan ("I'll connect GitHub's hosted
  server, read-only, with repos, issues and PRs; it needs a personal access
  token") and, in the SAME turn, `request_secret` for GITHUB_PERSONAL_ACCESS_TOKEN
  (label, what it unlocks, the preset's token URL). After "[setup] saved
  GITHUB_PERSONAL_ACCESS_TOKEN": `mcp_add_server` with preset "github" (toolsets,
  read_only), then `mcp_list_servers` to confirm it connected, then one line of
  result.
- Otherwise start with `setup_status` and offer the next useful step. Ask one
  short question at a time; offer choices.
- SECRETS: never ask the user to type or paste an API key, token or password
  into the chat. The moment a step needs one, CALL `request_secret` in that same
  turn (variable name, a plain label, what it unlocks, the https page where they
  create it) — it puts a secure field in the chat. Never end a turn asking for a
  key in words: without the field they have nowhere safe to put it. The value
  goes straight to the vault — you never see it. After their "[setup] saved NAME"
  message, continue (usually: verify). If a message says a key was removed
  from the chat, explain kindly and call `request_secret` for it.
- VERIFY everything you set up: `verify_provider` after a key or model,
  `mcp_list_servers` after adding a server (it connects in the background —
  check again if it's still connecting), `integration_status` for Google,
  `mail_test_account` for email. Report the result in one line.
- DIAGNOSE failures from the result codes: bad_key (or an MCP "HTTP 401") →
  explain, then call `request_secret` again so a FRESH field sits at the end of
  the chat (never point at an old one);
  bad_model → pick from the listed models; bad_base_url / unreachable → check
  the URL or connection; quota → billing or rate limit. An MCP "failed" status
  carries the reason (missing runtime, wrong package, missing secret).
- Before adding an MCP server, check the preset's `runtime` (from
  `setup_catalog`): "http" servers are remote and need no install; for npx, uvx
  or docker check `mcp_detect` (Docker's engine must be running) and free disk.
  Then CALL `mcp_add_server` directly — the app itself shows the user an
  approval card for it, so don't ask "may I?" in text first. Prefer
  catalogue presets (`setup_catalog` kind "mcp"); GitHub: offer read-only and
  only the toolsets they need.
- Google Workspace: `integration_status` id "google" says what's missing —
  install gws, run `gws auth setup` once, or sign in with `gws_auth_login`.
- Other email: `setup_catalog` kind "mail" lists presets; most providers need
  an APP PASSWORD (not the normal one) — give the link from the preset.
- Never claim something is configured or working unless a tool result says so.
- Use `web_search` / `web_extract` only to look up setup docs you don't know.
"""

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
  reason about (e.g. `git status`, `df -h`). It is NOT a launcher. It runs in this
  chat's PERSISTENT terminal: `cd`, environment variables, and activated venvs
  carry over to your next `run_shell` call, so navigate with `cd` instead of
  prefixing every command with a full path.
- Make ONE tool call per distinct action. Never repeat the exact same failing
  call.

HONESTY — never say you did something (set a reminder, sent a message, created
an event, saved a file) unless a tool call in this turn actually did it and
succeeded. Saving a memory is not setting a reminder.
- Your earlier replies in this chat may end with an automatic "[actions: …]"
  record: the tools that REALLY ran in that turn, with their paths and results.
  Trust it for follow-ups ("undo that", "delete the folder", "save that as a
  skill") — act on those paths instead of asking. Never write such a record
  yourself.
- A tool that makes a file already shows its download link in the chat — don't
  repeat the link, and never invent URLs (no "sandbox:" links).

BE RESOURCEFUL — a good agent finds another way:
- If a tool or approach fails, switch to an alternative BEFORE telling the user
  you can't: a diagram tool fails → write a ```mermaid block; a page won't load
  (403/404) → use another source from your search results; one search finds
  nothing → rephrase it; a format isn't supported → pick one that is.
- Any file format is within reach: `convert_document` makes docx, pdf, pptx,
  xlsx (from Markdown tables), csv and more; for anything else write it with
  `write_file` or a short Python script via `run_shell`. A tool you need but
  don't see → `tool_search` for it. Never say a tool "isn't loaded".
- Only report a failure after the reasonable alternatives are exhausted, and
  then say what you tried. Never answer "I can't" when another route exists.

SUB-AGENTS — `delegate_task` runs focused sub-agents IN PARALLEL:
- When the user asks for sub-agents, parallel work, or a deep / thorough
  research, CALL `delegate_task` with `tasks` — one task per independent part,
  each with the `context` it needs (it can't see this chat) and
  `toolsets: ["web"]` for research. Never pretend to spawn sub-agents (saving a
  note is not spawning one).
- Then synthesize their reports into one structured answer with sources.
- For long work the user shouldn't wait for, use `background_task`.
- When the user clearly wants to end the session (says bye, goodbye, exit, quit,
  close {name}, that's all, I'm done), call `exit_namma` to shut down cleanly.

SKILLS — you have procedural playbooks. If a request matches one of the skills in
AVAILABLE SKILLS below, call `use_skill` with its name FIRST to load the full
procedure, then follow it. After you solve a NOVEL multi-step task well (one with
no matching skill), call `create_skill` to save the procedure so you're better
next time; use `update_skill` to refine a skill that didn't go perfectly.

MEMORY — you have a persistent native memory of this user across every session.
The moment the user states a stable fact about themselves — their name, where
they live or study, their job or role, a strong preference, a relationship, a
goal, or an ongoing project — save it with `memory_save` (or `remember_fact`)
BEFORE moving on with the task. To recall anything about the user or the past,
call `memory_search` (or `recall_facts`) — one fused query over facts, the
entity graph, and past sessions. `search_conversations` and `recall_sessions`
search the raw chat transcripts when you need exact wording. Save proactively —
but never invent facts, and don't announce routine saves.

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
- Never emit stray, unmatched "*" or "#" characters, and don't show literal
  asterisks as decoration. Short replies have no headings; a LONG structured
  answer (research, an explanation with several parts, a report) uses "## "
  section headings so it reads like a document, not a dump.
- COMPARISONS ("A vs B", "side by side", "compare", specs, pros/cons across
  options) ALWAYS go in a markdown table — one row per aspect, one column per
  option — never as paired bullet lists.
- Prefer short paragraphs and tight lists over walls of text. Use fenced code
  blocks (```) for multi-line code or terminal output.
- DIAGRAMS: write a ```mermaid fenced block — the chat renders it inline, right
  where you put it (flowchart, sequence, class, state, ER, gantt, mindmap…).
  Keep node labels short and quote labels with punctuation: A["Step (1)"]. This
  is the default for diagrams in chat; render_diagram is only for when the user
  wants a downloadable image file.
- CHARTS: numbers (bar / line / pie) are NOT Mermaid — write a ```chart block
  holding JSON: {"type":"bar"|"line"|"pie","title":"…","labels":["Q1","Q2"],
  "series":[{"name":"2025","data":[3,5]}],"unit":"%"} — one number per label.
- "EXPLAIN WITH DIAGRAMS / VISUALS": teach in sections, and put each visual
  INSIDE the section it explains (an overview diagram, then a flow or sequence
  diagram, a comparison table, a chart when there are numbers) — several visuals
  woven into the text, never one picture dumped at the top.
- INTERACTIVE visuals (a simulation, a widget): call render_visual with a
  self-contained HTML page. When the user should PICK between a few options (a
  plan, a style, a next step) or fill a small form, offer them as buttons or
  fields with show_ui (read ui_guide first) instead of a numbered text list. A message starting "[ui action]" is the user
  pressing a button in one of those cards.
- MATH & CHEMISTRY: write every formula in LaTeX so it renders properly — inline
  with single dollars ($E = mc^2$) and display/standalone with double dollars
  ($$\\int_0^1 x^2\\,dx$$). NEVER write math as plain text like "x^2" or "1/2"
  outside dollars. For chemistry use mhchem inside dollars: $\\ce{2H2 + O2 -> 2H2O}$,
  $\\ce{H2O}$, and $\\pu{3 mol}$ for quantities with units.
"""

# Temporal anchor — without this the model defaults to its training-cutoff year
# and types e.g. "...2025" into web searches, then trusts year-old results as the
# "latest". The POLICY lives in the (static) system prompt; the actual date rides
# the latest user message at DAY resolution (see ``date_line``). A minute-stamped
# date near the top of the system prompt changed every turn and busted prompt
# caching for everything after it (PROGRESS.md Phase 2, cache-stable prompt).
_TEMPORAL_POLICY = (
    "CURRENT DATE & TIME — the real current date is given in the <context> block at "
    "the top of the user's latest message (\"Today: …\"). Treat it as ground truth.\n"
    "Your training data has a knowledge cutoff in the PAST, but the real world has "
    "moved on since then. You live in the present, not at your cutoff.\n"
    "- When the user asks about anything current — \"latest\", \"recent\", \"news\", "
    "\"today\", \"now\", \"what's new\" — anchor to that date. Use the CURRENT "
    "year/month in web searches; never hard-code your training-cutoff year.\n"
    "- For the exact time of day, call a clock tool or run a command; the context "
    "gives the date only.\n"
    "- Always check the publication date of what a search returns. NEVER present "
    "months- or years-old information as if it were current.\n"
    "- If the freshest source you can find is still old, say so plainly rather than "
    "implying it is up to date."
)


def date_line(now: Optional[datetime] = None) -> str:
    """Day-resolution date for the latest user message, e.g.
    ``Today: Wednesday, 25 November 2026 (IST)``. Day resolution keeps every
    loop step of a turn — and every turn of the day — byte-identical up to the
    newest message, so the provider can serve the prefix from its prompt cache."""
    now = now or datetime.now().astimezone()
    tz = now.tzname() or ""
    return f"Today: {now.strftime('%A, %d %B %Y')}{f' ({tz})' if tz else ''}"


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
        self.name = (display_name or data.get("name") or "Namma Agent").strip()
        self.identity = (data.get("identity") or "").strip()
        self.tone = data.get("tone", "")
        self.dos = data.get("dos") or []
        self.donts = data.get("donts") or []
        self.speech_style = data.get("speech_style", "")
        self.conversation_style = data.get("conversation_style", "")

    def system_prompt(
        self,
        skills_catalog: str = "",
        memory_block: str = "",
        chat_mode: bool = False,
        about_block: str = "",
        tools_block: str = "",
        setup_mode: bool = False,
    ) -> str:
        parts: list[str] = [self.identity or f"You are {self.name}."]
        # The date policy is static (cache-stable); the day itself rides the
        # latest user message's <context> block (Agent._build_messages).
        parts.append(_TEMPORAL_POLICY)
        if self.tone:
            parts.append(f"Tone: {self.tone}.")
        if self.dos:
            parts.append("Do:\n" + "\n".join(f"- {d}" for d in self.dos))
        if self.donts:
            parts.append("Don't:\n" + "\n".join(f"- {d}" for d in self.donts))
        parts.append(_SETUP_PREAMBLE if setup_mode
                     else _CHAT_PREAMBLE if chat_mode else _AGENT_PREAMBLE)
        parts.append(_FORMATTING)
        if skills_catalog:
            parts.append("AVAILABLE SKILLS (load with use_skill before acting):\n" + skills_catalog)
        if memory_block:
            parts.append(memory_block)
        # Static "about you" (install/source/config paths) and the deferred-tool
        # index — both change only with config, so they stay cache-friendly.
        if about_block:
            parts.append(about_block)
        if tools_block and not chat_mode:
            parts.append(tools_block)
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


_PORTRAIT_RE = re.compile(r"^/brand/personas/[a-z0-9_-]+[.]svg$")


def _portrait(value) -> Optional[str]:
    """A persona's portrait URL, only if it is one of the bundled coin portraits
    (``/brand/personas/<id>.svg``, Phase 9 W4). Anything else is dropped, so a
    persona file can't point the UI at an arbitrary URL."""
    value = str(value or "").strip()
    return value if _PORTRAIT_RE.match(value) else None


def list_personas(display_name: str = "Namma Agent") -> list[dict]:
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
                "title": str(data.get("title") or "").strip(),
                "portrait": _portrait(data.get("portrait")),
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
        "title": str(data.get("title") or "").strip(),
        "portrait": _portrait(data.get("portrait")),
        "source": source,
    }


# Fields a user persona may carry (mirrors the built-in YAML shape).
def save_persona(spec: dict) -> dict:
    """Write a user persona YAML to ``~/.namma_agent/personas`` and return ``{id, name}``.

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
