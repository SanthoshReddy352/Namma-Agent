// Settings → WatchersTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { deleteWatcher, listWatchers, runWatcher, toggleWatcher } from "../../api.js";
import { get, agoTs, Section, Toggle } from "./shared.jsx";

// ── Watchers: event-driven triggers with a "does it matter" gate ──────────────
export function triggerLabel(t) {
  if (!t) return "?";
  if (t.type === "file") return `file · ${t.path}`;
  if (t.type === "email") return `email · ${t.query || "is:unread"}`;
  if (t.type === "web") return `web · ${t.url}`;
  if (t.type === "calendar") return `calendar · within ${t.within_minutes ?? 30} min`;
  return t.type || "?";
}

export function WatchersTab() {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(0);        // id being checked
  const [confirmId, setConfirmId] = useState(0);
  const [ranMsg, setRanMsg] = useState("");

  const load = () => listWatchers().then((r) => setItems(r?.watchers || []));
  useEffect(() => { load(); }, []);

  const doToggle = async (it) => { await toggleWatcher(it.id, !it.enabled); load(); };
  const doDelete = async (id) => { setConfirmId(0); await deleteWatcher(id); load(); };
  const doRun = async (it) => {
    setBusy(it.id); setRanMsg("");
    const r = await runWatcher(it.id);
    setBusy(0);
    setRanMsg(r?.ok ? `“${it.name}”: ${r.last_result || r.outcome || "checked"}`
                    : `“${it.name}” couldn't be checked (watchers disabled?).`);
    load();
  };

  return (
    <>
      <Section title="Watchers"
               hint="Event-driven triggers: when a file lands, an email arrives, a page changes, or an event nears, a cheap “does it matter?” model pass filters noise, then you get a message (or a follow-up task runs first). Create one by asking in chat — e.g. “tell me when an invoice PDF lands in my Downloads”.">
        {items === null && <div className="text-sm text-fg-subtle">Loading…</div>}
        {items?.length === 0 && (
          <div className="text-sm text-fg-muted">
            No watchers yet. Ask the assistant to watch something for you — it picks the trigger and cadence.
          </div>
        )}
        {(items || []).map((it) => (
          <div key={it.id}
               className="rounded-xl border border-border px-3.5 py-2.5 flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-base font-medium text-fg truncate">{it.name}</span>
                <span className="text-xs rounded-full border border-border px-2 py-0.5 text-fg-subtle shrink-0 max-w-[220px] truncate">{triggerLabel(it.trigger)}</span>
              </div>
              <div className="text-xs text-fg-subtle truncate">
                {it.intent} · checked {agoTs(it.last_check_ts)} · fired {agoTs(it.last_fired_ts)}
                {it.last_result ? ` · ${it.last_result}` : ""}
              </div>
            </div>
            <button onClick={() => doRun(it)} disabled={busy === it.id}
                    className="shrink-0 px-2.5 py-1 rounded-lg border border-border text-sm hover:border-brand/60 disabled:opacity-50">
              {busy === it.id ? "Checking…" : "Check now"}
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
      <Section title="How firing works"
               hint="Trigger checks are cheap polls with no model calls. Only when something actually changed does one model pass judge it against the watcher's intent — ignore / notify / act. Actions run with destructive tools always declined, and results deliver like routines (messaging channels, desktop fallback)." />
    </>
  );
}
