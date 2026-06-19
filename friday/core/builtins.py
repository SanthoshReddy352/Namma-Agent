"""Built-in tools wired to core services (memory, persona, delegation).

These are always available regardless of which capability modules are loaded.
Phase 7 ports the domain modules (file/web/security/...) on top of this.

Wave 4 adds the tools that need live core handles (DB / provider / agent), so
they can't live in the stateless auto-discovery package under ``friday/tools``:

  * memory:   remember_fact, recall_facts, forget_fact, search_conversations
  * delegate: delegate_task (one sub-agent tool replacing v1 Delegate/MoA/Research)
  * persona:  switch_persona, list_personas
"""
from __future__ import annotations

from friday.core.memory import Database
from friday.core.persona import _PERSONA_DIR, load_persona
from friday.core.tools import ToolRegistry, ToolResult

#: Read-only tools a delegated sub-agent may use to research/answer a sub-task.
_RESEARCH_TOOLS = (
    "web_search", "web_extract", "web_crawl", "read_document",
    "get_weather", "get_news", "recall_facts", "system_info",
)


def register_memory_tools(registry: ToolRegistry, db: Database, notes=None) -> None:
    """Register memory tools against the database (and optional MemoryNotes).

    Structured facts (key/value) + conversation/session recall live on ``db``;
    free-form curated prose (USER.md / MEMORY.md) lives on ``notes`` when given.
    """

    def remember_fact(args: dict) -> ToolResult:
        key = (args.get("key") or "").strip()
        value = (args.get("value") or "").strip()
        if not key or not value:
            return ToolResult(ok=False, content="", error="both 'key' and 'value' are required")
        db.save_fact(key, value, category=args.get("category", "general"))
        return ToolResult(ok=True, content=f"Saved: {key} = {value}")

    def recall_facts(args: dict) -> ToolResult:
        query = (args.get("query") or "").strip()
        hits = db.search_facts(query) if query else db.all_facts()
        if not hits:
            return ToolResult(ok=True, content="No matching facts.")
        lines = "\n".join(f"- {h['key']}: {h['value']}" for h in hits)
        return ToolResult(ok=True, content=lines, data=hits)

    registry.register(
        name="remember_fact",
        description="Save a durable fact about the user for future conversations.",
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

    def forget_fact(args: dict) -> ToolResult:
        key = (args.get("key") or "").strip()
        if not key:
            return ToolResult(ok=False, content="", error="'key' is required")
        removed = db.delete_fact(key)
        if not removed:
            return ToolResult(ok=False, content="", error=f"no fact named {key!r}")
        return ToolResult(ok=True, content=f"Forgot: {key}")

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
        name="recall_facts",
        description="Search saved facts about the user. Omit query to list all.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "keywords to search; empty lists all"},
            },
        },
        handler=recall_facts,
    )

    registry.register(
        name="forget_fact",
        description="Delete a saved fact about the user by its key.",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string", "description": "the fact key to forget"}},
            "required": ["key"],
        },
        handler=forget_fact,
        destructive=True,
    )

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
        if scope in ("facts", "all"):
            done["facts"] = db.clear_facts()
        if scope in ("conversations", "sessions", "all"):
            done["conversations"] = db.clear_conversations()
        if scope in ("notes", "all") and notes is not None:
            notes.reset()
            done["notes"] = True
        return ToolResult(ok=True, content=f"Cleared memory (scope={scope}): {done}", data=done)

    registry.register(
        name="clear_memory",
        description=("Erase stored memory. scope: 'facts' (user facts), 'conversations' "
                     "(chat history + summaries), 'notes' (USER.md/MEMORY.md), or 'all'."),
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["facts", "conversations", "notes", "all"],
                          "description": "what to wipe (default all)"},
            },
        },
        handler=clear_memory,
        destructive=True,
    )

    # Scope-aware memory: when the current turn belongs to a project (or learning
    # topic), durable details are saved to that scope's dedicated memory, resolved
    # from the turn-local session id. No-op outside a scoped session.
    def _scoped_note(args: dict, scope_type: str, label: str) -> ToolResult:
        from friday.core.interactive import get_current_session

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
                                  error="This chat is not in a project; use remember_note instead.")
        else:
            from friday.core.learning import topic_for_session  # lazy (Wave 3)
            topic = topic_for_session(db, sid)
            scope_id = topic["id"] if topic else None
            if not scope_id:
                return ToolResult(ok=False, content="", error="Not in a learning topic.")
        db.add_scope_memory(scope_type, scope_id, content)
        return ToolResult(ok=True, content=f"Saved to {label} memory.")

    registry.register(
        name="remember_project_note",
        description=("Save a durable detail to the CURRENT project's dedicated memory so it is "
                     "never forgotten (a decision, requirement, name, preference, or fact about "
                     "the project). Only meaningful inside a project chat."),
        parameters={
            "type": "object",
            "properties": {"note": {"type": "string", "description": "the project detail to remember"}},
            "required": ["note"],
        },
        handler=lambda a: _scoped_note(a, "project", "project"),
    )

    if notes is None:
        return

    def read_memory(_args: dict) -> ToolResult:
        block = notes.block() or "(memory notes are empty)"
        return ToolResult(ok=True, content=block)

    def remember_note(args: dict) -> ToolResult:
        note = (args.get("note") or "").strip()
        if not note:
            return ToolResult(ok=False, content="", error="'note' is required")
        notes.append_note(note)
        return ToolResult(ok=True, content="Noted to long-term memory.")

    def update_user_profile(args: dict) -> ToolResult:
        content = (args.get("content") or "").strip()
        if not content:
            return ToolResult(ok=False, content="", error="'content' is required")
        if args.get("mode") == "replace":
            notes.write_user(content)
            return ToolResult(ok=True, content="Rewrote the user profile.")
        notes.write_user(notes.read_user().rstrip() + "\n" + content)
        return ToolResult(ok=True, content="Updated the user profile.")

    registry.register(
        name="read_memory",
        description="Read FRIDAY's curated long-term notes (USER profile + MEMORY working notes).",
        parameters={"type": "object", "properties": {}},
        handler=read_memory,
    )
    registry.register(
        name="remember_note",
        description=("Append a durable free-form note to long-term MEMORY (for context that "
                     "isn't a single key/value fact — ongoing projects, decisions, how the user "
                     "likes to work)."),
        parameters={
            "type": "object",
            "properties": {"note": {"type": "string", "description": "the note to remember"}},
            "required": ["note"],
        },
        handler=remember_note,
    )
    registry.register(
        name="update_user_profile",
        description=("Add to (or, with mode='replace', rewrite) the curated USER profile — a "
                     "narrative of who the user is and how they like to work."),
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "markdown to add or the full new profile"},
                "mode": {"type": "string", "enum": ["append", "replace"], "description": "default append"},
            },
            "required": ["content"],
        },
        handler=update_user_profile,
    )


