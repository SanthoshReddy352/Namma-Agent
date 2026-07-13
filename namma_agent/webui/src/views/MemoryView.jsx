import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { memoryStatus, memoryRecall, memoryRemember, memoryConsolidate, memoryForget, memoryGraph } from "../api.js";
import MemoryGraph from "../components/MemoryGraph.jsx";

// The "Memory" tab — a premium window into Cognee's semantic + knowledge-graph
// memory, alongside Projects and the Learning Room. The knowledge graph (an
// Obsidian-style force layout) is the hero; below it sit all FOUR Cognee
// memory-lifecycle ops — recall, remember, improve (consolidate → cognify) and
// forget. Everything proxies the connected cognee MCP server via /api/memory/*,
// so it degrades gracefully when Cognee is off.
export default function MemoryView() {
  const { confirmAction, dark } = useOutletContext();
  const [status, setStatus] = useState(null);
  const [graph, setGraph] = useState({ nodes: [], edges: [], note: null, cloudLimited: false });
  const [loadingGraph, setLoadingGraph] = useState(false);

  const connected = status?.connected;

  const reloadGraph = useCallback(async () => {
    setLoadingGraph(true);
    const g = await memoryGraph();
    if (g?.ok) setGraph({ nodes: g.nodes || [], edges: g.edges || [], note: g.note || null, cloudLimited: !!g.cloud_limited });
    setLoadingGraph(false);
  }, []);

  const refreshStatus = useCallback(() => memoryStatus().then(setStatus), []);

  useEffect(() => {
    memoryStatus().then((s) => { setStatus(s); if (s?.connected) reloadGraph(); });
  }, [reloadGraph]);

  const pending = status?.pending_consolidation || 0;

  return (
    <>
      <header className="flex items-center gap-3 px-6 h-12 border-b border-line dark:border-night-line">
        <h1 className="font-serif text-lg">Memory</h1>
        {status && (
          <span className={`text-[11px] px-2 py-0.5 rounded-full ${connected
            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400"
            : "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400"}`}>
            {connected ? "Cognee connected" : "Cognee offline"}
          </span>
        )}
        {connected && (
          <span className="text-[12px] text-ink-faint dark:text-night-faint">
            {graph.nodes.length} entities · {graph.edges.length} links
          </span>
        )}
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto space-y-6">
          <p className="text-ink-soft dark:text-night-faint text-[14px]">
            Your knowledge as a living <b>semantic + knowledge graph</b>, powered by
            {" "}<a href="https://www.cognee.ai" target="_blank" rel="noreferrer" className="text-brand-deep underline">Cognee</a>.
            Three views — <b>Graph</b> (organic force layout), <b>Schema</b> (entity types
            + how they relate) and <b>Ranked</b> (columns by type). Drag nodes, scroll to
            zoom, hover to trace, click a node to inspect its relations.
          </p>

          {status && !connected && (
            <div className="rounded-2xl border border-amber-300/60 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-4 text-[13.5px] text-amber-800 dark:text-amber-300">
              {status.hint || "Cognee memory isn't connected."} Open
              {" "}<b>Settings → MCP → Servers</b> and turn on the <b>cognee</b> server.
            </div>
          )}

          {/* HERO — the knowledge graph */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <div className="text-[15px] font-medium">Knowledge graph</div>
              <button onClick={reloadGraph} disabled={!connected || loadingGraph}
                      className="text-[12.5px] px-2.5 py-1 rounded-lg border border-line dark:border-night-line text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft disabled:opacity-50">
                {loadingGraph ? "Loading…" : "↻ Refresh"}
              </button>
            </div>
            {/* Canvas adapts to the app theme (light/dark). */}
            <div className="relative rounded-2xl shadow-pop"
                 style={{ background: "linear-gradient(135deg, rgba(47,107,255,0.10), rgba(124,58,237,0.10))", padding: 1 }}>
              <MemoryGraph nodes={graph.nodes} edges={graph.edges} dark={dark} height={560} />
              {connected && graph.cloudLimited && graph.nodes.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center p-6 pointer-events-none">
                  <div className="max-w-md text-center rounded-2xl bg-paper-panel/90 dark:bg-night-panel/90 border border-line dark:border-night-line p-5 shadow-pop pointer-events-auto">
                    <div className="text-[14px] font-medium mb-1">Graph view is self-hosted-only</div>
                    <div className="text-[12.5px] text-ink-soft dark:text-night-faint">{graph.note}</div>
                  </div>
                </div>
              )}
            </div>
          </section>

          <AskPanel disabled={!connected} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <RememberPanel disabled={!connected} onChanged={reloadGraph} onSession={refreshStatus} />
            <ConsolidatePanel disabled={!connected} pending={pending}
                              onChanged={() => { reloadGraph(); refreshStatus(); }} />
          </div>
          <ForgetPanel disabled={!connected} confirmAction={confirmAction}
                       onChanged={() => { reloadGraph(); refreshStatus(); }} />
        </div>
      </main>
    </>
  );
}

const card = "rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel p-5";
const field = "w-full rounded-lg px-3 py-2 bg-paper-soft dark:bg-night border border-line dark:border-night-line outline-none focus:border-brand text-[14px]";
const primary = "px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50 text-[14px]";

