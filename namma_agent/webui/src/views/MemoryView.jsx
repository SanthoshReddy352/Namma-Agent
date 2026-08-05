import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  memoryStatus, memoryRecall, memoryRemember, memoryConsolidate, memoryForget,
  memoryGraph, memoryItems, memoryCore, saveMemoryCore, memoryEnvironment,
} from "../api.js";
import MemoryGraph from "../components/MemoryGraph.jsx";

// The "Memory" tab — a window into Engram, the native memory engine
// (docs/MEMORY_SYSTEM_DESIGN.md §9). Native memory is always on: no offline
// state, no container. Panes: status ribbon · knowledge-graph hero · core
// memory editor (the two always-in-context blocks) · ask/recall · facts
// browser · remember · improve · environment · danger zone.
export default function MemoryView() {
  const { confirmAction, dark } = useOutletContext();
  const [status, setStatus] = useState(null);
  const [graph, setGraph] = useState({ nodes: [], edges: [], note: null });
  const [loadingGraph, setLoadingGraph] = useState(false);
  // Time travel: pct ∈ [0,100] maps [first memory … now]; 100 = live view.
  const [history, setHistory] = useState(false);
  const [asOfPct, setAsOfPct] = useState(100);

  const asOfIso = useCallback((pct) => {
    if (!status?.since || pct >= 100) return "";
    const start = new Date(status.since).getTime();
    const end = Date.now();
    return new Date(start + (end - start) * (pct / 100)).toISOString();
  }, [status?.since]);

  const reloadGraph = useCallback(async (asOf = "") => {
    setLoadingGraph(true);
    const g = await memoryGraph(false, asOf);
    if (g?.ok) setGraph({ nodes: g.nodes || [], edges: g.edges || [], note: g.note || null });
    setLoadingGraph(false);
  }, []);

  const refreshStatus = useCallback(() => memoryStatus().then(setStatus), []);
  const refreshAll = useCallback(() => { refreshStatus(); reloadGraph(); }, [refreshStatus, reloadGraph]);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  // Scrubbing the slider (or toggling history off) re-queries the graph as-of.
  useEffect(() => {
    if (!history) { reloadGraph(); return; }
    const t = setTimeout(() => reloadGraph(asOfIso(asOfPct)), 250);   // debounce scrub
    return () => clearTimeout(t);
  }, [history, asOfPct, asOfIso, reloadGraph]);

  return (
    <>
      <header className="flex items-center gap-3 px-6 h-12 border-b border-line dark:border-night-line">
        <h1 className="font-serif text-lg">Memory</h1>
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
          Memory active
        </span>
        {status && (
          <span className="text-[12px] text-ink-faint dark:text-night-faint">
            {status.items ?? 0} facts · {status.entities ?? 0} entities · {status.relations ?? 0} links
            {status.memory_quality != null &&
              ` · ${Math.round(status.memory_quality * 100)}% quality`}
            {status.pending_writes > 0 && ` · ${status.pending_writes} writing…`}
          </span>
        )}
        {status?.last_consolidation && (
          <span className="ml-auto text-[11.5px] text-ink-faint dark:text-night-faint">
            Last improved {new Date(status.last_consolidation.at).toLocaleString()}
          </span>
        )}
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto space-y-6">
          <p className="text-ink-soft dark:text-night-faint text-[14px]">
            Your knowledge as a living <b>semantic + knowledge graph</b> — native, in-process,
            always on. Every chat is considered for memory; contradictions supersede old facts
            instead of deleting them, so history stays queryable. Everything here is yours to
            inspect, edit, and delete.
          </p>

          {/* HERO — the knowledge graph (+ time travel over the bi-temporal store) */}
          <section>
            <div className="flex items-center justify-between mb-2 gap-3">
              <div className="text-[15px] font-medium">Knowledge graph</div>
              <div className="flex items-center gap-2">
                {status?.since && (
                  <button onClick={() => { setHistory(!history); setAsOfPct(100); }}
                          className={`text-[12.5px] px-2.5 py-1 rounded-lg border ${history
                            ? "border-brand text-brand-deep dark:text-brand bg-brand/10"
                            : "border-line dark:border-night-line text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft"}`}>
                    ⏱ History
                  </button>
                )}
                <button onClick={() => reloadGraph(history ? asOfIso(asOfPct) : "")} disabled={loadingGraph}
                        className="text-[12.5px] px-2.5 py-1 rounded-lg border border-line dark:border-night-line text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft disabled:opacity-50">
                  {loadingGraph ? "Loading…" : "↻ Refresh"}
                </button>
              </div>
            </div>
            {history && (
              <div className="flex items-center gap-3 mb-2 text-[12.5px] text-ink-soft dark:text-night-faint">
                <span className="shrink-0">{new Date(status.since).toLocaleDateString()}</span>
                <input type="range" min="0" max="100" value={asOfPct}
                       onChange={(e) => setAsOfPct(Number(e.target.value))}
                       className="flex-1 accent-[var(--brand,#2f6bff)]" />
                <span className="shrink-0">
                  {asOfPct >= 100 ? "now" : new Date(asOfIso(asOfPct)).toLocaleString()}
                </span>
              </div>
            )}
            <div className="relative rounded-2xl shadow-pop"
                 style={{ background: "linear-gradient(135deg, rgba(47,107,255,0.10), rgba(124,58,237,0.10))", padding: 1 }}>
              <MemoryGraph nodes={graph.nodes} edges={graph.edges} dark={dark} height={520} />
              {graph.nodes.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center p-6 pointer-events-none">
                  <div className="max-w-md text-center rounded-2xl bg-paper-panel/90 dark:bg-night-panel/90 border border-line dark:border-night-line p-5 shadow-pop">
                    <div className="text-[14px] font-medium mb-1">No graph yet</div>
                    <div className="text-[12.5px] text-ink-soft dark:text-night-faint">
                      Chat naturally or use “Remember something” below — extracted facts and their
                      entities appear here as they're learned.
                    </div>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Core memory — the two always-in-context blocks */}
          <CoreMemoryPanel />

          <AskPanel />

          <FactsBrowser onChanged={refreshAll} confirmAction={confirmAction} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <RememberPanel onChanged={refreshAll} />
            <ImprovePanel onChanged={refreshAll} last={status?.last_consolidation} />
          </div>

          <EnvironmentPanel />

          <ForgetPanel confirmAction={confirmAction} onChanged={refreshAll} />
        </div>
      </main>
    </>
  );
}