def register_project_tools(registry: ToolRegistry, db: Database) -> None:
    """Project document tools (multi-document RAG). Scope resolves from the
    turn-local session: both tools only work inside a project chat."""
    from friday.core.interactive import get_current_session

    def _project_id() -> str | None:
        sid = get_current_session()
        sess = db.get_session(sid) if sid else None
        return (sess or {}).get("project_id")

    def search_project_documents(args: dict) -> ToolResult:
        from friday.core.docindex import format_excerpts, retrieve

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
                            get_comms=None, config: dict | None = None) -> None:
    """Learning-Room teacher tools: plan the path, mark progress, quiz, score the
    learner, save topic memory, and (from a normal chat) suggest the Learning Room.
    Scope is resolved from the turn-local session via the learning topic it belongs
    to; quiz/suggestion push typed events straight to the browser.

    ``get_comms`` lazily resolves the CommsManager (it's built after the registry)
    so module-completion progress can be pushed to Telegram when configured."""
    from friday.core.interactive import emit_event, get_current_session

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
        # Resolve the module from THIS chat thread first — the global "current"
        # pointer can lag the thread the teacher is actually in.
        own = _session_module(topic)
        mid = (args.get("module_id") or (own or {}).get("id")
               or topic.get("progress", {}).get("current_module") or "").strip()
        if not mid:
            return ToolResult(ok=False, content="", error="no current module to complete")
        module = next((m for m in (topic.get("plan") or []) if m["id"] == mid), None)
        # Cross-module continuity: persist a recap (concepts + the running example)
        # to topic memory so EVERY later module teaches on top of it.
        recap = (args.get("recap") or "").strip()
        if recap and module:
            db.add_scope_memory("learning", topic["id"],
                                f"Module recap — {module['title']}: {recap}")
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
        question = (args.get("question") or "").strip()
        options = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
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
            "options": options,
            "answer_index": answer_index,
            "explanation": (args.get("explanation") or "").strip(),
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
        "options, the 0-based answer_index, and a short explanation.",
        {"type": "object", "properties": {
            "question": {"type": "string"},
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

    This is the hermes learning loop, adapted to FRIDAY's single agent loop:
    the model loads a relevant playbook with ``use_skill`` and, after solving a
    novel multi-step task, saves the procedure with ``create_skill`` (refining it
    later with ``update_skill``). All of it is visible in the tool timeline."""

    def list_skills(_args: dict) -> ToolResult:
        skills = store.all()
        if not skills:
            return ToolResult(ok=True, content="No skills installed yet.")
        lines = [f"- {s.name} [{s.source}]: {s.one_line(180)}" for s in skills]
        return ToolResult(ok=True, content="Available skills:\n" + "\n".join(lines),
                          data={"skills": [s.name for s in skills]})

    def use_skill(args: dict) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, content="", error="'name' is required")
        body = store.render(name)
        if body is None:
            avail = ", ".join(s.name for s in store.all()) or "(none)"
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
        description="List FRIDAY's available skills (procedural playbooks) and their descriptions.",
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
                     "task well, so FRIDAY can reuse it next time. Write the body as a clear "
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


def register_agent_tools(registry: ToolRegistry, agent, provider, db) -> None:
    """Register delegate_task + persona tools. Needs the live agent/provider/db.

    ``delegate_task`` runs a bounded sub-agent over a read-only research toolset
    (a fresh registry that excludes itself, so delegation can't recurse).
    """
    from friday.core.agent import Agent  # local import avoids an import cycle

    def delegate_task(args: dict) -> ToolResult:
        task = (args.get("task") or "").strip()
        if not task:
            return ToolResult(ok=False, content="", error="'task' is required")
        sub_registry = ToolRegistry()
        for name in _RESEARCH_TOOLS:
            tool = registry.get(name)
            if tool is not None:
                sub_registry.add(tool)
        # Inherit the main agent's tool-step budget so an unlimited config
        # (tool_loop_limit <= 0) lets deep research run to completion instead of
        # being capped at a hidden sub-agent limit.
        sub = Agent(provider, sub_registry, db, persona=agent.persona,
                    tool_loop_limit=agent.tool_loop_limit, max_history_turns=4)
        instruction = (
            "You are a focused sub-task/research agent. Use your tools to actually "
            "complete the task below, then report concise findings (with source URLs "
            "where relevant). Do not ask follow-up questions.\n\nTASK: " + task
        )
        try:
            result = sub.process_turn(instruction, session_id=sub.new_session())
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content="", error=f"delegation failed: {exc}")
        return ToolResult(ok=True, content=result.content or "(no findings)",
                          data={"tools_used": result.tools_used})

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
        return sorted(p.stem for p in _PERSONA_DIR.glob("*.yaml"))

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
        ids = _persona_ids()
        if not ids:
            return ToolResult(ok=True, content="No personas installed.")
        lines = [f"- {pid}: {load_persona(pid).name}" for pid in ids]
        return ToolResult(ok=True, content="Available personas:\n" + "\n".join(lines),
                          data={"current": agent.persona.id, "available": ids})

    registry.register(
        name="delegate_task",
        description=("Hand a self-contained research or multi-step sub-task to a focused "
                     "sub-agent and get its findings back. Use for web research, multi-source "
                     "lookups, or anything worth isolating from the main conversation."),
        parameters={
            "type": "object",
            "properties": {"task": {"type": "string", "description": "the sub-task to complete, stated fully"}},
            "required": ["task"],
        },
        handler=delegate_task,
    )

    registry.register(
        name="switch_persona",
        description="Switch FRIDAY's active persona for the rest of the session.",
        parameters={
            "type": "object",
            "properties": {"persona": {"type": "string", "description": "persona id, e.g. 'friday_concise'"}},
            "required": ["persona"],
        },
        handler=switch_persona,
    )

    registry.register(
        name="list_personas",
        description="List the available personas and which one is active.",
        parameters={"type": "object", "properties": {}},
        handler=list_personas,
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
