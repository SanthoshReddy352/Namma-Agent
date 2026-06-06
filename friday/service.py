"""FridayService — assembles the v2 runtime (provider + tools + memory + agent
+ narration) behind one object that the backend server and tests drive.

Keeping wiring here (not in the FastAPI layer) means the same service can be used
headless, from tests, or behind any front end.
"""
from __future__ import annotations

from typing import Callable, Optional

from friday.config import load_config
from friday.core.agent import Agent, AgentResult
from friday.core.builtins import register_memory_tools
from friday.core.events import fanout
from friday.core.memory import Database
from friday.core.narration import NarrationEngine
from friday.core.persona import load_persona
from friday.core.providers import from_config
from friday.core.tools import ToolRegistry

EmitFn = Callable[[str, dict], None]
TokenFn = Callable[[str], None]
ApprovalFn = Callable[[str, dict], bool]
SpeakFn = Callable[[str], None]


class FridayService:
    def __init__(
        self,
        config: Optional[dict] = None,
        speak: Optional[SpeakFn] = None,
        provider=None,
        registry: Optional[ToolRegistry] = None,
        db: Optional[Database] = None,
    ):
        self.config = config or load_config()
        conv = self.config.get("conversation", {})
        db_path = (self.config.get("database") or {}).get("path", "data/friday.db")

        self.db = db or Database(db_path)
        self.registry = registry or ToolRegistry()
        register_memory_tools(self.registry, self.db)
        self.provider = provider or from_config(self.config)
        self.persona = load_persona(self.config.get("persona", "friday_core"))

        self.narration = NarrationEngine(
            speak or (lambda _t: None),
            progress_delays=tuple(conv.get("progress_delays_s", [4.0, 12.0, 25.0])),
        )

        self.agent = Agent(
            self.provider, self.registry, self.db, self.persona,
            tool_loop_limit=conv.get("tool_loop_limit", 10),
            max_history_turns=conv.get("max_history_turns", 12),
        )

    # -- introspection -----------------------------------------------------

    def info(self) -> dict:
        prov = self.provider
        names = getattr(prov, "_providers", None)
        provider_names = [p.name for p in names] if names else [prov.name]
        return {
            "provider": provider_names,
            "model": getattr(prov, "model", ""),
            "persona": self.persona.id,
            "tools": self.registry.names(),
        }

    def set_persona(self, persona_id: str) -> None:
        self.persona = load_persona(persona_id)
        self.agent.persona = self.persona

    def new_session(self) -> str:
        return self.agent.new_session()

    # -- turn driving ------------------------------------------------------

    def run_turn(
        self,
        text: str,
        session_id: Optional[str] = None,
        sink: Optional[EmitFn] = None,
        on_token: Optional[TokenFn] = None,
        approval: Optional[ApprovalFn] = None,
    ) -> AgentResult:
        """Run one turn. Events fan out to the narration engine and the given sink."""
        emit = fanout(self.narration.handle_event, sink)
        # Temporarily attach the combined emit for this turn (thread-confined use).
        self.agent._emit = emit  # type: ignore[attr-defined]
        return self.agent.process_turn(text, session_id=session_id, on_token=on_token, approval=approval)
