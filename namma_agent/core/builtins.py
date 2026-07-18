"""Built-in tools wired to core services (memory, persona, delegation).

These are always available regardless of which capability modules are loaded.
Phase 7 ports the domain modules (file/web/security/...) on top of this.

Wave 4 adds the tools that need live core handles (DB / provider / agent), so
they can't live in the stateless auto-discovery package under ``namma_agent/tools``:

  * memory:   remember_fact, recall_facts, forget_fact, search_conversations
  * delegate: delegate_task (one sub-agent tool replacing v1 Delegate/MoA/Research)
  * persona:  switch_persona, list_personas
"""
from __future__ import annotations

import html as _html
import re as _re
from typing import Optional

from namma_agent.core.memory import Database
from namma_agent.core.persona import (
    delete_user_persona, list_personas as _list_personas, load_persona, save_persona,
)
from namma_agent.core.tools import ToolRegistry, ToolResult

# ── Quiz text normalisation ──────────────────────────────────────────────────
# The model sometimes writes a check in HTML (`<code>type(x)</code>`, `<br>`) or
# entity-encoded snippets (`&lt;class 'int'&gt;`) instead of markdown. The quiz
# card renders text as markdown, which DROPS bare HTML tags and leaves the rest
# looking broken. We convert it to clean markdown up front so the card always
# renders correctly, whatever form the model used.
_CODE_RE = _re.compile(r"<code>(.*?)</code>", _re.DOTALL | _re.IGNORECASE)
_BR_RE = _re.compile(r"<br\s*/?>", _re.IGNORECASE)
_TAG_RE = _re.compile(r"</?(?:b|i|strong|em|p|span|div|pre|tt|kbd|samp|code)\b[^>]*>", _re.IGNORECASE)


def _quiz_md(text: str, *, inline: bool = False) -> str:
    """Normalise model-authored quiz text to clean markdown.

    - ``<code>…</code>`` → backticks (a fenced block when it spans lines),
    - ``<br>`` → a line break,
    - HTML entities (``&lt;`` …) decoded,
    - stray inline tags stripped.

    ``inline=True`` (an option label, which is a single-line button) collapses
    newlines to spaces and wraps any bare ``<…>`` snippet (e.g. ``<class 'int'>``)
    in backticks so it shows as a code chip instead of being eaten as an HTML tag.
    """
    if not text:
        return ""

    def _code_sub(m):
        # <br> inside the snippet are real line breaks; convert them before deciding
        # inline-vs-fenced so a multi-line snippet becomes a proper code block.
        inner = _html.unescape(_BR_RE.sub("\n", m.group(1))).strip("\n")
        return f"\n```\n{inner}\n```\n" if "\n" in inner else f"`{inner}`"

    t = _CODE_RE.sub(_code_sub, str(text))
    t = _BR_RE.sub("\n", t)
    t = _TAG_RE.sub("", t)
    t = _html.unescape(t)
    if inline:
        t = _re.sub(r"\s*\n\s*", " ", t).strip()
        if "`" not in t and ("<" in t or ">" in t):
            t = f"`{t}`"
        return t
    return _re.sub(r"[ \t]+\n", "\n", t).strip()


#: Read-only tools a delegated sub-agent may use to research/answer a sub-task.
_RESEARCH_TOOLS = (
    "web_search", "web_extract", "web_crawl", "read_document",
    "get_weather", "get_news", "recall_facts", "system_info",
)


