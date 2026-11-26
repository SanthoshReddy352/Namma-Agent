import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  IconAffiliate, IconBrain, IconChartBar, IconHistory, IconPencil, IconRefresh, IconSchema,
  IconSearch, IconSparkles, IconTrash, IconX,
} from "@tabler/icons-react";
import {
  memoryStatus, memoryRecall, memoryRemember, memoryConsolidate, memoryForget,
  memoryGraph, memoryItems, memoryCore, saveMemoryCore, memoryEnvironment,
  memoryGraphSchema, memoryGraphRanked, memoryGraphRebuild,
} from "../api.js";
import MemoryGraph from "../components/MemoryGraph.jsx";
import EntityPanel from "../components/memory/EntityPanel.jsx";
import SchemaView from "../components/memory/SchemaView.jsx";
import RankedView from "../components/memory/RankedView.jsx";
import { searchNodes, typeColor } from "../components/memory/graphModel.js";
import Button from "../components/ui/Button.jsx";
import IconButton from "../components/ui/IconButton.jsx";
import { EmptyState } from "../components/ui/Misc.jsx";

// The Memory page (Phase 10 redesign) — a window into Engram.
//   • Explore: Graph (typed entities + typed, directed relations; focus an
//     entity to see its neighbourhood and the facts behind it), Schema (types
//     and relation kinds derived from the data) and Ranked (centrality ·
//     salience · recency, every component shown).
//   • Manage: core memory, ask, the facts browser, remember / improve,
//     environment, forget.
// Surfaces are translucent over the app's painted-paper background and use
// the semantic tokens only, so every theme (light and dark) re-skins it.

const TABS = [
  { id: "graph", label: "Graph", Icon: IconAffiliate },
  { id: "schema", label: "Schema", Icon: IconSchema },
  { id: "ranked", label: "Ranked", Icon: IconChartBar },
];
const TAB_KEY = "namma-memory-tab";

const card = "rounded-2xl border border-border bg-surface/80 backdrop-blur-sm p-5";
const field = "w-full rounded-lg px-3 h-9 bg-surface-sunken border border-border outline-none focus:border-accent text-base text-fg placeholder:text-fg-subtle";
const sectionTitle = "text-prose font-medium text-fg";

