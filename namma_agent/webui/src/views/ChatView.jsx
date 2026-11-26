import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useOutletContext } from "react-router-dom";
import { clearMemory, downloadChat, learningModuleSession, listSkills, switchLearningModel, switchProjectModel } from "../api.js";
import Logo from "../components/Logo.jsx";
import ModelPicker from "../components/ui/ModelPicker.jsx";
import Message, { MessageActionsContext } from "../components/Message.jsx";
import Timeline from "../components/Timeline.jsx";
import Composer from "../components/Composer.jsx";
import TodoPanel from "../components/TodoPanel.jsx";
import RunsPanel from "../components/RunsPanel.jsx";
import { RenderSessionContext } from "../components/Visuals.jsx";
import { UiActionContext } from "../components/A2uiBlock.jsx";
import { ChatSendContext } from "../chatContexts.js";
import { IconArrowRight, IconChevronLeft, IconCircleCheck, IconDownload, IconSchool } from "@tabler/icons-react";

// Quiz cards appear only in Learning Room lessons — loaded on demand (Phase 6).
const QuizCard = lazy(() => import("../components/QuizCard.jsx"));

const HELP_TEXT = `Commands you can type:
- **/new** — start a new chat
- **/clear** — wipe my memory
- **/agent** — switch to agent mode (tools + skills)
- **/chat** — switch to chat mode (talk only)
- **/setup** — setup mode: I help you configure models, MCP servers, Google (Gmail/Calendar), email and messaging
- **!\`<command>\`** — run a shell command, e.g. \`!df -h\`
- **/help** — show this list`;

