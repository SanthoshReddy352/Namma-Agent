import { useState } from "react";
import { cancelRun } from "../api.js";

// Sub-agent runs for the current chat (delegate_task children, nested
// orchestrator children, background tasks), docked above the message bar next
// to the todo panel. Fed live by `subagent` events; each active run can be
// cancelled (cancelling a run cancels its whole subtree on the server).
const ACTIVE = new Set(["queued", "running"]);

const STATUS_TONE = {
  queued: "bg-border",
  running: "bg-brand animate-pulse",
  completed: "bg-emerald-500",
  partial: "bg-amber-500",
  failed: "bg-red-500",
  cancelled: "bg-fg-subtle",
  interrupted: "bg-fg-subtle",
};

function order(runs) {
  // Parents first, each followed by its children (one level of nesting is shown
  // by depth; deeper runs are leaves by design).
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
  // Orphans (parent from an older page of history) still show.
  for (const r of runs) if (!out.includes(r)) out.push(r);
  return out;
}

export default function RunsPanel({ runs = [] }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState({});
  if (!runs.length) return null;
  const active = runs.filter((r) => ACTIVE.has(r.status));
  const done = runs.length - active.length;
  const expanded = open || active.length > 0;
  const shown = order(open ? runs : active);

  async function cancel(id) {
    setBusy((b) => ({ ...b, [id]: true }));
    await cancelRun(id);
    setBusy((b) => ({ ...b, [id]: false }));
  }

  return (
    <div className="mb-2 rounded-2xl border border-border bg-surface-raised shadow-soft overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={expanded}
              className="w-full flex items-center justify-between px-3.5 py-2 text-left hover:bg-surface-hover transition">
        <span className="text-sm font-medium text-fg-soft">
          Sub-agents ({active.length} active · {done} finished)
        </span>
        <span className="text-xs text-fg-subtle">{open ? "Hide finished" : "Show all"}</span>
      </button>
      {expanded && shown.length > 0 && (
        <ul className="max-h-[200px] overflow-y-auto px-3.5 pb-2.5 space-y-1.5">
          {shown.map((r) => (
            <li key={r.id} className={`flex items-start justify-between gap-3 ${r.depth > 1 ? "ml-5" : ""}`}>
              <div className="min-w-0 flex items-start gap-2">
                <span className={`mt-[6px] h-2 w-2 rounded-full shrink-0 ${STATUS_TONE[r.status] || "bg-line"}`} aria-hidden="true" />
                <div className="min-w-0">
                  <div className="text-sm text-fg truncate" title={r.goal}>
                    {r.kind === "background" ? "Background: " : ""}{r.name || r.goal}
                  </div>
                  <div className="text-xs text-fg-subtle">
                    {r.status}
                    {r.role === "orchestrator" ? " · orchestrator" : ""}
                    {r.current_tool ? ` · running ${r.current_tool}` : ""}
                    {r.steps ? ` · ${r.steps} step${r.steps === 1 ? "" : "s"}` : ""}
                    {r.exit_reason && r.exit_reason !== "completed" && !ACTIVE.has(r.status) ? ` · ${r.exit_reason}` : ""}
                  </div>
                </div>
              </div>
              {ACTIVE.has(r.status) && (
                <button type="button" onClick={() => cancel(r.id)} disabled={!!busy[r.id]}
                        aria-label={`Cancel sub-agent ${r.name || r.goal}`}
                        className="shrink-0 text-xs px-2 py-0.5 rounded-md border border-border text-fg-muted hover:text-red-600 hover:border-red-300 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
                  Cancel
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
