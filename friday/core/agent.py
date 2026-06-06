"""The FRIDAY v2 agent loop.

ONE loop replaces v1's intent_recognizer + planning engine + routing stack:

    build messages (system = persona + facts, + recent history, + user turn)
    loop (bounded):
        resp = provider.generate(messages, tools, stream)
        if resp has tool_calls:
            (speak resp.content preamble if present)
            execute each tool, append results
            continue
        else:
            final answer -> persist -> return

Events (token / preamble / tool_started / tool_finished / turn_completed) are
emitted through an optional ``emit`` callback so the narration layer (Phase 3),
the backend WebSocket (Phase 4), and TTS can all subscribe to the same stream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from friday.core.logger import logger
from friday.core.memory import Database
from friday.core.persona import Persona, load_persona
from friday.core.providers.base import Provider
from friday.core.tools import ToolRegistry

# emit(event_type, payload_dict)
EmitFn = Callable[[str, dict], None]
# on_token(text_chunk)
TokenFn = Callable[[str], None]
# approval(tool_name, args) -> True to proceed (may block awaiting the user)
ApprovalFn = Callable[[str, dict], bool]


@dataclass
class AgentResult:
    content: str
    session_id: str
    tools_used: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class Agent:
    def __init__(
        self,
        provider: Provider,
        registry: ToolRegistry,
        db: Database,
        persona: Optional[Persona] = None,
        *,
        tool_loop_limit: int = 10,
        max_history_turns: int = 12,
        emit: Optional[EmitFn] = None,
    ):
        self.provider = provider
        self.registry = registry
        self.db = db
        self.persona = persona or load_persona()
        self.tool_loop_limit = tool_loop_limit
        self.max_history_turns = max_history_turns
        self._emit = emit or (lambda _e, _p: None)

    # -- sessions ----------------------------------------------------------

    def new_session(self) -> str:
        return self.db.create_session(persona=self.persona.id)

    def set_persona(self, persona_id: str) -> None:
        self.persona = load_persona(persona_id)

    # -- main loop ---------------------------------------------------------

    def process_turn(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        on_token: Optional[TokenFn] = None,
        approval: Optional[ApprovalFn] = None,
    ) -> AgentResult:
        if not session_id:
            session_id = self.new_session()

        self._emit("turn_started", {"session_id": session_id, "text": user_input})

        messages = self._build_messages(user_input, session_id)
        self.db.add_turn(session_id, "user", user_input)

        tool_defs = self.registry.definitions()
        tools_used: list[str] = []
        usage: dict = {}
        final_content = ""

        for step in range(self.tool_loop_limit):
            stream = on_token is not None
            resp = self.provider.generate(messages, tools=tool_defs, stream=stream, on_token=on_token)
            usage = resp.usage or usage

            if not resp.has_tool_calls:
                final_content = resp.content
                break

            # Natural spoken preamble that came alongside the tool call.
            if resp.content.strip():
                self._emit("preamble", {"session_id": session_id, "text": resp.content})

            # Record the assistant's tool-call turn in the working message list.
            messages.append({"role": "assistant", "content": resp.content, "tool_calls": resp.tool_calls})

            for tc in resp.tool_calls:
                tools_used.append(tc.name)
                tool = self.registry.get(tc.name)
                # Gate destructive tools behind the per-turn approval callback.
                # The approval callback owns any user-facing prompt/round-trip
                # (e.g. the server emits its own id'd approval_request), so the
                # agent does not emit a separate approval event here.
                if tool is not None and tool.destructive and approval is not None:
                    if not approval(tc.name, tc.args):
                        from friday.core.tools import ToolResult
                        declined = ToolResult(ok=False, content="", error="User declined the action.")
                        self._emit("tool_finished", {
                            "session_id": session_id, "tool": tc.name,
                            "ok": False, "summary": "declined",
                        })
                        messages.append({"role": "tool", "tool_call_id": tc.id,
                                         "name": tc.name, "content": declined.as_message_content()})
                        continue
                self._emit("tool_started", {"session_id": session_id, "tool": tc.name, "args": tc.args})
                result = self.registry.execute(tc.name, tc.args)
                self.db.log_audit(session_id, tc.name, tc.args, result.as_message_content(), result.ok)
                self._emit("tool_finished", {
                    "session_id": session_id, "tool": tc.name,
                    "ok": result.ok, "summary": result.as_message_content()[:200],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result.as_message_content(),
                })
        else:
            logger.warning("[agent] tool loop limit (%d) reached", self.tool_loop_limit)
            final_content = final_content or "I hit the tool-step limit before finishing. Let's narrow that down."

        self.db.add_turn(session_id, "assistant", final_content, tools_used)
        self._emit("turn_completed", {
            "session_id": session_id, "content": final_content, "tools_used": tools_used,
        })
        return AgentResult(content=final_content, session_id=session_id,
                           tools_used=tools_used, usage=usage)

    # -- helpers -----------------------------------------------------------

    def _build_messages(self, user_input: str, session_id: str) -> list[dict]:
        facts = self.db.all_facts()
        system = self.persona.system_prompt(facts=facts)
        messages: list[dict] = [{"role": "system", "content": system}]
        messages.extend(self.db.recent_turns(session_id, self.max_history_turns))
        messages.append({"role": "user", "content": user_input})
        return messages