def register_memory_tools(registry: ToolRegistry, db: Database,
                          get_plugin_ingestor=None, get_engram=None) -> None:
    """Register memory tools. **Engram is THE memory** (docs/MEMORY_SYSTEM_DESIGN.md):
    the native in-process engine — bounded core memory in every prompt, bi-temporal
    facts + entity graph, fused millisecond recall. ``memory_save`` /
    ``memory_search`` / ``memory_forget`` are the primary surface;
    ``remember_fact`` / ``recall_facts`` stay as thin aliases. An external memory
    MCP server (e.g. a Cognee plugin) can still be attached — ``get_plugin_ingestor``
    resolves a duck-typed ``ingest_text`` sink used only when Engram is absent.

    What still lives on ``db`` is the *transcript* store — verbatim chat history
    and session summaries (``search_conversations`` / ``recall_sessions``). That
    is a log of what was said, not memory of what it means.
    """

    def _engram():
        return get_engram() if get_engram else None

    def _queue_ingest(text: str) -> bool:
        """Queue text into the memory write pipeline (never blocks the turn).
        Engram first; an external plugin ingestor is a fallback."""
        eng = _engram()
        if eng is not None:
            eng.writer.ingest_text(text)
            return True
        ingestor = get_plugin_ingestor() if get_plugin_ingestor else None
        if ingestor is None:
            return False
        ingestor.ingest_text(text)
        return True

    def memory_save(args: dict) -> ToolResult:
        """Core-memory curation + semantic write-through (the primary save tool)."""
        eng = _engram()
        if eng is None:
            return ToolResult(ok=False, content="", error="memory engine not available")
        action = (args.get("action") or "add").strip().lower()
        block = (args.get("block") or "auto").strip().lower()
        text = (args.get("text") or "").strip()
        old = (args.get("old_text") or "").strip()
        # An untrusted-channel sender (core.trust) never writes memory — not even
        # via an explicit save the model was talked into. Quarantine for review.
        from namma_agent.core.trust import get_message_trust
        if get_message_trust() == "untrusted":
            eng.writer.quarantine(text or old, source="memory_save")
            return ToolResult(ok=True, content=(
                "This message came from an unverified sender, so nothing was saved — "
                "the text was quarantined for the owner's review."))
        if action in ("replace", "remove") and not old:
            return ToolResult(ok=False, content="", error="'old_text' is required for "
                                                          f"action={action}")
        if action == "remove":
            r = eng.core.remove(block if block != "auto" else "user", old)
            return (ToolResult(ok=True, content=f"Removed from core memory ({r['pct']}% full).")
                    if r.get("ok") else ToolResult(ok=False, content="", error=r.get("error")))
        if not text:
            return ToolResult(ok=False, content="", error="'text' is required")
        if block == "auto":
            # Not identity-grade → straight to the semantic pipeline (extraction,
            # dedup, contradiction handling happen there, in the background).
            eng.writer.ingest_text(text)
            return ToolResult(ok=True, content="Remembering (queued into long-term memory).")
        r = (eng.core.replace(block, old, text) if action == "replace"
             else eng.core.add(block, text))
        if not r.get("ok"):
            return ToolResult(ok=False, content="", error=r.get("error"))
        # Core entries are also durable facts — stored directly (not through the
        # background pipeline) so an explicit save is recallable immediately and
        # survives even when no model is reachable.
        eng.store.add_item(text, kind="preference", importance=0.9, source="core")
        note = f" ({r.get('note')})" if r.get("note") else ""
        return ToolResult(ok=True, content=f"Saved to core memory — '{r['block']}' now "
                                           f"{r['pct']}% full{note}.")

    registry.register(
        name="memory_save",
        description=("Save to long-term memory. block='user' (identity, standing "
                     "preferences) or 'agent' (environment facts, lessons learned) pins "
                     "it into the small ALWAYS-VISIBLE core memory; block='auto' "
                     "(default) stores a regular durable fact. action=replace/remove "
                     "edits an existing core entry matched by old_text substring."),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "the fact/preference to remember"},
                "block": {"type": "string", "enum": ["auto", "user", "agent"],
                          "description": "where it lives (default auto)"},
                "action": {"type": "string", "enum": ["add", "replace", "remove"],
                           "description": "core-memory edit action (default add)"},
                "old_text": {"type": "string",
                             "description": "substring of the core entry to replace/remove"},
            },
            "required": ["text"],
        },
        handler=memory_save,
    )

    def memory_search(args: dict) -> ToolResult:
        eng = _engram()
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, content="", error="'query' is required")
        if eng is None:
            # Engram missing (bare test service) — fall back to a memory plugin.
            if "mcp_cognee_recall" in registry:
                return registry.execute("mcp_cognee_recall", {"query": query})
            return ToolResult(ok=False, content="", error="memory engine not available")
        hits = eng.recall(query, k=int(args.get("k", 8)),
                          include_expired=bool(args.get("include_expired", False)))
        if not hits:
            return ToolResult(ok=True, content="No stored memory matches.")
        lines = []
        for h in hits:
            date = (h.get("created_at") or "")[:10]
            expired = " (superseded)" if h.get("expired") else ""
            lines.append(f"- [{h.get('kind', 'fact')}{' · ' + date if date else ''}]"
                         f"{expired} {h['text']}")
        return ToolResult(ok=True, content="\n".join(lines), data={"matches": len(hits)})

    registry.register(
        name="memory_search",
        description=("Search long-term memory (facts, preferences, entity relations, "
                     "past-session traces) with one fused query. Use BEFORE answering "
                     "anything about the user, their life, work, people, or past "
                     "conversations. include_expired=true also shows superseded facts "
                     "(history of what changed)."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what to look for"},
                "k": {"type": "integer", "description": "max results (default 8)"},
                "include_expired": {"type": "boolean",
                                    "description": "include superseded facts (default false)"},
            },
            "required": ["query"],
        },
        handler=memory_search,
    )

    def memory_forget(args: dict) -> ToolResult:
        eng = _engram()
        if eng is None:
            return ToolResult(ok=False, content="", error="memory engine not available")
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, content="", error="'query' is required")
        n = eng.store.forget_matching(query, hard=bool(args.get("hard", False)))
        if n == 0:
            return ToolResult(ok=True, content="Nothing in memory matches that.")
        verb = "Deleted" if args.get("hard") else "Invalidated"
        return ToolResult(ok=True, content=f"{verb} {n} memory item(s) matching {query!r}.")

    registry.register(
        name="memory_forget",
        description=("Forget stored memory matching a query. Default marks facts as "
                     "no-longer-true (history kept); hard=true erases them entirely."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what to forget"},
                "hard": {"type": "boolean", "description": "erase instead of invalidate"},
            },
            "required": ["query"],
        },
        handler=memory_forget,
        destructive=True,
    )

    def remember_fact(args: dict) -> ToolResult:
        """Alias kept under its old name so existing prompts/habits still work."""
        key = (args.get("key") or "").strip()
        value = (args.get("value") or "").strip()
        if not key or not value:
            return ToolResult(ok=False, content="", error="both 'key' and 'value' are required")
        if not _queue_ingest(f"User {key.replace('_', ' ')}: {value}"):
            return ToolResult(ok=False, content="",
                              error="memory engine not available")
        return ToolResult(ok=True, content=f"Remembering: {key} = {value}")

    registry.register(
        name="remember_fact",
        description=("Save a durable fact about the user into long-term memory "
                     "(background). Alias of memory_save with block=auto."),
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "short fact name, e.g. 'preferred_editor'"},
                "value": {"type": "string", "description": "the fact value"},
                "category": {"type": "string", "description": "optional grouping"},
            },
            "required": ["key", "value"],
        },
        handler=remember_fact,
    )

    def recall_facts(args: dict) -> ToolResult:
        """Alias kept under its old name; recall is Engram's fused search now."""
        return memory_search({"query": args.get("query"), "k": 8})

    registry.register(
        name="recall_facts",
        description=("Recall what is known about the user from long-term memory "
                     "(alias of memory_search)."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "the question to recall an answer for"},
            },
            "required": ["query"],
        },
        handler=recall_facts,
    )

    def search_conversations(args: dict) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, content="", error="'query' is required")
        hits = db.search_turns(query, limit=int(args.get("limit", 10)))
        if not hits:
            return ToolResult(ok=True, content="No matching messages.")
        lines = "\n".join(f"[{h['role']}] {h['content'][:200]}" for h in hits)
        return ToolResult(ok=True, content=lines, data=hits)

    registry.register(
        name="search_conversations",
        description="Search past conversation messages (across sessions) for keywords.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "keywords to look for"},
                "limit": {"type": "integer", "description": "max messages (default 10)"},
            },
            "required": ["query"],
        },
        handler=search_conversations,
    )

    def recall_sessions(args: dict) -> ToolResult:
        hits = db.search_sessions((args.get("query") or "").strip(),
                                  limit=int(args.get("limit", 5)))
        if not hits:
            return ToolResult(ok=True, content="No summarized past sessions match.")
        lines = [f"[{h['created_at'][:10]}] {h['summary']}" for h in hits]
        return ToolResult(ok=True, content="\n\n".join(lines), data=hits)

    registry.register(
        name="recall_sessions",
        description=("Search summaries of past conversation sessions for cross-session "
                     "recall. Omit query to list recent session summaries."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "topic keywords; empty lists recent"},
                "limit": {"type": "integer", "description": "max sessions (default 5)"},
            },
        },
        handler=recall_sessions,
    )

    def clear_memory(args: dict) -> ToolResult:
        scope = (args.get("scope") or "all").lower()
        done: dict = {}
        if scope in ("memory", "cognee", "facts", "all"):
            eng = _engram()
            if eng is not None:
                done["memory"] = eng.store.wipe()
            if "mcp_cognee_forget" in registry:
                r = registry.execute("mcp_cognee_forget", {"everything": True})
                done["cognee"] = "cleared" if r.ok else f"failed: {r.error or r.content}"
        if scope in ("conversations", "sessions", "all"):
            done["conversations"] = db.clear_conversations()
        return ToolResult(ok=True, content=f"Cleared memory (scope={scope}): {done}", data=done)

    registry.register(
        name="clear_memory",
        description=("Erase stored memory. scope: 'memory' (long-term memory: facts, "
                     "graph, core memory), 'conversations' (chat history + summaries), "
                     "or 'all'."),
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["memory", "conversations", "all"],
                          "description": "what to wipe (default all)"},
            },
        },
        handler=clear_memory,
        destructive=True,
    )

    # Scope-aware memory: when the current turn belongs to a project (or learning
    # topic), durable details are saved to that scope's dedicated memory, resolved
    # from the turn-local session id. No-op outside a scoped session. The scope
    # row is what gets injected verbatim into the scope's system prompt (fast,
    # deterministic); the same note is ALSO queued into the memory pipeline so it
    # becomes part of the knowledge graph and is recallable from any chat.
    def _scoped_note(args: dict, scope_type: str, label: str) -> ToolResult:
        from namma_agent.core.interactive import get_current_session

        content = (args.get("note") or args.get("content") or "").strip()
        if not content:
            return ToolResult(ok=False, content="", error="'note' is required")
        sid = get_current_session()
        sess = db.get_session(sid) if sid else None
        if not sess:
            return ToolResult(ok=False, content="", error="No active session.")
        if scope_type == "project":
            scope_id = sess.get("project_id")
            if not scope_id:
                return ToolResult(ok=False, content="",
                                  error="This chat is not in a project; use memory_save instead.")
            scope_name = (db.get_project(scope_id) or {}).get("name", "")
        else:
            from namma_agent.core.learning import topic_for_session  # lazy (Wave 3)
            topic = topic_for_session(db, sid)
            scope_id = topic["id"] if topic else None
            if not scope_id:
                return ToolResult(ok=False, content="", error="Not in a learning topic.")
            scope_name = (topic or {}).get("title", "")
        db.add_scope_memory(scope_type, scope_id, content)
        _queue_ingest(f"{label.capitalize()} \"{scope_name or scope_id}\": {content}")
        return ToolResult(ok=True, content=f"Saved to {label} memory (and queued into the knowledge graph).")

    registry.register(
        name="remember_project_note",
        description=("Save a durable detail to the CURRENT project's dedicated memory so it is "
                     "never forgotten (a decision, requirement, name, preference, or fact about "
                     "the project). Also grows the long-term memory graph. Only meaningful "
                     "inside a project chat."),
        parameters={
            "type": "object",
            "properties": {"note": {"type": "string", "description": "the project detail to remember"}},
            "required": ["note"],
        },
        handler=lambda a: _scoped_note(a, "project", "project"),
    )


