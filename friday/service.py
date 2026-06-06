"""FridayService — assembles the v2 runtime (provider + tools + memory + agent
+ narration) behind one object that the backend server and tests drive.

Keeping wiring here (not in the FastAPI layer) means the same service can be used
headless, from tests, or behind any front end.
"""
from __future__ import annotations

from typing import Callable, Optional

from friday.config import load_config
from friday.core.agent import Agent, AgentResult
from friday.core.builtins import register_agent_tools, register_memory_tools
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
        # Auto-discover capability tools (file/shell/system/apps/...). Skipped
        # when a registry is injected (tests provide their own minimal set).
        self.mcp = None
        if registry is None:
            from friday.tools import load_tools

            load_tools(self.registry)
            # Wave 5: connect configured MCP servers and register their tools.
            self.mcp = self._build_mcp(self.config, self.registry)
        self.provider = provider or from_config(self.config)
        self.persona = load_persona(self.config.get("persona", "friday_core"))

        # Voice: local Piper TTS (output + narration) and local STT (push-to-talk).
        # Both degrade gracefully when binaries/models/hardware are absent.
        self.tts = self._build_tts(self.config)
        self._stt = None  # lazy (loads a whisper model on first use)
        speak_fn = speak or (self.tts.speak if self.tts else (lambda _t: None))

        self.narration = NarrationEngine(
            speak_fn,
            progress_delays=tuple(conv.get("progress_delays_s", [4.0, 12.0, 25.0])),
        )
        self._speak = speak_fn

        self.agent = Agent(
            self.provider, self.registry, self.db, self.persona,
            tool_loop_limit=conv.get("tool_loop_limit", 10),
            max_history_turns=conv.get("max_history_turns", 12),
        )

        # Wave 4: delegate_task + persona tools need the live agent/provider/db.
        # Skipped when a registry is injected (tests provide their own minimal set).
        if registry is None:
            register_agent_tools(self.registry, self.agent, self.provider, self.db)

        # Wave 5: messaging channels (Telegram/Discord). The Telegram inbound
        # bridge routes phone messages through a full turn. Off unless tokens
        # are set; skipped under injected registry (tests) to avoid net threads.
        self.comms = self._build_comms() if registry is None else None
        if self.comms is not None and self.comms.telegram.available:
            self.comms.start_inbound(lambda text: self.run_turn(text).content)

        # Wave 5: fire due reminders in the background (speak + notify).
        self.reminders = self._build_reminder_runner() if registry is None else None
        if self.reminders is not None:
            self.reminders.start()

    # -- mcp ---------------------------------------------------------------

    @staticmethod
    def _build_mcp(config: dict, registry):
        try:
            from friday.mcp import MCPManager

            mcp = MCPManager.from_config(config)
            mcp.register_into(registry)
            return mcp
        except Exception as exc:  # noqa: BLE001
            from friday.core.logger import logger
            logger.warning("[service] MCP setup failed: %s", exc)
            return None

    # -- reminders ---------------------------------------------------------

    def _build_reminder_runner(self):
        try:
            from friday.core.reminder_runner import ReminderRunner

            def on_fire(reminder: dict) -> None:
                msg = f"Reminder: {reminder.get('text', '')}"
                self._speak(msg)
                if self.comms is not None and self.comms.any_available:
                    self.comms.send(msg)

            interval = float((self.config.get("scheduler") or {}).get("poll_seconds", 30))
            return ReminderRunner(on_fire, interval=interval)
        except Exception:  # noqa: BLE001
            return None

    # -- comms -------------------------------------------------------------

    @staticmethod
    def _build_comms():
        try:
            from friday.comms import CommsManager

            return CommsManager()
        except Exception:  # noqa: BLE001
            return None

    # -- voice -------------------------------------------------------------

    @staticmethod
    def _build_tts(config: dict):
        if not (config.get("voice") or {}).get("enabled", True):
            return None
        try:
            from friday.voice.tts import PiperTTS

            return PiperTTS(config)
        except Exception:  # noqa: BLE001
            return None

    @property
    def stt(self):
        if self._stt is None:
            try:
                from friday.voice.stt import LocalSTT

                self._stt = LocalSTT(self.config)
            except Exception:  # noqa: BLE001
                self._stt = False
        return self._stt or None

    def stop_speaking(self) -> None:
        if self.tts:
            self.tts.stop()

    def transcribe_once(self) -> str:
        stt = self.stt
        return stt.record_until_silence() if stt and stt.available() else ""

    def _speak_final(self, event: str, payload: dict) -> None:
        """Speak the final answer when a turn completes (preamble/progress are
        already spoken by the narration engine)."""
        if event == "turn_completed" and payload.get("content"):
            self._speak(payload["content"])

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
        """Run one turn. Events fan out to narration, final-answer speech, and the sink."""
        emit = fanout(self.narration.handle_event, self._speak_final, sink)
        # Temporarily attach the combined emit for this turn (thread-confined use).
        self.agent._emit = emit  # type: ignore[attr-defined]
        return self.agent.process_turn(text, session_id=session_id, on_token=on_token, approval=approval)
