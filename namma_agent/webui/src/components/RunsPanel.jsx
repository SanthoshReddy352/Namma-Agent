import { useEffect, useState } from "react";
import { IconChevronDown, IconCircleCheck, IconCircleX, IconLoader2, IconMessages, IconPlayerStop, IconSitemap } from "@tabler/icons-react";
import { cancelRun } from "../api.js";

// Sub-agent runs for the current chat (delegate_task children, nested
// orchestrator children, background tasks). Fed live by `subagent` events.
// Each run opens to show what it was asked and what it is doing (Phase 9):
//   - Brief: the exact message the sub-agent received (goal + context);
//   - role, step budget, toolsets and skills;
//   - Steps: a live trail of its tool calls (argument preview + outcome);
//   - Result: its summary, or the error;
//   - Transcript: the sub-agent's own conversation, loaded on demand.
// Active runs can be cancelled (that cancels the whole subtree on the server).
const ACTIVE = new Set(["queued", "running"]);

const STATUS_TONE = {
  queued: "bg-border",
  running: "bg-accent animate-pulse",
  completed: "bg-success",
  partial: "bg-warning",
  failed: "bg-danger",
  cancelled: "bg-fg-subtle",
  interrupted: "bg-fg-subtle",
};

export function orderRuns(runs) {
  // Parents first, each followed by its children.
  const byParent = {};
  for (const r of runs) (byParent[r.parent_id || ""] ||= []).push(r);
  const out = [];
  const walk = (pid) => {
    for (const r of (byParent[pid] || []).sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""))) {
      out.push(r);
      walk(r.id);
    }
  };
  walk("");
  for (const r of runs) if (!out.includes(r)) out.push(r);   // orphans still show
  return out;
}

// The brief as sent; older runs (before the brief was stored) rebuild it.
export function runBrief(r) {
  const m = r.meta || {};
  if (m.prompt) return m.prompt;
  return `GOAL: ${r.goal || ""}${m.context ? `\n\nCONTEXT FROM THE MAIN AGENT:\n${m.context}` : ""}`;
}

export default function RunsPanel({ runs = [], docked = true }) {
  const [showAll, setShowAll] = useState(false);
  const [openId, setOpenId] = useState(null);
  if (!runs.length) return null;
  const active = runs.filter((r) => ACTIVE.has(r.status));
  const done = runs.length - active.length;
  const listed = docked ? (showAll ? runs : active) : runs;
  const shown = orderRuns(listed);

  return (
    <div className={docked ? "mb-2 rounded-2xl border border-border bg-surface-raised/85 backdrop-blur-md shadow-soft overflow-hidden" : ""}>
      <div className={`flex items-center justify-between gap-2 ${docked ? "px-3.5 py-2" : "pb-2"}`}>
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-fg-soft">
          <IconSitemap size={15} stroke={1.8} aria-hidden="true" />
          Sub-agents <span className="text-fg-subtle font-normal">· {active.length} active · {done} finished</span>
        </span>
        {docked && done > 0 && (
          <button type="button" onClick={() => setShowAll((o) => !o)} className="text-xs text-fg-subtle hover:text-fg">
            {showAll ? "Hide finished" : "Show all"}
          </button>
        )}
      </div>
      {shown.length > 0 && (
        <ul className={`${docked ? "max-h-[46vh] px-2 pb-2" : ""} overflow-y-auto space-y-1.5`}>
          {shown.map((r) => (
            <RunCard key={r.id} run={r} open={openId === r.id} onToggle={() => setOpenId((id) => (id === r.id ? null : r.id))} />
          ))}
        </ul>
      )}
    </div>
  );
}