def register_project_tools(registry: ToolRegistry, db: Database) -> None:
    """Project document tools (multi-document RAG). Scope resolves from the
    turn-local session: both tools only work inside a project chat."""
    from namma_agent.core.interactive import get_current_session

    def _project_id() -> str | None:
        sid = get_current_session()
        sess = db.get_session(sid) if sid else None
        return (sess or {}).get("project_id")

    def search_project_documents(args: dict) -> ToolResult:
        from namma_agent.core.docindex import format_excerpts, retrieve

        pid = _project_id()
        if not pid:
            return ToolResult(ok=False, content="",
                              error="This chat is not in a project — no documents to search.")
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, content="", error="'query' is required")
        excerpts = retrieve(db, pid, query, k=int(args.get("k", 6)))
        return ToolResult(ok=True, content=format_excerpts(excerpts),
                          data={"matches": len(excerpts)})

    def list_project_documents(_args: dict) -> ToolResult:
        pid = _project_id()
        if not pid:
            return ToolResult(ok=False, content="",
                              error="This chat is not in a project — no documents to list.")
        docs = db.list_project_documents(pid)
        if not docs:
            return ToolResult(ok=True, content="No documents uploaded to this project yet.")
        lines = []
        for d in docs:
            note = ""
            if d["status"] == "flagged":
                note = " — FLAGGED (possible prompt injection; quarantined from retrieval)"
            elif d["status"] == "error":
                note = " — failed to index"
            lines.append(f"- {d['name']} ({d['chunk_count']} chunks, {d['bytes']} bytes){note}")
        return ToolResult(ok=True, content="\n".join(lines), data={"count": len(docs)})

    registry.register(
        name="search_project_documents",
        description=("Search the CURRENT project's uploaded documents and get the most "
                     "relevant passages (with file/section citations). Use this whenever a "
                     "question could be answered by the project's documents — and search "
                     "again with different keywords if the first pass misses."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "keywords or a short question to find passages for"},
                "k": {"type": "integer", "description": "max excerpts (default 6)"},
            },
            "required": ["query"],
        },
        handler=search_project_documents,
    )
    def search_project_history(args: dict) -> ToolResult:
        pid = _project_id()
        if not pid:
            return ToolResult(ok=False, content="",
                              error="This chat is not in a project.")
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, content="", error="'query' is required")
        hits = db.search_turns(query, limit=int(args.get("limit", 10)), project_id=pid)
        if not hits:
            return ToolResult(ok=True, content="No earlier project messages match.")
        lines = [f"[{h['created_at'][:10]} · {h['role']}] {h['content'][:240]}" for h in hits]
        return ToolResult(ok=True, content="\n".join(lines), data={"matches": len(hits)})

    registry.register(
        name="list_project_documents",
        description="List the documents uploaded to the CURRENT project (name, size, status).",
        parameters={"type": "object", "properties": {}},
        handler=list_project_documents,
    )
    registry.register(
        name="search_project_history",
        description=("Search what was said in THIS project's earlier chat sessions "
                     "(cross-session recall). Use it when the user refers to something "
                     "discussed before that isn't in the summaries above."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "keywords to look for"},
                "limit": {"type": "integer", "description": "max messages (default 10)"},
            },
            "required": ["query"],
        },
        handler=search_project_history,
    )