const card = "rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel p-5";
const field = "w-full rounded-lg px-3 py-2 bg-paper-soft dark:bg-night border border-line dark:border-night-line outline-none focus:border-brand text-[14px]";
const primary = "px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50 text-[14px]";
const ghost = "px-2.5 py-1 rounded-lg border border-line dark:border-night-line text-[12.5px] text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft disabled:opacity-50";

// ── Core memory editor — User + Agent blocks with usage bars, inline edit ────
function CoreMemoryPanel() {
  const [core, setCore] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = useCallback(() => memoryCore().then((r) => { if (r?.ok) setCore(r); }), []);
  useEffect(() => { load(); }, [load]);

  async function save(body) {
    setMsg(null);
    const r = await saveMemoryCore(body);
    if (r?.ok) { load(); }
    else setMsg({ ok: false, text: r?.error || "Couldn't save." });
    return r?.ok;
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Core memory</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        Small, curated, and in <b>every</b> system prompt — who you are and what the agent has
        learned about working with you. Zero lookups, zero latency. Bounded on purpose: dense
        one-liners beat paragraphs.
      </div>
      {msg && <div className="mb-2 text-[12.5px] text-amber-600 dark:text-amber-400">{msg.text}</div>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {["user", "agent"].map((block) => (
          <CoreBlock key={block} block={block} data={core?.[block]} onSave={save} />
        ))}
      </div>
    </section>
  );
}

function CoreBlock({ block, data, onSave }) {
  const [adding, setAdding] = useState("");
  const [editId, setEditId] = useState(null);
  const [editText, setEditText] = useState("");

  const entries = data?.entries || [];
  const pct = data?.pct ?? 0;

  return (
    <div className="rounded-xl border border-line dark:border-night-line p-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[13.5px] font-medium">{block === "user" ? "About you" : "Agent notes"}</div>
        <span className="text-[11px] text-ink-faint dark:text-night-faint">{pct}% full</span>
      </div>
      <div className="h-1.5 rounded-full bg-paper-soft dark:bg-night mb-2.5 overflow-hidden">
        <div className={`h-full rounded-full ${pct > 80 ? "bg-amber-500" : "bg-brand"}`} style={{ width: `${pct}%` }} />
      </div>
      <ul className="space-y-1.5 mb-2.5">
        {entries.length === 0 && (
          <li className="text-[12.5px] text-ink-faint dark:text-night-faint italic">Nothing pinned yet.</li>
        )}
        {entries.map((e) => (
          <li key={e.id} className="group flex items-start gap-1.5 text-[13px]">
            {editId === e.id ? (
              <div className="flex-1 flex gap-1.5">
                <input value={editText} onChange={(ev) => setEditText(ev.target.value)} className={field}
                       onKeyDown={async (ev) => {
                         if (ev.key === "Enter" && editText.trim()) {
                           if (await onSave({ block, action: "replace", entry_id: e.id, text: editText.trim() })) setEditId(null);
                         }
                         if (ev.key === "Escape") setEditId(null);
                       }} autoFocus />
                <button className={ghost} onClick={async () => {
                  if (editText.trim() && await onSave({ block, action: "replace", entry_id: e.id, text: editText.trim() })) setEditId(null);
                }}>Save</button>
              </div>
            ) : (
              <>
                <span className="flex-1 leading-snug">{e.text}</span>
                <button title="Edit" className="opacity-0 group-hover:opacity-100 text-ink-faint hover:text-brand text-[12px]"
                        onClick={() => { setEditId(e.id); setEditText(e.text); }}>✎</button>
                <button title="Remove" className="opacity-0 group-hover:opacity-100 text-ink-faint hover:text-red-500 text-[12px]"
                        onClick={() => onSave({ block, action: "remove", entry_id: e.id })}>✕</button>
              </>
            )}
          </li>
        ))}
      </ul>
      <div className="flex gap-1.5">
        <input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="Pin a durable fact…"
               className={field}
               onKeyDown={async (e) => {
                 if (e.key === "Enter" && adding.trim()) {
                   if (await onSave({ block, action: "add", text: adding.trim() })) setAdding("");
                 }
               }} />
        <button className={ghost} disabled={!adding.trim()}
                onClick={async () => { if (await onSave({ block, action: "add", text: adding.trim() })) setAdding(""); }}>
          Add
        </button>
      </div>
    </div>
  );
}

// ── Ask / recall — fused search with provenance + valid-time chips ───────────
function AskPanel() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState(null);   // null | [] | [..]
  const [err, setErr] = useState(null);

  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true); setResults(null); setErr(null);
    const r = await memoryRecall(q.trim());
    setBusy(false);
    if (r?.ok) setResults(r.results || []);
    else setErr(r?.error || "Recall failed.");
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Ask my memory</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        One fused query over facts, the entity graph, and past conversations — milliseconds,
        with provenance. e.g. “what languages do I like?”, “what am I building?”
      </div>
      <div className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
               placeholder="Ask anything you've told me…" className={field} />
        <button onClick={ask} disabled={busy || !q.trim()} className={primary}>
          {busy ? "Searching…" : "Ask"}
        </button>
      </div>
      {err && <div className="mt-3 rounded-lg p-3 text-[13px] bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-300">{err}</div>}
      {results && (
        <div className="mt-3 space-y-1.5">
          {results.length === 0 && (
            <div className="text-[13px] text-ink-faint dark:text-night-faint">No stored memory matches.</div>
          )}
          {results.map((r, i) => (
            <div key={i} className="rounded-lg p-2.5 bg-paper-soft dark:bg-night text-[13.5px] leading-relaxed">
              <span>{r.text}</span>
              <span className="ml-2 inline-flex gap-1 align-middle">
                <Chip>{r.kind || "fact"}</Chip>
                {r.created_at && <Chip>{r.created_at.slice(0, 10)}</Chip>}
                {r.source && <Chip>{r.source}</Chip>}
                {r.expired && <Chip tone="amber">superseded</Chip>}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Chip({ children, tone }) {
  const cls = tone === "amber"
    ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400"
    : "bg-brand/10 text-brand-deep dark:text-brand";
  return <span className={`text-[10.5px] px-1.5 py-0.5 rounded-full ${cls}`}>{children}</span>;
}

// ── Facts browser — filterable table with per-row forget ─────────────────────
const KINDS = ["", "fact", "preference", "event", "insight"];

function FactsBrowser({ onChanged, confirmAction }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState("");
  const [showExpired, setShowExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    const r = await memoryItems(kind, showExpired);
    if (r?.ok) setItems(r.items || []);
    setBusy(false);
  }, [kind, showExpired]);

  useEffect(() => { if (open) load(); }, [open, load]);

  async function forgetRow(item) {
    const ok = await confirmAction?.(`Forget “${item.text.slice(0, 120)}”?`, "Forget");
    if (!ok) return;
    await memoryForget({ item_id: item.id });
    load(); onChanged?.();
  }

  return (
    <section className={card}>
      <button className="w-full flex items-center justify-between" onClick={() => setOpen(!open)}>
        <div className="text-[15px] font-medium">Facts browser</div>
        <span className="text-[12px] text-ink-faint dark:text-night-faint">{open ? "▲ Hide" : "▼ Show"}</span>
      </button>
      {open && (
        <>
          <div className="flex items-center gap-3 mt-3 mb-2">
            <select value={kind} onChange={(e) => setKind(e.target.value)}
                    className="rounded-lg px-2 py-1.5 bg-paper-soft dark:bg-night border border-line dark:border-night-line text-[13px]">
              {KINDS.map((k) => <option key={k} value={k}>{k || "all kinds"}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-[12.5px] text-ink-soft dark:text-night-faint cursor-pointer">
              <input type="checkbox" checked={showExpired} onChange={(e) => setShowExpired(e.target.checked)} />
              show superseded & archived
            </label>
            <button className={ghost} onClick={load} disabled={busy}>{busy ? "…" : "↻"}</button>
            <span className="ml-auto text-[12px] text-ink-faint dark:text-night-faint">{items.length} shown</span>
          </div>
          <div className="max-h-80 overflow-y-auto divide-y divide-line dark:divide-night-line">
            {items.length === 0 && !busy && (
              <div className="py-4 text-[13px] text-ink-faint dark:text-night-faint">Nothing stored yet.</div>
            )}
            {items.map((it) => (
              <div key={it.id} className={`group py-2 flex items-start gap-2 text-[13px] ${it.expired_at ? "opacity-60" : ""}`}>
                <div className="flex-1 leading-snug">
                  {it.text}
                  <span className="ml-2 inline-flex gap-1 align-middle">
                    <Chip>{it.kind}</Chip>
                    {it.created_at && <Chip>{it.created_at.slice(0, 10)}</Chip>}
                    {it.frequency > 1 && <Chip>×{it.frequency}</Chip>}
                    {it.expired_at && <Chip tone="amber">superseded</Chip>}
                    {it.archived_at && !it.expired_at && <Chip tone="amber">archived</Chip>}
                    {it.screen_status === "flagged" && <Chip tone="amber">quarantined</Chip>}
                  </span>
                </div>
                {!it.expired_at && (
                  <button title="Forget" onClick={() => forgetRow(it)}
                          className="opacity-0 group-hover:opacity-100 text-ink-faint hover:text-red-500 text-[12px] shrink-0">✕</button>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

// ── Remember — explicit save through the write pipeline ──────────────────────
function RememberPanel({ onChanged }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    if (!text.trim() || busy) return;
    setBusy(true); setMsg(null);
    const r = await memoryRemember(text.trim());
    setBusy(false);
    if (r?.ok) {
      setMsg({ ok: true, text: "Queued — the graph updates in a few seconds." });
      setText("");
      setTimeout(() => onChanged?.(), 4000);
    } else setMsg({ ok: false, text: r?.error || "Couldn't store that." });
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Remember something</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        Fact extraction + contradiction handling run in the background on your selected model.
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
                placeholder="e.g. I'm building Namma Agent and I love Python."
                className={`${field} resize-y`} />
      <div className="flex items-center justify-end mt-3 gap-2">
        {msg && <span className={`text-[12px] ${msg.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{msg.text}</span>}
        <button onClick={save} disabled={busy || !text.trim()} className={primary}>
          {busy ? "Storing…" : "Remember"}
        </button>
      </div>
    </section>
  );
}

// ── Improve — the consolidation op + last-run report card ────────────────────
const REPORT_LABELS = [
  ["sessions_summarized", "sessions summarized"],
  ["promoted", "facts promoted"],
  ["merged", "duplicates merged"],
  ["archived", "archived"],
  ["events_expired", "events expired"],
  ["insights", "new insights"],
  ["skill_drafts", "skills drafted"],
  ["skills_reinforced", "facts reinforced by skill use"],
  ["core_compacted", "core compacted"],
  ["quality_scored", "facts audited"],
  ["quality_junk", "low-value facts flagged"],
];

function reportLine(report) {
  const parts = REPORT_LABELS
    .filter(([k]) => (report?.[k] || 0) > 0)
    .map(([k, label]) => `${report[k]} ${label}`);
  // Storage quality is a rate, not a count — it belongs even when it's 0.
  if (report?.memory_quality != null) {
    parts.push(`${Math.round(report.memory_quality * 100)}% memory quality`);
  }
  return parts.length ? parts.join(" · ") : "nothing needed changing";
}

function ImprovePanel({ onChanged, last }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function run() {
    if (busy) return;
    setBusy(true); setMsg(null);
    const r = await memoryConsolidate();
    setBusy(false);
    if (r?.ok) { setMsg({ ok: true, text: r.content || "Consolidated." }); onChanged?.(); }
    else setMsg({ ok: false, text: r?.error || "Couldn't consolidate." });
  }

  return (
    <section className={card}>
      <div className="text-[15px] font-medium mb-1">Improve memory</div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        One sleep-time pass: summarize finished chats, promote missed facts, merge duplicates,
        let stale facts fade, reflect into insights, compact core memory, re-probe the machine.
        Runs on its own when idle (see Settings → Memory) — or right now.
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={run} disabled={busy} className={primary}>
          {busy ? "Improving…" : "Improve now"}
        </button>
        {msg && <span className={`text-[12.5px] ${msg.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{msg.text}</span>}
      </div>
      {last?.at && !msg && (
        <div className="mt-3 rounded-lg p-2.5 bg-paper-soft dark:bg-night text-[12.5px] text-ink-soft dark:text-night-faint">
          Last improved {new Date(last.at).toLocaleString()}
          {last.reason && ` (${last.reason})`}: {reportLine(last)}.
        </div>
      )}
    </section>
  );
}

// ── Environment — the L5 host model (read-only + refresh) ────────────────────
function EnvironmentPanel() {
  const [env, setEnv] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (refresh = false) => {
    setBusy(true);
    const r = await memoryEnvironment(refresh);
    if (r?.ok) setEnv(r.environment);
    setBusy(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const tools = Object.keys(env?.tools || {});

  return (
    <section className={card}>
      <div className="flex items-center justify-between mb-1">
        <div className="text-[15px] font-medium">Environment</div>
        <button className={ghost} disabled={busy} onClick={() => load(true)}>
          {busy ? "…" : "↻ Refresh"}
        </button>
      </div>
      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mb-3">
        The machine model injected into every prompt — so the agent never guesses paths and
        knows which programs are actually installed here.
      </div>
      {env && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-[13px]">
          <Row k="OS" v={env.os} />
          <Row k="User" v={env.user} />
          <Row k="Home" v={env.home} />
          <Row k="Shell" v={env.shell} />
          <Row k="Drives" v={(env.drives || []).map((d) => d.root + (d.free_gb != null ? ` (${d.free_gb} GB free)` : "")).join(" · ")} />
          <Row k="Key folders" v={Object.keys(env.folders || {}).join(" · ")} />
          {tools.length > 0 && <Row k={`Tools found (${tools.length})`} v={tools.join(" · ")} />}
          {env.apps_indexed && <Row k="Apps indexed" v={String(env.apps_indexed)} />}
        </div>
      )}
    </section>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex gap-2 min-w-0">
      <span className="text-ink-faint dark:text-night-faint shrink-0 w-28">{k}</span>
      <span className="truncate" title={v}>{v || "—"}</span>
    </div>
  );
}

// ── Forget / danger zone ─────────────────────────────────────────────────────
function ForgetPanel({ confirmAction, onChanged }) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function forgetQuery() {
    if (!query.trim() || busy) return;
    setBusy(true); setMsg(null);
    const r = await memoryForget({ query: query.trim() });
    setBusy(false);
    if (r?.ok) { setMsg({ ok: true, text: r.content || `Forgot ${r.forgot}.` }); setQuery(""); onChanged?.(); }
    else setMsg({ ok: false, text: r?.error || "Couldn't forget." });
  }

  async function forgetAll() {
    if (busy) return;
    const ok = await confirmAction?.("Forget ALL memory? Every fact, entity, relationship and core-memory entry is deleted. This can't be undone.", "Forget everything");
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
        Matching facts are invalidated (kept in history as superseded). “Forget everything”
        really deletes it all — facts, graph, and core memory.
      </div>
      <div className="flex gap-2 mb-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") forgetQuery(); }}
               placeholder="Forget everything about… (a topic, a person, a project)" className={field} />
        <button onClick={forgetQuery} disabled={busy || !query.trim()} className={primary}>Forget</button>
      </div>
      <div className="flex items-center gap-3">
        <button onClick={forgetAll} disabled={busy}
                className="px-3 py-1.5 rounded-lg border text-[13px] disabled:opacity-50"
                style={{ borderColor: "#dc262666", color: "#dc2626" }}>
          {busy ? "Working…" : "Forget everything"}
        </button>
        {msg && <span className={`text-[12.5px] ${msg.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{msg.text}</span>}
      </div>
    </section>
  );
}
