import { useEffect, useRef } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { clearMemory, learningModuleSession, switchLearningModel, switchProjectModel } from "../api.js";
import Logo from "../components/Logo.jsx";
import Message from "../components/Message.jsx";
import QuizCard from "../components/QuizCard.jsx";
import Timeline from "../components/Timeline.jsx";
import Composer from "../components/Composer.jsx";

const HELP_TEXT = `Commands you can type:
- **/new** — start a new chat
- **/clear** — wipe my memory
- **/agent** — switch to agent mode (tools + skills)
- **/chat** — switch to chat mode (talk only)
- **!\`<command>\`** — run a shell command, e.g. \`!df -h\`
- **/help** — show this list`;

// The main conversation surface. State (messages, WS turn channel, mode, …)
// comes from the shared app context via the router Outlet.
export default function ChatView() {
  const {
    connected, messages, timeline, status, mode, setMode, config, assistantName,
    voiceOn, setVoiceOn, send, stop, newChat, refreshSessions, showLocal,
    chatContext, suggestion, sendToSession, openChat,
    configuredModels, currentModel, selectModel, switchModelNewSession, chatHasTurns, confirmAction,
    currentSessionId, setActiveModel,
  } = useOutletContext();
  const navigate = useNavigate();

  // Change the chat's brain. Before the first message it's a silent re-pick; once
  // the chat is underway, switching starts a NEW session (the new model can't see
  // the old context) — we confirm first, in the same chat thread.
  async function onPickModel(modelId) {
    if (modelId === currentModel) return;
    const label = configuredModels.find((m) => m.id === modelId)?.label || modelId || "the default model";
    if (chatHasTurns) {
      const ok = await confirmAction(
        `Switch to ${label}? This starts a new session in this chat — the new model won't see the earlier messages.`,
        "Switch model");
      if (!ok) return;
      switchModelNewSession(modelId);
    } else {
      selectModel(modelId);
    }
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
    if (low.startsWith("/mode ")) {
      const m = low.slice(6).trim();
      if (m === "agent" || m === "chat") { setMode(m); return showLocal(`Switched to **${m}** mode.`); }
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
  const busy = status === "thinking";
  // Show the "thinking…" dots while a turn is in flight but nothing is on screen yet:
  // no tool steps in the timeline and no assistant text streaming. Covers the compose
  // gap before the first token — long for deferred teaching turns that render first.
  const last = messages[messages.length - 1];
  const awaitingOutput = busy && timeline.length === 0
    && (!last || last.role !== "assistant" || !last.content);

  return (
    <>
      <header className="flex items-center justify-between px-5 h-12 border-b border-line dark:border-night-line">
        <div className="flex items-center gap-2 text-[13px] text-ink-faint dark:text-night-faint min-w-0">
          {chatContext?.project ? (
            <>
              <Breadcrumb navigate={navigate} crumbs={[
                { label: "Projects", to: "/projects" },
                { label: chatContext.project.name, to: `/projects/${chatContext.project.id}` },
                { label: chatContext.title || "New Chat" },   // active leaf, not clickable
              ]} />
              {configuredModels.length > 0 && (
                <>
                  <span className="mx-1 shrink-0">·</span>
                  <ModelSwitcher models={configuredModels} current={currentModel}
                                 defaultModel={config?.model || "default"} onPick={onPickModelProject} />
                </>
              )}
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
              {configuredModels.length > 0 && (
                <>
                  <span className="mx-1 shrink-0">·</span>
                  <ModelSwitcher models={configuredModels} current={currentModel}
                                 defaultModel={config?.model || "default"} onPick={onPickModelLearning} />
                </>
              )}
            </>
          ) : (
            <>
              <ModelSwitcher models={configuredModels} current={currentModel}
                             defaultModel={config?.model || "cloud agent"} onPick={onPickModel} />
              <span className="mx-1">·</span>
              <span className="capitalize">{mode} mode</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setVoiceOn((v) => !v)}
            title={voiceOn ? "Voice on — reads replies aloud (browser TTS). Click to mute." : "Voice off. Click to read replies aloud (browser TTS)."}
            className={`grid place-items-center h-7 w-7 rounded-lg transition ${voiceOn ? "text-brand-deep" : "text-ink-faint dark:text-night-faint hover:text-ink dark:hover:text-night-ink"}`}>
            {voiceOn ? <SpeakerOnIcon /> : <SpeakerOffIcon />}
          </button>
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-400"}`} title={connected ? "connected" : "reconnecting…"} />
        </div>
      </header>

      {empty ? (
        <div className="flex-1 grid place-items-center px-4">
          <div className="w-full max-w-2xl -mt-10">
            <div className="text-center mb-6">
              <Logo size={52} className="mx-auto mb-4" />
              <h1 className="font-serif text-3xl text-ink dark:text-night-ink">Hey, I'm {assistantName}.</h1>
              <p className="mt-2 text-ink-soft dark:text-night-faint">
                {mode === "chat" ? "Let's talk." : "Ask me to do something — I'll show my work."}
              </p>
            </div>
            <Composer onSend={handleSend} onStop={stop} busy={busy} mode={mode} setMode={setMode} autoFocus name={assistantName} />
          </div>
        </div>
      ) : (
        <>
          <main ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 md:px-6">
            <div className="max-w-3xl mx-auto py-6 space-y-5">
              {messages.map((m) => {
                if (m.role === "quiz") {
                  return <QuizCard key={m.id} quiz={m.quiz} onAnswered={(quiz, r) => {
                    // Hand the result back to the teacher in the quiz's own session
                    // so the lesson always moves to the next step (never a dead end).
                    if (quiz?.session_id) {
                      sendToSession(quiz.session_id,
                        `[quiz answer] I chose “${r.picked}” for “${quiz.question}” — that was ` +
                        `${r.correct ? "correct" : "incorrect"}. Continue the lesson from here.`);
                    }
                  }} />;
                }
                if (m.role === "module_done") {
                  return <ModuleDoneCard key={m.id} info={m.info} navigate={navigate}
                                         openChat={openChat} />;
                }
                if (m.role === "divider") {
                  return (
                    <div key={m.id} className="flex items-center gap-3 py-1 text-[11.5px] text-ink-faint dark:text-night-faint">
                      <span className="flex-1 h-px bg-line dark:bg-night-line" />
                      <span className="shrink-0">↻ {m.content}</span>
                      <span className="flex-1 h-px bg-line dark:bg-night-line" />
                    </div>
                  );
                }
                return <Message key={m.id} {...m} />;
              })}
              {awaitingOutput && <ThinkingRow name={assistantName} />}
              {busy && timeline.length > 0 && <Timeline items={timeline} />}
              {/* Gentle "want to go deeper?" nudge, centered below the reply — solo
                  chats only (never inside a project workspace or the Learning Room). */}
              {suggestion && !busy && !chatContext?.project && !chatContext?.topic && (
                <div className="flex justify-center pt-1">
                  <button onClick={() => navigate(`/learning?suggest=${encodeURIComponent(suggestion)}`)}
                          className="flex items-center gap-2 text-[13.5px] rounded-full border border-brand-soft/60 bg-brand-wash dark:bg-night-soft text-brand-deep px-3.5 py-2 hover:shadow-soft transition">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M2 9 12 4l10 5-10 5L2 9Z" /><path d="M6 11v5c0 1 2.7 2.5 6 2.5s6-1.5 6-2.5v-5" /></svg>
                    Want to go deeper? Learn “{suggestion}” in the Learning Room →
                  </button>
                </div>
              )}
            </div>
          </main>
          <footer className="px-4 md:px-6 pb-4">
            <div className="max-w-3xl mx-auto">
              <Composer onSend={handleSend} onStop={stop} busy={busy} mode={mode} setMode={setMode} name={assistantName} />
              <div className="text-center text-[11px] text-ink-faint dark:text-night-faint mt-1.5">
                {assistantName} can make mistakes. Verify important actions.
              </div>
            </div>
          </footer>
        </>
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
      <div className="flex-1 min-w-0 flex items-center gap-2 text-[13.5px] text-ink-faint dark:text-night-faint">
        <span>{name} is thinking</span>
        <span className="inline-flex items-center gap-1 text-ink-soft dark:text-night-ink">
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
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="m8.5 12.5 2.5 2.5 5-5.5" /></svg>
      </div>
      <div className="flex-1 min-w-0 rounded-2xl border border-emerald-300/60 dark:border-emerald-500/30 bg-emerald-50/70 dark:bg-emerald-500/10 p-4">
        <div className="text-[11px] uppercase tracking-wider text-emerald-700 dark:text-emerald-300 mb-1">Module complete</div>
        <div className="font-medium text-[15px] mb-1">🎉 “{module_title}” is done — {done}/{total} modules complete.</div>
        {next ? (
          <button onClick={continueNext}
                  className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-brand text-white hover:bg-brand-deep text-[13.5px] font-medium">
            Continue to “{next.title}”
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </button>
        ) : (
          <button onClick={() => navigate(`/learning/${topic_id}`)}
                  className="mt-2 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-emerald-600 text-white hover:bg-emerald-700 text-[13.5px] font-medium">
            🎓 Whole path complete — back to the dashboard
          </button>
        )}
      </div>
    </div>
  );
}

// The in-chat brain picker. Lists the configured model profiles (Settings →
// Models) plus a "Default" entry (the provider in config). Picking a different
// model mid-chat starts a new session — handled by the caller (onPick). When no
// models are configured it links to where you add them.
function ModelSwitcher({ models = [], current = "", defaultModel, onPick }) {
  if (!models.length) {
    return <span title="Add models in Settings → Models">{defaultModel} · <span className="opacity-70">add models in Settings</span></span>;
  }
  return (
    <select value={current} onChange={(e) => onPick(e.target.value)} title="Switch the model for this chat"
            className="rounded-md px-1.5 py-0.5 outline-none cursor-pointer max-w-[220px] truncate
                       bg-paper-soft dark:bg-night-soft text-ink dark:text-night-ink
                       border border-line dark:border-night-line hover:border-brand focus:border-brand
                       [&>option]:bg-paper [&>option]:dark:bg-night-panel [&>option]:text-ink [&>option]:dark:text-night-ink">
      {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
    </select>
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
                className="grid place-items-center h-6 w-6 rounded-full hover:bg-paper-sink dark:hover:bg-night-panel text-ink-soft dark:text-night-ink shrink-0">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
        </button>
      )}
      {crumbs.map((c, i) => {
        const active = i === crumbs.length - 1;
        return (
          <span key={i} className="flex items-center gap-1.5 min-w-0">
            {i > 0 && <span className="shrink-0">/</span>}
            {active || !c.to ? (
              <span className={`truncate ${active ? "text-ink dark:text-night-ink font-medium" : ""}`}>{c.label}</span>
            ) : (
              <button onClick={() => navigate(c.to)} className="hover:text-ink dark:hover:text-night-ink hover:underline truncate shrink-0">{c.label}</button>
            )}
          </span>
        );
      })}
    </div>
  );
}

const SpeakerOnIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5Z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14" /></svg>);
const SpeakerOffIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5Z" /><line x1="22" y1="9" x2="16" y2="15" /><line x1="16" y1="9" x2="22" y2="15" /></svg>);
