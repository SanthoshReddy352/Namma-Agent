"""OpenAI-compatible HTTP surface (Phase 7f) — Namma as a drop-in backend.

Any client that speaks the OpenAI Chat Completions API — a third-party chat UI,
a script using the ``openai`` SDK, an editor plugin — can point its base URL at
this server and talk to the **whole agent**: tools, memory, persona, approval
policy. That is the cheap substitute for Hermes's separate IDE/ACP adapter: one
route instead of a second integration surface.

Two things are deliberately different from a raw model API, because Namma is an
agent and not a model:

*The last user message is the turn.* Namma keeps its own conversation state
(sessions, memory, compaction), so the client's replayed ``messages`` history is
not re-fed as context — that would double the history and fight compaction.
Earlier messages are used only to pick the session. A ``system`` message is
prepended to the turn text as a one-off instruction, since the persona is
Namma's own.

*Sessions come from the ``user`` field.* Two calls with the same ``user`` land
in the same Namma session, so a third-party frontend gets real continuity
(including memory) instead of a fresh amnesiac chat per request. The mapping is
recovered from the session title after a restart, so continuity survives one.

**Destructive tools are declined here.** An HTTP caller has no approval channel
— the same rule routines and watchers run under (Phase 8 / Phase 2). Silently
running them because the request came over HTTP would be the wrong default.

Auth: `/v1/*` is behind the Phase 6a token exactly like `/api/*` (enforced in
``api.py``'s middleware). It executes real tools, so an open `/v1` would be a
bigger hole than any read-only API route.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from namma_agent.core.logger import logger

#: Session titles for API-created chats carry this prefix, which is how a
#: ``user`` is mapped back to its session after a restart.
SESSION_PREFIX = "API · "


class ChatMessage(BaseModel):
    role: str = "user"
    content: Any = ""          # str, or the list-of-parts form clients may send


class ChatCompletionsBody(BaseModel):
    model: str = ""
    messages: list[ChatMessage] = []
    stream: bool = False
    user: str = ""
    # Accepted and ignored — a model's sampling knobs don't apply to an agent
    # turn, and silently 400ing on them would break otherwise-fine clients.
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


def _text_of(content: Any) -> str:
    """Flatten OpenAI's content shapes to plain text (str, or a parts list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(p for p in parts if p)
    return str(content or "")


def _turn_input(messages: list[ChatMessage]) -> str:
    """The text to run: the last user message, with any system message prefixed
    as a one-off instruction."""
    user_text = ""
    for message in reversed(messages):
        if message.role == "user":
            user_text = _text_of(message.content).strip()
            break
    system = "\n".join(_text_of(m.content).strip() for m in messages
                       if m.role == "system" and _text_of(m.content).strip())
    if system:
        return f"[instructions for this message]\n{system}\n\n{user_text}"
    return user_text


def register_openai_api(app: FastAPI, service) -> None:
    """Mount ``/v1/chat/completions`` and ``/v1/models`` onto the app."""

    # user id → session id. Populated lazily; the DB lookup below means a
    # restart doesn't lose continuity.
    sessions: dict[str, str] = {}

    def _model_ids() -> list[str]:
        from namma_agent.config import configured_models
        ids = []
        for entry in configured_models(service.config):
            model = str(entry.get("model") or "").strip()
            if model and model not in ids:
                ids.append(model)
        if not ids:
            default = str((service.config.get("provider") or {}).get("model") or "")
            if default:
                ids.append(default)
        return ids

    def _session_for(user: str) -> str:
        key = (user or "default").strip() or "default"
        if key in sessions:
            return sessions[key]
        title = f"{SESSION_PREFIX}{key}"
        # Recover the session after a restart rather than stranding its history.
        try:
            for row in service.db.list_sessions(limit=200):
                if (row.get("title") or "") == title:
                    sessions[key] = row["id"]
                    return row["id"]
        except Exception as exc:  # noqa: BLE001 — a lookup failure just means new
            logger.debug("[openai-api] session lookup failed: %s", exc)
        session_id = service.db.create_session()
        service.db.rename_session(session_id, title)
        sessions[key] = session_id
        return session_id

    def _completion_id() -> str:
        return f"chatcmpl-{uuid.uuid4().hex[:24]}"

    def _run(text: str, session_id: str, model: str, on_token=None):
        # No approval channel over HTTP → destructive tools are declined, the
        # same contract routines and watchers run under.
        return service.run_turn(
            text, session_id=session_id, on_token=on_token,
            approval=lambda _name, _args: False,
            model_id=model or None)

    @app.get("/v1/models")
    def list_models():
        now = int(time.time())
        return {"object": "list",
                "data": [{"id": mid, "object": "model", "created": now,
                          "owned_by": "namma-agent"} for mid in _model_ids()]}

    @app.post("/v1/chat/completions")
    def chat_completions(body: ChatCompletionsBody):
        text = _turn_input(body.messages)
        if not text:
            return {"error": {"message": "no user message in `messages`",
                              "type": "invalid_request_error"}}
        session_id = _session_for(body.user)
        model = body.model or (_model_ids() or [""])[0]
        created = int(time.time())
        completion_id = _completion_id()

        if not body.stream:
            result = _run(text, session_id, body.model)
            usage = result.usage or {}
            return {
                "id": completion_id, "object": "chat.completion",
                "created": created, "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": result.content},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": int(usage.get("input_tokens") or 0),
                    "completion_tokens": int(usage.get("output_tokens") or 0),
                    "total_tokens": int(usage.get("input_tokens") or 0)
                    + int(usage.get("output_tokens") or 0),
                },
                # Not in the OpenAI schema — additive, so compliant clients
                # ignore it while Namma-aware ones can follow the conversation.
                "namma": {"session_id": session_id,
                          "tools_used": result.tools_used or []},
            }

        def _sse():
            def chunk(delta: dict, finish: Optional[str] = None) -> str:
                payload = {"id": completion_id, "object": "chat.completion.chunk",
                           "created": created, "model": model,
                           "choices": [{"index": 0, "delta": delta,
                                        "finish_reason": finish}]}
                return f"data: {json.dumps(payload)}\n\n"

            yield chunk({"role": "assistant", "content": ""})
            queue: list[str] = []
            try:
                # run_turn streams into on_token; collect and flush after, since
                # this generator is synchronous. Clients still get the chunked
                # framing they expect.
                result = _run(text, session_id, body.model,
                              on_token=lambda t: queue.append(t))
                for token in queue:
                    yield chunk({"content": token})
                if not queue and result.content:
                    yield chunk({"content": result.content})
            except Exception as exc:  # noqa: BLE001 — the stream must end cleanly
                logger.warning("[openai-api] turn failed: %s", exc)
                yield chunk({"content": f"\n[error: {exc}]"})
            yield chunk({}, finish="stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(_sse(), media_type="text/event-stream")
