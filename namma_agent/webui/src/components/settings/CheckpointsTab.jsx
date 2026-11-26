// Settings → CheckpointsTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { deleteCheckpoint, listCheckpoints, restoreCheckpoint } from "../../api.js";
import { Section } from "./shared.jsx";

// Phase 7b — restore points. The approval gate asks BEFORE a destructive tool
// runs (and needs you to predict the consequence); this is the other half:
// undo a change you already said yes to.
export function CheckpointsTab() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");        // id being restored
  const [confirmId, setConfirmId] = useState("");
  const [report, setReport] = useState(null);

  const load = () => listCheckpoints().then(setData);
  useEffect(() => { load(); }, []);

  const doRestore = async (id) => {
    setConfirmId(""); setBusy(id); setReport(null);
    const r = await restoreCheckpoint(id);
    setBusy("");
    setReport(r);
    load();
  };
  const doDelete = async (id) => { await deleteCheckpoint(id); load(); };

  const items = data?.items || [];
  const status = data?.status || {};
  const fmtTime = (iso) => (iso || "").replace("T", " ").slice(0, 16);
  const fileName = (p) => (p || "").split(/[\\/]/).pop();

  return (
    <>
      <Section title="Restore points"
               hint="Before a tool changes files, the assistant snapshots them here. Restoring puts them back. You can also just say “undo that” in chat.">
        {data === null && <div className="text-sm text-fg-subtle">Loading…</div>}
        {items.length === 0 && data !== null && (
          <div className="text-sm text-fg-muted">
            Nothing to undo — no tool has changed files yet.
          </div>
        )}
        {report && (
          <div className={`rounded-xl border px-3.5 py-2.5 text-sm ${report.ok ? "border-emerald-500/40 text-success" : "border-amber-500/50 text-warning"}`}>
            {report.ok
              ? `Restored ${report.restored?.length || 0} path(s)${report.deleted?.length ? `, removed ${report.deleted.length} created path(s)` : ""}.`
              : `Partly restored. Could not put back: ${(report.failed || []).map((f) => `${fileName(f.path)} (${f.why})`).join("; ")}`}
          </div>
        )}
        {items.map((it) => (
          <div key={it.id}
               className="rounded-xl border border-border px-3.5 py-2.5 flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-base font-medium text-fg truncate">{it.tool}</span>
                <span className="text-xs rounded-full border border-border px-2 py-0.5 text-fg-subtle shrink-0">
                  {it.entries?.length || 0} path{(it.entries?.length || 0) === 1 ? "" : "s"}
                </span>
                {it.restored_at && (
                  <span className="text-xs rounded-full px-2 py-0.5 shrink-0 text-success border border-emerald-500/40">restored</span>
                )}
                {(it.entries || []).some((e) => e.truncated) && (
                  <span className="text-xs rounded-full px-2 py-0.5 shrink-0 text-warning border border-amber-500/40"
                        title="Something here was too large to copy — a restore can only do part of it.">partial</span>
                )}
              </div>
              <div className="text-xs text-fg-subtle truncate">
                {fmtTime(it.created_at)} · {(it.entries || []).map((e) => fileName(e.path)).slice(0, 4).join(", ")}
              </div>
            </div>
            {confirmId === it.id ? (
              <button onClick={() => doRestore(it.id)}
                      className="shrink-0 px-2.5 py-1 rounded-lg text-sm text-white bg-success">
                Restore?
              </button>
            ) : (
              <button onClick={() => setConfirmId(it.id)} disabled={busy === it.id}
                      className="shrink-0 px-2.5 py-1 rounded-lg border border-border text-sm hover:border-brand/60 disabled:opacity-50">
                {busy === it.id ? "Restoring…" : "Undo"}
              </button>
            )}
            <button onClick={() => doDelete(it.id)}
                    className="shrink-0 px-2.5 py-1 rounded-lg border border-danger/40 text-danger text-sm hover:bg-danger/10">
              Forget
            </button>
          </div>
        ))}
      </Section>

      <Section title="Storage"
               hint="Restore points are pruned automatically — oldest first — so they can't fill your disk.">
        <div className="rounded-xl border border-border px-3.5 py-2.5 text-sm text-fg-muted">
          {status.count || 0} restore point{status.count === 1 ? "" : "s"} · {status.total_mb || 0} MB
          of {status.max_total_mb || 0} MB · kept {status.max_age_days || 0} days
          {status.enabled === false && " · DISABLED in config"}
        </div>
        <div className="text-xs text-fg-subtle leading-relaxed">
          Shell commands are not covered: what an arbitrary command will touch can't be
          known from the command itself, and a half-promise of undo would be worse than none.
        </div>
      </Section>
    </>
  );
}
