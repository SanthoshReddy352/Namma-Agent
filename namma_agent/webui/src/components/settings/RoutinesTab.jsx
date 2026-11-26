// Settings → RoutinesTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { deleteRoutine, listRoutines, runRoutine, toggleRoutine } from "../../api.js";
import { get, agoTs, Section, Toggle } from "./shared.jsx";

// ── Routines: standing scheduled agent runs (created by asking the assistant) ──
export function scheduleLabel(s) {
  if (!s) return "?";
  if (s.kind === "interval") return `every ${s.every_minutes} min`;
  if (s.kind === "weekly") {
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    return `${days[s.weekday] ?? "?"} at ${s.at}`;
  }
  return `daily at ${s.at}`;
}
export function RoutinesTab() {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(0);        // id being run
  const [confirmId, setConfirmId] = useState(0);
  const [ranMsg, setRanMsg] = useState("");

  const load = () => listRoutines().then((r) => setItems(r?.routines || []));
  useEffect(() => { load(); }, []);

  const doToggle = async (it) => { await toggleRoutine(it.id, !it.enabled); load(); };
  const doDelete = async (id) => { setConfirmId(0); await deleteRoutine(id); load(); };
  const doRun = async (it) => {
    setBusy(it.id); setRanMsg("");
    const r = await runRoutine(it.id);
    setBusy(0);
    setRanMsg(r?.ok ? `“${it.name}” ran — result delivered to your channels.`
                    : `“${it.name}” failed to run.`);
    load();
  };

  return (
    <>
      <Section title="Routines"
               hint="Standing scheduled tasks: each run is a full agent task whose result is messaged to you (Telegram/Signal/… or a desktop notification). Create one by asking in chat — e.g. “every morning at 8, brief me on my calendar and the top AI news”.">
        {items === null && <div className="text-sm text-fg-subtle">Loading…</div>}
        {items?.length === 0 && (
          <div className="text-sm text-fg-muted">
            No routines yet. Ask the assistant to create one — it handles the schedule for you.
          </div>
        )}
        {(items || []).map((it) => (
          <div key={it.id}
               className="rounded-xl border border-border px-3.5 py-2.5 flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-base font-medium text-fg truncate">{it.name}</span>
                <span className="text-xs rounded-full border border-border px-2 py-0.5 text-fg-subtle shrink-0">{scheduleLabel(it.schedule)}</span>
              </div>
              <div className="text-xs text-fg-subtle truncate">
                {it.prompt} · last run {agoTs(it.last_run_ts)}
              </div>
            </div>
            <button onClick={() => doRun(it)} disabled={busy === it.id}
                    className="shrink-0 px-2.5 py-1 rounded-lg border border-border text-sm hover:border-brand/60 disabled:opacity-50">
              {busy === it.id ? "Running…" : "Run now"}
            </button>
            {confirmId === it.id ? (
              <button onClick={() => doDelete(it.id)}
                      className="shrink-0 px-2.5 py-1 rounded-lg text-sm text-white bg-danger">
                Sure?
              </button>
            ) : (
              <button onClick={() => setConfirmId(it.id)}
                      className="shrink-0 px-2.5 py-1 rounded-lg border border-danger/40 text-danger text-sm hover:bg-danger/10">
                Delete
              </button>
            )}
            <Toggle label="" checked={!!it.enabled} onChange={() => doToggle(it)} />
          </div>
        ))}
        {ranMsg && <div className="text-sm text-fg-muted">{ranMsg}</div>}
      </Section>
      <Section title="How results reach you"
               hint="Runs deliver over your configured messaging channels (Settings → Messaging); with none configured, you get a desktop notification. Destructive tools are always declined during scheduled runs." />
    </>
  );
}