def register_learning_tools(registry: ToolRegistry, db: Database,
                            get_comms=None, config: dict | None = None,
                            get_memory_writer=None) -> None:
    """Learning-Room teacher tools: plan the path, mark progress, quiz, score the
    learner, save topic memory, and (from a normal chat) suggest the Learning Room.
    Scope is resolved from the turn-local session via the learning topic it belongs
    to; quiz/suggestion push typed events straight to the browser.

    ``get_comms`` lazily resolves the CommsManager (it's built after the registry)
    so module-completion progress can be pushed to Telegram when configured.
    ``get_memory_writer`` lazily resolves Engram's writer (``ingest_text`` /
    ``ingest_learning``) so a completed module's recap also grows the knowledge
    graph (no-op when memory isn't wired)."""
    from namma_agent.core.interactive import emit_event, get_current_session

    def _topic():
        sid = get_current_session()
        if not sid:
            return None
        try:
            return db.get_topic_by_session(sid)
        except Exception:  # noqa: BLE001
            return None

    def _session_module(topic: dict) -> Optional[dict]:
        """The module whose chat thread the current turn is running in (None in
        the path chat). Keeps quiz/completion attribution state-aware instead of
        trusting the topic's global 'current module' pointer."""
        sid = get_current_session()
        for m in (topic or {}).get("plan") or []:
            if m.get("session_id") == sid:
                return m
        return None

    def set_learning_plan(args: dict) -> ToolResult:
        topic = _topic()
        if not topic:
            return ToolResult(ok=False, content="", error="Not in a learning topic.")
        modules = args.get("modules") or []
        if not isinstance(modules, list) or not modules:
            return ToolResult(ok=False, content="", error="'modules' must be a non-empty list.")
        db.set_learning_plan(topic["id"], modules)
        emit_event("learning_plan_updated", {"topic_id": topic["id"]})
        return ToolResult(ok=True, content=f"Learning path set with {len(modules)} module(s).")

    def mark_module_complete(args: dict) -> ToolResult:
        topic = _topic()
        if not topic:
            return ToolResult(ok=False, content="", error="Not in a learning topic.")
        # Resolve which module to complete — robustly. The model often passes a
        # positional guess ("1", "module 2") that does NOT match the real id
        # ("mod1"); blindly trusting it makes mark_module a silent no-op (the path
        # never advances, the React flow never updates). So: accept an explicit id
        # ONLY if it's real; otherwise prefer the thread we're teaching in, then the
        # topic's current pointer, and finally a positional index as a last resort.
        plan = topic.get("plan") or []
        valid_ids = {m["id"] for m in plan}
        own = _session_module(topic)
        raw = str(args.get("module_id") or "").strip()
        cur = topic.get("progress", {}).get("current_module")
        mid = ""
        for cand in (raw, (own or {}).get("id"), cur):
            if cand and str(cand).strip() in valid_ids:
                mid = str(cand).strip()
                break
        if not mid:  # positional fallback: "1" / "module 2" → the nth module
            num = _re.search(r"\d+", raw)
            if num and 0 <= int(num.group()) - 1 < len(plan):
                mid = plan[int(num.group()) - 1]["id"]
        if not mid:
            return ToolResult(ok=False, content="", error="no current module to complete")
        module = next((m for m in plan if m["id"] == mid), None)
        # Cross-module continuity: persist a recap (concepts + the running example)
        # to topic memory so EVERY later module teaches on top of it.
        recap = (args.get("recap") or "").strip()
        if recap and module:
            db.add_scope_memory("learning", topic["id"],
                                f"Module recap — {module['title']}: {recap}")
            _ingest_learning_recap(topic, module, recap)
        updated = db.mark_module(topic["id"], mid, "done")
        plan = (updated or {}).get("plan") or []
        nxt = next((m for m in plan if m.get("status") == "current"), None)
        prog = (updated or {}).get("progress") or {}
        # Rich event: the UI drops a "module complete → continue" card into the
        # chat so the learner always has a concrete next step.
        emit_event("learning_progress", {
            "topic_id": topic["id"],
            "module_id": mid,
            "module_title": (module or {}).get("title", ""),
            "done": prog.get("done", 0),
            "total": prog.get("total", 0),
            "next": ({"id": nxt["id"], "title": nxt["title"]} if nxt else None),
            "session_id": get_current_session(),
        })
        _notify_progress(topic, module, updated)
        tail = f" Next module: \"{nxt['title']}\" (the learner opens it from the path)." if nxt \
            else " That was the final module — the path is complete."
        return ToolResult(ok=True, content=f"Module '{mid}' marked complete.{tail}")

    def _ingest_learning_recap(topic: dict, module: Optional[dict], recap: str) -> None:
        """Grow the knowledge graph from what the learner just studied. The recap
        (concepts + the running example) is queued into Engram's background write
        pipeline so a completed module shows up as entities/relationships in the
        Memory graph. Best-effort: silently no-ops when memory isn't wired."""
        ingestor = get_memory_writer() if get_memory_writer else None
        if ingestor is None:
            return
        text = (f"Learning topic \"{topic.get('title', '')}\" — completed module "
                f"\"{(module or {}).get('title', '')}\". {recap}")
        try:
            ingestor.ingest_learning(text)
        except Exception:  # noqa: BLE001
            pass

    def _notify_progress(topic: dict, module: Optional[dict], updated: Optional[dict]) -> None:
        """Push module-completion progress to Telegram/Discord (config-gated,
        best-effort — teaching never fails because a notification did)."""
        cfg = (config or {}).get("learning") or {}
        if not cfg.get("notify_progress", True):
            return
        comms = get_comms() if get_comms else None
        if comms is None or not getattr(comms, "any_available", False):
            return
        prog = (updated or topic).get("progress") or {}
        done, total = prog.get("done", 0), prog.get("total", 0)
        mtitle = (module or {}).get("title", "a module")
        msg = (f"📘 Learning progress — “{topic['title']}”: module “{mtitle}” complete "
               f"({done}/{total} modules).")
        if done >= total and total:
            msg = (f"🎓 You finished the whole path for “{topic['title']}” — all "
                   f"{total} modules. Brilliant work!")
        try:
            comms.send(msg)
        except Exception:  # noqa: BLE001
            pass

    def pose_quiz(args: dict) -> ToolResult:
        topic = _topic()
        # Normalise any HTML/entities the model used into clean markdown so the card
        # renders right (question/explanation as block markdown, options inline).
        question = _quiz_md(args.get("question") or "")
        code = _html.unescape(args.get("code") or "").strip()
        # The card has a DEDICATED code slot. If the model ALSO put the snippet in the
        # question as a fenced block, it would render twice — hoist it out: drop the
        # fenced block from the question, and use it as the code if no code field was
        # given. This kills the duplicate while keeping the snippet visible once.
        fenced = _re.findall(r"```[A-Za-z0-9]*\n(.*?)```", question, _re.DOTALL)
        if fenced:
            question = _re.sub(r"```[A-Za-z0-9]*\n.*?```", "", question, flags=_re.DOTALL).strip()
            if not code:
                code = fenced[0].strip()
        options = [_quiz_md(o, inline=True) for o in (args.get("options") or []) if str(o).strip()]
        if not question:
            return ToolResult(ok=False, content="",
                              error="pose_quiz needs a 'question'. The check question must "
                                    "live in this card — do not ask it in chat text.")
        if len(options) < 2:
            return ToolResult(ok=False, content="",
                              error="pose_quiz needs at least 2 non-empty 'options'. Provide "
                                    "the options here — never list them in chat text.")
        own = _session_module(topic) if topic else None
        # Clamp answer_index into range so a bad index can never produce a card with
        # no correct answer.
        try:
            answer_index = int(args.get("answer_index", 0))
        except (TypeError, ValueError):
            answer_index = 0
        answer_index = max(0, min(answer_index, len(options) - 1))
        import json as _json
        import uuid as _uuid
        session_id = get_current_session()
        payload = {
            "quiz_id": _uuid.uuid4().hex,  # ties the persisted card to its answer
            "question": question,
            # Code the question refers to, shown as a code block in the card so the
            # learner can actually read it before answering (never just in chat).
            # Already entity-decoded and de-duplicated against the question above.
            "code": code,
            "options": options,
            "answer_index": answer_index,
            "explanation": _quiz_md(args.get("explanation") or ""),
            "topic_id": topic["id"] if topic else None,
            # Attribute the check to the module whose THREAD it was posed in, not
            # the global pointer (they diverge when revisiting other modules).
            "module_id": (own or {}).get("id")
                         or (topic or {}).get("progress", {}).get("current_module"),
            "session_id": session_id,  # route the card to the right chat
        }
        emit_event("quiz", payload)
        # Persist the card as a 'quiz' turn so it survives leaving/reopening the
        # chat (recent_turns keeps it out of the model's message history).
        if session_id:
            db.add_turn(session_id, "quiz", _json.dumps(payload))
        # Tell the model the card is now on screen and to NOT restate it — restating
        # the question in prose is exactly what produces an "inline" question.
        return ToolResult(ok=True, content="(The multiple-choice card is now displayed to the "
                          "learner. Do NOT repeat the question or the options in your message — "
                          "the card IS the question. Wait for their answer.)")

    def record_understanding(args: dict) -> ToolResult:
        topic = _topic()
        if not topic:
            return ToolResult(ok=False, content="", error="Not in a learning topic.")
        insights = {
            "understanding": args.get("score"),
            "analysis": (args.get("analysis") or "").strip() or None,
            "strengths": args.get("strengths"),
            "gaps": args.get("gaps"),
        }
        db.set_learning_insights(topic["id"], {k: v for k, v in insights.items() if v is not None})
        emit_event("learning_insights", {"topic_id": topic["id"]})
        return ToolResult(ok=True, content="Noted the learner's understanding.")

    def remember_learning_note(args: dict) -> ToolResult:
        topic = _topic()
        note = (args.get("note") or "").strip()
        if not topic:
            return ToolResult(ok=False, content="", error="Not in a learning topic.")
        if not note:
            return ToolResult(ok=False, content="", error="'note' is required")
        db.add_scope_memory("learning", topic["id"], note)
        # Also grow the knowledge graph so the learner's goal/background is
        # recallable from ANY chat, not just this topic's threads.
        ingestor = get_memory_writer() if get_memory_writer else None
        if ingestor is not None:
            ingestor.ingest_text(f"Learning topic \"{topic.get('title', '')}\": {note}")
        return ToolResult(ok=True, content="Saved to this topic's memory.")

    def set_teaching_preference(args: dict) -> ToolResult:
        topic = _topic()
        if not topic:
            return ToolResult(ok=False, content="", error="Not in a learning topic.")
        instruction = (args.get("instruction") or "").strip()
        if not instruction:
            return ToolResult(ok=False, content="", error="'instruction' is required")
        db.add_teaching_preference(topic["id"], instruction)
        emit_event("learning_insights", {"topic_id": topic["id"]})
        return ToolResult(ok=True,
                          content=f"Standing preference saved — it now applies in every "
                                  f"module of this topic: {instruction}")

    def suggest_learning(args: dict) -> ToolResult:
        topic = (args.get("topic") or "").strip()
        if not topic:
            return ToolResult(ok=False, content="", error="'topic' is required")
        # Solo chats ONLY: a learning suggestion makes no sense inside the Learning
        # Room itself (they're already there) or a project chat (a focused workspace).
        # Gate it server-side so the gentle nudge can never surface anywhere else,
        # regardless of what the model does.
        sid = get_current_session()
        sess = db.get_session(sid) if sid else None
        kind = (sess or {}).get("kind") or "chat"
        if kind != "chat" or (sess or {}).get("project_id"):
            return ToolResult(ok=True, content="(not a solo chat — learning suggestion skipped)")
        emit_event("learn_suggestion", {"topic": topic, "session_id": sid})
        return ToolResult(ok=True, content="")  # silent: the UI shows a gentle nudge

    registry.register(
        "set_learning_plan",
        "Create or replace the learning path for the current topic: an ordered list of "
        "5–9 focused modules, each {title, summary}. Call this first if no path exists.",
        {"type": "object", "properties": {"modules": {"type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "title": {"type": "string"},
                "summary": {"type": "string"}}, "required": ["title"]}}},
         "required": ["modules"]},
        set_learning_plan,
    )
    registry.register(
        "mark_module_complete",
        "Mark a module done once the learner has genuinely understood it (e.g. passed a "
        "quick check); advances to the next module. ALWAYS pass `recap`: 2-3 sentences "
        "naming the concepts taught AND the running example you used, so the next module "
        "builds on the same example instead of starting cold.",
        {"type": "object", "properties": {
            "module_id": {"type": "string", "description": "defaults to current"},
            "recap": {"type": "string",
                      "description": "what was taught + the running example used + how the learner did"}}},
        mark_module_complete,
    )
    registry.register(
        "set_teaching_preference",
        "Save a STANDING teaching preference for this topic — how the learner wants to be "
        "taught from now on, in every module (e.g. 'research every answer before replying', "
        "'use cricket examples', 'always show runnable code'). Phrase it as a crisp "
        "imperative instruction.",
        {"type": "object", "properties": {"instruction": {"type": "string"}},
         "required": ["instruction"]},
        set_teaching_preference,
    )
    registry.register(
        "pose_quiz",
        "Show the learner an interactive multiple-choice check. Provide the question, "
        "options, the 0-based answer_index, and a short explanation. If the question "
        "refers to a code snippet (e.g. 'what does this print?'), you MUST include that "
        "code in the `code` field — it renders as a code block in the card so the learner "
        "can read it. NEVER ask about code without putting it in `code`; the learner "
        "cannot see anything you only wrote in chat. Question/options/explanation render "
        "as MARKDOWN — use inline `backticks` for short code or literal output (e.g. "
        "`type(x)`, `<class 'int'>`). Do NOT write raw HTML such as <code> or <br>.",
        {"type": "object", "properties": {
            "question": {"type": "string"},
            "code": {"type": "string",
                     "description": "code the question is about, shown as a code block "
                                    "(required whenever the question references code)"},
            "options": {"type": "array", "items": {"type": "string"}},
            "answer_index": {"type": "integer"},
            "explanation": {"type": "string"}},
         "required": ["question", "options", "answer_index"]},
        pose_quiz,
    )
    registry.register(
        "record_understanding",
        "Save your running read of THIS learner: a 0–100 understanding score and a short "
        "analytical note on how they think and where they struggle, so future modules adapt.",
        {"type": "object", "properties": {
            "score": {"type": "integer", "description": "0–100"},
            "analysis": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "gaps": {"type": "array", "items": {"type": "string"}}}},
        record_understanding,
    )
    registry.register(
        "remember_learning_note",
        "Save a durable fact about this learning topic or the learner's goal to the "
        "topic's dedicated memory.",
        {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]},
        remember_learning_note,
    )
    registry.register(
        "suggest_learning",
        "Call in a normal solo chat when you detect the user is trying to LEARN a topic "
        "more deeply — asking follow-up 'why/how' questions, going step by step, asking to "
        "be taught/explained, or clearly struggling to grasp a concept. It offers them the "
        "Learning Room for that topic via a gentle nudge under your reply. Pass a short, "
        "specific `topic` (e.g. 'recursion', 'how neural networks learn'). Call it at most "
        "once for a given topic; do not use it for quick factual or task requests.",
        {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]},
        suggest_learning,
    )