function RunCard({ run: r, open, onToggle }) {
  const [busy, setBusy] = useState(false);
  const meta = r.meta || {};
  const trail = meta.trail || [];
  const live = ACTIVE.has(r.status);
  async function cancel(e) {
    e.stopPropagation();
    setBusy(true);
    await cancelRun(r.id);
    setBusy(false);
  }
  return (
    <li className={`rounded-xl border border-border bg-surface ${r.depth > 1 ? "ml-4" : ""}`} data-run={r.id}>
      <div className="flex items-start gap-2 px-3 py-2">
        <button type="button" onClick={onToggle} aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} details for ${r.name || r.goal}`}
                className="min-w-0 flex-1 flex items-start gap-2 text-left">
          <span className={`mt-[7px] h-2 w-2 rounded-full shrink-0 ${STATUS_TONE[r.status] || "bg-border"}`} aria-hidden="true" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium text-fg truncate" title={r.goal}>
              {r.kind === "background" ? "Background: " : ""}{r.name || r.goal}
            </span>
            <span className="block text-xs text-fg-subtle truncate">
              {r.status}
              {r.role === "orchestrator" ? " · orchestrator" : ""}
              {r.steps ? ` · ${r.steps}${meta.step_limit ? `/${meta.step_limit}` : ""} step${r.steps === 1 ? "" : "s"}` : ""}
              {r.current_tool ? ` · running ${r.current_tool}` : ""}
              {r.exit_reason && r.exit_reason !== "completed" && !live ? ` · ${r.exit_reason}` : ""}
            </span>
          </span>
          <IconChevronDown size={15} stroke={1.8} aria-hidden="true" className={`mt-1 shrink-0 text-fg-subtle transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        {live && (
          <button type="button" onClick={cancel} disabled={busy} aria-label={`Cancel sub-agent ${r.name || r.goal}`} title="Cancel"
                  className="shrink-0 grid place-items-center h-6 w-6 rounded-md text-fg-muted hover:text-danger hover:bg-surface-hover disabled:opacity-50">
            <IconPlayerStop size={14} stroke={1.8} aria-hidden="true" />
          </button>
        )}
      </div>
      {open && (
        <div className="border-t border-border px-3 py-2.5 space-y-3 text-sm">
          <Section label="Brief">
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-fg-soft bg-bg/60 rounded-md p-2 max-h-48 overflow-y-auto">{runBrief(r)}</pre>
          </Section>
          {((meta.toolsets || []).length > 0 || (meta.skills || []).length > 0) && (
            <div className="flex flex-wrap gap-1">
              {(meta.toolsets || []).map((t) => <Chip key={`t-${t}`}>{t}</Chip>)}
              {(meta.skills || []).map((s) => <Chip key={`s-${s}`} tone="accent">skill: {s}</Chip>)}
            </div>
          )}
          <Section label={`Steps${trail.length ? ` (${trail.length})` : ""}`}>
            {trail.length ? (
              <ol className="space-y-1">
                {trail.map((s, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs">
                    {s.status === "running" ? <IconLoader2 size={13} className="mt-0.5 shrink-0 text-accent animate-spin" aria-hidden="true" />
                      : s.status === "error" ? <IconCircleX size={13} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
                      : <IconCircleCheck size={13} className="mt-0.5 shrink-0 text-success" aria-hidden="true" />}
                    <span className="min-w-0">
                      <span className="font-mono text-fg">{s.tool}</span>
                      {s.args && s.args !== "{}" && <span className="text-fg-subtle"> {s.args}</span>}
                      {s.result && <span className="block text-fg-muted truncate" title={s.result}>→ {s.result}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (r.tools_used || []).length ? (
              <p className="text-xs text-fg-muted">Used: {(r.tools_used || []).join(", ")}</p>
            ) : <p className="text-xs text-fg-subtle">{live ? "Thinking…" : "No tool calls."}</p>}
          </Section>
          {(r.summary || r.error) && (
            <Section label={r.error ? "Error" : "Result"}>
              <p className={`whitespace-pre-wrap break-words text-xs ${r.error ? "text-danger" : "text-fg-soft"} max-h-48 overflow-y-auto`}>{r.error || r.summary}</p>
            </Section>
          )}
          {r.child_session_id && <Transcript sessionId={r.child_session_id} live={live} />}
        </div>
      )}
    </li>
  );
}

function Transcript({ sessionId, live }) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState(null);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const load = () => fetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
      .then((r) => (r.ok ? r.json() : null)).then((d) => alive && setTurns(d?.turns || [])).catch(() => alive && setTurns([]));
    load();
    const t = live ? setInterval(load, 3000) : null;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [open, sessionId, live]);
  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
              className="inline-flex items-center gap-1.5 text-xs text-accent hover:underline">
        <IconMessages size={13} stroke={1.8} aria-hidden="true" />{open ? "Hide transcript" : "Show the sub-agent's transcript"}
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 max-h-72 overflow-y-auto rounded-md bg-bg/60 p-2">
          {turns === null ? <p className="text-xs text-fg-subtle">Loading…</p>
            : turns.length === 0 ? <p className="text-xs text-fg-subtle">Nothing yet.</p>
            : turns.map((t, i) => (
              <div key={i} className="text-xs">
                <span className="font-semibold text-fg-muted uppercase tracking-wide text-2xs">{t.role}</span>
                <p className="whitespace-pre-wrap break-words text-fg-soft">{String(t.content || "").slice(0, 4000)}</p>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

const Section = ({ label, children }) => (
  <div>
    <div className="text-2xs font-semibold uppercase tracking-wider text-fg-subtle mb-1">{label}</div>
    {children}
  </div>
);
const Chip = ({ children, tone }) => (
  <span className={`text-2xs px-1.5 py-0.5 rounded-md border ${tone === "accent" ? "border-accent/40 text-accent" : "border-border text-fg-muted"}`}>{children}</span>
);
