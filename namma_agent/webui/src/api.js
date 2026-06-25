import { useCallback, useEffect, useRef, useState } from "react";
import { playSound } from "./sounds.js";
import { notify } from "./notify.js";

function wsURL() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

async function j(url, opts) {
  try {
    const r = await fetch(url, opts);
    return await r.json();
  } catch {
    return null;
  }
}

// ── REST helpers ────────────────────────────────────────────────────────────
export const fetchConfig = () => j("/api/config");
export const fetchSettings = () => j("/api/settings");
export const saveSettings = (config, env) =>
  j("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ config, env }) });
export const clearMemory = (scope) =>
  j("/api/memory/clear", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope }) });
export const fetchProviders = () => j("/api/providers");
export const fetchEnvStatus = (keys) => j(`/api/env_status?keys=${encodeURIComponent((keys || []).join(","))}`);
export const fetchConfiguredModels = () => j("/api/configured_models");
export const saveConfiguredModels = (models) =>
  j("/api/configured_models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ models }) });
export const fetchModels = (type, baseUrl = "", apiKey = "") =>
  j(`/api/models?type=${encodeURIComponent(type)}&base_url=${encodeURIComponent(baseUrl)}` +
    (apiKey ? `&api_key=${encodeURIComponent(apiKey)}` : ""));
// List a configured provider's models — server resolves its base_url + key.
export const fetchModelsForProvider = (providerId) =>
  j(`/api/models?provider_id=${encodeURIComponent(providerId)}`);
export const fetchConfiguredProviders = () => j("/api/configured_providers");
export const saveConfiguredProviders = (providers) =>
  j("/api/configured_providers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ providers }) });
export const listSessions = () => j("/api/sessions");
export const loadSession = (id) => j(`/api/sessions/${id}`);
export const deleteSession = (id) => j(`/api/sessions/${id}`, { method: "DELETE" });
export const shutdownApi = () => j("/api/shutdown", { method: "POST" });

// ── Comms gateway (inbound messaging service) ────────────────────────────────
export const fetchCommsStatus = () => j("/api/comms/status");
export const startComms = () => j("/api/comms/start", { method: "POST" });
export const stopComms = () => j("/api/comms/stop", { method: "POST" });

// ── Version + self-update ─────────────────────────────────────────────────────
export const fetchVersion = () => j("/api/version");
export const checkUpdate = () => j("/api/update/check");
export const applyUpdate = () => j("/api/update/apply", { method: "POST" });
export const uninstallApp = (scope) =>
  j("/api/uninstall", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope }) });