def register_skill_tools(registry: ToolRegistry, store) -> None:
    """Register the skill (procedural-memory) tools against a live SkillStore.

    This is the hermes learning loop, adapted to Namma Agent's single agent loop:
    the model loads a relevant playbook with ``use_skill`` and, after solving a
    novel multi-step task, saves the procedure with ``create_skill`` (refining it
    later with ``update_skill``). All of it is visible in the tool timeline."""

    def list_skills(_args: dict) -> ToolResult:
        # Only the skills the user left enabled are usable; don't advertise the rest.
        skills = [s for s in store.all() if s.enabled]
        if not skills:
            return ToolResult(ok=True, content="No skills enabled.")
        lines = []
        for s in skills:
            miss = "" if s.supported else f" — needs {', '.join(s.missing())}"
            lines.append(f"- {s.name} [{s.source}]: {s.one_line(180)}{miss}")
        return ToolResult(ok=True, content="Available skills:\n" + "\n".join(lines),
                          data={"skills": [s.name for s in skills]})

    def use_skill(args: dict) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, content="", error="'name' is required")
        existing = store.get(name)
        if existing is not None and not existing.enabled:
            return ToolResult(ok=False, content="",
                              error=f"skill {name!r} is disabled (turn it on in Settings → Skills)")
        body = store.render(name)
        if body is None:
            avail = ", ".join(s.name for s in store.all() if s.enabled) or "(none)"
            return ToolResult(ok=False, content="",
                              error=f"no skill named {name!r}. Available: {avail}")
        return ToolResult(ok=True, content=body)

    def create_skill(args: dict) -> ToolResult:
        name = (args.get("name") or "").strip()
        desc = (args.get("description") or "").strip()
        body = (args.get("body") or "").strip()
        if not (name and desc and body):
            return ToolResult(ok=False, content="",
                              error="'name', 'description', and 'body' are all required")
        skill = store.create(name, desc, body, category=args.get("category", ""),
                             tags=args.get("tags") or [])
        return ToolResult(ok=True, content=f"Saved skill '{skill.name}' to {skill.directory}.")

    def update_skill(args: dict) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, content="", error="'name' is required")
        skill = store.update(name, body=args.get("body"), description=args.get("description"))
        if skill is None:
            return ToolResult(ok=False, content="", error=f"no skill named {name!r}")
        return ToolResult(ok=True, content=f"Updated skill '{skill.name}'.")

    registry.register(
        name="list_skills",
        description="List Namma Agent's available skills (procedural playbooks) and their descriptions.",
        parameters={"type": "object", "properties": {}},
        handler=list_skills,
    )
    registry.register(
        name="use_skill",
        description=("Load a skill's full procedure into context, then follow it. Call this "
                     "whenever a request matches a skill's purpose listed in AVAILABLE SKILLS."),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "the skill name to load"}},
            "required": ["name"],
        },
        handler=use_skill,
    )
    registry.register(
        name="create_skill",
        description=("Save a reusable procedure as a new skill after solving a novel multi-step "
                     "task well, so Namma Agent can reuse it next time. Write the body as a clear "
                     "markdown playbook (When to Use / Procedure / Verification)."),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "short kebab-case skill name"},
                "description": {"type": "string", "description": "when this skill should be used (the trigger)"},
                "body": {"type": "string", "description": "the markdown playbook body"},
                "category": {"type": "string", "description": "optional grouping"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "description", "body"],
        },
        handler=create_skill,
    )
    registry.register(
        name="update_skill",
        description="Improve an existing skill — update its procedure body and/or its description.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "body": {"type": "string", "description": "new markdown body (optional)"},
                "description": {"type": "string", "description": "new trigger description (optional)"},
            },
            "required": ["name"],
        },
        handler=update_skill,
    )


