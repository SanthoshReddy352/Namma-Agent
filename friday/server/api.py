"""FastAPI + WebSocket backend for FRIDAY v2.

REST: health, config, tools, persona.
WebSocket ``/ws``: the live turn channel. The client sends ``user_input``; the
server streams a typed event protocol back:

    {"type": "token",            "text": ...}
    {"type": "preamble",         "text": ...}
    {"type": "tool_started",     "tool": ..., "args": ...}
    {"type": "approval_request", "id": ..., "tool": ..., "args": ...}
    {"type": "tool_finished",    "tool": ..., "ok": ...}
    {"type": "turn_completed",   "content": ..., "tools_used": ...}
    {"type": "turn_result",      "content": ..., "session_id": ...}

For destructive tools the server emits ``approval_request`` and waits for the
client's ``{"type": "approval_response", "id": ..., "approved": bool}``.
"""
from __future__ import annotations

import asyncio
import itertools
import queue
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from friday.core.logger import logger
from friday.service import FridayService

_WEBUI_DIST = Path(__file__).resolve().parent.parent / "webui" / "dist"


class PersonaBody(BaseModel):
    id: str


def create_app(service: Optional[FridayService] = None) -> FastAPI:
    service = service or FridayService()
    app = FastAPI(title="FRIDAY v2")
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/config")
    def config():
        return service.info()

    @app.get("/api/tools")
    def tools():
        return {"tools": service.registry.definitions()}

    @app.post("/api/persona")
    def set_persona(body: PersonaBody):
        service.set_persona(body.id)
        return {"persona": service.persona.id}

    @app.post("/api/session")
    def new_session():
        return {"session_id": service.new_session()}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        outgoing: asyncio.Queue = asyncio.Queue()
        approvals: dict[str, queue.Queue] = {}
        counter = itertools.count()

        async def sender():
            while True:
                item = await outgoing.get()
                if item is None:
                    return
                await websocket.send_json(item)

        sender_task = asyncio.create_task(sender())

        def push(item: dict):
            loop.call_soon_threadsafe(outgoing.put_nowait, item)

        def sink(event: str, payload: dict):
            push({"type": event, **payload})

        def on_token(text: str):
            push({"type": "token", "text": text})

        def approval(tool: str, args: dict) -> bool:
            aid = str(next(counter))
            resp_q: queue.Queue = queue.Queue()
            approvals[aid] = resp_q
            push({"type": "approval_request", "id": aid, "tool": tool, "args": args})
            try:
                return bool(resp_q.get(timeout=300))
            except queue.Empty:
                return False

        async def run_turn(text: str, session_id: Optional[str]):
            try:
                result = await asyncio.to_thread(
                    service.run_turn, text, session_id, sink, on_token, approval
                )
                push({
                    "type": "turn_result",
                    "content": result.content,
                    "session_id": result.session_id,
                    "tools_used": result.tools_used,
                })
            except Exception as exc:  # noqa: BLE001
                logger.error("[ws] turn failed: %s", exc)
                push({"type": "error", "message": str(exc)})

        try:
            while True:
                msg = await websocket.receive_json()
                mtype = msg.get("type")
                if mtype == "user_input":
                    asyncio.create_task(run_turn(msg.get("text", ""), msg.get("session_id")))
                elif mtype == "approval_response":
                    q = approvals.pop(msg.get("id"), None)
                    if q is not None:
                        q.put(bool(msg.get("approved")))
                elif mtype == "ping":
                    push({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            push(None)
            await sender_task

    # Serve the built GUI (Phase 5) if present.
    if _WEBUI_DIST.exists():
        app.mount("/", StaticFiles(directory=str(_WEBUI_DIST), html=True), name="webui")

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    run()
