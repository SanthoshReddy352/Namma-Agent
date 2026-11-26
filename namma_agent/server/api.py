"""FastAPI + WebSocket backend for Namma Agent.

REST: health, config, tools, persona.
WebSocket ``/ws``: the live turn channel. The client sends ``user_input``; the
server streams a typed event protocol back:

    {"type": "token",            "text": ...}
    {"type": "preamble",         "text": ..., "visible": ...}  # visible = canonical
    #   bubble content so far (media only) — the client rewinds the streamed bubble
    #   to it so progress lines live in the activity timeline, not the chat bubble.
    #   Omitted on teaching turns, whose explanations stay in the answer.
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
import json
import queue
import re
import threading
import time
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from namma_agent.config import data_dir as _data_dir
from namma_agent.core.logger import logger
from namma_agent.core.providers.base import usage_tokens
from namma_agent.service import NammaAgentService

_UPLOAD_DIR = _data_dir() / "uploads"
_DEFAULT_MAX_UPLOAD_MB = 50


def _upload_limit_bytes(config: Optional[dict]) -> int:
    """``server.max_upload_mb`` (default 50) in bytes."""
    try:
        mb = float(((config or {}).get("server") or {}).get("max_upload_mb") or _DEFAULT_MAX_UPLOAD_MB)
    except (TypeError, ValueError):
        mb = _DEFAULT_MAX_UPLOAD_MB
    return int(max(mb, 0.001) * 1024 * 1024)


def _unique_upload_path(directory: Path, name: str) -> Path:
    """``directory/name``, or ``name (2).ext``, ``name (3).ext``… if taken."""
    dest = directory / name
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while dest.exists():
        dest = directory / f"{stem} ({n}){suffix}"
        n += 1
    return dest
_MEDIA_DIR = _data_dir() / "media"

_WEBUI_DIST = Path(__file__).resolve().parent.parent / "webui" / "dist"


class PersonaBody(BaseModel):
    id: str


class PersonaSaveBody(BaseModel):
    id: str = ""
    name: str = ""
    identity: str = ""
    tone: str = ""
    dos: list | str = []      # list, or newline-separated text from the UI
    donts: list | str = []


class PersonaGenerateBody(BaseModel):
    description: str = ""


class OnboardingBody(BaseModel):
    name: str = ""
    facts: dict = {}


class SettingsBody(BaseModel):
    config: dict = {}   # deep-merged into user_config.yaml
    env: dict = {}      # written to .env (e.g. API keys)


class TrustBody(BaseModel):
    channel: str
    level: str


class SecretBody(BaseModel):
    name: str
    value: str = ""


class SecretsMigrateBody(BaseModel):
    scrub: bool = False


class McpServerToggleBody(BaseModel):
    name: str
    enabled: bool = True


class McpServersBody(BaseModel):
    servers: list = []


class McpServerBody(BaseModel):
    server: dict
    replace: bool = False


class McpNameBody(BaseModel):
    name: str


class McpImportBody(BaseModel):
    config: Any = None
    url: str = ""


class SetupSecretBody(BaseModel):
    name: str
    value: str


class SetupVerifyBody(BaseModel):
    provider: str
    model: str = ""


class ActiveModelBody(BaseModel):
    model_id: str = ""


class SetupOnboardBody(BaseModel):
    type: str
    model: str
    key: str = ""
    base_url: str = ""


class SetupMailBody(BaseModel):
    address: str
    provider: str = "custom"
    id: str = ""
    imap_host: str = ""
    smtp_host: str = ""
    imap_port: int = 0
    smtp_port: int = 0


class McpPresetBody(BaseModel):
    preset: str
    params: dict = {}
    name: str = ""


class MemoryRecallBody(BaseModel):
    query: str = ""
    top_k: int = 8
    include_expired: bool = False


class MemoryRememberBody(BaseModel):
    text: str = ""


class MemoryForgetBody(BaseModel):
    query: str = ""
    item_id: str = ""
    everything: bool = False
    hard: bool = False       # hard-delete instead of invalidate


class MemoryGraphMergeBody(BaseModel):
    """Phase 10: fold entity ``source`` into ``target``."""
    source: str = ""
    target: str = ""


class MemoryGraphEntityBody(BaseModel):
    """Phase 10: rename / retype an entity."""
    name: str = ""
    type: str = ""


class MemoryCoreBody(BaseModel):
    block: str = "user"      # user | agent
    action: str = "add"      # add | replace | remove
    text: str = ""
    entry_id: int = 0        # addresses an exact entry (from GET /api/memory/core)
    old_text: str = ""       # …or substring matching (the tool-side contract)


class MemorySettingsBody(BaseModel):
    settings: dict = {}      # prefetch, k, salience_min_chars, budget_per_hour,
                             # write_approval


class MemoryPendingBody(BaseModel):
    """Phase 7c: resolve the write-approval queue."""
    item_id: str = ""
    approve: bool = True
    all: bool = False        # resolve every pending fact the same way


class MemoryClearBody(BaseModel):
    scope: str = "all"  # facts | conversations | notes | all


class UninstallBody(BaseModel):
    scope: str = "all"  # all | keep-data


class NotifyBody(BaseModel):
    title: str = "Namma Agent"
    body: str = ""


class TtsBody(BaseModel):
    """POST /api/voice/tts — text to read with the OS voice (Phase 9)."""
    text: str
    voice: str = ""
    rate: int = 0


class AutostartBody(BaseModel):
    enabled: bool = False


class ConfiguredProvidersBody(BaseModel):
    providers: list = []   # [{id?, label, type, base_url, api_key_env}, …]


class ConfiguredModelsBody(BaseModel):
    models: list = []   # [{id?, label, provider, model}, …]


class PackExportBody(BaseModel):
    skills: list = []   # skill names to include
    tools: list = []    # tool file names to include


class SkillToggleBody(BaseModel):
    name: str = ""
    enabled: bool = True


class SkillNameBody(BaseModel):
    name: str = ""


class ToolToggleBody(BaseModel):
    name: str = ""
    enabled: bool = True


class ToolsetToggleBody(BaseModel):
    category: str = ""
    enabled: bool = True


class ProjectBody(BaseModel):
    name: str = ""
    description: str = ""


class RenameBody(BaseModel):
    title: str = ""


class FileChatBody(BaseModel):
    project_id: str | None = None  # null/"" to unfile


class ScopeMemoryBody(BaseModel):
    content: str = ""


class LearningBody(BaseModel):
    topic: str = ""
    depth: str = "solid"


class LearningSettingsBody(BaseModel):
    # {"self_review": {enabled, weekday, at}, "learning": {notify_progress,
    #  nudge_after_days}} — only the keys present are changed.
    settings: dict = {}


class PlanBody(BaseModel):
    modules: list = []


class SwitchModelBody(BaseModel):
    session_id: str = ""
    model: str = ""


class QuizResultBody(BaseModel):
    question: str = ""
    correct: bool = False
    module_id: str | None = None
    user_answer: str = ""
    quiz_id: str = ""              # ties the answer back to the persisted card
    options: list = []
    answer_index: int | None = None
    picked_index: int | None = None
    explanation: str = ""


_DEPTH_PHRASE = {
    "curious": "a friendly overview",
    "solid": "a solid, usable understanding",
    "deep": "a deep understanding, including the why",
    "expert": "a rigorous, expert-level command",
}


def _path_chat_intro(topic: dict) -> str:
    """A seeded opening for the topic's path chat so it never looks like an
    empty new chat (no model call)."""
    title = topic.get("title") or "this topic"
    n = len(topic.get("plan") or [])
    lines = [f"🗺️ This is the **path chat** for **{title}** — your home base for the whole "
             f"journey{f' ({n} modules)' if n else ''}."]
    lines.append("\nHere you can:")
    lines.append("- **Ask anything about the path** — why it's ordered this way, what a module covers, where a subtopic lives.")
    lines.append("- **Reshape it** — add, drop, split, or reorder modules; change the pace.")
    lines.append("- **Set standing preferences** — tell me *how* to teach you from now on "
                 "(e.g. “research every answer”, “use cricket examples”, “always show code”) "
                 "and I'll apply it in every module.")
    lines.append("\nThe actual lessons happen inside each module's own chat — open one from "
                 "the learning path. What would you like to know or change?")
    return "\n".join(lines)


def _module_intro(topic: Optional[dict], module: Optional[dict]) -> str:
    """A warm, specific opening line for a brand-new module chat (no model call)."""
    topic = topic or {}
    module = module or {}
    tname = topic.get("title") or "this topic"
    mtitle = module.get("title") or tname
    summary = (module.get("summary") or "").strip()
    plan = topic.get("plan") or []
    idx = next((i for i, m in enumerate(plan) if m.get("id") == module.get("id")), None)
    pos = f" — module {idx + 1} of {len(plan)}" if idx is not None and plan else ""
    depth = _DEPTH_PHRASE.get(topic.get("depth", "solid"), "a solid understanding")

    lines = [f"👋 Welcome! Today we're learning **{mtitle}**{pos}, on our way to {depth} of "
             f"**{tname}**."]
    if summary:
        lines.append(f"\nHere's what this part covers: {summary}")
    lines.append(
        "\nI'll teach it step by step — simple real-life examples, a diagram or two, and a "
        "quick check so it really sticks. Whenever you're ready, just say **“I'm ready”** "
        "(or ask me anything) and we'll begin.")
    return "\n".join(lines)


def _switch_intro(topic: Optional[dict], module: Optional[dict],
                  model_label: str, recap: str) -> str:
    """The seeded opening when the learner switches the model mid-topic: it tells
    them which brain is teaching now, recaps what was covered so the new model isn't
    cold, and points at the next step. Mirrors the warm module-intro template."""
    topic = topic or {}
    tname = topic.get("title") or "this topic"
    mtitle = (module or {}).get("title") or tname
    lines = [f"🔄 You're now learning with **{model_label}**. I've picked up right where we "
             f"left off — no need to start over."]
    if (recap or "").strip():
        lines.append("\n**Where we are so far:**\n" + recap.strip())
    else:
        lines.append(f"\nWe're just getting going on **{mtitle}**.")
    lines.append("\nReady to keep going? Say **“I'm ready”** (or ask me anything) and we'll "
                 "continue from here.")
    return "\n".join(lines)


def _project_switch_intro(project: Optional[dict], model_label: str, recap: str) -> str:
    """The seeded opening when the user switches the model mid-chat in a project: it
    tells them which brain is answering now and recaps the chat so the new model isn't
    cold. Mirrors ``_switch_intro`` for the Learning Room."""
    pname = (project or {}).get("name") or "this project"
    lines = [f"🔄 You're now chatting with **{model_label}**. I've picked up right where we "
             f"left off — no need to start over."]
    if (recap or "").strip():
        lines.append("\n**Where we are so far:**\n" + recap.strip())
    else:
        lines.append(f"\nWe're just getting started in **{pname}**.")
    lines.append("\nReady to keep going? Ask me anything and we'll continue from here.")
    return "\n".join(lines)


def _restore_turns(db, session_id: str) -> list[dict]:
    """Session history for the UI, with persisted quiz cards restored.

    A 'quiz' turn is written the moment `pose_quiz` fires — i.e. BEFORE the
    assistant's full text turn is persisted at the end of the loop — so each
    card is moved to sit after its assistant message, matching the live view.
    The recorded answer (if any) is attached so the card reopens answered."""
    import json as _json

    out: list[dict] = []
    pending: list[dict] = []
    for t in db.session_turns(session_id):
        if t["role"] != "quiz":
            out.append(t)
            if t["role"] == "assistant" and pending:
                out.extend(pending)
                pending = []
            continue
        try:
            quiz = _json.loads(t["content"])
        except ValueError:
            continue  # malformed card — drop rather than break the chat
        answer = db.get_quiz_result(quiz.get("quiz_id") or "")
        if answer is not None:
            picked = answer.get("picked_index")
            if picked is None and answer.get("user_answer") in (quiz.get("options") or []):
                picked = (quiz.get("options") or []).index(answer["user_answer"])
            quiz["picked"] = picked
        pending.append({"role": "quiz", "content": "", "quiz": quiz,
                        "created_at": t.get("created_at")})
    out.extend(pending)
    return out


def create_app(service: Optional[NammaAgentService] = None) -> FastAPI:
    service = service or NammaAgentService()
    app = FastAPI(title="Namma Agent")
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Access-token auth (Phase 6a) ─────────────────────────────────────
    # When a token is configured (server.auth_token / NAMMA_AUTH_TOKEN), every
    # /api/* request must present it — Authorization: Bearer, X-Namma-Token, or
    # ?token= — compared constant-time. Exempt: /api/health (Docker/systemd
    # healthchecks) and everything outside the guarded prefixes (the static UI
    # shell is data-free; /webhooks/* carry their own platform verification).
    # The websocket enforces the same token itself (middleware doesn't see WS
    # upgrades).
    #
    # Phase 7f: /v1/* (the OpenAI-compatible surface) is guarded too. It runs
    # real agent turns with real tools — leaving it open would be a far bigger
    # hole than any /api route, since third-party clients point straight at it.
    def _auth_token() -> str:
        from namma_agent.config import auth_token
        return auth_token(service.config)

    def _token_ok(supplied: Optional[str]) -> bool:
        import hmac
        expected = _auth_token()
        return (not expected) or bool(
            supplied and hmac.compare_digest(supplied.strip(), expected))

    @app.middleware("http")
    async def _require_token(request: Request, call_next):
        path = request.url.path
        # Sandboxed visuals (iframe sandbox="allow-scripts", no same-origin) run
        # with an opaque origin and send ``Origin: null``. Their CSP already
        # blocks the network; refusing null-origin requests is the second lock.
        if request.headers.get("origin") == "null":
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "forbidden"}, status_code=403)
        guarded = path.startswith("/api") or path.startswith("/v1")
        # Provider OAuth callbacks are a top-level redirect from the provider's
        # site, which can't carry the token. They're guarded by their own
        # single-use, 10-minute nonce in the path instead (core/oauth.py).
        oauth_callback = bool(re.match(r"^/api/oauth/[a-z0-9_-]+/callback(/|$)", path))
        if _auth_token() and guarded and path != "/api/health" and not oauth_callback:
            supplied = request.headers.get("x-namma-token") or \
                request.query_params.get("token")
            authz = request.headers.get("authorization", "")
            if not supplied and authz.lower().startswith("bearer "):
                supplied = authz[7:]
            if not _token_ok(supplied):
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/desktop/focus")
    def desktop_focus():
        """Bring this process's native window forward (a second launch calls this
        instead of opening a duplicate window). ``focused: false`` = no window
        here (headless server / browser fallback)."""
        import sys as _sys

        launcher = _sys.modules.get("namma_agent.app")
        focused = bool(launcher is not None and launcher.focus_window())
        return {"ok": True, "focused": focused}

    @app.post("/api/desktop/update-state")
    def desktop_update_state(body: dict):
        """The desktop shell reports electron-updater's state here (Phase 9 W3),
        so /api/update/check can tell the web UI an update is available."""
        from namma_agent.core import desktop
        if not desktop.enabled():
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not running under the desktop app"}, status_code=404)
        return {"ok": True, "state": desktop.set_update_state(body or {})}

    # -- inbound webhooks (Slack / WhatsApp) -------------------------------
    # These platforms can't be polled, so they push events here. We ACK fast and
    # run the agent turn on a background thread (Slack requires a <3s response).

    def _dispatch_inbound(channel: str, text: str) -> None:
        bridge = service.comms.webhook_bridge(channel) if service.comms else None
        if bridge is not None and text:
            threading.Thread(target=bridge.handle_text, args=(text,), daemon=True).start()

    @app.get("/webhooks/whatsapp")
    def whatsapp_verify(request: Request):
        """Meta's webhook verification handshake (echo hub.challenge when the token matches)."""
        bridge = service.comms.webhook_bridge("whatsapp") if service.comms else None
        q = request.query_params
        challenge = bridge.verify(q.get("hub.mode", ""), q.get("hub.verify_token", ""),
                                  q.get("hub.challenge", "")) if bridge else None
        if challenge is None:
            return Response(status_code=403)
        return Response(content=challenge, media_type="text/plain")

    @app.post("/webhooks/whatsapp")
    async def whatsapp_webhook(request: Request):
        from namma_agent.comms.whatsapp import extract_texts
        try:
            payload = json.loads(await request.body() or b"{}")
        except Exception:  # noqa: BLE001
            payload = {}
        for text in extract_texts(payload):
            _dispatch_inbound("whatsapp", text)
        return {"ok": True}

    @app.get("/api/whatsapp/qr")
    def whatsapp_qr():
        """Link status for the QR (personal-number) WhatsApp backend. The Settings
        UI polls this: while unlinked it returns a QR data URI to scan; once the
        phone links the session, ``linked`` flips true and ``qr`` clears."""
        from namma_agent.comms.whatsapp_qr import (
            WhatsAppQRChannel,
            _neonize_installed,
            whatsapp_mode,
        )

        if whatsapp_mode() != "qr":
            # Backend not applied on the server yet (the setting needs Save + a
            # gateway (re)start). Report neonize separately so the UI guides right.
            return {"mode": "cloud", "available": False, "neonize": _neonize_installed(),
                    "linked": False, "qr": None}
        ch = service.comms.whatsapp if service.comms else None
        if isinstance(ch, WhatsAppQRChannel):
            return ch.status()
        # QR mode selected but the gateway isn't running yet (channel not built).
        return WhatsAppQRChannel().status()

    @app.post("/api/whatsapp/qr/relink")
    def whatsapp_relink():
        """Reconnect: log the current WhatsApp session out and re-establish so a
        fresh QR is issued (to link a different phone or recover a dropped link)."""
        from namma_agent.comms.whatsapp_qr import WhatsAppQRChannel, whatsapp_mode

        if whatsapp_mode() != "qr":
            return {"ok": False, "error": "WhatsApp backend is not set to QR mode."}
        ch = service.comms.whatsapp if service.comms else None
        if not isinstance(ch, WhatsAppQRChannel):
            return {"ok": False, "error": "Start the messaging gateway first, then reconnect."}
        return {"ok": ch.relink()}

    @app.post("/webhooks/slack")
    async def slack_webhook(request: Request):
        from namma_agent.comms.slack import extract_texts, verify_signature
        raw = await request.body()
        try:
            payload = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            payload = {}
        # Slack's one-time URL verification handshake.
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        bridge = service.comms.webhook_bridge("slack") if service.comms else None
        if bridge is None:
            return {"ok": False}
        secret = getattr(bridge, "signing_secret", "")
        if secret:  # verify the request actually came from Slack
            ts = request.headers.get("X-Slack-Request-Timestamp", "")
            sig = request.headers.get("X-Slack-Signature", "")
            if not verify_signature(secret, ts, sig, raw):
                return Response(status_code=401)
        for text in extract_texts(payload):
            _dispatch_inbound("slack", text)
        return {"ok": True}

    @app.get("/api/config")
    def config():
        return service.info()

    # -- OS-native voice (Phase 9): read-aloud + dictation via the system's own
    # speech engines (Windows SAPI, macOS `say`, espeak-ng), not the browser's.
    @app.get("/api/voice")
    def voice_status():
        from namma_agent.core import os_voice
        return os_voice.status(service.config)

    @app.post("/api/voice/tts")
    def voice_tts(body: TtsBody):
        from namma_agent.core import os_voice
        prefs = service.config.get("voice") or {}
        try:
            wav = os_voice.synthesize(body.text, voice=body.voice or prefs.get("tts_voice", ""),
                                      rate=body.rate or int(prefs.get("tts_rate", 0) or 0))
        except os_voice.VoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.post("/api/voice/stt")
    async def voice_stt(request: Request):
        """Dictation: the body is a WAV recording (the web UI records 16 kHz mono
        PCM). Returns {text, engine}. The size cap is enforced while reading."""
        from namma_agent.core import os_voice
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > os_voice.MAX_STT_BYTES:
                raise HTTPException(status_code=413, detail="That recording is too long.")
            chunks.append(chunk)
        prefs = service.config.get("voice") or {}
        engine = request.query_params.get("engine") or prefs.get("stt_engine", "auto")
        if engine == "browser":
            engine = "auto"
        try:
            return await asyncio.to_thread(os_voice.transcribe, b"".join(chunks), engine,
                                           prefs.get("stt_language", ""))
        except os_voice.VoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/tools")
    def tools():
        """All tools grouped by toolset, with enabled/destructive flags, plus the
        active toolset profile and tool-search mode (Toolsets tab)."""
        return service.tools_overview()

    @app.post("/api/tools/profile")
    def tools_profile(body: dict):
        """Pick a toolset profile preset (general/productivity/code/research/minimal)."""
        return service.set_tool_profile(str(body.get("profile") or ""))

    @app.post("/api/tools/search")
    def tools_search_mode(body: dict):
        """Tool search mode: auto (defer past the threshold) | always | off."""
        return service.set_tool_search(str(body.get("mode") or ""))

    # -- Skill & Tool packs (export / import) ------------------------------
    @app.get("/api/pack/items")
    def pack_items():
        """User-created skills + tools available to bundle into a pack."""
        from namma_agent.core import packs
        from namma_agent.tools.authoring import USER_TOOLS_DIR
        if service.skills is None:
            return {"skills": [], "tools": []}
        return packs.list_items(service.skills, USER_TOOLS_DIR)

    @app.post("/api/pack/export")
    def pack_export(body: PackExportBody):
        """Build a pack zip from the selection and save it under ~/.namma_agent/exports."""
        from namma_agent.config import assistant_name
        from namma_agent.core import packs
        from namma_agent.tools.authoring import USER_TOOLS_DIR
        if service.skills is None:
            return {"ok": False, "error": "skills unavailable"}
        name = assistant_name(service.config)
        data = packs.build_pack(service.skills, USER_TOOLS_DIR,
                                body.skills, body.tools, created_by=name)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "namma_agent"
        filename = f"{slug}-pack-{_dt.now():%Y%m%d-%H%M}.zip"
        export_dir = Path("~/.namma_agent/exports").expanduser()
        export_dir.mkdir(parents=True, exist_ok=True)
        dest = export_dir / filename
        dest.write_bytes(data)
        logger.info("[packs] exported %s (%d bytes)", dest, len(data))
        return {"ok": True, "filename": filename, "path": str(dest),
                "bytes": len(data)}

    @app.get("/api/pack/download/{filename}")
    def pack_download(filename: str):
        from starlette.responses import FileResponse, JSONResponse
        safe = Path(filename).name
        dest = Path("~/.namma_agent/exports").expanduser() / safe
        if not dest.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(dest, media_type="application/zip", filename=safe)

    @app.post("/api/pack/inspect")
    async def pack_inspect(file: UploadFile = File(...)):
        """Describe an uploaded pack without writing anything (import preview)."""
        from namma_agent.core import packs
        from namma_agent.tools.authoring import USER_TOOLS_DIR
        if service.skills is None:
            return {"error": "skills unavailable"}
        data = await file.read()
        try:
            return packs.inspect_pack(data, service.skills, USER_TOOLS_DIR)
        except ValueError as exc:
            return {"error": str(exc)}

    @app.post("/api/pack/install")
    async def pack_install(
        file: UploadFile = File(...),
        approved_tools: str = Form(""),   # comma-separated tool names the user OK'd
        skills: str = Form(""),           # comma-separated skill names to install
        overwrite: str = Form("false"),
    ):
        """Install selected skills + explicitly approved tools from a pack."""
        from namma_agent.core import packs
        from namma_agent.tools.authoring import USER_TOOLS_DIR
        if service.skills is None:
            return {"error": "skills unavailable"}
        data = await file.read()
        split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
        try:
            summary = packs.install_pack(
                data, service.skills, USER_TOOLS_DIR, service.registry,
                approved_tools=split(approved_tools),
                skill_names=split(skills) if skills.strip() else None,
                overwrite=overwrite.lower() in ("1", "true", "yes"),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"ok": True, "summary": summary}

    @app.get("/api/personas")
    def list_personas_ep():
        """Available personas (user + built-in) with a one-line identity, plus the
        active one and the current assistant name — drives the Settings dropdown."""
        from namma_agent.config import assistant_name
        from namma_agent.core.persona import list_personas

        name = assistant_name(service.config)
        return {"personas": list_personas(name), "active": service.persona.id,
                "assistant_name": name}

    @app.get("/api/personas/{persona_id}")
    def get_persona_ep(persona_id: str):
        """Full editable spec of one persona — for the editor / 'view all instructions'."""
        from namma_agent.core.persona import get_persona_spec
        spec = get_persona_spec(persona_id)
        if spec is None:
            return {"ok": False, "error": "persona not found"}
        return {"ok": True, "persona": spec}

    @app.post("/api/persona")
    def set_persona(body: PersonaBody):
        from namma_agent.config import update_config

        service.set_persona(body.id)
        update_config({"persona": body.id})  # persist the choice across restarts
        return {"persona": service.persona.id}

    @app.post("/api/personas")
    def save_persona_ep(body: PersonaSaveBody):
        """Create/update a user persona (manual or AI-drafted) and return the
        refreshed list so the dropdown updates immediately."""
        from namma_agent.config import assistant_name
        from namma_agent.core.persona import list_personas, save_persona

        try:
            saved = save_persona(body.model_dump())
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "saved": saved,
                "personas": list_personas(assistant_name(service.config))}

    @app.post("/api/personas/generate")
    def generate_persona_ep(body: PersonaGenerateBody):
        """Have the assistant draft a persona spec from a freeform description."""
        return service.generate_persona(body.description)

    @app.delete("/api/personas/{persona_id}")
    def delete_persona_ep(persona_id: str):
        """Delete a user persona (built-ins are immutable). If it was active, fall
        back to the default."""
        from namma_agent.config import assistant_name, update_config
        from namma_agent.core.persona import delete_user_persona, list_personas

        ok = delete_user_persona(persona_id)
        if ok and service.persona.id == persona_id:
            service.set_persona("core")
            update_config({"persona": "core"})
        return {"ok": ok, "active": service.persona.id,
                "personas": list_personas(assistant_name(service.config))}

    @app.post("/api/session")
    def new_session():
        return {"session_id": service.new_session()}

    @app.get("/api/sessions")
    def list_sessions():
        # Sidebar shows only *unfiled* chats — chats that belong to a project live
        # in that project, never in the global recent list.
        return {"sessions": service.db.list_sessions(project_id="")}

    @app.get("/api/sessions/{session_id}")
    def session_history(session_id: str):
        # Include the chat's "home" (project or learning topic) so the chat view can
        # show a breadcrumb back to where it belongs.
        meta = service.db.get_session(session_id) or {}
        project = None
        pid = meta.get("project_id")
        if pid:
            p = service.db.get_project(pid)
            if p:
                project = {"id": p["id"], "name": p["name"]}
        topic = None
        # Topic resolution scans every learning topic's plan — only worth it for
        # learning sessions; plain/project chats skip it entirely.
        if (meta.get("kind") or "chat") == "learning":
            t = service.db.get_topic_by_session(session_id)
            if t:
                plan = t.get("plan") or []
                mod = next((m for m in plan
                            if m.get("session_id") == session_id), None)
                topic = {"id": t["id"], "title": t["title"], "module": (mod or {}).get("title")}
                # If this module's lesson is finished, carry the "module complete →
                # continue" info so the chat view can re-derive the card on every
                # load. The live `learning_progress` event is transient (lost on
                # reload / if it never reached the client); deriving it from
                # persisted state guarantees the learner always has a next step.
                if mod and (mod.get("status") or "todo") == "done":
                    idx = plan.index(mod)
                    nxt = plan[idx + 1] if idx + 1 < len(plan) else None
                    prog = t.get("progress") or {}
                    topic["module_done"] = {
                        "topic_id": t["id"],
                        "module_title": mod.get("title", ""),
                        "done": prog.get("done", 0),
                        "total": prog.get("total", 0),
                        "next": ({"id": nxt["id"], "title": nxt["title"]} if nxt else None),
                    }
        from namma_agent.tools.todo import todos_for
        return {"session_id": session_id,
                "turns": _restore_turns(service.db, session_id),
                "project": project, "topic": topic,
                "model": (meta.get("model") or "").strip(),
                "title": (meta.get("title") or "").strip(),
                # The agent's live TODO plan (in-memory) so the panel above the
                # message bar survives a reload while the server is up.
                "todos": todos_for(session_id)}

    @app.get("/api/sessions/{session_id}/export")
    def export_session(session_id: str):
        """Download the whole chat as a zip: chat.md (the transcript) + media/
        (every generated diagram/image/simulation the chat references), with the
        links in chat.md rewritten so it renders offline."""
        from starlette.responses import JSONResponse

        from namma_agent.config import assistant_name
        from namma_agent.core.chat_export import build_chat_zip

        meta = service.db.get_session(session_id)
        if not meta:
            return JSONResponse({"error": "not found"}, status_code=404)
        turns = service.db.session_turns(session_id)
        filename, data = build_chat_zip(turns, meta, assistant_name(service.config))
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        return {"deleted": service.db.delete_session(session_id)}

    @app.patch("/api/sessions/{session_id}")
    def rename_session(session_id: str, body: RenameBody):
        return {"renamed": service.db.rename_session(session_id, body.title)}

    @app.post("/api/sessions/{session_id}/project")
    def file_chat(session_id: str, body: FileChatBody):
        return {"filed": service.db.set_session_project(session_id, body.project_id)}

    # -- projects ----------------------------------------------------------

    @app.get("/api/projects")
    def list_projects():
        return {"projects": service.db.list_projects()}

    @app.post("/api/projects")
    def create_project(body: ProjectBody):
        return {"project": service.db.create_project(body.name, body.description)}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        project = service.db.get_project(project_id)
        if not project:
            return {"project": None}
        return {
            "project": project,
            "sessions": service.db.list_sessions(project_id=project_id),
            "memory": service.db.list_scope_memory("project", project_id),
            "documents": service.db.list_project_documents(project_id),
        }

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, body: ProjectBody):
        return {"project": service.db.update_project(
            project_id, name=body.name or None, description=body.description)}

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str):
        deleted = service.db.delete_project(project_id)
        if deleted:  # the index rows are gone; remove the files on disk too
            import shutil

            from namma_agent.core.docindex import PROJECT_FILES_DIR
            shutil.rmtree(PROJECT_FILES_DIR / project_id, ignore_errors=True)
        return {"deleted": deleted}

    @app.post("/api/projects/{project_id}/sessions")
    def new_project_session(project_id: str):
        sid = service.db.create_session_in(project_id=project_id)
        # Cross-session continuity: summarize this project's finished chats in the
        # background so the new chat's prompt carries what was discussed before.
        threading.Thread(target=service.summarize_project_sessions,
                         args=(project_id,), daemon=True).start()
        return {"session_id": sid}

    # -- project documents (multi-document RAG) -----------------------------

    @app.post("/api/projects/{project_id}/documents")
    async def upload_project_document(project_id: str, file: UploadFile = File(...)):
        """Upload + ingest a document into the project's knowledge base. Enforces
        the 25-files-per-project and 10MB-per-file caps; screens for prompt
        injection (flagged files are quarantined out of retrieval)."""
        from namma_agent.core import docindex

        if not service.db.get_project(project_id):
            return {"ok": False, "error": "project not found"}
        if service.db.count_project_documents(project_id) >= docindex.MAX_FILES_PER_PROJECT:
            return {"ok": False,
                    "error": f"Project document limit reached "
                             f"({docindex.MAX_FILES_PER_PROJECT} files). Remove one first."}
        data = await file.read()
        if len(data) > docindex.MAX_FILE_BYTES:
            return {"ok": False,
                    "error": f"'{file.filename}' is too large "
                             f"({len(data) / 1e6:.1f} MB). The limit is 10 MB per file."}
        if not data:
            return {"ok": False, "error": "the uploaded file is empty"}
        dest = docindex.save_upload(project_id, file.filename or "upload", data)
        doc = await asyncio.to_thread(
            docindex.ingest_document, service.db, project_id, str(dest), Path(file.filename or "upload").name)
        return {"ok": True, "document": doc,
                "documents": service.db.list_project_documents(project_id)}

    @app.get("/api/projects/{project_id}/documents")
    def list_project_documents(project_id: str):
        return {"documents": service.db.list_project_documents(project_id)}

    @app.delete("/api/projects/{project_id}/documents/{doc_id}")
    def delete_project_document(project_id: str, doc_id: str):
        doc = service.db.get_project_document(doc_id)
        deleted = service.db.delete_project_document(doc_id)
        if deleted and doc and doc.get("path"):
            Path(doc["path"]).unlink(missing_ok=True)
        return {"deleted": deleted,
                "documents": service.db.list_project_documents(project_id)}

    @app.post("/api/projects/{project_id}/documents/{doc_id}/trust")
    def trust_project_document(project_id: str, doc_id: str):
        """User override for a flagged document: include it in retrieval anyway."""
        doc = service.db.get_project_document(doc_id)
        if not doc or doc["project_id"] != project_id:
            return {"ok": False, "error": "document not found"}
        service.db.set_document_status(doc_id, "trusted")
        return {"ok": True, "documents": service.db.list_project_documents(project_id)}

    @app.post("/api/projects/{project_id}/memory")
    def add_project_memory(project_id: str, body: ScopeMemoryBody):
        eid = service.db.add_scope_memory("project", project_id, body.content)
        # The scope row is prompt context for this project's chats; the FACT also
        # enters Engram's pipeline so it's part of the knowledge graph everywhere.
        if (body.content or "").strip():
            name = (service.db.get_project(project_id) or {}).get("name", project_id)
            service.engram.writer.ingest_text(
                f"Project \"{name}\": {body.content.strip()}", source="project")
        return {"id": eid, "memory": service.db.list_scope_memory("project", project_id)}

    @app.delete("/api/scope_memory/{entry_id}")
    def delete_scope_memory(entry_id: int):
        return {"deleted": service.db.delete_scope_memory_entry(entry_id)}

    # -- learning room -----------------------------------------------------

    @app.get("/api/learning")
    def list_learning():
        return {"topics": service.db.list_learning_topics()}

    @app.post("/api/learning")
    def create_learning(body: LearningBody):
        topic = service.db.create_learning_topic(body.topic, body.depth)
        return {"topic": topic}

    @app.post("/api/learning/from_document")
    async def create_learning_from_document(file: UploadFile = File(...)):
        """Build a topic + path from an uploaded syllabus (level auto-detected).
        The document is screened first; injection or non-syllabus content flags
        the upload and nothing is created."""
        data = await file.read()
        if not data:
            return {"ok": False, "reasons": ["the uploaded file is empty"]}
        if len(data) > 10 * 1024 * 1024:
            return {"ok": False, "reasons": ["the file exceeds the 10 MB limit"]}
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = _UPLOAD_DIR / Path(file.filename or "syllabus").name
        dest.write_bytes(data)
        return await asyncio.to_thread(
            service.learning_from_document, str(dest), Path(file.filename or "syllabus").name)

    @app.get("/api/learning/{topic_id}")
    def get_learning(topic_id: str):
        topic = service.db.get_learning_topic(topic_id)
        if not topic:
            return {"topic": None}
        return {
            "topic": topic,
            "insights": service.db.topic_insights(topic_id),
            "memory": service.db.list_scope_memory("learning", topic_id),
        }

    @app.delete("/api/learning/{topic_id}")
    def delete_learning(topic_id: str):
        return {"deleted": service.db.delete_learning_topic(topic_id)}

    @app.delete("/api/learning/{topic_id}/preferences/{index}")
    def delete_teaching_preference(topic_id: str, index: int):
        return {"topic": service.db.remove_teaching_preference(topic_id, index)}

    @app.patch("/api/learning/{topic_id}/plan")
    def update_plan(topic_id: str, body: PlanBody):
        return {"topic": service.db.set_learning_plan(topic_id, body.modules)}

    @app.post("/api/learning/{topic_id}/session")
    def learning_path_session(topic_id: str):
        """The topic's path chat (its overview session), seeded with an intro so
        opening it never shows a blank 'new chat'."""
        topic = service.db.get_learning_topic(topic_id)
        if not topic:
            return {"session_id": None}
        sid = topic["session_id"]
        # Seed only if the thread has no *assistant* turn yet — path-build prompts
        # (sent silently by the dashboard) may already sit in the history.
        turns = service.db.session_turns(sid)
        if not any(t["role"] == "assistant" for t in turns):
            service.db.add_turn(sid, "assistant", _path_chat_intro(topic))
        return {"session_id": sid}

    @app.post("/api/learning/{topic_id}/module/{module_id}/session")
    def module_session(topic_id: str, module_id: str):
        sid = service.db.module_session(topic_id, module_id)
        # Seed a warm intro so a freshly-opened module never shows a blank chat —
        # the learner lands on the teacher introducing what's ahead.
        if sid and not service.db.session_turns(sid):
            topic = service.db.get_learning_topic(topic_id)
            module = next((m for m in (topic.get("plan") or [])
                           if m.get("id") == module_id), None) if topic else None
            service.db.add_turn(sid, "assistant", _module_intro(topic, module))
        return {"session_id": sid}

    @app.post("/api/learning/switch_model")
    def learning_switch_model(body: SwitchModelBody):
        """Switch a Learning-Room thread to a different configured model WITHOUT a cold
        restart: summarize the current session, spin up a fresh session bound to the new
        model, re-point the topic/module onto it, and seed a recap so the new model
        continues seamlessly. Returns the new session id to open."""
        old_sid = body.session_id
        topic = service.db.get_topic_by_session(old_sid) if old_sid else None
        if not topic:
            return {"ok": False, "error": "Not a learning session."}
        module = next((m for m in (topic.get("plan") or [])
                       if m.get("session_id") == old_sid), None)
        label = next((m.get("label") for m in service.configured_models()
                      if m.get("id") == body.model), None) or body.model or "the default model"
        recap = service.learning_recap(old_sid, topic, module)
        new_sid = service.db.create_session_in(kind="learning")
        service.db.set_session_model(new_sid, body.model or None)
        service.db.repoint_learning_session(old_sid, new_sid)
        service.db.add_turn(new_sid, "assistant", _switch_intro(topic, module, label, recap))
        logger.info("[learning] model switch %s → %s (session %s → %s)",
                    (module or {}).get("title") or topic["title"], label, old_sid[:8], new_sid[:8])
        return {"ok": True, "session_id": new_sid, "model": body.model, "recap": recap}

    @app.post("/api/projects/switch_model")
    def project_switch_model(body: SwitchModelBody):
        """Switch a project chat to a different configured model WITHOUT a cold
        restart — the exact mirror of the Learning-Room switch: summarize the current
        session, spin up a fresh session in the SAME project bound to the new model,
        seed a recap so the new model continues seamlessly, and carry the chat's title
        over. Returns the new session id to open."""
        old_sid = body.session_id
        meta = service.db.get_session(old_sid) if old_sid else None
        pid = (meta or {}).get("project_id")
        if not meta or not pid:
            return {"ok": False, "error": "Not a project chat."}
        project = service.db.get_project(pid)
        label = next((m.get("label") for m in service.configured_models()
                      if m.get("id") == body.model), None) or body.model or "the default model"
        recap = service.project_recap(old_sid, project)
        new_sid = service.db.create_session_in(project_id=pid, kind="chat")
        service.db.set_session_model(new_sid, body.model or None)
        # Carry the chat's name over so the switch keeps the same thread in the sidebar.
        title = (meta.get("title") or "").strip()
        if title:
            service.db.rename_session(new_sid, title)
        service.db.add_turn(new_sid, "assistant", _project_switch_intro(project, label, recap))
        logger.info("[project] model switch %s → %s (session %s → %s)",
                    (project or {}).get("name") or pid, label, old_sid[:8], new_sid[:8])
        return {"ok": True, "session_id": new_sid, "model": body.model, "recap": recap}

    @app.post("/api/learning/{topic_id}/quiz")
    def record_quiz(topic_id: str, body: QuizResultBody):
        service.db.record_quiz(topic_id, body.question, body.correct,
                               module_id=body.module_id, user_answer=body.user_answer,
                               quiz_uid=body.quiz_id, options=body.options or None,
                               answer_index=body.answer_index,
                               picked_index=body.picked_index,
                               explanation=body.explanation)
        return {"insights": service.db.topic_insights(topic_id)}

    @app.post("/api/shutdown")
    def shutdown():
        service.shutdown()
        return {"ok": True, "message": "Namma Agent is shutting down."}

    @app.post("/api/notify")
    def notify(body: NotifyBody):
        """Show a native OS desktop notification (reliable inside the pywebview
        desktop window, where the browser Notification API doesn't surface toasts).
        The frontend gates on the user's master + per-event toggles before calling.

        ``ok`` is False when the OS won't render toasts (e.g. Windows
        notifications switched off) — the UI then shows an in-app banner instead,
        so the notification still reaches the user in both the browser tab and
        the desktop window."""
        from namma_agent.core.notifications import notification_status, send_native_notification
        ok = send_native_notification(body.title, body.body)
        return {"ok": ok, "reason": "" if ok else notification_status().get("reason", "")}

    @app.get("/api/notify/status")
    def notify_status():
        """Whether native desktop toasts can actually be displayed here, and why
        not when they can't. Drives the Settings hint + the in-app fallback."""
        from namma_agent.core.notifications import notification_status
        return notification_status()

    @app.get("/api/autostart")
    def autostart_status():
        """Start-on-login state for the Settings → Behavior toggle (Phase 5)."""
        from namma_agent.core import autostart
        return autostart.status()

    @app.post("/api/autostart")
    def autostart_set(body: AutostartBody):
        """Register/unregister launching the app at user login (HKCU Run key on
        Windows, XDG autostart entry on Linux). Never raises — failures come
        back as {ok: False, error} for the UI."""
        from namma_agent.core import autostart
        return autostart.set_enabled(bool(body.enabled))

    @app.get("/api/version")
    def version():
        from namma_agent.version import __version__
        return {"version": __version__}

    @app.get("/api/update/check")
    def update_check():
        """Is a newer version published? Safe/non-blocking — returns data on failure."""
        from namma_agent.core.updater import check_for_update
        return check_for_update()

    @app.post("/api/update/apply")
    def update_apply():
        """Launch the detached update script (fetch → reinstall → rebuild → relaunch)."""
        from namma_agent.core.updater import apply_update
        return apply_update()

    @app.post("/api/uninstall")
    def uninstall(body: UninstallBody):
        """Start the detached uninstaller, then shut down so it can remove the files.
        scope='all' wipes everything; 'keep-data' backs up chats/config first."""
        import threading

        from namma_agent.core.uninstaller import apply_uninstall
        result = apply_uninstall(body.scope)
        # Desktop app: the Electron shell runs the NSIS uninstaller and quits,
        # stopping this backend itself, so don't race it by exiting first.
        if result.get("started") and not result.get("shell_exits"):
            # Let the HTTP response flush, then shut the backend down so the
            # uninstaller can delete the (now-unlocked) install directory.
            threading.Timer(1.0, service.shutdown).start()
        return result

    @app.get("/api/onboarding")
    def onboarding_status():
        return service.onboarding_status()

    @app.post("/api/onboarding")
    def complete_onboarding(body: OnboardingBody):
        return service.complete_onboarding(body.name, body.facts)

    # -- setup (Phase 5): secure secrets, verification, first-run onboarding ----

    @app.post("/api/setup/secret")
    def setup_secret(body: SetupSecretBody):
        """The ONLY way a credential value enters the app from the setup UI: the
        secure field posts here → the vault. Never echoed, never logged; the
        response carries the name only."""
        result = service.setup_save_secret(body.name, body.value)
        logger.info("[setup] secret %s saved=%s", body.name, result.get("ok"))
        return result

    @app.get("/api/setup/status")
    def setup_status(google: bool = True):
        return service.setup_status(check_gws=google)

    @app.get("/api/setup/integrations")
    def setup_integrations(google: bool = True):
        return {"integrations": service.setup_integrations(check_gws=google)}

    @app.post("/api/setup/verify")
    def setup_verify(body: SetupVerifyBody):
        """Real check of a provider (+ one tiny call when a model is given)."""
        return service.setup_verify_provider(body.provider, body.model)

    @app.post("/api/setup/onboard")
    def setup_onboard(body: SetupOnboardBody):
        """First run: save key → provider → verify → default model (only if OK)."""
        return service.setup_onboard_provider(body.type, body.model, body.key, body.base_url)

    @app.post("/api/setup/mail")
    def setup_mail(body: SetupMailBody):
        return service.setup_mail_add(body.address, body.provider, body.id, body.imap_host,
                                      body.smtp_host, body.imap_port, body.smtp_port)

    @app.post("/api/setup/mail/test")
    def setup_mail_test(body: dict):
        return service.setup_mail_test(str(body.get("account") or ""))

    @app.get("/api/settings")
    def get_settings():
        """Effective config (for the settings UI) + which secret env keys are set."""
        import os as _os

        from namma_agent.config import load_config

        env_keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                    "NAMMA_TELEGRAM_TOKEN", "NAMMA_TELEGRAM_CHAT_ID", "NAMMA_API_KEY",
                    "NAMMA_DISCORD_WEBHOOK_URL", "NAMMA_DISCORD_BOT_TOKEN",
                    "NAMMA_DISCORD_CHANNEL_ID", "NAMMA_SLACK_WEBHOOK_URL",
                    "NAMMA_SLACK_APP_TOKEN", "NAMMA_SLACK_BOT_TOKEN",
                    "NAMMA_WHATSAPP_MODE", "NAMMA_WHATSAPP_TOKEN", "NAMMA_WHATSAPP_PHONE_ID",
                    "NAMMA_WHATSAPP_TO", "NAMMA_WHATSAPP_VERIFY_TOKEN", "NAMMA_SIGNAL_API_URL",
                    "NAMMA_SIGNAL_NUMBER", "NAMMA_SIGNAL_RECIPIENT", "NAMMA_SLACK_SIGNING_SECRET"]
        return {
            "config": load_config(),
            "env_set": {k: bool(_os.environ.get(k)) for k in env_keys},
        }

    @app.post("/api/settings")
    def update_settings(body: SettingsBody):
        from namma_agent.config import update_config
        from namma_agent.core.secrets import save_settings_env

        # Secrets go to the vault (their stale .env copy is dropped); other env
        # values go to .env. Names only are logged / returned — never values.
        try:
            saved = save_settings_env(body.env) if body.env else {"vault": [], "env": []}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        written = saved["vault"] + saved["env"]
        merged = update_config(body.config) if body.config else None
        logger.info("[settings] updated config keys=%s env keys=%s (vault: %s)",
                    list((body.config or {}).keys()), written, saved["vault"])
        # Apply live — rebuild the provider so a changed brain / base_url / API key
        # takes effect on the next turn, no restart. (Runs when the provider config
        # OR an env key changed; env-only edits rebuild against the current config.)
        if merged is not None or written:
            service.apply_config(merged)
        return {"ok": True, "config": merged, "env_written": written,
                "vault_written": saved["vault"],
                "note": "Applied live — no restart needed."}

    @app.post("/api/memory/clear")
    def clear_memory(body: MemoryClearBody):
        return service.clear_memory(body.scope)

    # -- comms gateway (start/stop the inbound messaging service) -----------

    # -- skills (Settings → Skills tab) -------------------------------------

    @app.get("/api/skills")
    def list_skills():
        """All skills with enabled/supported/requirement info for the Skills tab."""
        return {"skills": service.skills_detail()}

    @app.post("/api/skills/toggle")
    def toggle_skill(body: SkillToggleBody):
        """Enable/disable a skill; persists to user_config.yaml (skills.disabled).

        Approving a draft from the review queue is just this with enabled=true —
        the skill joins the catalog and stops being a proposal."""
        return service.set_skill_enabled(body.name, body.enabled)

    @app.get("/api/skills/market")
    def skills_market():
        """The curated skills index, with installed flags."""
        return service.skills_market_index()

    @app.post("/api/skills/market/preview")
    def skills_market_preview(body: dict):
        """Fetch + analyse a skill from a URL (licence, files, scripts, risks)."""
        return service.skills_market_preview(str(body.get("url") or ""))

    @app.post("/api/skills/market/install")
    def skills_market_install(body: dict):
        """Install a previewed skill — lands DISABLED for review."""
        return service.skills_market_install(str(body.get("url") or ""),
                                             overwrite=bool(body.get("overwrite")))

    @app.post("/api/skills/delete")
    def delete_skill(body: SkillNameBody):
        """Discard a learned skill (the review queue's "no thanks"). Bundled
        skills are refused — those are turned off, never deleted."""
        return service.delete_skill(body.name)

    # -- toolsets (Settings → Toolsets tab) ---------------------------------

    @app.post("/api/tools/toggle")
    def toggle_tool(body: ToolToggleBody):
        """Enable/disable a single tool; persists to user_config.yaml (tools.disabled)."""
        return service.set_tool_enabled(body.name, body.enabled)

    @app.post("/api/toolset/toggle")
    def toggle_toolset(body: ToolsetToggleBody):
        """Enable/disable every tool in a toolset at once; persists the disabled-set."""
        return service.set_toolset_enabled(body.category, body.enabled)

    # -- MCP servers (Settings → MCP: Config + Servers) ---------------------

    @app.get("/api/mcp")
    def mcp_status():
        """MCP config JSON + connected servers and their tools for the MCP tabs."""
        return service.mcp_detail()

    @app.post("/api/mcp/reload")
    def mcp_reload():
        """Reconnect MCP servers from the saved config (no restart) and return state."""
        return service.reload_mcp()

    @app.post("/api/mcp/server/toggle")
    def mcp_server_toggle(body: McpServerToggleBody):
        """Enable/disable an entire MCP server (persists + reconnects)."""
        return service.set_mcp_server_enabled(body.name, body.enabled)

    # Phase 5: validation, the add-server wizard, import, detection.
    @app.post("/api/mcp/validate")
    def mcp_validate(body: McpServersBody):
        """Check a server list without saving: {ok, servers, errors, warnings}."""
        return service.mcp_validate(body.servers)

    @app.post("/api/mcp/servers")
    def mcp_save_servers(body: McpServersBody):
        """Replace the server list (Config editor). Refused when invalid."""
        return service.mcp_save_servers(body.servers)

    @app.post("/api/mcp/server/add")
    def mcp_add_server(body: McpServerBody):
        """Validate + persist ONE server and start only it."""
        return service.mcp_add_server(body.server, replace=body.replace)

    @app.post("/api/mcp/server/remove")
    def mcp_remove_server(body: McpNameBody):
        return service.mcp_remove_server(body.name)

    @app.post("/api/mcp/import")
    def mcp_import(body: McpImportBody):
        """Preview servers from a pasted config (Claude Desktop / VS Code /
        server.json) or a URL. Saves nothing."""
        return service.mcp_import(body.config, url=body.url)

    @app.get("/api/mcp/detect")
    def mcp_detect():
        """Runtimes, disk space, servers configured in other apps, Docker MCP images."""
        return service.mcp_detect()

    @app.get("/api/mcp/catalog")
    def mcp_catalog():
        """Curated server presets for the add-server wizard."""
        return service.mcp_catalog()

    @app.post("/api/mcp/preset")
    def mcp_preset(body: McpPresetBody):
        """Build (and validate) a server entry from a preset + answers. Saves nothing."""
        return service.mcp_build_preset(body.preset, body.params, body.name)

    # -- Engram memory (the Memory tab — native, always on) -----------------

    @app.get("/api/memory/status")
    def memory_status():
        """Engine status: counts, core-memory usage, pending writes, last
        consolidation. Native memory has no offline state."""
        return service.memory_status()

    @app.post("/api/memory/recall")
    def memory_recall(body: MemoryRecallBody):
        """Fused recall (BM25 + graph + episodic) with provenance + timestamps."""
        return service.memory_recall(body.query, k=body.top_k,
                                     include_expired=body.include_expired)

    @app.post("/api/memory/remember")
    def memory_remember(body: MemoryRememberBody):
        """Queue text into the write pipeline (extraction/resolution run in the
        background on the user-selected model)."""
        return service.memory_remember(body.text)

    @app.post("/api/memory/consolidate")
    def memory_consolidate():
        """The 'Improve memory' op: summarize finished sessions, merge duplicate
        facts, refresh the host model. Returns a report card."""
        return service.memory_consolidate()

    @app.post("/api/memory/forget")
    def memory_forget(body: MemoryForgetBody):
        """Invalidate (default) or hard-delete matching memory — or wipe everything."""
        return service.memory_forget(query=body.query, item_id=body.item_id,
                                     everything=body.everything, hard=body.hard)

    @app.get("/api/memory/graph")
    def memory_graph(include_expired: bool = False, as_of: str = ""):
        """The knowledge graph as {nodes, edges}. ``as_of`` (ISO timestamp)
        time-travels to what memory knew at that moment (the history slider)."""
        return service.memory_graph(include_expired=include_expired, as_of=as_of)

    # Phase 10 graph primitives: nodes/edges come from /api/memory/graph; these
    # are the focused reads and the two entity-management writes.
    @app.get("/api/memory/graph/nodes")
    def memory_graph_nodes(include_expired: bool = False, as_of: str = ""):
        g = service.memory_graph(include_expired=include_expired, as_of=as_of)
        return {"ok": True, "nodes": g["nodes"], "count": len(g["nodes"])}

    @app.get("/api/memory/graph/edges")
    def memory_graph_edges(include_expired: bool = False, as_of: str = ""):
        g = service.memory_graph(include_expired=include_expired, as_of=as_of)
        return {"ok": True, "edges": g["edges"], "count": len(g["edges"])}

    @app.get("/api/memory/graph/entity/{entity_id}")
    def memory_graph_entity(entity_id: str):
        """Neighbourhood: attributes, aliases, relations and source facts."""
        return service.memory_graph_entity(entity_id)

    @app.post("/api/memory/graph/entity/{entity_id}")
    def memory_graph_update_entity(entity_id: str, body: MemoryGraphEntityBody):
        return service.memory_graph_update_entity(entity_id, name=body.name,
                                                  type=body.type)

    @app.get("/api/memory/graph/schema")
    def memory_graph_schema():
        """Entity types + relation types derived from the live graph."""
        return service.memory_graph_schema()

    @app.get("/api/memory/graph/ranked")
    def memory_graph_ranked(limit: int = 50, include_self: bool = True):
        """Entities by centrality / salience / recency (components included)."""
        return service.memory_graph_ranked(limit=limit, include_self=include_self)

    @app.get("/api/memory/graph/search")
    def memory_graph_search(q: str = "", limit: int = 20):
        return service.memory_graph_search(q, limit=limit)

    @app.post("/api/memory/graph/merge")
    def memory_graph_merge(body: MemoryGraphMergeBody):
        return service.memory_graph_merge(body.source, body.target)

    @app.post("/api/memory/graph/rebuild")
    def memory_graph_rebuild():
        """Re-derive the whole graph from the stored facts."""
        return service.memory_graph_rebuild()

    @app.get("/api/memory/items")
    def memory_items(kind: str = "", include_expired: bool = False):
        """The facts browser: live (or all) memory items with lifecycle fields."""
        return service.memory_items(kind=kind, include_expired=include_expired)

    @app.get("/api/memory/pending")
    def memory_pending(limit: int = 100):
        """Phase 7c: facts the agent extracted on its own that are waiting for
        the user's yes/no (memory.write_approval). These are NOT memory yet —
        never indexed, never embedded, never recalled."""
        return service.memory_pending(limit=limit)

    @app.post("/api/memory/pending/resolve")
    def memory_resolve_pending(body: MemoryPendingBody):
        """Approve (release into memory) or reject (discard) a pending fact —
        or all of them at once."""
        return service.memory_resolve_pending(item_id=body.item_id,
                                              approve=body.approve,
                                              all_items=body.all)

    @app.get("/api/memory/low_quality")
    def memory_low_quality(limit: int = 50):
        """Facts the quality audit scored poorly (worst first) + the aggregate
        Memory Quality figures — the review queue for pruning noise."""
        return service.memory_low_quality(limit=limit)

    @app.get("/api/memory/core")
    def memory_core():
        """The two L1 core-memory blocks (entries + usage) for the editor."""
        return service.memory_core()

    @app.post("/api/memory/core")
    def memory_core_save(body: MemoryCoreBody):
        """Add / replace / remove a core-memory entry (screened + budget-capped)."""
        return service.memory_core_save(body.block, body.action, text=body.text,
                                        entry_id=body.entry_id, old_text=body.old_text)

    @app.get("/api/memory/environment")
    def memory_environment(refresh: bool = False):
        """The L5 host model (read-only card; refresh=true re-probes the machine)."""
        return service.memory_environment(refresh=refresh)

    # -- memory settings (the single Settings → Memory section) -------------

    @app.get("/api/memory/settings")
    def memory_settings():
        """Live Engram knobs + status for Settings → Memory."""
        return service.memory_settings()

    @app.post("/api/memory/settings")
    def memory_settings_save(body: MemorySettingsBody):
        """Persist memory tuning to user_config.yaml and apply it live."""
        return service.save_memory_settings(body.settings)

    @app.get("/api/comms/status")
    def comms_status():
        return service.comms_status()

    @app.post("/api/comms/trust")
    def comms_trust(body: TrustBody):
        """Set a channel's trust level (owner/trusted/untrusted) — persisted to
        user_config.yaml and applied to the running bridges immediately."""
        return service.set_channel_trust(body.channel, body.level)

    @app.get("/api/security/overview")
    def security_overview():
        """One payload for the Settings → Security tab: trust levels, sandbox,
        secrets inventory (names only), quarantine log, audit trail."""
        return service.security_overview()

    # -- checkpoints (Phase 7b): undo a turn's file changes -------------------

    @app.get("/api/checkpoints")
    def checkpoints_list(session_id: str = "", limit: int = 50):
        return service.checkpoints_overview(session_id=session_id, limit=limit)

    @app.post("/api/checkpoints/{checkpoint_id}/restore")
    def checkpoint_restore(checkpoint_id: str):
        """Restore the files as they were before that tool ran. The response
        lists what was restored, what was deleted, and what could NOT be put
        back — a partial restore is never reported as a clean one."""
        return service.restore_checkpoint(checkpoint_id)

    @app.delete("/api/checkpoints/{checkpoint_id}")
    def checkpoint_delete(checkpoint_id: str):
        return service.delete_checkpoint(checkpoint_id)

    # -- secrets vault (Phase 1d): inventory is names-only, never values ------

    @app.get("/api/secrets")
    def secrets_overview():
        return service.secrets_overview()

    @app.post("/api/secrets")
    def secret_set(body: SecretBody):
        return service.secret_set(body.name, body.value)

    @app.delete("/api/secrets/{name}")
    def secret_delete(name: str):
        return service.secret_delete(name)

    @app.post("/api/secrets/migrate")
    def secrets_migrate(body: SecretsMigrateBody):
        """Opt-in migration of secret-looking .env entries into the OS vault."""
        return service.migrate_secrets(scrub=body.scrub)

    @app.post("/api/comms/start")
    def comms_start():
        return service.start_comms()

    @app.post("/api/comms/stop")
    def comms_stop():
        return service.stop_comms()

    @app.get("/api/search")
    def search_chats(q: str = ""):
        """Cross-chat keyword search for the sidebar search box."""
        return {"results": service.search_chats(q)}

    # -- message actions (Phase 4) ------------------------------------------------

    @app.delete("/api/sessions/{session_id}/turns/{turn_id}")
    def turn_delete(session_id: str, turn_id: int):
        ok = service.db.delete_turn(session_id, turn_id)
        if ok:
            event_log.publish({"type": "history_changed", "session_id": session_id})
        return {"ok": ok}

    @app.post("/api/sessions/{session_id}/truncate")
    def turn_truncate(session_id: str, body: dict):
        """Rewind a chat: delete the given turn and everything after it (regenerate
        and edit-and-resend then send the user message again)."""
        try:
            turn_id = int(body.get("from_turn_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="from_turn_id is required") from exc
        removed = service.db.delete_turns_from(session_id, turn_id)
        event_log.publish({"type": "history_changed", "session_id": session_id})
        return {"ok": True, "removed": removed}

    @app.post("/api/sessions/{session_id}/branch")
    def turn_branch(session_id: str, body: dict):
        """A new chat that copies this one up to and including the given turn."""
        try:
            turn_id = int(body.get("upto_turn_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="upto_turn_id is required") from exc
        new_id = service.db.branch_session(session_id, turn_id)
        if not new_id:
            raise HTTPException(status_code=404, detail="nothing to branch")
        return {"ok": True, "session_id": new_id}

    # -- inline visuals & render feedback (Phase 4) ------------------------------

    @app.get("/api/visuals/{visual_id}")
    def visual_html(visual_id: str):
        """The stored HTML of a render_visual visual. The client wraps it in a
        sandboxed iframe (srcdoc, CSP connect-src 'none'); it is served as plain
        text so the browser never renders it on the app's origin."""
        from fastapi.responses import PlainTextResponse

        from namma_agent.tools.visuals import load_visual
        html = load_visual(visual_id)
        if html is None:
            raise HTTPException(status_code=404, detail="no such visual")
        return PlainTextResponse(html, headers={"X-Content-Type-Options": "nosniff",
                                                "Cache-Control": "private, max-age=3600"})

    @app.post("/api/render_error")
    def render_error(body: dict):
        """A mermaid / chart / visual / A2UI block failed to render in the browser.
        Noted per chat; the model hears about it at the start of its next turn."""
        return service.note_render_error(
            str(body.get("session_id") or ""), str(body.get("kind") or "visual"),
            str(body.get("error") or ""), str(body.get("snippet") or ""))

    # -- delegation runs (Phase 3) ---------------------------------------------

    @app.get("/api/runs")
    def runs_list(session_id: str = "", kind: str = "", limit: int = 100):
        """Sub-agent runs (delegate_task children and background tasks), newest first."""
        return {"runs": service.list_runs(session_id=session_id, kind=kind, limit=limit)}

    @app.get("/api/runs/{run_id}")
    def runs_get(run_id: str):
        run = service.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="no such run")
        return run

    @app.post("/api/runs/{run_id}/cancel")
    def runs_cancel(run_id: str):
        """Cancel a run and its whole subtree."""
        return service.cancel_run(run_id)

    @app.get("/api/usage/requests")
    def usage_requests(session_id: str = "", limit: int = 100, days: int = 7):
        """Per-request usage log (Phase 2): the newest model calls — chat steps
        and background work — plus the by-kind breakdown and cache-read ratio."""
        return {"requests": service.db.usage_requests(session_id=session_id, limit=limit),
                "breakdown": service.db.usage_breakdown(days=days)}

    @app.get("/api/status")
    def background_status():
        """Every background subsystem at a glance (memory writer, consolidator,
        routines, background tasks, reminders, comms) + a 7-day usage summary."""
        return service.background_status()

    # -- proactive routines (scheduled agent runs → comms) -------------------

    @app.get("/api/routines")
    def routines_list():
        return {"routines": service.list_routines()}

    @app.post("/api/routines/toggle")
    def routines_toggle(body: dict):
        ok = service.set_routine_enabled(int(body.get("id", 0)),
                                         bool(body.get("enabled", True)))
        return {"ok": ok}

    @app.delete("/api/routines/{routine_id}")
    def routines_delete(routine_id: int):
        return {"ok": service.delete_routine(routine_id)}

    @app.post("/api/routines/{routine_id}/run")
    def routines_run(routine_id: int):
        content = service.run_routine_now(routine_id)
        return {"ok": content is not None, "content": content or ""}

    # -- event watchers (trigger + gate + action → comms) ---------------------

    @app.get("/api/watchers")
    def watchers_list():
        return {"watchers": service.list_watchers()}

    @app.post("/api/watchers/toggle")
    def watchers_toggle(body: dict):
        ok = service.set_watcher_enabled(int(body.get("id", 0)),
                                         bool(body.get("enabled", True)))
        return {"ok": ok}

    @app.delete("/api/watchers/{watcher_id}")
    def watchers_delete(watcher_id: int):
        return {"ok": service.delete_watcher(watcher_id)}

    @app.post("/api/watchers/{watcher_id}/run")
    def watchers_run(watcher_id: int):
        res = service.run_watcher_now(watcher_id)
        return {"ok": res is not None, **(res or {})}

    # -- learning settings (Settings → System → Learning) ---------------------
    # Deliberately NOT under /api/learning/… — that prefix is the Learning Room's
    # topic namespace, where GET /api/learning/{topic_id} would swallow "settings".

    @app.get("/api/learning_settings")
    def learning_settings():
        """The weekly-review schedule + Learning-Room knobs, with the live state
        of both background threads."""
        return service.learning_settings()

    @app.post("/api/learning_settings")
    def learning_settings_save(body: LearningSettingsBody):
        """Persist to user_config.yaml and apply live (runners start/stop now)."""
        return service.save_learning_settings(body.settings)

    # -- weekly self-review (measured self-improvement) -----------------------

    @app.get("/api/self_review")
    def self_review_overview():
        """Report + snapshot trend + proposals — the Learning tab's payload."""
        return service.self_review_overview()

    @app.post("/api/self_review/run")
    def self_review_run():
        """Manual 'Run review now' — no comms delivery, result shown in the UI."""
        return {"ok": True, "report": service.run_self_review(deliver=False)}

    @app.post("/api/self_review/proposals/{pid}/{action}")
    def self_review_resolve(pid: int, action: str):
        if action not in ("accept", "reject"):
            return {"ok": False, "detail": "action must be accept or reject"}
        ok, detail = service.resolve_self_review_proposal(
            pid, "accepted" if action == "accept" else "rejected")
        return {"ok": ok, "detail": detail}

    @app.get("/api/providers")
    def providers():
        """The provider catalogue in the Phase 9 contract shape —
        ``{providers: [{id, label, group, auth, key_env, key_url, base_url,
        needs_base_url, key_set, connected, docs_url, …}], groups, active}``."""
        from namma_agent.core.providers.catalog import GROUPS, provider_catalog

        pcfg = service.config.get("provider") or {}
        return {
            "providers": provider_catalog(service.configured_providers()),
            "groups": list(GROUPS),
            "active": {
                "type": pcfg.get("type", ""),
                "model": pcfg.get("model", ""),
                "base_url": pcfg.get("base_url", ""),
            },
        }

    # -- provider OAuth (Phase 9 W2: OpenRouter PKCE) -----------------------
    from namma_agent.core.oauth import OAuthError, OAuthManager

    oauth = OAuthManager()
    app.state.oauth = oauth

    @app.post("/api/providers/{provider_id}/oauth/start")
    def provider_oauth_start(provider_id: str, request: Request):
        """Begin an official PKCE sign-in. Returns ``{authorize_url}`` for the UI
        to open; the provider redirects back to ``/api/oauth/{id}/callback/…``."""
        from fastapi.responses import JSONResponse

        server_base = str(request.base_url).rstrip("/")
        # Only this app's own pages may start a flow: CORS is open (*), so without
        # this a third-party site could start one and later feed the callback a
        # code from ITS OWN account (login CSRF → the user's chats on its key).
        # (Loopback origins on any port are this machine — e.g. the Vite dev server.)
        origin = (request.headers.get("origin") or "").rstrip("/")
        loopback = bool(re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", origin))
        if origin and origin != server_base and not loopback:
            return JSONResponse({"ok": False, "error": "cross-origin sign-in refused"},
                                status_code=403)
        if not oauth.supports(provider_id):
            return JSONResponse({"ok": False, "error": f"{provider_id!r} has no sign-in flow"},
                                status_code=404)
        try:
            flow = oauth.start(provider_id, server_base)
        except OAuthError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        logger.info("[oauth] %s sign-in started", provider_id)
        return {"ok": True, "authorize_url": flow["authorize_url"]}

    def _oauth_finish(provider_id: str, state: str, code: str, error: str = ""):
        from urllib.parse import quote

        from fastapi.responses import RedirectResponse

        if error:
            msg = f"Sign-in was cancelled or refused ({error})."
        else:
            try:
                key_env, key = oauth.finish(provider_id, state, code)
                saved = service.setup_save_secret(key_env, key)
                if saved.get("ok"):
                    logger.info("[oauth] %s connected (vault=%s)", provider_id, saved.get("vault"))
                    return RedirectResponse(f"/settings/model?connected={quote(provider_id)}",
                                            status_code=303)
                msg = saved.get("error") or "Couldn't store the key."
            except OAuthError as exc:
                msg = str(exc)
        logger.warning("[oauth] %s sign-in failed: %s", provider_id, msg)
        return RedirectResponse(f"/settings/model?oauth_error={quote(msg)}"
                                f"&provider={quote(provider_id)}", status_code=303)

    @app.get("/api/oauth/{provider_id}/callback/{state}")
    def provider_oauth_callback_nonce(provider_id: str, state: str, code: str = "",
                                      error: str = ""):
        """OpenRouter echoes no ``state``, so the nonce rides in the path."""
        return _oauth_finish(provider_id, state, code, error)

    @app.get("/api/oauth/{provider_id}/callback")
    def provider_oauth_callback(provider_id: str, code: str = "", state: str = "",
                                error: str = ""):
        """Contract path; the nonce comes as ``?state=``."""
        return _oauth_finish(provider_id, state, code, error)

    # -- the default model (Phase 9 W2: explicit active_model) ---------------

    @app.get("/api/active_model")
    def get_active_model():
        return {"model_id": service.active_model_id()}

    @app.post("/api/active_model")
    def post_active_model(body: ActiveModelBody):
        """Make a configured model the default brain (``{model_id}``; "" clears)."""
        result = service.set_active_model(body.model_id)
        if result.get("ok"):
            logger.info("[settings] default model -> %s", result.get("model_id"))
        return result

    @app.get("/api/env_status")
    def env_status(keys: str = ""):
        """Which of the given .env keys are set (true/false) — so the UI can show
        a “key set” badge per provider without ever exposing the value. ``keys`` is
        a comma-separated list of env var names."""
        import os as _os
        names = [k.strip() for k in (keys or "").split(",") if k.strip()]
        return {"env_set": {k: bool(_os.environ.get(k)) for k in names}}

    @app.get("/api/configured_providers")
    def configured_providers():
        """The user's named provider connections (for the Providers tab and the
        provider picker in the Models tab)."""
        return {"providers": service.configured_providers()}

    @app.post("/api/configured_providers")
    def save_configured_providers(body: ConfiguredProvidersBody):
        """Persist the named provider connections to user_config.yaml and apply
        them live (no restart): models built on these providers rebuild on the
        next turn with the new type/base_url/key."""
        from namma_agent.config import configured_providers as _norm
        from namma_agent.config import update_config

        normalised = _norm({"providers": body.providers})
        update_config({"providers": normalised})
        applied = service.reload_providers(normalised)
        logger.info("[settings] saved %d provider(s)", len(applied))
        return {"ok": True, "providers": applied}

    @app.get("/api/configured_models")
    def configured_models():
        """The user's curated, switchable model profiles (for the chat switcher
        and the Models settings tab)."""
        return {"models": service.configured_models()}

    @app.post("/api/configured_models")
    def save_configured_models(body: ConfiguredModelsBody):
        """Persist the model-profile list to user_config.yaml and apply it live
        (no restart): new profiles are immediately switchable in chat."""
        from namma_agent.config import configured_models as _norm
        from namma_agent.config import update_config

        # Normalise (guarantee ids) before persisting so saved == served.
        normalised = _norm({"models": body.models})
        update_config({"models": normalised})
        applied = service.reload_models(normalised)
        logger.info("[settings] saved %d model profile(s)", len(applied))
        return {"ok": True, "models": applied}

    @app.get("/api/models")
    def models(type: str = "", base_url: str = "", api_key: str = "", provider_id: str = ""):
        """Live list of available models (best-effort).

        Pass ``provider_id`` to list a configured provider's models — the server
        resolves its type/base_url and reads its API key from that provider's own
        ``.env`` var. (Or pass ``type``/``base_url``/``api_key`` directly.) Returns
        the names plus ``source`` (live/fallback) and a human ``error`` so the UI
        can explain a short or empty list instead of silently showing defaults.
        """
        from namma_agent.core.providers.catalog import list_models_result

        if provider_id:
            conn = next((p for p in service.configured_providers()
                         if p["id"] == provider_id), None)
            if conn is None:
                return {"models": [], "source": "fallback",
                        "error": f"Unknown provider “{provider_id}”."}
            type = type or conn.get("type", "")
            base_url = base_url or conn.get("base_url", "")
            if not api_key and conn.get("api_key_env"):
                import os as _os
                api_key = _os.environ.get(conn["api_key_env"], "") or ""
        return list_models_result(type, base_url, api_key)

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        """Save an attached document and return its path so the agent can read it
        (via read_document). Used by the chat UI's attach button."""
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        limit = _upload_limit_bytes(service.config)
        safe_name = Path(file.filename or "upload").name or "upload"
        dest = _unique_upload_path(_UPLOAD_DIR, safe_name)
        # Stream to disk in chunks with a hard size cap: reading the whole body
        # into memory let one request exhaust RAM, and a same-named upload
        # silently overwrote an earlier attachment.
        size = 0
        try:
            with dest.open("wb") as fh:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(
                            status_code=413,
                            detail=f"file exceeds the {limit // (1024 * 1024)} MB upload limit "
                                   "(server.max_upload_mb)")
                    fh.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        logger.info("[upload] saved %s (%d bytes)", dest, size)
        return {"ok": True, "path": str(dest.resolve()), "name": dest.name, "bytes": size}

    # -- event protocol v2 (Phase 4): one app-level log, seq + replay ---------
    #
    # Every chat event goes through ``event_log`` (server/event_log.py): it gets
    # a ``seq``, lands in a ring buffer, and fans out to EVERY connected socket.
    # A reconnecting client resumes from its last seq, so a dropped connection
    # no longer loses the in-flight reply. Turn state that must survive a
    # reconnect (approval / password waits, Stop flags, per-chat locks) lives
    # here at app level, not inside one connection.
    from namma_agent.server.event_log import EventLog

    event_log = EventLog(size=500)
    app.state.event_log = event_log
    _broadcast = getattr(service, "broadcast", None)
    if _broadcast is not None:
        # Process-wide events (sub-agent runs that outlive a turn) join the log.
        _broadcast.subscribe(lambda e, p: event_log.publish({"type": e, **p}))
    approvals: dict[str, queue.Queue] = {}
    passwords: dict[str, queue.Queue] = {}
    # Tools the user chose to "allow for the rest of this session", keyed by
    # session id — remembered for that chat only.
    session_allow: dict[str, set[str]] = {}
    counter = itertools.count()
    # Per-session cancel flags so the Stop button only halts the chat it was
    # pressed in — several turns (one per chat) can run concurrently.
    cancel_flags: dict[str, dict] = {}
    # One turn at a time per chat (keyed by event loop too: test clients each
    # run their own loop, and an asyncio.Lock is bound to the loop it was used
    # on). A new prompt waits for a stopping turn to wind down.
    turn_locks: dict[tuple, asyncio.Lock] = {}
    # Strong references to running turn tasks: a turn outlives the socket that
    # started it (the client may reconnect and resume), and asyncio only keeps
    # weak references to tasks — an unreferenced one can be collected mid-run.
    turn_tasks: set = set()

    def publish(item: dict) -> dict:
        return event_log.publish(item)

    def sink(event: str, payload: dict):
        publish({"type": event, **payload})

    def make_approval(session_id: str):
        def approval(tool: str, args: dict) -> bool:
            # Already approved for the whole session? Run it without prompting.
            if tool in session_allow.get(session_id, set()):
                return True
            aid = str(next(counter))
            resp_q: queue.Queue = queue.Queue()
            approvals[aid] = resp_q
            publish({"type": "approval_request", "id": aid, "tool": tool,
                     "args": args, "session_id": session_id})
            # Wait for the answer in short slices so Stop also releases a turn
            # parked on an approval card (it used to block for up to 300 s).
            resp = None
            deadline = time.monotonic() + 300
            try:
                while resp is None:
                    flag = cancel_flags.get(session_id)
                    if (flag and flag.get("stop")) or time.monotonic() >= deadline:
                        approvals.pop(aid, None)
                        return False
                    try:
                        resp = resp_q.get(timeout=0.25)
                    except queue.Empty:
                        continue
            finally:
                # Every open tab drops the card, whoever answered.
                publish({"type": "approval_resolved", "id": aid, "session_id": session_id})
            # The client answers with {approved, scope}: scope "session" remembers
            # the tool so later calls in this chat skip the prompt. (A bare bool is
            # still honored for safety.)
            if not isinstance(resp, dict):
                return bool(resp)
            approved = bool(resp.get("approved"))
            if approved and resp.get("scope") == "session":
                session_allow.setdefault(session_id, set()).add(tool)
            return approved
        return approval

    def askpass(prompt: str):
        """Request a sudo password from the UI. The secret is returned to the
        caller (run_shell) and never logged or persisted here."""
        pid = "pw" + str(next(counter))
        resp_q: queue.Queue = queue.Queue()
        passwords[pid] = resp_q
        publish({"type": "password_request", "id": pid, "prompt": prompt})
        try:
            return resp_q.get(timeout=180) or None
        except queue.Empty:
            return None

    async def run_turn(text: str, session_id: Optional[str], mode: str,
                       client_ref: Optional[str], model: Optional[str] = None):
        # Resolve the session id up front so every event of this turn — tokens
        # included — is tagged with it. New chats (no session_id) get a fresh
        # session row here, bound to the chosen model; the client maps its
        # provisional ref to this id.
        sid = session_id or service.db.create_session(
            persona=service.persona.id, model=model or None)
        # Switching model mid-chat no longer needs a new session (Phase 4): the
        # client sends the model it wants for THIS turn and it becomes the
        # chat's model from here on.
        sess = service.db.get_session(sid)
        bound = (sess or {}).get("model") or ""
        if model and model != bound:
            service.db.set_session_model(sid, model)
            bound = model
        effective_model = bound or model or ""
        key = (id(asyncio.get_running_loop()), sid)
        lock = turn_locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            # Visible "queued" state: this prompt waits for the turn that is
            # still running (or winding down after Stop) in the same chat.
            publish({"type": "turn_queued", "session_id": sid, "client_ref": client_ref})
        async with lock:
            await _run_locked_turn(text, sid, mode, client_ref, effective_model)

    async def _run_locked_turn(text: str, sid: str, mode: str,
                               client_ref: Optional[str], effective_model: str):
        flag = {"stop": False}
        cancel_flags[sid] = flag
        publish({"type": "session_started", "session_id": sid, "client_ref": client_ref,
                 "model": effective_model})

        def on_token_sid(t: str):
            publish({"type": "token", "text": t, "session_id": sid})

        try:
            result = await asyncio.to_thread(
                service.run_turn, text, sid, sink, on_token_sid,
                make_approval(sid), mode, lambda: flag["stop"], askpass,
                effective_model,
            )
            _u = result.usage or {}
            publish({
                "type": "turn_result",
                "content": result.content,
                "session_id": result.session_id,
                "tools_used": result.tools_used,
                # Per-turn stats for the UI: time-to-first-token (seconds) and the
                # headline token total — fresh input + cache writes + output, summed
                # across the whole tool loop. Cheap cache *reads* are reported
                # separately as `cached` so the headline matches the provider's
                # usage dashboard.
                "ttft": result.ttft,
                "tokens": usage_tokens(_u),
                "cached": _u.get("cache_read_tokens", 0) or 0,
                "exit_reason": result.exit_reason,
                "user_turn_id": result.user_turn_id,
                "assistant_turn_id": result.assistant_turn_id,
                # Structured activity timeline (thinking / tool steps) for the
                # transparency UI — pinned under the reply, persisted via turn meta.
                "steps": result.steps,
            })
            # Auto-title the chat from its first exchange (background, best-effort)
            # so the sidebar shows a concise label, not the raw first message.
            async def _title(tsid: str):
                title = await asyncio.to_thread(service.auto_title, tsid)
                if title:
                    publish({"type": "session_titled", "session_id": tsid, "title": title})
            asyncio.create_task(_title(result.session_id))
        except Exception as exc:  # noqa: BLE001
            logger.error("[ws] turn failed: %s", exc)
            publish({"type": "error", "message": str(exc), "session_id": sid})
        finally:
            # Only drop OUR flag — never a newer turn's.
            if cancel_flags.get(sid) is flag:
                cancel_flags.pop(sid, None)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        # Phase 6a: same token as /api/* (?token= on the WS URL — headers are
        # awkward from browsers). 4401 = our "unauthorized" close code.
        # The desktop shell injects X-Namma-Token on every request to its
        # backend (including this upgrade), so the page never holds the token.
        if not _token_ok(websocket.query_params.get("token")
                         or websocket.headers.get("x-namma-token")):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        loop = asyncio.get_running_loop()
        outgoing: asyncio.Queue = asyncio.Queue()

        async def sender():
            while True:
                item = await outgoing.get()
                if item is None:
                    return
                await websocket.send_json(item)

        sender_task = asyncio.create_task(sender())

        def push(item):
            """Connection-local send (thread-safe). ``None`` stops the sender."""
            loop.call_soon_threadsafe(outgoing.put_nowait, item)

        # Not subscribed to the log until the client says where it left off
        # (``resume``) — so replay and live events can't interleave. A client
        # that sends anything else first is subscribed live-only.
        sub = {"unsubscribe": None}

        def ensure_subscribed(after=None, boot=None) -> None:
            if sub["unsubscribe"] is not None:
                if after is None:
                    return
                sub["unsubscribe"]()          # a second resume restarts the feed
            unsubscribe, replay, ok = event_log.subscribe(push, after=after, boot=boot)
            sub["unsubscribe"] = unsubscribe
            for item in replay:
                push(item)
            if not ok:
                push({"type": "resync_required", "boot": event_log.boot,
                      "seq": event_log.seq})

        push({"type": "hello", "boot": event_log.boot, "seq": event_log.seq})

        try:
            while True:
                msg = await websocket.receive_json()
                mtype = msg.get("type")
                if mtype == "resume":
                    try:
                        after = int(msg.get("from_seq"))
                    except (TypeError, ValueError):
                        after = None
                    ensure_subscribed(after=after, boot=msg.get("boot"))
                    continue
                ensure_subscribed()
                if mtype == "user_input":
                    task = asyncio.create_task(run_turn(
                        msg.get("text", ""), msg.get("session_id"),
                        msg.get("mode", "agent"), msg.get("client_ref"),
                        msg.get("model")))
                    turn_tasks.add(task)
                    task.add_done_callback(turn_tasks.discard)
                elif mtype == "approval_response":
                    q = approvals.pop(msg.get("id"), None)
                    if q is not None:
                        q.put({"approved": bool(msg.get("approved")),
                               "scope": msg.get("scope") or "once"})
                elif mtype == "password_response":
                    # Hand the secret straight to the waiting tool; never log it.
                    q = passwords.pop(msg.get("id"), None)
                    if q is not None:
                        q.put(msg.get("password") or "")
                elif mtype == "stop":
                    # Cancel only the turn for the named session (or every in-flight
                    # turn when no session is given — e.g. a global stop).
                    sid = msg.get("session_id")
                    flags = [cancel_flags[sid]] if sid in cancel_flags else (
                        list(cancel_flags.values()) if sid is None else [])
                    for f in flags:
                        f["stop"] = True
                    push({"type": "stop_speaking"})  # tell this browser to hush
                    # "stopping" until the turn really ends (its turn_result).
                    publish({"type": "stopped", "session_id": sid,
                             "running": bool(flags)})
                elif mtype == "stop_speech":
                    push({"type": "stop_speaking"})  # barge-in: cancel browser TTS
                elif mtype == "ping":
                    push({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            if sub["unsubscribe"] is not None:
                sub["unsubscribe"]()
            push(None)
            await sender_task

    # OpenAI-compatible surface (Phase 7f): /v1/chat/completions + /v1/models,
    # so any OpenAI-speaking client can drive the whole agent. Registered BEFORE
    # the SPA catch-all below, which would otherwise swallow /v1 GETs.
    from namma_agent.server.openai_api import register_openai_api
    register_openai_api(app, service)

    # Serve generated artifacts (diagrams / images / simulations) as downloadable
    # static files so the chat/Learning-Room UI can render and download them.
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/api/media", StaticFiles(directory=str(_MEDIA_DIR)), name="media")

    # Serve the built GUI (Phase 5) if present, with SPA fallback so client routes
    # (/projects, /learning, …) resolve to index.html on a hard refresh.
    if _WEBUI_DIST.exists():
        from starlette.responses import FileResponse

        _assets = _WEBUI_DIST / "assets"
        if _assets.exists():
            app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

        # index.html must never be cached: it points at hashed JS/CSS, so a cached
        # copy would keep loading a stale bundle (and stale UI) after an update.
        _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            candidate = _WEBUI_DIST / full_path
            if full_path and candidate.is_file() and _WEBUI_DIST in candidate.resolve().parents:
                # Hashed assets are immutable; everything else (incl. index.html) no-cache.
                if candidate.suffix == ".html":
                    return FileResponse(candidate, headers=_NO_CACHE)
                return FileResponse(candidate)
            return FileResponse(_WEBUI_DIST / "index.html", headers=_NO_CACHE)

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    run()
