import { useEffect, useRef, useState } from "react";
import { fetchConfig, useFriday } from "./api.js";
import Message from "./components/Message.jsx";
import Timeline from "./components/Timeline.jsx";
import Composer from "./components/Composer.jsx";
import Settings from "./components/Settings.jsx";

export default function App() {
  const { connected, messages, timeline, status, approval, send, respondApproval } = useFriday();
  const [config, setConfig] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    fetchConfig().then(setConfig);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, timeline]);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="relative h-9 w-9 grid place-items-center">
            <span className="absolute inset-0 rounded-full bg-glow/30 blur-md" />
            <span className="relative h-9 w-9 rounded-full bg-gradient-to-br from-glow to-accent grid place-items-center font-bold text-ink-900">F</span>
          </div>
          <div>
            <div className="font-semibold tracking-tight">FRIDAY</div>
            <div className="text-[11px] text-ink-50/40">
              {config?.model || "cloud agent"} · {status === "thinking" ? "thinking…" : "ready"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`} title={connected ? "connected" : "disconnected"} />
          <button onClick={() => setShowSettings(true)} className="text-ink-50/50 hover:text-ink-50 text-sm">⚙ Settings</button>
        </div>
      </header>

      {/* Conversation */}
      <main ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-8">
        <div className="max-w-3xl mx-auto py-4 space-y-3">
          {messages.length === 0 && (
            <div className="text-center text-ink-50/40 mt-24">
              <div className="text-2xl font-semibold text-ink-50/70">Hey, I'm FRIDAY.</div>
              <p className="mt-2">Ask me to do something — I'll narrate as I work.</p>
            </div>
          )}
          {messages.map((m) => (
            <Message key={m.id} {...m} />
          ))}
          {(timeline.length > 0 && status === "thinking") && <Timeline items={timeline} />}
        </div>
      </main>

      {/* Composer */}
      <footer className="px-4 md:px-8 pb-5">
        <div className="max-w-3xl mx-auto">
          <Composer onSend={send} busy={status === "thinking"} />
        </div>
      </footer>

      {approval && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/60">
          <div className="glass rounded-2xl p-6 w-[420px] max-w-[90vw] animate-rise">
            <h3 className="text-lg font-semibold mb-1">Approve action?</h3>
            <p className="text-ink-50/60 text-sm mb-1">FRIDAY wants to run a sensitive tool:</p>
            <div className="font-mono text-accent text-sm mb-2">{approval.tool}</div>
            <pre className="text-[12px] bg-ink-900/60 rounded-lg p-3 overflow-auto max-h-40 text-ink-50/70">{JSON.stringify(approval.args, null, 2)}</pre>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => respondApproval(false)} className="px-4 py-2 rounded-xl bg-ink-700 hover:bg-ink-600">Deny</button>
              <button onClick={() => respondApproval(true)} className="px-4 py-2 rounded-xl bg-glow text-white shadow-glow">Approve</button>
            </div>
          </div>
        </div>
      )}

      {showSettings && <Settings config={config} onClose={() => setShowSettings(false)} />}
    </div>
  );
}