def register_agent_tools(registry: ToolRegistry, agent, provider, db,
                         get_comms=None, bg_store_path=None) -> dict:
    """Register delegate_task + background-task + persona tools. Needs the live
    agent/provider/db. Returns handles for the service's status surface
    (``{"background_tasks": callable}``).

    ``delegate_task`` runs a bounded sub-agent; ``background_task`` runs the same
    kind of sub-agent on a detached thread (the conversation continues; a comms
    ping fires when it finishes). Both use a fresh registry that excludes the
    delegation tools themselves (no recursion) and **never contains destructive
    tools** — a sub-agent has no approval channel, so it must not be able to
    change state unsupervised. An optional ``toolsets`` arg widens the default
    read-only research set to other (non-destructive) toolsets.
    """
    import threading as _threading
    import time as _time
    import uuid as _uuid

    from namma_agent.core.agent import Agent  # local import avoids an import cycle

    _EXCLUDE_FROM_SUBAGENT = {"delegate_task", "background_task",
                              "check_background_task"}
    #: Background task registry: id → {name, task, status, result, ...}.
    #: Mirrored to a JSON store so finished results survive a restart; a task
    #: that was still running when the process died shows as "interrupted".
    _bg_tasks: dict[str, dict] = {}
    _bg_lock = _threading.Lock()
    _BG_KEEP = 50  # newest entries kept in the store

    from namma_agent.tools import _jsonstore
    _bg_path = (bg_store_path if bg_store_path is not None
                else _jsonstore.store_path("background_tasks",
                                           "background_tasks.json"))

    def _bg_public(entry: dict) -> dict:
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    def _bg_save() -> None:
        with _bg_lock:
            entries = sorted((_bg_public(e) for e in _bg_tasks.values()),
                             key=lambda e: e.get("started_at") or 0)[-_BG_KEEP:]
        try:
            _jsonstore.save(_bg_path, entries)
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            from namma_agent.core.logger import logger
            logger.debug("[bg-task] store save failed: %s", exc)

    # Boot: restore past tasks; anything the previous process left "running"
    # can't be resumed (its thread died with the process) — mark it clearly.
    _interrupted = False
    for _entry in _jsonstore.load(_bg_path):
        if _entry.get("id"):
            if _entry.get("status") == "running":
                _entry["status"] = "interrupted"
                _entry["error"] = "the app restarted while this task was running"
                _interrupted = True
            _bg_tasks[_entry["id"]] = _entry
    if _interrupted:
        _bg_save()

    def _sub_registry(toolsets: Optional[list] = None) -> ToolRegistry:
        """The tool surface a sub-agent sees: requested (non-destructive) toolsets
        or, by default / as a fallback, the read-only research set."""
        sub_registry = ToolRegistry()
        wanted = {str(t).strip() for t in (toolsets or []) if str(t).strip()}
        if wanted:
            for tool in registry.all():
                if (tool.name in _EXCLUDE_FROM_SUBAGENT or tool.destructive
                        or not tool.enabled):
                    continue
                if tool.name in wanted or (tool.category or "general") in wanted:
                    sub_registry.add(tool)
        if len(sub_registry) == 0:
            for name in _RESEARCH_TOOLS:
                tool = registry.get(name)
                if tool is not None:
                    sub_registry.add(tool)
        return sub_registry

    def _run_subagent(task: str, toolsets: Optional[list] = None):
        # Inherit the main agent's tool-step budget so an unlimited config
        # (tool_loop_limit <= 0) lets deep research run to completion instead of
        # being capped at a hidden sub-agent limit.
        sub = Agent(provider, _sub_registry(toolsets), db, persona=agent.persona,
                    tool_loop_limit=agent.tool_loop_limit, max_history_turns=4)
        instruction = (
            "You are a focused sub-task/research agent. Use your tools to actually "
            "complete the task below, then report concise findings (with source URLs "
            "where relevant). Do not ask follow-up questions.\n\nTASK: " + task
        )
        return sub.process_turn(instruction, session_id=sub.new_session())

    def delegate_task(args: dict) -> ToolResult:
        task = (args.get("task") or "").strip()
        if not task:
            return ToolResult(ok=False, content="", error="'task' is required")
        try:
            result = _run_subagent(task, args.get("toolsets"))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content="", error=f"delegation failed: {exc}")
        return ToolResult(ok=True, content=result.content or "(no findings)",
                          data={"tools_used": result.tools_used})

    def background_task(args: dict) -> ToolResult:
        task = (args.get("task") or "").strip()
        if not task:
            return ToolResult(ok=False, content="", error="'task' is required")
        name = (args.get("name") or task).strip()[:60]
        task_id = _uuid.uuid4().hex[:8]
        entry = {"id": task_id, "name": name, "task": task, "status": "running",
                 "result": "", "error": "", "started_at": _time.time(),
                 "finished_at": None}
        with _bg_lock:
            _bg_tasks[task_id] = entry
        _bg_save()

        def _work() -> None:
            try:
                res = _run_subagent(task, args.get("toolsets"))
                entry["result"] = res.content or "(no findings)"
                entry["status"] = "done"
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc)
                entry["status"] = "failed"
            entry["finished_at"] = _time.time()
            _bg_save()
            # Ping the user over comms when a channel is configured — the whole
            # point of a background task is not having to sit and wait for it.
            try:
                comms = get_comms() if get_comms else None
                if comms is not None and getattr(comms, "any_available", False):
                    if entry["status"] == "done":
                        comms.send(f"✅ Background task “{name}” finished:\n\n"
                                   f"{entry['result'][:800]}")
                    else:
                        comms.send(f"❌ Background task “{name}” failed: "
                                   f"{entry['error'][:200]}")
            except Exception:  # noqa: BLE001 — notification is best-effort
                pass

        thread = _threading.Thread(target=_work, name=f"bg-task-{task_id}",
                                   daemon=True)
        entry["_thread"] = thread
        thread.start()
        return ToolResult(
            ok=True,
            content=(f"Started background task {task_id} (“{name}”). The "
                     f"conversation continues meanwhile — check on it with "
                     f"check_background_task."),
            data={"id": task_id})

    def check_background_task(args: dict) -> ToolResult:
        task_id = (args.get("id") or "").strip()
        with _bg_lock:
            entries = dict(_bg_tasks)
        if task_id:
            entry = entries.get(task_id)
            if entry is None:
                return ToolResult(ok=False, content="",
                                  error=f"no background task {task_id!r}")
            if entry["status"] == "running":
                return ToolResult(ok=True, content=f"Task {task_id} (“{entry['name']}”) "
                                                   "is still running.",
                                  data={"status": "running"})
            if entry["status"] in ("failed", "interrupted"):
                return ToolResult(ok=True, content=f"Task {task_id} {entry['status']}: "
                                                   f"{entry['error']}",
                                  data={"status": entry["status"]})
            return ToolResult(ok=True, content=entry["result"],
                              data={"status": "done"})
        if not entries:
            return ToolResult(ok=True, content="No background tasks have been started.")
        lines = [f"- {e['id']} “{e['name']}” — {e['status']}"
                 for e in entries.values()]
        return ToolResult(ok=True, content="Background tasks:\n" + "\n".join(lines),
                          data={"tasks": [{k: v for k, v in e.items()
                                           if not k.startswith("_")}
                                          for e in entries.values()]})

    def _summarize_turns(turns: list[dict]) -> str:
        convo = "\n".join(f"{t['role']}: {t['content']}" for t in turns
                          if t.get("role") in ("user", "assistant"))[:12000]
        prompt = [
            {"role": "system", "content": (
                "Summarize this conversation in 3-5 sentences for long-term recall. "
                "Capture what the user wanted, what was done/decided, and any durable "
                "facts or preferences. Be specific and terse. No preamble.")},
            {"role": "user", "content": convo},
        ]
        resp = provider.generate(prompt, tools=None, stream=False)
        return (resp.content or "").strip()

    def summarize_session(args: dict) -> ToolResult:
        sid = (args.get("session_id") or "").strip()
        if not sid:
            return ToolResult(ok=False, content="", error="'session_id' is required")
        turns = db.session_turns(sid)
        if not turns:
            return ToolResult(ok=False, content="", error="that session has no turns")
        try:
            summary = _summarize_turns(turns)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content="", error=f"summarization failed: {exc}")
        if summary:
            db.set_session_summary(sid, summary)
        return ToolResult(ok=True, content=summary or "(empty summary)")

    def _persona_ids() -> list[str]:
        return [p["id"] for p in _list_personas()]

    def switch_persona(args: dict) -> ToolResult:
        name = (args.get("persona") or "").strip()
        if not name:
            return ToolResult(ok=False, content="", error="'persona' is required")
        if name not in _persona_ids():
            return ToolResult(ok=False, content="",
                              error=f"unknown persona {name!r}; available: {', '.join(_persona_ids())}")
        agent.set_persona(name)
        return ToolResult(ok=True, content=f"Switched persona to {load_persona(name).name} ({name}).")

    def list_personas(_args: dict) -> ToolResult:
        rows = _list_personas()
        if not rows:
            return ToolResult(ok=True, content="No personas installed.")
        lines = [f"- {r['id']} ({r['source']}): {r['name']} — {r['identity_line']}" for r in rows]
        return ToolResult(ok=True, content="Available personas:\n" + "\n".join(lines),
                          data={"current": agent.persona.id, "available": [r["id"] for r in rows]})

    def create_persona(args: dict) -> ToolResult:
        """Create or edit a persona the user describes (editing = same id/name).
        Saves to the user persona dir; optionally switch to it right away."""
        try:
            saved = save_persona({
                "id": (args.get("id") or "").strip(),
                "name": args.get("name") or "",
                "identity": args.get("identity") or "",
                "tone": args.get("tone") or "",
                "dos": args.get("dos") or [],
                "donts": args.get("donts") or [],
            })
        except ValueError as exc:
            return ToolResult(ok=False, content="", error=str(exc))
        if args.get("activate"):
            agent.set_persona(saved["id"])
        verb = "Activated" if args.get("activate") else "Saved"
        return ToolResult(ok=True, content=f"{verb} persona {saved['name']} ({saved['id']}).",
                          data=saved)

    def delete_persona(args: dict) -> ToolResult:
        pid = (args.get("persona") or "").strip()
        if not pid:
            return ToolResult(ok=False, content="", error="'persona' is required")
        if not delete_user_persona(pid):
            return ToolResult(ok=False, content="",
                              error=f"no user persona {pid!r} to delete (built-ins can't be removed)")
        if agent.persona.id == pid:  # deleted the active one → fall back to default
            agent.set_persona("core")
        return ToolResult(ok=True, content=f"Deleted persona {pid!r}.")

    registry.register(
        name="delegate_task",
        description=("Hand a self-contained research or multi-step sub-task to a focused "
                     "sub-agent and get its findings back (blocks until done). Use for web "
                     "research, multi-source lookups, or anything worth isolating from the "
                     "main conversation. For long tasks prefer background_task."),
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "the sub-task to complete, stated fully"},
                "toolsets": {"type": "array", "items": {"type": "string"},
                             "description": ("optional toolset/tool names to expose to the "
                                             "sub-agent instead of the default research set "
                                             "(destructive tools are always excluded)")},
            },
            "required": ["task"],
        },
        handler=delegate_task,
    )

    registry.register(
        name="background_task",
        description=("Run a self-contained sub-task on a background sub-agent and return "
                     "IMMEDIATELY with a task id — the conversation continues while it works. "
                     "The user is pinged over their messaging channel when it finishes; "
                     "results are fetched with check_background_task. Use for long research "
                     "or anything the user shouldn't have to wait for."),
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "the sub-task to complete, stated fully"},
                "name": {"type": "string", "description": "short human label for the task"},
                "toolsets": {"type": "array", "items": {"type": "string"},
                             "description": ("optional toolset/tool names to expose to the "
                                             "sub-agent instead of the default research set "
                                             "(destructive tools are always excluded)")},
            },
            "required": ["task"],
        },
        handler=background_task,
    )

    registry.register(
        name="check_background_task",
        description=("Check background tasks started with background_task: with an id, "
                     "return that task's status/result; without, list all tasks."),
        parameters={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "task id (omit to list all)"}},
        },
        handler=check_background_task,
    )

    registry.register(
        name="switch_persona",
        description="Switch Namma Agent's active persona for the rest of the session.",
        parameters={
            "type": "object",
            "properties": {"persona": {"type": "string", "description": "persona id, e.g. 'core' or a user persona"}},
            "required": ["persona"],
        },
        handler=switch_persona,
    )

    registry.register(
        name="list_personas",
        description="List the available personas (with a one-line identity) and which is active.",
        parameters={"type": "object", "properties": {}},
        handler=list_personas,
    )

    registry.register(
        name="create_persona",
        description=("Create a NEW persona — or EDIT an existing user persona by reusing its "
                     "id — from a design the user asks for. Provide a name and an identity "
                     "(the 'You are …' system-prompt text; use the literal token {name} where "
                     "the assistant's name belongs). Optionally set activate=true to switch to "
                     "it immediately."),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "display name for the persona"},
                "identity": {"type": "string", "description": "the 'You are …' identity; use {name} for the assistant's name"},
                "tone": {"type": "string", "description": "a few comma-separated tone words"},
                "dos": {"type": "array", "items": {"type": "string"}, "description": "short DO rules"},
                "donts": {"type": "array", "items": {"type": "string"}, "description": "short DON'T rules"},
                "id": {"type": "string", "description": "reuse an existing id to EDIT it (optional)"},
                "activate": {"type": "boolean", "description": "switch to this persona now"},
            },
            "required": ["name", "identity"],
        },
        handler=create_persona,
    )

    registry.register(
        name="delete_persona",
        description="Delete a user-created persona by id (built-in personas can't be removed).",
        parameters={
            "type": "object",
            "properties": {"persona": {"type": "string", "description": "persona id to delete"}},
            "required": ["persona"],
        },
        handler=delete_persona,
    )

    registry.register(
        name="summarize_session",
        description=("Summarize a conversation session into a few sentences and store it for "
                     "cross-session recall (later found via recall_sessions)."),
        parameters={
            "type": "object",
            "properties": {"session_id": {"type": "string", "description": "the session id to summarize"}},
            "required": ["session_id"],
        },
        handler=summarize_session,
    )

    # Expose summarization for the service's auto-summary-on-new-session hook.
    registry._summarize_turns = _summarize_turns  # type: ignore[attr-defined]

    def _bg_listing() -> list[dict]:
        with _bg_lock:
            return sorted((_bg_public(e) for e in _bg_tasks.values()),
                          key=lambda e: e.get("started_at") or 0, reverse=True)

    # Handles for the service's background-status surface (/api/status).
    return {"background_tasks": _bg_listing}
