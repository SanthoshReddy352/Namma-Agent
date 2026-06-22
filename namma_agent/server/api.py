"""FastAPI + WebSocket backend for Namma Agent.

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
import json
import queue
import re
import threading
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from namma_agent.core.logger import logger
from namma_agent.core.providers.base import usage_tokens
from namma_agent.service import NammaAgentService

_UPLOAD_DIR = Path("data/uploads")
_MEDIA_DIR = Path("data/media")

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
    config: dict = {}   # deep-merged into config.local.yaml
    env: dict = {}      # written to .env (e.g. API keys)


class MemoryClearBody(BaseModel):
    scope: str = "all"  # facts | conversations | notes | all


class UninstallBody(BaseModel):
    scope: str = "all"  # all | keep-data


class NotifyBody(BaseModel):
    title: str = "Namma Agent"
    body: str = ""


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

    @app.get("/api/health")
    def health():
        return {"ok": True}

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

    @app.get("/api/tools")
    def tools():
        """All tools grouped by toolset, with enabled/destructive flags (Toolsets tab)."""
        return {"tools": service.tools_detail()}

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
        from namma_agent.core import packs
        from namma_agent.config import assistant_name
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
        return {"session_id": session_id,
                "turns": _restore_turns(service.db, session_id),
                "project": project, "topic": topic,
                "model": (meta.get("model") or "").strip(),
                "title": (meta.get("title") or "").strip()}

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
        The frontend gates on the user's master + per-event toggles before calling."""
        from namma_agent.core.notifications import send_native_notification
        ok = send_native_notification(body.title, body.body)
        return {"ok": ok}

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
        if result.get("started"):
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
                    "NAMMA_WHATSAPP_TOKEN", "NAMMA_WHATSAPP_PHONE_ID", "NAMMA_WHATSAPP_TO",
                    "NAMMA_WHATSAPP_VERIFY_TOKEN", "NAMMA_SIGNAL_API_URL",
                    "NAMMA_SIGNAL_NUMBER", "NAMMA_SIGNAL_RECIPIENT", "NAMMA_SLACK_SIGNING_SECRET"]
        return {
            "config": load_config(),
            "env_set": {k: bool(_os.environ.get(k)) for k in env_keys},
        }

    @app.post("/api/settings")
    def update_settings(body: SettingsBody):
        from namma_agent.config import set_env_values, update_config

        merged = update_config(body.config) if body.config else None
        written = set_env_values(body.env) if body.env else []
        logger.info("[settings] updated config keys=%s env keys=%s",
                    list((body.config or {}).keys()), written)
        # Apply live — rebuild the provider so a changed brain / base_url / API key
        # takes effect on the next turn, no restart. (Runs when the provider config
        # OR an env key changed; env-only edits rebuild against the current config.)
        if merged is not None or written:
            service.apply_config(merged)
        return {"ok": True, "config": merged, "env_written": written,
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
        """Enable/disable a skill; persists to config.local.yaml (skills.disabled)."""
        return service.set_skill_enabled(body.name, body.enabled)

    # -- toolsets (Settings → Toolsets tab) ---------------------------------

    @app.post("/api/tools/toggle")
    def toggle_tool(body: ToolToggleBody):
        """Enable/disable a single tool; persists to config.local.yaml (tools.disabled)."""
        return service.set_tool_enabled(body.name, body.enabled)

    @app.post("/api/toolset/toggle")
    def toggle_toolset(body: ToolsetToggleBody):
        """Enable/disable every tool in a toolset at once; persists the disabled-set."""
        return service.set_toolset_enabled(body.category, body.enabled)

    @app.get("/api/comms/status")
    def comms_status():
        return service.comms_status()

    @app.post("/api/comms/start")
    def comms_start():
        return service.start_comms()

    @app.post("/api/comms/stop")
    def comms_stop():
        return service.stop_comms()

    @app.get("/api/providers")
    def providers():
        """Provider catalog (with .env key-set flags) + the active provider config."""
        from namma_agent.core.providers.catalog import provider_catalog

        pcfg = service.config.get("provider") or {}
        return {
            "providers": provider_catalog(),
            "active": {
                "type": pcfg.get("type", ""),
                "model": pcfg.get("model", ""),
                "base_url": pcfg.get("base_url", ""),
            },
        }

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
        """Persist the named provider connections to config.local.yaml and apply
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
        """Persist the model-profile list to config.local.yaml and apply it live
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
        safe_name = Path(file.filename or "upload").name
        dest = _UPLOAD_DIR / safe_name
        data = await file.read()
        dest.write_bytes(data)
        logger.info("[upload] saved %s (%d bytes)", dest, len(data))
        return {"ok": True, "path": str(dest.resolve()), "name": safe_name, "bytes": len(data)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        outgoing: asyncio.Queue = asyncio.Queue()
        approvals: dict[str, queue.Queue] = {}
        passwords: dict[str, queue.Queue] = {}
        # Tools the user chose to "allow for the rest of this session" — keyed by
        # session id, so a session-wide approval is remembered for that chat only and
        # later calls to the same tool skip the prompt. Cleared when the socket closes.
        session_allow: dict[str, set[str]] = {}
        counter = itertools.count()
        # Per-session cancel flags so the Stop button only halts the chat it was
        # pressed in — several turns (one per chat) can run concurrently here.
        cancel_flags: dict[str, dict] = {}

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

        def make_approval(session_id: str):
            def approval(tool: str, args: dict) -> bool:
                # Already approved for the whole session? Run it without prompting.
                if tool in session_allow.get(session_id, set()):
                    return True
                aid = str(next(counter))
                resp_q: queue.Queue = queue.Queue()
                approvals[aid] = resp_q
                push({"type": "approval_request", "id": aid, "tool": tool,
                      "args": args, "session_id": session_id})
                try:
                    resp = resp_q.get(timeout=300)
                except queue.Empty:
                    return False
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
            push({"type": "password_request", "id": pid, "prompt": prompt})
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
            # A session's model is sticky: the first turn binds it, later turns use
            # the bound model (switching mid-chat starts a NEW session, by design).
            sess = service.db.get_session(sid)
            bound = (sess or {}).get("model") or ""
            if not bound and model:
                service.db.set_session_model(sid, model)
                bound = model
            effective_model = bound or model or ""
            flag = {"stop": False}
            cancel_flags[sid] = flag
            push({"type": "session_started", "session_id": sid, "client_ref": client_ref,
                  "model": effective_model})

            def on_token_sid(t: str):
                push({"type": "token", "text": t, "session_id": sid})

            try:
                result = await asyncio.to_thread(
                    service.run_turn, text, sid, sink, on_token_sid,
                    make_approval(sid), mode, lambda: flag["stop"], askpass,
                    effective_model,
                )
                _u = result.usage or {}
                push({
                    "type": "turn_result",
                    "content": result.content,
                    "session_id": result.session_id,
                    "tools_used": result.tools_used,
                    # Per-turn stats for the UI: time-to-first-token (seconds) and the
                    # headline token total — fresh input + cache writes + output, summed
                    # across the whole tool loop. Cheap cache *reads* (the prompt prefix
                    # re-served on every step) are reported separately as `cached` so the
                    # headline matches the provider's usage dashboard.
                    "ttft": result.ttft,
                    "tokens": usage_tokens(_u),
                    "cached": _u.get("cache_read_tokens", 0) or 0,
                    # Structured activity timeline (thinking / tool steps) for the
                    # transparency UI — pinned under the reply, persisted via turn meta.
                    "steps": result.steps,
                })
                # Auto-title the chat from its first exchange (background, best-effort)
                # so the sidebar shows a concise label, not the raw first message.
                async def _title(tsid: str):
                    title = await asyncio.to_thread(service.auto_title, tsid)
                    if title:
                        push({"type": "session_titled", "session_id": tsid, "title": title})
                asyncio.create_task(_title(result.session_id))
            except Exception as exc:  # noqa: BLE001
                logger.error("[ws] turn failed: %s", exc)
                push({"type": "error", "message": str(exc), "session_id": sid})
            finally:
                cancel_flags.pop(sid, None)

        try:
            while True:
                msg = await websocket.receive_json()
                mtype = msg.get("type")
                if mtype == "user_input":
                    asyncio.create_task(run_turn(
                        msg.get("text", ""), msg.get("session_id"),
                        msg.get("mode", "agent"), msg.get("client_ref"),
                        msg.get("model")))
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
                    push({"type": "stop_speaking"})  # tell the browser to hush
                    push({"type": "stopped", "session_id": sid})
                elif mtype == "stop_speech":
                    push({"type": "stop_speaking"})  # barge-in: cancel browser TTS
                elif mtype == "ping":
                    push({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            push(None)
            await sender_task

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