// The main conversation surface. State (messages, WS turn channel, mode, …)
// comes from the shared app context via the router Outlet.
export default function ChatView() {
  const {
    connected, messages, timeline, status, todos, runs, mode, setMode, config, assistantName,
    handsfree, setHandsfree, handsfreeStatus,
    send, stop, newChat, refreshSessions, showLocal,
    chatContext, suggestion, sendToSession, openChat,
    configuredModels, currentModel, selectModel, chatHasTurns, confirmAction,
    currentSessionId, setActiveModel, respondApproval,
    regenerate, editResend, branch, removeMessage, showDivider, sessions, openSettings, rightPane, titleSlot,
  } = useOutletContext();
  const navigate = useNavigate();
  // Enabled skills for the composer's "/" menu.
  const [skills, setSkills] = useState([]);
  useEffect(() => {
    listSkills().then((r) => setSkills((r?.skills || []).filter((s) => s.enabled !== false && !s.draft)
      .map((s) => ({ name: s.name, description: (s.description || "").slice(0, 90) }))));
  }, []);

  // Change the chat's brain. Before the first message it's a silent re-pick; once
  // the chat is underway, the new model simply continues THIS conversation
  // (Phase 4: no new session — it sees the earlier messages); a divider marks
  // where the switch happened.
  async function onPickModel(modelId) {
    if (modelId === currentModel) return;
    const label = configuredModels.find((m) => m.id === modelId)?.label || modelId || "the default model";
    selectModel(modelId);
    if (chatHasTurns) showDivider(`Switched to ${label} · continues this chat`);
  }

  // Switching the model inside a Learning-Room thread does NOT cold-start: the
  // server recaps the current session and seeds the recap into a fresh session on
  // the new model, so the lesson continues. We confirm first, then open it.
  async function onPickModelLearning(modelId) {
    if (modelId === currentModel) return;
    const label = configuredModels.find((m) => m.id === modelId)?.label || modelId || "the default model";
    const sid = currentSessionId?.();
    if (!sid) { selectModel(modelId); return; }  // thread not started yet — just re-pick
    const ok = await confirmAction(
      `Switch this lesson to ${label}? I'll summarize what we've covered so far and continue from there — you won't lose your progress.`,
      "Switch model");
    if (!ok) return;
    const r = await switchLearningModel(sid, modelId);
    if (r?.session_id) { setActiveModel?.(modelId); openChat(r.session_id); }
  }

  // Switching the model inside a project chat works exactly like the Learning-Room
  // switch: the server summarizes the current session and seeds the recap into a
  // fresh session (kept in the same project) on the new model, so the conversation
  // continues instead of cold-starting. We confirm first, then open it.
  async function onPickModelProject(modelId) {
    if (modelId === currentModel) return;
    const label = configuredModels.find((m) => m.id === modelId)?.label || modelId || "the default model";
    const sid = currentSessionId?.();
    if (!sid) { selectModel(modelId); return; }  // chat not started yet — just re-pick
    const ok = await confirmAction(
      `Switch this chat to ${label}? I'll summarize what we've covered so far and continue from there — you won't lose the thread.`,
      "Switch model");
    if (!ok) return;
    const r = await switchProjectModel(sid, modelId);
    if (r?.session_id) { setActiveModel?.(modelId); openChat(r.session_id); }
  }

  // Phase 9: one model picker overlay for every chat kind (plain, project,
  // learning) — opened from the composer chip or the command palette.
  const pickModel = chatContext?.project ? onPickModelProject
    : chatContext?.topic ? onPickModelLearning : onPickModel;
  const [pickerOpen, setPickerOpen] = useState(false);
  useEffect(() => {
    const open = () => setPickerOpen(true);
    window.addEventListener("namma-open-model-picker", open);
    return () => window.removeEventListener("namma-open-model-picker", open);
  }, []);
  const modelLabel = configuredModels.find((m) => m.id === currentModel)?.label || config?.model || "";
  const sid = currentSessionId?.();
  const currentTitle = (sessions || []).find((x) => x.id === sid)?.title || "";

  const scrollRef = useRef(null);
  const stickRef = useRef(true); // only auto-scroll when the user is at the bottom

  useEffect(() => {
    if (stickRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, timeline]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  // Intercept slash/bang commands client-side; otherwise send as a normal turn.
  function handleSend(text, attachments = []) {
    const t = (text || "").trim();
    const low = t.toLowerCase();
    if (low === "/new") return newChat();
    if (low === "/help") return showLocal(HELP_TEXT);
    if (low === "/agent") { setMode("agent"); return showLocal("Switched to **agent** mode."); }
    if (low === "/chat") { setMode("chat"); return showLocal("Switched to **chat** mode."); }
    if (low === "/setup") {
      setMode("setup");
      return showLocal("Switched to **setup** mode. Tell me what to configure — a model provider, MCP servers, Google (Gmail / Calendar / Drive), another email account, or messaging. Keys go into a secure field, never the chat.");
    }
    if (low.startsWith("/mode ")) {
      const m = low.slice(6).trim();
      if (m === "agent" || m === "chat" || m === "setup") { setMode(m); return showLocal(`Switched to **${m}** mode.`); }
    }
    if (low === "/clear") {
      clearMemory("all").then(() => { refreshSessions(); newChat(); showLocal("Memory cleared."); });
      return;
    }
    if (t.startsWith("!")) {
      const cmd = t.slice(1).trim();
      if (cmd) return send(`Run this shell command with run_shell and show me the output:\n${cmd}`, attachments);
      return;
    }
    send(text, attachments);
  }

  const empty = messages.length === 0;
  const lastAssistantId = [...messages].reverse().find((m) => m.role === "assistant")?.id;
  const busy = status === "thinking" || status === "queued";
  // Phase 6: STABLE context values. An inline object/function here would hand
  // every memoised <Message> a new context on each streamed token, re-rendering
  // (and re-parsing the markdown of) the whole transcript.
  const messageActions = useMemo(() => ({ regenerate, editResend, branch, remove: removeMessage, busy }),
    [regenerate, editResend, branch, removeMessage, busy]);
  const onUiAction = useCallback((action) => send(
    "[ui action] " + action.name + " " + JSON.stringify(action.context || {})), [send]);
  // Show the "thinking…" dots while a turn is in flight but nothing is on screen yet:
  // no tool steps in the timeline and no assistant text streaming. Covers the compose
  // gap before the first token — long for deferred teaching turns that render first.
  const last = messages[messages.length - 1];
  const awaitingOutput = busy && timeline.length === 0
    && (!last || last.role !== "assistant" || !last.content);

  return (
    <>
      {/* This chat's header lives in the window's titlebar band (Hermes
          layout): title or breadcrumbs, plus Download. No voice toggle. */}
      {titleSlot && createPortal(
        <>
          <div className="flex items-center gap-2 text-sm text-fg-muted min-w-0 flex-1">
          {chatContext?.project ? (
            <>
              <Breadcrumb navigate={navigate} crumbs={[
                { label: "Projects", to: "/projects" },
                { label: chatContext.project.name, to: `/projects/${chatContext.project.id}` },
                { label: chatContext.title || "New Chat" },   // active leaf, not clickable
              ]} />
            </>
          ) : chatContext?.topic ? (
            <>
              <Breadcrumb navigate={navigate} crumbs={[
                { label: "Learning Room", to: "/learning" },
                { label: chatContext.topic.title, to: `/learning/${chatContext.topic.id}` },
                // Leaf: the module thread, or "Path chat" for the overview thread —
                // either way the back arrow lands on the topic dashboard.
                { label: chatContext.topic.module || "Path chat" },
              ]} />
            </>
          ) : (
            <span className="truncate text-fg">{currentTitle || "New chat"}</span>
          )}
        </div>
          {chatHasTurns && currentSessionId?.() && (
            <button type="button" onClick={() => downloadChat(currentSessionId())}
                    aria-label="Download chat" title="Download chat — a zip with the transcript (chat.md) and this chat's media"
                    className="grid place-items-center h-6 w-6 rounded-sm text-fg-muted hover:text-fg hover:bg-surface-sunken">
              <DownloadIcon />
            </button>
          )}
        </>, titleSlot)}

      <div className="relative flex-1 flex flex-col min-h-0">
        {empty ? (
          <div className="relative flex-1 grid place-items-center px-4">
            <div className="w-full max-w-2xl -mt-10">
              <div className="chat-legible text-center mb-7">
                {/* The highlighted mark: a solid coin (opaque face, bold engraving)
                    so it reads cleanly over the painted background in every theme. */}
                <div className="relative mx-auto mb-5 h-[88px] w-[88px]">
                  <span aria-hidden="true" className="hero-halo absolute inset-[-28px] rounded-full" />
                  <Logo size={88} variant="medallion" solid className="relative" />
                </div>
                <h1 className="font-serif text-xl font-semibold tracking-tight text-fg">Hey, I'm {assistantName}.</h1>
                <p className="mt-1.5 text-base text-fg-muted">
                  {mode === "chat" ? "Let's talk." : "Ask me to do something — I'll show my work."}
                </p>
              </div>
              <Composer skills={skills} onSend={handleSend} onStop={stop} busy={busy} mode={mode} setMode={setMode} autoFocus name={assistantName}
                        handsfree={handsfree} setHandsfree={setHandsfree} handsfreeStatus={handsfreeStatus}
                        modelLabel={modelLabel} onOpenModelPicker={() => setPickerOpen(true)} />
            </div>
          </div>
        ) : (
          <>
            <main ref={scrollRef} onScroll={onScroll} className="chat-legible relative flex-1 overflow-y-auto px-4 md:px-6">
              <RenderSessionContext.Provider value={currentSessionId?.() || null}>
              <UiActionContext.Provider value={onUiAction}>
              <MessageActionsContext.Provider value={messageActions}>
              <ChatSendContext.Provider value={send}>
              <div className="max-w-3xl mx-auto py-6 space-y-5">
                {messages.map((m) => {
                  if (m.role === "quiz") {
                    return <Suspense key={m.id} fallback={null}><QuizCard quiz={m.quiz} onAnswered={(quiz, r) => {
                      // Hand the result back to the teacher in the quiz's own session
                      // so the lesson always moves to the next step (never a dead end).
                      if (quiz?.session_id) {
                        sendToSession(quiz.session_id,
                          `[quiz answer] I chose “${r.picked}” for “${quiz.question}” — that was ` +
                          `${r.correct ? "correct" : "incorrect"}. Continue the lesson from here.`);
                      }
                    }} /></Suspense>;
                  }
                  if (m.role === "module_done") {
                    return <ModuleDoneCard key={m.id} info={m.info} navigate={navigate}
                                           openChat={openChat} />;
                  }
                  if (m.role === "divider") {
                    return (
                      <div key={m.id} className="flex items-center gap-3 py-1 text-xs text-fg-subtle">
                        <span className="flex-1 h-px bg-border" />
                        <span className="shrink-0">↻ {m.content}</span>
                        <span className="flex-1 h-px bg-border" />
                      </div>
                    );
                  }
                  return <Message key={m.id} {...m} isLastAssistant={m.id === lastAssistantId} />;
                })}
                {awaitingOutput && <ThinkingRow name={assistantName} />}
                {busy && timeline.length > 0 && <Timeline items={timeline} onApprove={respondApproval} />}
                {/* Gentle "want to go deeper?" nudge, centered below the reply — solo
                    chats only (never inside a project workspace or the Learning Room). */}
                {suggestion && !busy && !chatContext?.project && !chatContext?.topic && (
                  <div className="flex justify-center pt-1">
                    <button onClick={() => navigate(`/learning?suggest=${encodeURIComponent(suggestion)}`)}
                            className="flex items-center gap-2 text-base rounded-full border border-brand-soft/60 bg-accent-wash text-brand-deep px-3.5 py-2 hover:shadow-soft transition">
                      <IconSchool size={16} stroke={1.7} aria-hidden="true" />
                      Want to go deeper? Learn “{suggestion}” in the Learning Room →
                    </button>
                  </div>
                )}
              </div>
              </ChatSendContext.Provider>
              </MessageActionsContext.Provider>
              </UiActionContext.Provider>
              </RenderSessionContext.Provider>
            </main>
            <footer className="relative px-4 md:px-6 pb-4">
              <div className="max-w-3xl mx-auto">
                {(status === "stopping" || status === "queued") && (
                  <div role="status" aria-live="polite"
                       className="mb-2 text-sm text-fg-muted flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" aria-hidden="true" />
                    {status === "stopping"
                      ? "Stopping — the current step is winding down."
                      : "Queued — your message runs as soon as the previous turn ends."}
                  </div>
                )}
                {!rightPane && <RunsPanel runs={runs} />}
                {!rightPane && <TodoPanel todos={todos} />}
                <Composer skills={skills} onSend={handleSend} onStop={stop} busy={busy} mode={mode} setMode={setMode} name={assistantName}
                          handsfree={handsfree} setHandsfree={setHandsfree} handsfreeStatus={handsfreeStatus}
                        modelLabel={modelLabel} onOpenModelPicker={() => setPickerOpen(true)} />
                <div className="text-center text-2xs text-fg-subtle mt-1.5">
                  {assistantName} can make mistakes. Verify important actions.
                </div>
              </div>
            </footer>
          </>
        )}
      </div>
      {pickerOpen && (
        <ModelPicker models={configuredModels} current={currentModel} onPick={pickModel}
                     onClose={() => setPickerOpen(false)} onManage={() => openSettings?.("Model")} />
      )}
    </>
  );
}

// "{name} is thinking …" with three gently bobbing dots — shown during the compose
// gap before the first token streams (and while a deferred teaching turn renders its
// visual). Mirrors the assistant message layout (avatar + left-aligned body).
function ThinkingRow({ name }) {
  return (
    <div className="flex gap-3 animate-rise" aria-live="polite">
      <div className="mt-0.5 h-7 w-7 shrink-0 grid place-items-center"><Logo size={26} /></div>
      <div className="flex-1 min-w-0 flex items-center gap-2 text-base text-fg-subtle">
        <span>{name} is thinking</span>
        <span className="inline-flex items-center gap-1 text-fg-soft">
          <span className="thinking-dot" style={{ animationDelay: "0ms" }} />
          <span className="thinking-dot" style={{ animationDelay: "160ms" }} />
          <span className="thinking-dot" style={{ animationDelay: "320ms" }} />
        </span>
      </div>
    </div>
  );
}

// Inline celebration when the teacher marks a module complete: shows progress
// and a one-click way into the NEXT module's own chat (or back to the path when
// the whole topic is finished) — the learner always has a concrete next step.
function ModuleDoneCard({ info, navigate, openChat }) {
  const { module_title, done, total, next, topic_id } = info || {};
  async function continueNext() {
    const r = await learningModuleSession(topic_id, next.id);
    if (r?.session_id) openChat(r.session_id);
  }
  return (
    <div className="flex gap-3 animate-rise">
      <div className="mt-0.5 h-7 w-7 shrink-0 grid place-items-center text-emerald-600">
        <IconCircleCheck size={22} stroke={1.8} aria-hidden="true" />
      </div>
      <div className="flex-1 min-w-0 rounded-2xl border border-emerald-300/60 dark:border-emerald-500/30 bg-emerald-50/70 dark:bg-emerald-500/10 p-4">
        <div className="text-2xs uppercase tracking-wider text-emerald-700 dark:text-emerald-300 mb-1">Module complete</div>
        <div className="font-medium text-prose mb-1">🎉 “{module_title}” is done — {done}/{total} modules complete.</div>
        {next ? (
          <button onClick={continueNext}
                  className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-brand text-white hover:bg-brand-deep text-base font-medium">
            Continue to “{next.title}”
            <IconArrowRight size={14} stroke={2} aria-hidden="true" />
          </button>
        ) : (
          <button onClick={() => navigate(`/learning/${topic_id}`)}
                  className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-emerald-600 text-white hover:bg-emerald-700 text-base font-medium">
            🎓 Whole path complete — back to the dashboard
          </button>
        )}
      </div>
    </div>
  );
}


// Breadcrumb from a list of crumbs. The LAST crumb is the active page (rendered
// plain, not clickable); any crumb with a `to` is a link. The back arrow goes to
// the parent (the crumb just before the active one) — e.g. the project/topic
// dashboard.
function Breadcrumb({ crumbs = [], navigate }) {
  const parent = crumbs.length >= 2 ? crumbs[crumbs.length - 2] : null;
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      {parent?.to && (
        <button onClick={() => navigate(parent.to)} title={`Back to ${parent.label}`}
                className="grid place-items-center h-6 w-6 rounded-full hover:bg-paper-sink dark:hover:bg-night-panel text-fg-soft shrink-0">
          <IconChevronLeft size={16} stroke={1.8} aria-hidden="true" />
        </button>
      )}
      {crumbs.map((c, i) => {
        const active = i === crumbs.length - 1;
        return (
          <span key={i} className="flex items-center gap-1.5 min-w-0">
            {i > 0 && <span className="shrink-0">/</span>}
            {active || !c.to ? (
              <span className={`truncate ${active ? "text-fg font-medium" : ""}`}>{c.label}</span>
            ) : (
              <button onClick={() => navigate(c.to)} className="hover:text-fg hover:underline truncate shrink-0">{c.label}</button>
            )}
          </span>
        );
      })}
    </div>
  );
}

const DownloadIcon = () => (<IconDownload size={16} stroke={1.7} aria-hidden="true" />);