export default function MemoryView() {
  const { confirmAction, dark } = useOutletContext();
  const [status, setStatus] = useState(null);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [tab, setTab] = useState(() => {
    try { return localStorage.getItem(TAB_KEY) || "graph"; } catch { return "graph"; }
  });
  const [schema, setSchema] = useState(null);
  const [ranked, setRanked] = useState(null);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState(false);
  const [asOfPct, setAsOfPct] = useState(100);
  const [rebuildMsg, setRebuildMsg] = useState(null);

  useEffect(() => { try { localStorage.setItem(TAB_KEY, tab); } catch { /* private mode */ } }, [tab]);

  const asOfIso = useCallback((pct) => {
    if (!status?.since || pct >= 100) return "";
    const start = new Date(status.since).getTime();
    return new Date(start + (Date.now() - start) * (pct / 100)).toISOString();
  }, [status?.since]);

  const reloadGraph = useCallback(async (asOf = "") => {
    setLoadingGraph(true);
    const g = await memoryGraph(!!asOf, asOf);
    if (g?.ok) setGraph({ nodes: g.nodes || [], edges: g.edges || [] });
    setLoadingGraph(false);
  }, []);
  const reloadSchema = useCallback(() => memoryGraphSchema().then((r) => r?.ok && setSchema(r)), []);
  const reloadRanked = useCallback(() => memoryGraphRanked(60).then((r) => r?.ok && setRanked(r)), []);
  const refreshStatus = useCallback(() => memoryStatus().then(setStatus), []);
  const refreshAll = useCallback(() => {
    refreshStatus(); reloadGraph(); setSchema(null); setRanked(null);
  }, [refreshStatus, reloadGraph]);

  useEffect(() => { refreshAll(); }, [refreshAll]);
  useEffect(() => {
    if (tab === "schema" && !schema) reloadSchema();
    if (tab === "ranked" && !ranked) reloadRanked();
  }, [tab, schema, ranked, reloadSchema, reloadRanked]);

  // Scrubbing the history slider re-queries the graph as-of (debounced).
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return undefined; }
    if (!history) { reloadGraph(); return undefined; }
    const t = setTimeout(() => reloadGraph(asOfIso(asOfPct)), 250);
    return () => clearTimeout(t);
  }, [history, asOfPct, asOfIso, reloadGraph]);

  const matches = useMemo(() => searchNodes(graph.nodes, query), [graph.nodes, query]);
  const nodeIds = useMemo(() => new Set(graph.nodes.map((n) => n.id)), [graph.nodes]);
  // Drop a focus that no longer exists (forgotten, merged, time-travelled away).
  useEffect(() => { if (selected && tab === "graph" && !nodeIds.has(selected)) setSelected(null); }, [nodeIds]); // eslint-disable-line react-hooks/exhaustive-deps

  async function rebuild() {
    setRebuildMsg(null);
    const r = await memoryGraphRebuild();
    if (r?.ok) {
      setRebuildMsg(`Rebuilt from your facts: ${r.after.entities} entities, ${r.after.relations} relations.`);
      refreshAll();
    } else setRebuildMsg(r?.error || "Couldn't rebuild.");
  }

  const pick = (id) => setSelected(id);

  return (
    <>
      <header className="flex items-center gap-3 px-6 h-12 border-b border-border">
        <h1 className="font-serif text-lg text-fg">Memory</h1>
        {status && (
          <div className="hidden md:flex items-center gap-1.5 text-xs text-fg-muted">
            <Stat n={status.items} label="facts" />
            <Stat n={status.entities} label="entities" />
            <Stat n={status.relations} label="relations" />
            {status.memory_quality != null && <Stat n={`${Math.round(status.memory_quality * 100)}%`} label="quality" />}
            {status.pending_writes > 0 && <span className="text-accent">· {status.pending_writes} writing…</span>}
          </div>
        )}
        <div className="ml-auto flex items-center gap-1">
          {status?.last_consolidation && (
            <span className="hidden lg:inline text-xs text-fg-subtle mr-2">
              Improved {new Date(status.last_consolidation.at).toLocaleString()}
            </span>
          )}
          <IconButton label="Refresh" onClick={refreshAll} disabled={loadingGraph}>
            <IconRefresh size={17} stroke={1.7} className={loadingGraph ? "animate-spin" : ""} />
          </IconButton>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 sm:px-6 py-5">
        <div className="max-w-6xl mx-auto space-y-5">
          {/* ── Explore ─────────────────────────────────────────────── */}
          <section className="rounded-2xl border border-border bg-surface/75 backdrop-blur-sm overflow-hidden" aria-label="Knowledge graph">
            <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-border">
              <div role="tablist" aria-label="Memory views" className="flex rounded-lg bg-surface-sunken p-0.5">
                {TABS.map(({ id, label, Icon }) => (
                  <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)}
                          className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-sm transition-colors ${tab === id
                            ? "bg-surface text-fg shadow-sm" : "text-fg-muted hover:text-fg"}`}>
                    <Icon size={15} stroke={1.8} />{label}
                  </button>
                ))}
              </div>
              <div className="relative flex-1 min-w-[180px] max-w-sm">
                <IconSearch size={15} stroke={1.8} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle pointer-events-none" />
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                       onKeyDown={(e) => { if (e.key === "Enter" && matches[0]) { pick(matches[0].id); setTab("graph"); } }}
                       placeholder="Find an entity…" aria-label="Find an entity"
                       className="w-full h-8 pl-8 pr-2 rounded-lg bg-surface-sunken border border-border outline-none focus:border-accent text-sm text-fg placeholder:text-fg-subtle" />
                {query && (
                  <ul className="absolute z-dropdown mt-1 w-full max-h-64 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg py-1" role="listbox">
                    {matches.slice(0, 8).map((n) => (
                      <li key={n.id} role="option" aria-selected={selected === n.id}>
                        <button type="button" onClick={() => { pick(n.id); setTab("graph"); setQuery(""); }}
                                className="w-full flex items-center gap-2 px-3 h-8 text-left text-sm hover:bg-surface-hover">
                          <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: typeColor(n.type) }} />
                          <span className="truncate text-fg">{n.label}</span>
                          {n.via && <span className="text-2xs text-fg-subtle truncate">aka {n.via}</span>}
                          <span className="ml-auto text-2xs text-fg-subtle capitalize">{n.type}</span>
                        </button>
                      </li>
                    ))}
                    {!matches.length && <li className="px-3 py-2 text-sm text-fg-subtle">No entity matches.</li>}
                  </ul>
                )}
              </div>
              <div className="ml-auto flex items-center gap-1">
                {tab === "graph" && status?.since && (
                  <Button size="sm" variant={history ? "primary" : "ghost"} aria-pressed={history}
                          onClick={() => { setHistory(!history); setAsOfPct(100); }}>
                    <IconHistory size={15} stroke={1.8} />History
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={rebuild} title="Re-derive the graph from every stored fact">
                  <IconSparkles size={15} stroke={1.8} />Rebuild
                </Button>
              </div>
            </div>
            {tab === "graph" && history && (
              <div className="flex items-center gap-3 px-4 py-2 border-b border-border text-sm text-fg-muted">
                <span className="shrink-0">{new Date(status.since).toLocaleDateString()}</span>
                <input type="range" min="0" max="100" value={asOfPct} aria-label="Show memory as of"
                       onChange={(e) => setAsOfPct(Number(e.target.value))} className="flex-1 accent-accent" />
                <span className="shrink-0 tabular-nums">{asOfPct >= 100 ? "now" : new Date(asOfIso(asOfPct)).toLocaleString()}</span>
              </div>
            )}
            {rebuildMsg && (
              <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border text-sm text-fg-muted">
                {rebuildMsg}
                <IconButton label="Dismiss" className="ml-auto h-6 w-6 min-w-6" onClick={() => setRebuildMsg(null)}><IconX size={14} /></IconButton>
              </div>
            )}

            <div className={`grid ${selected ? "lg:grid-cols-[1fr_360px]" : "grid-cols-1"}`}>
              <div className="min-w-0">
                {tab === "graph" && (graph.nodes.length ? (
                  <MemoryGraph nodes={graph.nodes} edges={graph.edges} selectedId={selected} onSelect={pick}
                               query={query} matches={matches} height={600} themeKey={String(dark)} />
                ) : (
                  <div className="h-[420px] grid place-items-center">
                    <EmptyState title={loadingGraph ? "Loading the graph…" : "No graph yet"}>
                      {!loadingGraph && "Chat naturally or use “Remember something” below — the people, places, projects and tools you mention appear here as typed entities with labelled relations."}
                    </EmptyState>
                  </div>
                ))}
                {tab === "schema" && <SchemaView schema={schema} loading={!schema} />}
                {tab === "ranked" && <RankedView data={ranked} loading={!ranked} selectedId={selected} onPick={pick} />}
              </div>
              {selected && (
                <div className="border-t lg:border-t-0 lg:border-l border-border min-h-0 lg:max-h-[600px] max-h-[520px]">
                  <EntityPanel entityId={selected} nodes={graph.nodes} onClose={() => setSelected(null)}
                               onPick={pick} onChanged={refreshAll} />
                </div>
              )}
            </div>
          </section>

          {/* ── Manage ──────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <CoreMemoryPanel />
            <AskPanel />
          </div>
          <FactsBrowser onChanged={refreshAll} confirmAction={confirmAction} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
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

function Stat({ n, label }) {
  return (
    <span className="inline-flex items-baseline gap-1 rounded-full border border-border bg-surface/70 px-2 h-6 items-center">
      <b className="text-fg font-semibold tabular-nums">{n ?? 0}</b>{label}
    </span>
  );
}

function Chip({ children, tone }) {
  const cls = tone === "warn" ? "bg-warning/15 text-warning" : "bg-accent-wash text-accent";
  return <span className={`text-2xs px-1.5 py-0.5 rounded-full ${cls}`}>{children}</span>;
}

// ── Core memory editor — User + Agent blocks with usage bars, inline edit ────
function CoreMemoryPanel() {
  const [core, setCore] = useState(null);
  const [msg, setMsg] = useState(null);
  const load = useCallback(() => memoryCore().then((r) => { if (r?.ok) setCore(r); }), []);
  useEffect(() => { load(); }, [load]);
  async function save(body) {
    setMsg(null);
    const r = await saveMemoryCore(body);
    if (r?.ok) load(); else setMsg(r?.error || "Couldn't save.");
    return r?.ok;
  }
  return (
    <section className={card}>
      <div className="flex items-center gap-2 mb-1"><IconBrain size={17} stroke={1.7} className="text-fg-subtle" /><h2 className={sectionTitle}>Core memory</h2></div>
      <p className="text-sm text-fg-subtle mb-3">
        Small, curated and in <b className="text-fg-muted">every</b> prompt — who you are and how to work with you.
      </p>
      {msg && <div className="mb-2 text-sm text-warning">{msg}</div>}
      <div className="space-y-3">
        {["user", "agent"].map((block) => <CoreBlock key={block} block={block} data={core?.[block]} onSave={save} />)}
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
  const commitEdit = async (id) => {
    if (editText.trim() && await onSave({ block, action: "replace", entry_id: id, text: editText.trim() })) setEditId(null);
  };
  const commitAdd = async () => {
    if (adding.trim() && await onSave({ block, action: "add", text: adding.trim() })) setAdding("");
  };
  return (
    <div className="rounded-xl border border-border p-3 bg-surface/60">
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-base font-medium text-fg">{block === "user" ? "About you" : "Agent notes"}</div>
        <span className="text-2xs text-fg-subtle">{pct}% full</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-sunken mb-2.5 overflow-hidden">
        <div className={`h-full rounded-full ${pct > 80 ? "bg-warning" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </div>
      <ul className="space-y-1 mb-2.5">
        {entries.length === 0 && <li className="text-sm text-fg-subtle italic">Nothing pinned yet.</li>}
        {entries.map((e) => (
          <li key={e.id} className="group flex items-start gap-1 text-sm">
            {editId === e.id ? (
              <div className="flex-1 flex gap-1.5">
                <input value={editText} onChange={(ev) => setEditText(ev.target.value)} className={field} autoFocus
                       onKeyDown={(ev) => { if (ev.key === "Enter") commitEdit(e.id); if (ev.key === "Escape") setEditId(null); }} />
                <Button size="sm" onClick={() => commitEdit(e.id)}>Save</Button>
              </div>
            ) : (
              <>
                <span className="flex-1 leading-snug text-fg py-1">{e.text}</span>
                <IconButton label="Edit" className="opacity-0 group-hover:opacity-100 focus:opacity-100 h-7 w-7 min-w-7"
                            onClick={() => { setEditId(e.id); setEditText(e.text); }}><IconPencil size={14} /></IconButton>
                <IconButton label="Remove" className="opacity-0 group-hover:opacity-100 focus:opacity-100 h-7 w-7 min-w-7 hover:text-danger"
                            onClick={() => onSave({ block, action: "remove", entry_id: e.id })}><IconX size={14} /></IconButton>
              </>
            )}
          </li>
        ))}
      </ul>
      <div className="flex gap-1.5">
        <input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="Pin a durable fact…" className={field}
               onKeyDown={(e) => { if (e.key === "Enter") commitAdd(); }} />
        <Button size="sm" className="h-9" disabled={!adding.trim()} onClick={commitAdd}>Add</Button>
      </div>
    </div>
  );
}

// ── Ask / recall — fused search with provenance + valid-time chips ───────────
function AskPanel() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState(null);
  const [err, setErr] = useState(null);
  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true); setResults(null); setErr(null);
    const r = await memoryRecall(q.trim());
    setBusy(false);
    if (r?.ok) setResults(r.results || []); else setErr(r?.error || "Recall failed.");
  }
  return (
    <section className={card}>
      <div className="flex items-center gap-2 mb-1"><IconSearch size={17} stroke={1.7} className="text-fg-subtle" /><h2 className={sectionTitle}>Ask my memory</h2></div>
      <p className="text-sm text-fg-subtle mb-3">
        One fused query over facts, the entity graph and past conversations — with provenance.
      </p>
      <div className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
               placeholder="e.g. where do I live now?" className={field} />
        <Button variant="primary" onClick={ask} disabled={busy || !q.trim()}>{busy ? "Searching…" : "Ask"}</Button>
      </div>
      {err && <div className="mt-3 rounded-lg p-3 text-sm bg-warning/10 text-warning">{err}</div>}
      {results && (
        <div className="mt-3 space-y-1.5 max-h-72 overflow-y-auto">
          {results.length === 0 && <div className="text-sm text-fg-subtle">No stored memory matches.</div>}
          {results.map((r, i) => (
            <div key={i} className="rounded-lg p-2.5 bg-surface-sunken text-sm leading-relaxed text-fg">
              <span>{r.text}</span>
              <span className="ml-2 inline-flex gap-1 align-middle flex-wrap">
                <Chip>{r.kind || "fact"}</Chip>
                {r.created_at && <Chip>{r.created_at.slice(0, 10)}</Chip>}
                {r.source && <Chip>{r.source}</Chip>}
                {r.expired && <Chip tone="warn">superseded</Chip>}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
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
    if (!(await confirmAction?.(`Forget “${item.text.slice(0, 120)}”?`, "Forget"))) return;
    await memoryForget({ item_id: item.id });
    load(); onChanged?.();
  }
  return (
    <section className={card}>
      <button type="button" className="w-full flex items-center justify-between" onClick={() => setOpen(!open)} aria-expanded={open}>
        <h2 className={sectionTitle}>Facts browser</h2>
        <span className="text-xs text-fg-subtle">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <>
          <div className="flex flex-wrap items-center gap-3 mt-3 mb-2">
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind"
                    className="rounded-lg px-2 h-8 bg-surface-sunken border border-border text-sm text-fg">
              {KINDS.map((k) => <option key={k} value={k}>{k || "all kinds"}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-sm text-fg-muted cursor-pointer">
              <input type="checkbox" checked={showExpired} onChange={(e) => setShowExpired(e.target.checked)} />
              show superseded & archived
            </label>
            <IconButton label="Refresh facts" onClick={load} disabled={busy}><IconRefresh size={15} /></IconButton>
            <span className="ml-auto text-xs text-fg-subtle">{items.length} shown</span>
          </div>
          <div className="max-h-80 overflow-y-auto divide-y divide-border">
            {items.length === 0 && !busy && <div className="py-4 text-sm text-fg-subtle">Nothing stored yet.</div>}
            {items.map((it) => (
              <div key={it.id} className={`group py-2 flex items-start gap-2 text-sm ${it.expired_at ? "opacity-60" : ""}`}>
                <div className="flex-1 leading-snug text-fg">
                  {it.text}
                  <span className="ml-2 inline-flex gap-1 align-middle flex-wrap">
                    <Chip>{it.kind}</Chip>
                    {it.created_at && <Chip>{it.created_at.slice(0, 10)}</Chip>}
                    {it.frequency > 1 && <Chip>×{it.frequency}</Chip>}
                    {it.expired_at && <Chip tone="warn">superseded</Chip>}
                    {it.archived_at && !it.expired_at && <Chip tone="warn">archived</Chip>}
                    {it.screen_status === "flagged" && <Chip tone="warn">quarantined</Chip>}
                  </span>
                </div>
                {!it.expired_at && (
                  <IconButton label="Forget" className="opacity-0 group-hover:opacity-100 focus:opacity-100 h-7 w-7 min-w-7 hover:text-danger"
                              onClick={() => forgetRow(it)}><IconX size={14} /></IconButton>
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
    if (r?.ok) { setMsg({ ok: true, text: "Queued — the graph updates in a few seconds." }); setText(""); setTimeout(() => onChanged?.(), 4000); }
    else setMsg({ ok: false, text: r?.error || "Couldn't store that." });
  }
  return (
    <section className={card}>
      <h2 className={`${sectionTitle} mb-1`}>Remember something</h2>
      <p className="text-sm text-fg-subtle mb-3">Extraction, entity resolution and contradiction handling run in the background on your selected model.</p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
                placeholder="e.g. My sister Priya works at Apollo Hospitals."
                className="w-full rounded-lg px-3 py-2 bg-surface-sunken border border-border outline-none focus:border-accent text-base text-fg placeholder:text-fg-subtle resize-y" />
      <div className="flex items-center justify-end mt-3 gap-2">
        {msg && <span className={`text-xs ${msg.ok ? "text-success" : "text-warning"}`}>{msg.text}</span>}
        <Button variant="primary" onClick={save} disabled={busy || !text.trim()}>{busy ? "Storing…" : "Remember"}</Button>
      </div>
    </section>
  );
}

// ── Improve — the consolidation op + last-run report card ────────────────────
const REPORT_LABELS = [
  ["sessions_summarized", "sessions summarized"], ["promoted", "facts promoted"],
  ["merged", "duplicates merged"], ["archived", "archived"], ["events_expired", "events expired"],
  ["insights", "new insights"], ["skill_drafts", "skills drafted"],
  ["skills_reinforced", "facts reinforced by skill use"], ["core_compacted", "core compacted"],
  ["quality_scored", "facts audited"], ["quality_junk", "low-value facts flagged"],
];

function reportLine(report) {
  const parts = REPORT_LABELS.filter(([k]) => (report?.[k] || 0) > 0).map(([k, label]) => `${report[k]} ${label}`);
  if (report?.memory_quality != null) parts.push(`${Math.round(report.memory_quality * 100)}% memory quality`);
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
      <h2 className={`${sectionTitle} mb-1`}>Improve memory</h2>
      <p className="text-sm text-fg-subtle mb-3">
        One sleep-time pass: summarize chats, promote missed facts, merge duplicates, let stale facts fade,
        reflect into insights. Runs on its own when idle — or now.
      </p>
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="primary" onClick={run} disabled={busy}>{busy ? "Improving…" : "Improve now"}</Button>
        {msg && <span className={`text-sm ${msg.ok ? "text-success" : "text-warning"}`}>{msg.text}</span>}
      </div>
      {last?.at && !msg && (
        <div className="mt-3 rounded-lg p-2.5 bg-surface-sunken text-sm text-fg-muted">
          Last improved {new Date(last.at).toLocaleString()}{last.reason && ` (${last.reason})`}: {reportLine(last)}.
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
        <h2 className={sectionTitle}>Environment</h2>
        <IconButton label="Re-probe this machine" disabled={busy} onClick={() => load(true)}><IconRefresh size={15} /></IconButton>
      </div>
      <p className="text-sm text-fg-subtle mb-3">The machine model in every prompt — so the agent never guesses paths.</p>
      {env && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
          <Row k="OS" v={env.os} /><Row k="User" v={env.user} /><Row k="Home" v={env.home} /><Row k="Shell" v={env.shell} />
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
      <span className="text-fg-subtle shrink-0 w-28">{k}</span>
      <span className="truncate text-fg" title={v}>{v || "—"}</span>
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
    if (!(await confirmAction?.("Forget ALL memory? Every fact, entity, relationship and core-memory entry is deleted. This can't be undone.", "Forget everything"))) return;
    setBusy(true); setMsg(null);
    const r = await memoryForget({ everything: true });
    setBusy(false);
    if (r?.ok) { setMsg({ ok: true, text: "Memory cleared." }); onChanged?.(); }
    else setMsg({ ok: false, text: r?.error || "Couldn't clear memory." });
  }
  return (
    <section className={card}>
      <h2 className={`${sectionTitle} mb-1`}>Forget</h2>
      <p className="text-sm text-fg-subtle mb-3">
        Matching facts are invalidated (kept in history as superseded). “Forget everything” really deletes it all.
      </p>
      <div className="flex gap-2 mb-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") forgetQuery(); }}
               placeholder="Forget everything about… (a topic, a person, a project)" className={field} />
        <Button variant="primary" onClick={forgetQuery} disabled={busy || !query.trim()}>Forget</Button>
      </div>
      <div className="flex items-center gap-3">
        <Button size="sm" variant="danger-outline" onClick={forgetAll} disabled={busy}>
          <IconTrash size={15} stroke={1.8} />{busy ? "Working…" : "Forget everything"}
        </Button>
        {msg && <span className={`text-sm ${msg.ok ? "text-success" : "text-warning"}`}>{msg.text}</span>}
      </div>
    </section>
  );
}