// "Ask my memory" — semantic/graph question → synthesised answer from the graph.
function AskPanel({ disabled }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState(null);

  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true); setAnswer(null);
    const r = await memoryRecall(q.trim());
    setBusy(false);
    setAnswer(r?.ok ? { ok: true, text: r.content } : { ok: false, text: r?.error || "Recall failed." });
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Ask my memory</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        e.g. “what languages do I like?”, “what am I building?” — rephrasing is fine.
      </div>
      <div className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} disabled={disabled}
               onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
               placeholder="Ask anything you've told me…" className={field} />
        <button onClick={ask} disabled={disabled || busy || !q.trim()} className={primary}>
          {busy ? "Thinking…" : "Ask"}
        </button>
      </div>
      {answer && (
        <div className={`mt-3 rounded-lg p-3 text-[14px] leading-relaxed whitespace-pre-wrap ${answer.ok
          ? "bg-paper-soft dark:bg-night text-ink dark:text-night-ink"
          : "bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-300"}`}>
          {answer.text}
        </div>
      )}
    </section>
  );
}

// "Remember" — store text. Permanent builds the graph; session is instant
// (buffered for the Consolidate/improve op).
function RememberPanel({ disabled, onChanged, onSession }) {
  const [text, setText] = useState("");
  const [permanent, setPermanent] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    if (!text.trim() || busy) return;
    setBusy(true); setMsg(null);
    const r = await memoryRemember(text.trim(), permanent);
    setBusy(false);
    if (r?.ok) {
      setMsg({ ok: true, text: permanent ? "Remembered → graph." : "Saved to session — consolidate to add it to the graph." });
      setText("");
      if (permanent) onChanged?.(); else onSession?.();
    } else setMsg({ ok: false, text: r?.error || "Couldn't store that." });
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Remember something</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        {permanent ? "Permanent builds the graph (takes a moment, then refreshes it)." : "Session is instant (no graph build) — then Consolidate to add it."}
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} disabled={disabled} rows={3}
                placeholder="e.g. I'm building Namma Agent and I love Python."
                className={`${field} resize-y`} />
      <div className="flex items-center justify-between mt-3 gap-2">
        <label className="flex items-center gap-2 text-[12.5px] text-ink-soft dark:text-night-faint cursor-pointer">
          <input type="checkbox" checked={permanent} onChange={(e) => setPermanent(e.target.checked)} disabled={disabled} />
          Build into graph
        </label>
        <div className="flex items-center gap-2">
          {msg && <span className={`text-[12px] ${msg.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{msg.text}</span>}
          <button onClick={save} disabled={disabled || busy || !text.trim()} className={primary}>
            {busy ? "Storing…" : "Remember"}
          </button>
        </div>
      </div>
    </section>
  );
}

// "Improve" / Consolidate — the 4th Cognee op. Promotes buffered session memories
// into the permanent knowledge graph via cognify (entity extraction + linking), so
// the graph visibly grows. Mirrors Cognee's memory-lifecycle "improve" step.
function ConsolidatePanel({ disabled, pending, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const has = pending > 0;

  async function run() {
    if (disabled || busy) return;
    setBusy(true); setMsg(null);
    const r = await memoryConsolidate();
    setBusy(false);
    if (r?.ok) { setMsg({ ok: true, text: r.content || "Consolidated." }); onChanged?.(); }
    else setMsg({ ok: false, text: r?.error || "Couldn't consolidate." });
  }

  return (
    <section className={card}>
      <div className="flex items-center gap-2 mb-1">
        <div className="text-[15px] font-medium">Improve memory</div>
        {has && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-brand/15 text-brand-deep dark:text-brand">
            {pending} pending
          </span>
        )}
      </div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        Consolidate your quick session notes into the graph — runs Cognee's <b>cognify</b>
        {" "}pipeline (entity extraction + linking), then the graph tightens.
      </div>
      <div className="flex items-center gap-3">
        <button onClick={run} disabled={disabled || busy || !has} className={primary}>
          {busy ? "Consolidating…" : has ? `Consolidate ${pending} into graph` : "Nothing to consolidate"}
        </button>
        {msg && <span className={`text-[12.5px] ${msg.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{msg.text}</span>}
      </div>
    </section>
  );
}

// "Forget" — destructive, confirms first; refreshes the graph after.
function ForgetPanel({ disabled, confirmAction, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function forgetAll() {
    if (disabled || busy) return;
    const ok = await confirmAction?.("Forget ALL Cognee memory? This deletes every entity and relationship and can't be undone.", "Forget everything");
    if (!ok) return;
    setBusy(true); setMsg(null);
    const r = await memoryForget({ everything: true });
    setBusy(false);
    if (r?.ok) { setMsg({ ok: true, text: "Memory cleared." }); onChanged?.(); }
    else setMsg({ ok: false, text: r?.error || "Couldn't clear memory." });
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Forget</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        Remove memory from Cognee's graph, vector, and relational stores.
      </div>
      <div className="flex items-center gap-3">
        <button onClick={forgetAll} disabled={disabled || busy}
                className="px-3 py-1.5 rounded-lg border text-[13px] disabled:opacity-50"
                style={{ borderColor: "#dc262666", color: "#dc2626" }}>
          {busy ? "Forgetting…" : "Forget everything"}
        </button>
        {msg && <span className={`text-[12.5px] ${msg.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{msg.text}</span>}
      </div>
    </section>
  );
}
