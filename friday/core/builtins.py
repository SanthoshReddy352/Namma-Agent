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


def register_memory_tools(registry: ToolRegistry, db: Database) -> None:
    """Register remember_fact / recall_facts against the database."""

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
        sub = Agent(provider, sub_registry, db, persona=agent.persona,
                    tool_loop_limit=8, max_history_turns=4)
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