// ── Personas ─────────────────────────────────────────────────────────────────
const _post = (url, body) =>
  j(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
export const fetchPersonas = () => j("/api/personas");
export const fetchPersona = (id) => j(`/api/personas/${encodeURIComponent(id)}`);
export const setPersona = (id) => _post("/api/persona", { id });
export const savePersona = (persona) => _post("/api/personas", persona);
export const generatePersona = (description) => _post("/api/personas/generate", { description });
export const deletePersona = (id) => j(`/api/personas/${encodeURIComponent(id)}`, { method: "DELETE" });

// ── Projects + chat organisation ────────────────────────────────────────────
const jpost = (url, body) =>
  j(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const jpatch = (url, body) =>
  j(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

export const listProjects = () => j("/api/projects");
export const createProject = (name, description = "") => jpost("/api/projects", { name, description });
export const getProject = (id) => j(`/api/projects/${id}`);
export const updateProject = (id, fields) => jpatch(`/api/projects/${id}`, fields);
export const deleteProject = (id) => j(`/api/projects/${id}`, { method: "DELETE" });
export const newProjectSession = (id) => jpost(`/api/projects/${id}/sessions`);
export const addProjectMemory = (id, content) => jpost(`/api/projects/${id}/memory`, { content });
// Switch a project chat to another configured model: the server recaps the
// current session and returns a fresh session id (seeded with that recap, kept in
// the same project) to open — the exact mirror of switchLearningModel.
export const switchProjectModel = (sessionId, model) =>
  jpost("/api/projects/switch_model", { session_id: sessionId, model });
export const deleteScopeMemory = (entryId) => j(`/api/scope_memory/${entryId}`, { method: "DELETE" });
export const renameSession = (id, title) => jpatch(`/api/sessions/${id}`, { title });
export const fileChat = (id, projectId) => jpost(`/api/sessions/${id}/project`, { project_id: projectId });

// ── Learning Room ───────────────────────────────────────────────────────────
export const listLearning = () => j("/api/learning");
export const createLearning = (topic, depth = "solid") => jpost("/api/learning", { topic, depth });
export const getLearning = (id) => j(`/api/learning/${id}`);
export const deleteLearning = (id) => j(`/api/learning/${id}`, { method: "DELETE" });
export const updateLearningPlan = (id, modules) => jpatch(`/api/learning/${id}/plan`, { modules });
export const learningModuleSession = (id, moduleId) => jpost(`/api/learning/${id}/module/${moduleId}/session`);
export const learningPathSession = (id) => jpost(`/api/learning/${id}/session`);
// Switch a learning thread to another configured model: the server recaps the
// current session and returns a fresh session id (seeded with that recap) to open.
export const switchLearningModel = (sessionId, model) =>
  jpost("/api/learning/switch_model", { session_id: sessionId, model });
export const recordLearningQuiz = (id, body) => jpost(`/api/learning/${id}/quiz`, body);
export const deleteTeachingPreference = (id, index) =>
  j(`/api/learning/${id}/preferences/${index}`, { method: "DELETE" });

export async function createLearningFromDocument(file) {
  const form = new FormData();
  form.append("file", file);
  return j("/api/learning/from_document", { method: "POST", body: form });
}

// ── Project documents (multi-document RAG) ──────────────────────────────────
export async function uploadProjectDocument(projectId, file) {
  const form = new FormData();
  form.append("file", file);
  return j(`/api/projects/${projectId}/documents`, { method: "POST", body: form });
}
export const deleteProjectDocument = (projectId, docId) =>
  j(`/api/projects/${projectId}/documents/${docId}`, { method: "DELETE" });
export const trustProjectDocument = (projectId, docId) =>
  jpost(`/api/projects/${projectId}/documents/${docId}/trust`);

export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return j("/api/upload", { method: "POST", body: form });
}

// ── Skill & Tool packs (export / import) ─────────────────────────────────────
export const fetchPackItems = () => j("/api/pack/items");
export const exportPack = (skills, tools) => jpost("/api/pack/export", { skills, tools });
export const packDownloadUrl = (filename) => `/api/pack/download/${encodeURIComponent(filename)}`;
export async function inspectPack(file) {
  const form = new FormData();
  form.append("file", file);
  return j("/api/pack/inspect", { method: "POST", body: form });
}
export async function installPack(file, { approvedTools = [], skills = null, overwrite = false } = {}) {
  const form = new FormData();
  form.append("file", file);
  form.append("approved_tools", (approvedTools || []).join(","));
  if (skills !== null) form.append("skills", (skills || []).join(","));
  form.append("overwrite", overwrite ? "true" : "false");
  return j("/api/pack/install", { method: "POST", body: form });
}

// ── Skills (Settings → Skills tab) ───────────────────────────────────────────
export const listSkills = () => j("/api/skills");
export const toggleSkill = (name, enabled) => jpost("/api/skills/toggle", { name, enabled });

// ── Tools / toolsets (Settings → Toolsets tab) ───────────────────────────────
export const listTools = () => j("/api/tools");
export const toggleTool = (name, enabled) => jpost("/api/tools/toggle", { name, enabled });
export const toggleToolset = (category, enabled) => jpost("/api/toolset/toggle", { category, enabled });

// ── MCP servers (Settings → MCP tab: Config + Servers) ───────────────────────
export const fetchMcp = () => j("/api/mcp");
export const reloadMcp = () => jpost("/api/mcp/reload");

let _id = 0;
const nextId = () => `m${++_id}`;

// Strip markdown so browser TTS reads words, not symbols.
function toPlainText(md) {
  return (md || "")
    .replace(/```[\s\S]*?```/g, ". code block. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/[*_>#]/g, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

// Speak via the browser's built-in TTS (Web Speech API). No server, no deps.
function browserSpeak(text) {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  const clean = toPlainText(text);
  if (!clean) return;
  const u = new SpeechSynthesisUtterance(clean);
  u.rate = 1.02;
  window.speechSynthesis.speak(u);
}
const browserHush = () => { if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel(); };

const EMPTY = { messages: [], timeline: [], status: "idle", streamId: null };
const blank = () => ({ messages: [], timeline: [], status: "idle", streamId: null });
const isProvisional = (k) => typeof k === "string" && k.startsWith("ref");
const LAST_SESSION_KEY = "namma-current-session";
const SERVER_ID_KEY = "namma-server-id";
// The "active model" — the brain the user last picked. New chats inherit it so a
// model choice sticks across chats instead of snapping back to the first profile.
const ACTIVE_MODEL_KEY = "namma-active-model";

/**
 * Core hook: one WebSocket turn channel feeding *per-session* state. Every chat
 * keeps its own messages / timeline / status, keyed by session id, so a turn
 * started in one chat keeps streaming while you read another, and several chats
 * can run at once. Events are routed by the `session_id` the server tags on each
 * message. A brand-new chat is held under a provisional `ref…` key until the
 * server assigns a real session id (`session_started`).
 */
export function useNammaAgent() {
  const [connected, setConnected] = useState(false);
  const [data, setData] = useState({});           // { [sid]: {messages,timeline,status,streamId} }
  const [currentSid, setCurrentSid] = useState(null); // viewed key (sid | ref… | null=empty)
  const [passwordReq, setPasswordReq] = useState(null);
  const [mode, setMode] = useState("agent");
  const [sessions, setSessions] = useState([]);
  const [shuttingDown, setShuttingDown] = useState(false);
  const [learningSignal, setLearningSignal] = useState(null); // {topic_id, at} — dashboard refresh
  const [voiceOn, setVoiceOn] = useState(false); // browser TTS auto-speak
  const [configuredModels, setConfiguredModels] = useState([]); // switchable brains
  const configuredModelsRef = useRef([]);
  configuredModelsRef.current = configuredModels;
  // The persisted active model — what new chats default to (see ACTIVE_MODEL_KEY).
  const [activeModel, setActiveModel] = useState(() => localStorage.getItem(ACTIVE_MODEL_KEY) || "");
  const activeModelRef = useRef(activeModel);
  activeModelRef.current = activeModel;
  const setActive = useCallback((modelId) => {
    if (!modelId) return;
    activeModelRef.current = modelId;
    setActiveModel(modelId);
    localStorage.setItem(ACTIVE_MODEL_KEY, modelId);
  }, []);
  const voiceRef = useRef(voiceOn);
  voiceRef.current = voiceOn;
  const dataRef = useRef({});                     // synchronous mirror of `data`
  const currentRef = useRef(null);
  currentRef.current = currentSid;
  const wsRef = useRef(null);
  const stopReconnectRef = useRef(false);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const now = () => Date.now();

  // Immutably update one session's slice (and keep the synchronous mirror fresh).
  const patch = useCallback((key, updater) => {
    if (!key) return;
    setData((all) => {
      const cur = all[key] || blank();
      const next = { ...cur, ...updater(cur) };
      const out = { ...all, [key]: next };
      dataRef.current = out;
      return out;
    });
  }, []);

  const refreshSessions = useCallback(async () => {
    const r = await listSessions();
    if (r?.sessions) setSessions(r.sessions);
  }, []);

  const connect = useCallback(() => {
    const ws = new WebSocket(wsURL());
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      if (!stopReconnectRef.current) setTimeout(connect, 1500);
    };
    ws.onmessage = (e) => handle(JSON.parse(e.data));
  }, []);

  // Append a streamed assistant chunk, opening a fresh assistant bubble if needed.
  // `meta` (on finalize) carries per-turn stats — { ttft, tokens } — for the footer.
  const appendToken = (cur, text, finalize, meta, steps) => {
    let { messages, streamId } = cur;
    if (!streamId) {
      streamId = nextId();
      messages = [...messages, { id: streamId, role: "assistant", content: "", at: now() }];
    }
    messages = messages.map((x) => (x.id === streamId
      ? { ...x, content: finalize ? (text ?? x.content) : x.content + text,
          ...(finalize ? { tools: finalize } : {}), ...(meta ? { meta } : {}),
          ...(steps ? { steps } : {}) }
      : x));
    return { messages, streamId };
  };

  // Fold a thinking/preamble/tool event into a session's live activity timeline —
  // the SAME reducer the backend uses (_record_step), so live and persisted match.
  const foldStep = (timeline, step) => {
    const tl = [...timeline];
    if (step.kind === "thinking" && tl.length && tl[tl.length - 1].kind === "thinking") {
      tl[tl.length - 1] = { ...tl[tl.length - 1], text: tl[tl.length - 1].text + step.text };
    } else {
      tl.push(step);
    }
    return tl;
  };

  function handle(msg) {
    const key = msg.session_id;
    switch (msg.type) {
      case "session_started": {
        // Promote the provisional `ref…` slice to the real session id.
        const ref = msg.client_ref, sid = msg.session_id;
        if (ref && sid) {
          setData((all) => {
            const out = { ...all };
            const prov = out[ref];
            if (prov) { out[sid] = { ...(out[sid] || blank()), ...prov }; delete out[ref]; }
            else if (!out[sid]) out[sid] = blank();
            dataRef.current = out;
            return out;
          });
          setCurrentSid((c) => (c === ref ? sid : c));
        }
        break;
      }
      case "token":
        patch(key, (cur) => ({ ...appendToken(cur, msg.text, null), status: "thinking" }));
        break;
      case "preamble":
        patch(key, (cur) => ({ timeline: foldStep(cur.timeline, { kind: "preamble", text: msg.text }) }));
        break;
      case "thinking":
        // Reasoning deltas — accumulate into a single running "Thinking" entry.
        patch(key, (cur) => ({ timeline: foldStep(cur.timeline, { kind: "thinking", text: msg.text }), status: "thinking" }));
        break;
      case "tool_started":
        patch(key, (cur) => ({ timeline: [...cur.timeline, { kind: "tool", tool: msg.tool, args: msg.args, state: "running" }] }));
        playSound("tool");
        break;
      case "tool_finished":
        patch(key, (cur) => {
          const copy = [...cur.timeline];
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].kind === "tool" && copy[i].tool === msg.tool && copy[i].state === "running") {
              copy[i] = { ...copy[i], state: msg.ok ? "ok" : "fail", summary: msg.summary };
              break;
            }
          }
          return { timeline: copy };
        });
        break;
      case "speak":
        // Only voice the chat you're actually looking at.
        if (voiceRef.current && key === currentRef.current) browserSpeak(msg.text);
        break;
      case "session_titled":
        // Model-generated chat title landed — patch the sidebar list in place, and
        // re-fetch to cover the case where the session isn't in the list yet.
        setSessions((list) => list.map((s) => (s.id === msg.session_id ? { ...s, title: msg.title } : s)));
        // Also update the chat's breadcrumb leaf ("New Chat" → the title) live.
        patch(msg.session_id, (cur) => ({ context: { ...(cur.context || {}), title: msg.title } }));
        refreshSessions();
        break;
      case "stop_speaking":
        browserHush();
        break;
      case "approval_request":
        // Inline approval: drop a card into THIS chat's live activity timeline (it
        // renders in place inside the working block, not as a global modal). It's
        // removed when the user answers (respondApproval).
        patch(key, (cur) => ({
          timeline: [...cur.timeline, { kind: "approval", id: msg.id, tool: msg.tool, args: msg.args }],
          status: "thinking",
        }));
        playSound("approval");
        notify("approval", { title: "Approval needed", body: `Allow ${msg.tool}?` });
        break;
      case "password_request":
        setPasswordReq({ id: msg.id, prompt: msg.prompt });
        playSound("input");
        notify("input", { title: "Input needed", body: msg.prompt || "Your assistant needs input." });
        break;
      case "turn_result": {
        patch(key, (cur) => {
          // Pin the activity timeline (thinking + tool steps) under the reply. Prefer
          // the server's structured steps; fall back to what we accumulated live.
          const steps = (msg.steps && msg.steps.length) ? msg.steps : cur.timeline;
          return {
            ...appendToken(cur, msg.content, msg.tools_used || [],
                           { ttft: msg.ttft, tokens: msg.tokens, cached: msg.cached },
                           steps),
            timeline: [], streamId: null, status: "idle",
          };
        });
        if (voiceRef.current && msg.content && key === currentRef.current) browserSpeak(msg.content);
        playSound("complete");
        // Desktop notification: the viewed chat finishing = "Response ready"; any
        // *other* chat finishing = a backgrounded task.
        {
          const snippet = toPlainText(msg.content || "").slice(0, 140);
          if (key === currentRef.current) notify("response", { title: "Response ready", body: snippet });
          else notify("background", { title: "Background task finished", body: snippet });
        }
        refreshSessions();
        if ((msg.tools_used || []).includes("exit_namma")) {
          stopReconnectRef.current = true;
          setTimeout(() => setShuttingDown(true), 1200);
        }
        break;
      }
      case "quiz": {
        // Interactive multiple-choice card rendered inline in the chat thread. The
        // question lives ONLY in this card — never let it go missing: if the event
        // somehow arrives without a session id, fall back to the open chat so the
        // learner always sees the artifact the teacher promised.
        const qsid = key || currentRef.current;
        const quiz = key ? msg : { ...msg, session_id: qsid };
        patch(qsid, (cur) => ({ messages: [...cur.messages, { id: nextId(), role: "quiz", quiz, at: now() }] }));
        break;
      }
      case "learn_suggestion":
        // A gentle "want me to teach this?" chip under the reply for this chat.
        patch(key, () => ({ suggestion: msg.topic }));
        break;
      case "learning_progress":
        // A module was completed: refresh dashboards AND drop a "continue" card
        // into the module's chat so the learner always has a concrete next step.
        setLearningSignal({ topic_id: msg.topic_id, at: Date.now() });
        if (msg.session_id && msg.module_title) {
          patch(msg.session_id, (cur) => ({
            messages: [...cur.messages, { id: nextId(), role: "module_done", info: msg, at: now() }],
          }));
        }
        break;
      case "learning_plan_updated":
      case "learning_insights":
        // Nudge any open Learning-Room dashboard to refresh from the server.
        setLearningSignal({ topic_id: msg.topic_id, at: Date.now() });
        break;
      case "stopped":
        if (key) patch(key, () => ({ status: "idle", streamId: null }));
        break;
      case "error":
        patch(key || currentRef.current, (cur) => ({
          messages: [...cur.messages, { id: nextId(), role: "error", content: msg.message }],
          streamId: null, status: "idle",
        }));
        playSound("error");
        notify("error", { title: "Turn failed", body: msg.message || "Something went wrong." });
        break;
      default:
        break;
    }
  }

  useEffect(() => {
    connect();
    refreshSessions();
    // Restore the last-viewed chat on a page *reload* (same server boot), but start
    // fresh after a server *restart*: a new server_id means relaunching the app, so
    // we drop the saved chat rather than reopening it.
    (async () => {
      const cfg = await fetchConfig();
      const boot = cfg?.server_id;
      const prevBoot = localStorage.getItem(SERVER_ID_KEY);
      if (boot && boot !== prevBoot) {
        localStorage.setItem(SERVER_ID_KEY, boot);
        localStorage.removeItem(LAST_SESSION_KEY);
        return; // fresh start
      }
      const saved = localStorage.getItem(LAST_SESSION_KEY);
      if (saved && !isProvisional(saved)) openSessionRef.current?.(saved);
    })();
    return () => wsRef.current && wsRef.current.close();
  }, [connect, refreshSessions]);

  // Persist the viewed chat so a page reload reopens it. (Clearing on "New chat"
  // is done in newChat() — not here — so it can't race the mount-time restore.)
  useEffect(() => {
    if (currentSid && !isProvisional(currentSid)) localStorage.setItem(LAST_SESSION_KEY, currentSid);
  }, [currentSid]);

  const send = useCallback((text, attachments = []) => {
    const clean = (text || "").trim();
    if ((!clean && attachments.length === 0) || !wsRef.current || wsRef.current.readyState !== 1) return;
    let payloadText = clean;
    if (attachments.length) {
      const list = attachments.map((a) => `- ${a.path}`).join("\n");
      payloadText = `${clean}\n\n[Attached document(s) — use read_document to read each]:\n${list}`.trim();
    }
    let key = currentRef.current;
    let clientRef = null;
    let sessionId = null;
    if (!key) { key = "ref" + nextId(); clientRef = key; setCurrentSid(key); }
    else if (isProvisional(key)) { clientRef = key; }
    else { sessionId = key; }
    // The chat's chosen brain: this chat's own pick, else the active model the user
    // last chose, else the first configured profile. Sticky: the server binds it on
    // the first turn and ignores it on later turns.
    const model = dataRef.current[key]?.model || activeModelRef.current
      || configuredModelsRef.current[0]?.id || null;
    const userMsg = { id: nextId(), role: "user", content: clean || "(sent attachment)", attachments, at: now() };
    patch(key, (cur) => ({ messages: [...cur.messages, userMsg], timeline: [], streamId: null, status: "thinking", suggestion: null }));
    playSound("sent");
    wsRef.current.send(JSON.stringify({
      type: "user_input", text: payloadText, session_id: sessionId, client_ref: clientRef, mode: modeRef.current, model,
    }));
  }, [patch]);

  // Run a turn in a specific session WITHOUT switching the viewed chat — used by
  // the Learning Room to build/modify a topic's path in its overview thread while
  // the learner stays on the dashboard. Events route back by session_id.
  const sendToSession = useCallback((sessionId, text, mode = "agent") => {
    if (!sessionId || !wsRef.current || wsRef.current.readyState !== 1) return false;
    patch(sessionId, () => ({ status: "thinking" }));
    wsRef.current.send(JSON.stringify({ type: "user_input", text, session_id: sessionId, mode }));
    return true;
  }, [patch]);

  const stop = useCallback(() => {
    const key = currentRef.current;
    const sid = key && !isProvisional(key) ? key : null;
    if (sid && wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify({ type: "stop", session_id: sid }));
    browserHush();
    if (key) patch(key, () => ({ status: "idle", streamId: null }));
  }, [patch]);

  // Answer an inline approval card. `scope` is "once" (allow this time) or "session"
  // (allow this tool for the rest of the chat — the server then stops prompting for
  // it). Sends the decision, then drops the card from whichever session's timeline
  // holds it (so it stops rendering).
  const respondApproval = useCallback((id, approved, scope = "once") => {
    if (id != null && wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ type: "approval_response", id, approved, scope }));
    }
    setData((all) => {
      let changed = false;
      const out = {};
      for (const [k, v] of Object.entries(all)) {
        const tl = (v.timeline || []).filter((it) => !(it.kind === "approval" && it.id === id));
        if (tl.length !== (v.timeline || []).length) { out[k] = { ...v, timeline: tl }; changed = true; }
        else out[k] = v;
      }
      if (changed) dataRef.current = out;
      return changed ? out : all;
    });
  }, []);

  // Send the sudo password straight over the socket (never kept in app state/history).
  const respondPassword = useCallback((password) => {
    if (passwordReq && wsRef.current) {
      wsRef.current.send(JSON.stringify({ type: "password_response", id: passwordReq.id, password: password || "" }));
    }
    setPasswordReq(null);
  }, [passwordReq]);

  const openSession = useCallback(async (id) => {
    setCurrentSid(id);
    // Don't clobber a chat that's mid-turn — keep its live streaming state.
    const existing = dataRef.current[id];
    if (existing && existing.status === "thinking") return;
    const r = await loadSession(id);
    if (!r) return;
    const messages = (r.turns || [])
      // "[quiz answer]" continuations and "[build path]" dashboard prompts are
      // plumbing for the model — the quiz card shows the pick, the dashboard
      // shows the path; neither needs a raw technical bubble in the history.
      .filter((t) => !(t.role === "user" &&
        (t.content?.startsWith("[quiz answer]") || t.content?.startsWith("[build path]"))))
      .map((t) => (t.role === "quiz"
        ? { id: nextId(), role: "quiz", quiz: t.quiz,
            at: t.created_at ? Date.parse(t.created_at) : undefined }
        : { id: nextId(), role: t.role === "user" ? "user" : "assistant", content: t.content,
            at: t.created_at ? Date.parse(t.created_at) : undefined,
            // Restore the assistant footer (tools used + stats) and the activity
            // timeline (thinking + tool steps, from turn meta) so both persist on reload.
            ...(t.role === "assistant"
              ? { tools: t.tools_used || [], meta: t.meta || null,
                  steps: (t.meta && t.meta.steps) || [] } : {}) }));
    // Re-derive the "module complete → continue" card from persisted state. The
    // live `learning_progress` event only appends it once and isn't saved with the
    // turns, so without this the button vanishes on reload (or never shows if the
    // event was missed). The server flags a finished module via topic.module_done.
    if (r.topic?.module_done) {
      messages.push({ id: nextId(), role: "module_done", info: r.topic.module_done, at: now() });
    }
    patch(id, () => ({
      messages,
      timeline: [], status: "idle", streamId: null, model: r.model || "",
      context: { project: r.project || null, topic: r.topic || null, title: r.title || "" },
    }));
  }, [patch]);
  const openSessionRef = useRef(openSession);
  openSessionRef.current = openSession;

  // New chat: detach the view (other chats keep running) and forget the persisted
  // session, so reloading an empty New chat stays a New chat.
  const newChat = useCallback(() => {
    localStorage.removeItem(LAST_SESSION_KEY);
    setCurrentSid(null);
  }, []);

  const removeSession = useCallback(async (id) => {
    await deleteSession(id);
    setData((all) => { const o = { ...all }; delete o[id]; dataRef.current = o; return o; });
    setCurrentSid((c) => (c === id ? null : c));
    if (localStorage.getItem(LAST_SESSION_KEY) === id) localStorage.removeItem(LAST_SESSION_KEY);
    refreshSessions();
  }, [refreshSessions]);

  // ── Model selection / switching ───────────────────────────────────────────
  const reloadConfiguredModels = useCallback(
    () => fetchConfiguredModels().then((r) => {
      const models = r?.models || [];
      setConfiguredModels(models);
      // Drop a stale active model that's no longer in the configured list.
      setActiveModel((am) => {
        if (am && !models.some((m) => m.id === am)) { localStorage.removeItem(ACTIVE_MODEL_KEY); return ""; }
        return am;
      });
      return models;
    }),
    []);
  useEffect(() => { reloadConfiguredModels(); }, [reloadConfiguredModels]);

  // Pick the brain for a chat that hasn't bound a model yet (empty / not-yet-sent).
  // No new session needed — the first turn binds it server-side.
  const selectModel = useCallback((modelId) => {
    let key = currentRef.current;
    if (!key) { key = "ref" + nextId(); setCurrentSid(key); }
    patch(key, () => ({ model: modelId }));
    setActive(modelId); // remember it as the default for future new chats
  }, [patch, setActive]);

  // Switch the brain MID-CHAT: starts a NEW session (fresh context) but keeps the
  // same on-screen thread — the prior messages stay visible above a divider, and
  // subsequent turns run on the new model in the new session. Caller confirms first.
  const switchModelNewSession = useCallback((modelId) => {
    const key = currentRef.current;
    const st = dataRef.current[key];
    if (!st) { selectModel(modelId); return; }
    const label = configuredModels.find((m) => m.id === modelId)?.label || modelId;
    const divider = { id: nextId(), role: "divider", content: `Switched to ${label} · new session`, at: now() };
    const newKey = "ref" + nextId();
    setData((all) => {
      const o = { ...all };
      o[newKey] = { ...EMPTY, messages: [...(st.messages || []), divider], model: modelId,
                    context: st.context || null };
      dataRef.current = o; return o;
    });
    setCurrentSid(newKey);
    setActive(modelId); // remember it as the default for future new chats
    localStorage.removeItem(LAST_SESSION_KEY); // the new session has no id until its first turn
  }, [configuredModels, selectModel, setActive, patch]);

  // Show a local (client-only) assistant message — used by /help and /clear.
  const showLocal = useCallback((content) => {
    let key = currentRef.current;
    if (!key) { key = "ref" + nextId(); setCurrentSid(key); }
    patch(key, (cur) => ({ messages: [...cur.messages, { id: nextId(), role: "assistant", content, at: now() }] }));
  }, [patch]);

  const cur = data[currentSid] || EMPTY;
  return {
    connected, messages: cur.messages, timeline: cur.timeline, status: cur.status,
    chatContext: cur.context || null, suggestion: cur.suggestion || null, learningSignal,
    passwordReq, mode, setMode, sessions, shuttingDown,
    voiceOn, setVoiceOn,
    configuredModels, currentModel: cur.model || activeModel || configuredModels[0]?.id || "",
    activeModel, setActiveModel: setActive, selectModel, switchModelNewSession, reloadConfiguredModels,
    chatHasTurns: (cur.messages || []).some((m) => m.role === "user"),
    send, sendToSession, stop, respondApproval, respondPassword, openSession, newChat, refreshSessions, removeSession, showLocal,
    currentSessionId: () => (currentRef.current && !isProvisional(currentRef.current) ? currentRef.current : null),
  };
}
