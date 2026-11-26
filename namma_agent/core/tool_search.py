"""Tool search — how the tool list scales (PROGRESS.md Phase 2, decision log).

Sending every tool schema on every model call cost ~10–11K tokens per request
at ~113 tools, OpenAI hard-fails past 128 tools, and selection accuracy drops
well before that. Instead, a turn sends a small, fixed set of **core** tools
plus three meta-tools, and the rest are **deferred**:

* ``tool_search(query)`` — keyword search over the deferred tools; the best
  matches come back *with their parameter schemas*, so one search is enough to
  call one.
* ``tool_describe(names)`` — full schemas for exact tool names.
* ``tool_call(name, arguments)`` — run a deferred tool. The agent loop unwraps
  it and runs the inner tool through the normal path: approval gate,
  checkpoint, audit log, media placement, verification nudge.

The sent list depends only on config and the session's scope — never on the
conversation — so it is identical on every request of a chat and the provider
can serve it from the prompt cache. A short index of deferred tool names, grouped
by toolset, rides the (equally static) system prompt so the model knows what
exists before it searches.

Config (``tools.search`` in config.yaml)::

    tools:
      search:
        mode: auto        # auto | always | off
        threshold: 40     # auto: defer only when more tools than this are exposed
        core: [...]       # always-loaded tool names (defaults: DEFAULT_CORE)
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

#: Tools that are always loaded: the everyday hands of the agent. Anything
#: here that the turn doesn't expose (disabled, scoped out) is simply skipped.
DEFAULT_CORE: tuple[str, ...] = (
    "run_shell", "read_file", "write_file", "list_dir", "find_files",
    "open_app", "web_search", "web_extract",
    "memory_search", "memory_save",
    "update_todos", "use_skill",
    # Live runs (2026-11-25, gpt-4.1-mini): small models essentially never call
    # tool_search, so anything deferred is invisible to them — asked to "spawn
    # sub-agents" it faked it with memory_save, asked for a reminder it saved a
    # memory and claimed success, asked for the weather it scraped the web. The
    # everyday ACTION tools therefore stay loaded; only niche ones are deferred.
    "delegate_task", "background_task", "check_background_task",
    "render_visual", "show_ui", "ui_guide", "fetch_image",
    "get_weather", "get_news", "read_document", "convert_document",
    "make_dir", "move_path", "copy_path", "delete_path", "organize_dir",
    "list_checkpoints", "rollback", "create_skill",
    "add_reminder", "list_reminders", "add_task", "list_tasks",
    "open_browser_url", "play_youtube", "send_notification",
    "search_conversations", "system_info",
    "about_namma", "exit_namma",
)

META_TOOLS = ("tool_search", "tool_describe", "tool_call")

# Toolset profiles: one-click presets (Settings → Toolsets, ``tools.profile``)
# mapping to the toolsets (tool categories) a profile exposes. ``general`` =
# everything enabled. A model profile's ``tools_allow`` and an explicit global
# ``tools.allow`` both win over the preset. "general" is always included: it
# holds uncategorized essentials such as exit_namma.
_BASE = ("general", "file_ops", "shell", "memory", "todo", "skills", "selfdoc")
PROFILES: dict[str, dict] = {
    "general": {"label": "General", "hint": "Every enabled tool.", "categories": None},
    "productivity": {
        "label": "Productivity",
        "hint": "Files, docs, mail and calendar, tasks, reminders, messaging, web.",
        "categories": _BASE + ("documents", "convert", "web", "browser", "apps", "gws",
                               "comms", "scheduler", "tasks", "goals", "focus", "routines",
                               "watchers", "weather", "news", "send_file", "vision",
                               "system", "learning_media", "agent"),
    },
    "code": {
        "label": "Code",
        "hint": "Files, shell, web docs, checkpoints, sub-agents, network checks.",
        "categories": _BASE + ("web", "documents", "convert", "checkpoints", "agent",
                               "authoring", "system", "network", "learning_media", "mcp"),
    },
    "research": {
        "label": "Research",
        "hint": "Web search and reading, documents, browser, diagrams, sub-agents.",
        "categories": _BASE + ("web", "browser", "documents", "convert", "learning_media",
                               "news", "agent", "vision", "mcp"),
    },
    "minimal": {
        "label": "Minimal",
        "hint": "Files, shell, web search and memory only — the smallest prompt.",
        "categories": _BASE + ("web",),
    },
}


def profile_categories(name: str) -> Optional[list[str]]:
    """The toolsets a profile exposes, or None for "everything" (general)."""
    prof = PROFILES.get((name or "general").strip().lower())
    cats = prof["categories"] if prof else None
    return list(cats) if cats else None


def profiles_list() -> list[dict]:
    return [{"id": k, "label": v["label"], "hint": v["hint"]} for k, v in PROFILES.items()]

DEFAULT_THRESHOLD = 40
#: Matches returned by one tool_search; the first FULL_SCHEMAS carry schemas.
SEARCH_LIMIT = 8
FULL_SCHEMAS = 5


def search_settings(config: Optional[dict]) -> dict:
    """Normalized ``tools.search`` settings."""
    raw = ((config or {}).get("tools") or {}).get("search") or {}
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("mode") or "auto").strip().lower()
    if mode not in ("auto", "always", "off"):
        mode = "auto"
    try:
        threshold = int(raw.get("threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    core = raw.get("core")
    core_list = ([str(c).strip() for c in core if str(c).strip()]
                 if isinstance(core, list) and core else list(DEFAULT_CORE))
    return {"mode": mode, "threshold": max(0, threshold), "core": core_list}


def split_tools(defs: list[dict], settings: dict) -> tuple[list[dict], list[dict]]:
    """Split the turn's callable tool defs into ``(sent, deferred)``.

    ``sent`` is the core tools (registration order kept) plus the meta-tools
    when anything is deferred; with nothing to defer, ``sent`` is ``defs``."""
    mode = settings.get("mode", "auto")
    if mode == "off" or not defs:
        return defs, []
    if mode == "auto" and len(defs) <= int(settings.get("threshold", DEFAULT_THRESHOLD)):
        return defs, []
    core = set(settings.get("core") or DEFAULT_CORE)
    sent = [d for d in defs if d["name"] in core]
    deferred = [d for d in defs if d["name"] not in core]
    if not deferred:
        return defs, []
    return sent + meta_definitions(), deferred


def meta_definitions() -> list[dict]:
    return [
        {
            "name": "tool_search",
            "description": (
                "Find one of your deferred tools (listed under MORE TOOLS in your "
                "instructions) by keywords, e.g. 'youtube', 'email send', "
                "'reminder'. Returns the best matches WITH their parameter "
                "schemas — then run one with tool_call. Search before telling the "
                "user you can't do something."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Keywords, or exact tool names separated by commas."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "tool_describe",
            "description": "Get the full parameter schemas of deferred tools by exact name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["names"],
            },
        },
        {
            "name": "tool_call",
            "description": (
                "Run a deferred tool by name with its arguments (an object matching "
                "the schema from tool_search / tool_describe). Approval rules apply "
                "exactly as for any other tool."),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact tool name."},
                    "arguments": {"type": "object",
                                  "description": "The tool's arguments."},
                },
                "required": ["name"],
            },
        },
    ]


_WORD = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _score(query_terms: list[str], d: dict, category: str) -> float:
    name = d["name"].lower()
    name_terms = set(_terms(name.replace("_", " ")))
    cat_terms = set(_terms((category or "").replace("_", " ")))
    desc_terms = _terms(d.get("description", ""))
    desc_set = set(desc_terms)
    score = 0.0
    for q in query_terms:
        if q in name_terms:
            score += 4
        elif any(t.startswith(q) or q.startswith(t) for t in name_terms if len(t) > 2):
            score += 2.5
        if q in cat_terms:
            score += 2
        if q in desc_set:
            score += 1 + min(desc_terms.count(q), 3) * 0.2
        elif len(q) > 3 and any(t.startswith(q) for t in desc_set):
            score += 0.6
    return score


def _compact(d: dict) -> dict:
    return {"name": d["name"], "description": d.get("description", ""),
            "parameters": d.get("parameters") or {"type": "object", "properties": {}}}


def search(query: str, deferred: list[dict], categories: Optional[dict] = None,
           limit: int = SEARCH_LIMIT) -> str:
    """Rank deferred tools against ``query``; render the result for the model."""
    categories = categories or {}
    by_name = {d["name"]: d for d in deferred}
    q = (query or "").strip()
    if not q:
        return "ERROR: give tool_search a query (keywords or tool names)."
    # Exact names (optionally comma-separated, or "select:a,b") win outright.
    raw_names = [n.strip() for n in re.split(r"[,\s]+", q.removeprefix("select:")) if n.strip()]
    exact = [by_name[n] for n in raw_names if n in by_name]
    if exact and len(exact) == len(raw_names):
        ranked = exact
    else:
        terms = _terms(q.replace("_", " "))
        scored = [(_score(terms, d, categories.get(d["name"], "")), i, d)
                  for i, d in enumerate(deferred)]
        ranked = [d for s, _, d in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0]
        ranked = exact + [d for d in ranked if d not in exact]
    ranked = ranked[:max(1, limit)]
    if not ranked:
        return (f"No deferred tool matches {q!r}. Try other keywords, or check the "
                "MORE TOOLS list in your instructions.")
    full = [_compact(d) for d in ranked[:FULL_SCHEMAS]]
    more = [f"- {d['name']}: {_one_line(d.get('description', ''))}"
            for d in ranked[FULL_SCHEMAS:]]
    out = ("Matching tools (run one with tool_call {\"name\": ..., \"arguments\": {...}}):\n"
           + json.dumps(full, ensure_ascii=False))
    if more:
        out += "\nAlso relevant (use tool_describe for their schemas):\n" + "\n".join(more)
    return out


def describe(names: Iterable[str], deferred: list[dict]) -> str:
    by_name = {d["name"]: d for d in deferred}
    wanted = [str(n).strip() for n in (names or []) if str(n).strip()]
    found = [_compact(by_name[n]) for n in wanted if n in by_name]
    missing = [n for n in wanted if n not in by_name]
    if not found:
        return ("ERROR: none of those are deferred tools you can call: "
                + ", ".join(missing or ["(no names given)"]))
    out = json.dumps(found, ensure_ascii=False)
    if missing:
        out += "\nNot available: " + ", ".join(missing)
    return out


def unwrap_call(args: dict) -> tuple[str, dict, str]:
    """``tool_call`` arguments → ``(name, arguments, error)``. Tolerates the
    arguments arriving as a JSON string (some models double-encode)."""
    name = str((args or {}).get("name") or "").strip()
    inner = (args or {}).get("arguments")
    if inner is None:
        inner = {}
    if isinstance(inner, str):
        try:
            inner = json.loads(inner) if inner.strip() else {}
        except ValueError as exc:
            return name, {}, f"tool_call arguments are not valid JSON: {exc}"
    if not isinstance(inner, dict):
        return name, {}, "tool_call arguments must be an object."
    if not name:
        return "", {}, "tool_call needs the tool's name."
    return name, inner, ""


def _one_line(text: str, width: int = 110) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= width else t[: width - 1] + "…"


def tools_block(deferred: list[dict], categories: Optional[dict] = None) -> str:
    """Static system-prompt index of the deferred tools, grouped by toolset."""
    if not deferred:
        return ""
    categories = categories or {}
    groups: dict[str, list[str]] = {}
    for d in deferred:
        groups.setdefault(categories.get(d["name"]) or "general", []).append(d["name"])
    lines = [
        f"MORE TOOLS — only your core tools are loaded; these {len(deferred)} more "
        "exist. When the user wants something none of your loaded tools does, FIRST "
        "call `tool_search` (it returns the parameters), then run the tool with "
        '`tool_call` {"name": "<tool>", "arguments": {...}} — approval rules are the '
        "same. Never improvise with unrelated tools or claim you can't before searching.",
    ]
    for cat in sorted(groups):
        lines.append(f"- {cat}: {', '.join(groups[cat])}")
    return "\n".join(lines)
