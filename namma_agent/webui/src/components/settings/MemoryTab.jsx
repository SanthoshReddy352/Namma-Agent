// Settings → MemoryTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { fetchMemorySettings, memoryPending, resolveMemoryPending, saveMemorySettings } from "../../api.js";
import { Section, Field, Input, Toggle, _box, _btn } from "./shared.jsx";

// The single "Memory" settings section — Engram, the native memory engine
// (docs/MEMORY_SYSTEM_DESIGN.md). ONE source of truth: every knob reads/writes
// the LIVE engine via /api/memory/settings (persisted to user_config.yaml).
// There is no separate memory backend to configure — external memory MCP
// servers are ordinary plugins under Settings → MCP.
// Phase 7c — the write-approval queue. Only rendered while the toggle is on.
export function PendingFactsQueue({ onResolved }) {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState("");

  const load = () => memoryPending().then((r) => setItems(r?.items || []));
  useEffect(() => { load(); }, []);

  const resolve = async (opts, key) => {
    setBusy(key);
    await resolveMemoryPending(opts);
    setBusy("");
    await load();
    onResolved?.();
  };

  if (items === null) return <div className="text-sm text-fg-subtle">Loading…</div>;
  if (items.length === 0) {
    return (
      <div className="text-sm text-fg-muted">
        Nothing waiting. New inferred facts will show up here for review.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-fg-muted">
          {items.length} waiting
        </span>
        <button className={_btn + " ml-auto text-sm"} disabled={busy === "all-yes"}
                onClick={() => resolve({ all: true, approve: true }, "all-yes")}>
          Approve all
        </button>
        <button className={_btn + " text-sm"} disabled={busy === "all-no"}
                onClick={() => resolve({ all: true, approve: false }, "all-no")}>
          Reject all
        </button>
      </div>
      {items.map((it) => (
        <div key={it.id} className="rounded-xl border border-border px-3.5 py-2.5">
          <div className="text-sm text-fg">{it.text}</div>
          {it.replaces && (
            <div className="text-xs text-warning mt-1">
              Would replace: “{it.replaces}”
            </div>
          )}
          <div className="flex items-center gap-2 mt-2">
            <span className="text-xs text-fg-subtle">
              {it.kind} · {(it.source || "chat")} · {(it.created_at || "").replace("T", " ").slice(0, 16)}
            </span>
            <button className={_btn + " ml-auto text-sm"} disabled={busy === it.id}
                    onClick={() => resolve({ item_id: it.id, approve: true }, it.id)}>
              Keep
            </button>
            <button className={_btn + " text-sm"} disabled={busy === it.id}
                    onClick={() => resolve({ item_id: it.id, approve: false }, it.id)}>
              Discard
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export function MemorySettingsTab({ wipe, cleared }) {
  const [cfg, setCfg] = useState(null);
  const [msg, setMsg] = useState(null);
  const [draft, setDraft] = useState({});   // numeric fields being typed

  const load = () => fetchMemorySettings().then((r) => { if (r) { setCfg(r); setDraft({}); } });
  useEffect(() => { load(); }, []);

  async function apply(patch) {
    setMsg(null);
    const r = await saveMemorySettings(patch);
    if (r?.ok) { setCfg(r); setMsg({ ok: true, text: "Saved — applied live." }); }
    else setMsg({ ok: false, text: r?.error || "Couldn't save." });
  }

  const numField = (key, label, hint, min = 0) => (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <Input value={draft[key] ?? String(cfg[key])}
               onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))}
               onBlur={() => {
                 if (draft[key] == null || String(cfg[key]) === draft[key]) return;
                 const n = parseInt(draft[key], 10);
                 if (!Number.isNaN(n) && n >= min) apply({ [key]: n });
                 else setMsg({ ok: false, text: `${label}: enter a whole number of at least ${min}.` });
               }}
               onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
      </div>
      <div className="text-xs text-fg-subtle mt-1">{hint}</div>
    </Field>
  );

  if (!cfg) return <div className="text-fg-subtle">Loading…</div>;
  const st = cfg.status || {};

  return (
    <div className="space-y-6">
      <Section title="Memory engine"
               hint="Engram — native, in-process, always on. Facts live in your local database; all memory model work (extraction, contradiction handling) runs on the model you picked in Settings → Model.">
        <div className={`${_box} flex items-center gap-3 flex-wrap`}>
          <span className="h-2.5 w-2.5 rounded-full shrink-0 bg-emerald-500" />
          <span className="text-base font-medium">Active</span>
          <span className="text-xs text-fg-subtle">
            {st.items ?? 0} facts · {st.entities ?? 0} entities · {st.relations ?? 0} links
            {st.pending_writes > 0 && ` · ${st.pending_writes} writing…`}
          </span>
          <span className="ml-auto text-xs text-fg-subtle">
            core memory: user {st.core_user?.pct ?? 0}% · agent {st.core_agent?.pct ?? 0}%
          </span>
        </div>
        <div className="text-xs text-fg-subtle">
          Browse, edit, and visualize everything in the <b>Memory</b> tab of the sidebar.
        </div>
      </Section>

      <Section title="Learning & recall"
               hint="How memory grows from chat and flows back into every turn. Changes apply live.">
        <Toggle label="Recall prefetch — automatically inject relevant memories into each turn"
                checked={!!cfg.prefetch} onChange={(v) => apply({ prefetch: v })} />
        {numField("k", "Prefetched memories per turn",
                  "How many top-scoring memories ride along with each message (1–20).", 1)}
        {numField("salience_min_chars", "Salience threshold (characters)",
                  "Messages shorter than this are never considered for memory extraction.")}
        {numField("budget_per_hour", "Write budget (model calls / hour)",
                  "Hard cap on background memory-pipeline model calls, so learning can never run away with your quota.", 1)}
        {msg && <div className={`text-sm ${msg.ok ? "text-success" : "text-warning"}`}>{msg.text}</div>}
      </Section>

      <Section title="Review what I learn"
               hint="Off by default — the agent learns as you talk, which is the point. Turn it on and every fact it INFERRED on its own waits here for your yes/no; explicit “remember this” saves are never gated, since you already decided those.">
        <Toggle label="Hold inferred facts for my approval before they become memory"
                checked={!!cfg.write_approval}
                onChange={(v) => apply({ write_approval: v })} />
        {cfg.write_approval && <PendingFactsQueue onResolved={load} />}
        {!cfg.write_approval && cfg.pending_count > 0 && (
          <div className="text-sm text-warning">
            {cfg.pending_count} fact(s) are still waiting from when this was on — turn it
            back on to review them.
          </div>
        )}
      </Section>

      <Section title="Self-improvement"
               hint="Sleep-time consolidation: summarize finished chats, promote missed facts, merge duplicates, let stale facts fade, reflect into insights, compact core memory. The Memory tab's “Improve now” always works regardless.">
        <Toggle label="Consolidate in the background — when idle and once daily"
                checked={!!cfg.consolidate_background}
                onChange={(v) => apply({ consolidate_background: v })} />
        {numField("idle_minutes", "Idle trigger (minutes)",
                  "Run after this much inactivity (0 = never on idle; repeats at most every 6 hours).")}
        <Field label="Daily at (HH:MM)">
          <div className="flex items-center gap-2">
            <Input value={draft.daily_at ?? String(cfg.daily_at ?? "")}
                   onChange={(v) => setDraft((d) => ({ ...d, daily_at: v }))}
                   onBlur={() => {
                     if (draft.daily_at == null || String(cfg.daily_at ?? "") === draft.daily_at) return;
                     const t = draft.daily_at.trim();
                     if (t === "" || /^([01]?\d|2[0-3]):[0-5]\d$/.test(t)) apply({ daily_at: t });
                     else setMsg({ ok: false, text: "Daily time: use HH:MM (24-hour), or leave it empty." });
                   }}
                   onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                   placeholder="03:30 — empty disables the daily run" />
          </div>
          <div className="text-xs text-fg-subtle mt-1">
            Local wall-clock time for the nightly pass (fires only while the app is running).
          </div>
        </Field>
        {cfg.status?.last_consolidation?.at && (
          <div className="text-xs text-fg-subtle">
            Last run: {new Date(cfg.status.last_consolidation.at).toLocaleString()}
            {cfg.status.last_consolidation.reason && ` (${cfg.status.last_consolidation.reason})`}
          </div>
        )}
      </Section>

      <Section title="External memory plugins"
               hint="Optional extra backends (e.g. Mem0, Zep) attach as ordinary MCP servers — additive, never load-bearing. Native memory keeps working with or without them.">
        <div className="text-sm text-fg-muted">
          Add or enable a memory server under <b>Settings → MCP</b>; its tools appear to the
          model as <span className="font-mono text-xs">mcp_&lt;server&gt;_*</span>.
        </div>
      </Section>

      <Section title="Data"
               hint="Memory = facts, graph and core memory. Chats are the raw transcripts. Erasing cannot be undone.">
        <div className="flex flex-wrap gap-2">
          {[["memory", "Clear memory"], ["conversations", "Clear chats"], ["all", "Clear everything"]].map(([s, label]) => (
            <button key={s} onClick={() => wipe(s)}
                    className="px-3 py-1.5 rounded-lg border border-border hover:bg-accent-wash">{label}</button>
          ))}
        </div>
        {cleared && <div className="mt-2 text-brand-deep text-sm">Cleared {cleared}.</div>}
      </Section>
    </div>
  );
}
