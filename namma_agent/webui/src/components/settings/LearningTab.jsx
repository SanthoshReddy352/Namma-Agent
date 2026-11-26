// Settings → LearningTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { fetchLearningSettings, saveLearningSettings, fetchSelfReview, resolveProposal, runSelfReview } from "../../api.js";
import { get, pctFmt, StatCard, Section, Field, Input, Select, Toggle } from "./shared.jsx";

// Mon=0 … Sun=6 — the same convention as the routines scheduler.
export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function LearningTab() {
  const [data, setData] = useState(null);
  const [cfg, setCfg] = useState(null);        // {self_review:{…}, learning:{…}}
  const [draft, setDraft] = useState({});      // unsaved text/number edits
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = () => fetchSelfReview().then((r) => { if (r) setData(r); });
  const loadCfg = () => fetchLearningSettings().then((r) => {
    if (r) { setCfg({ self_review: r.self_review, learning: r.learning }); setDraft({}); }
  });
  useEffect(() => { load(); loadCfg(); }, []);

  // Every knob writes user_config.yaml and applies live — the runners start and
  // stop with the toggle, so nothing here needs a restart (or a hand-edited file).
  const save = async (settings) => {
    const r = await saveLearningSettings(settings);
    if (r?.ok) {
      setCfg({ self_review: r.self_review, learning: r.learning });
      setDraft({});
      setErr("");
    } else {
      setErr(r?.error || "Couldn't save that setting.");
    }
  };

  const doRun = async () => {
    setBusy(true); setMsg("");
    const r = await runSelfReview();
    setBusy(false);
    setMsg(r?.ok ? "Review complete." : "Review failed — check the server log.");
    load();
  };
  const doResolve = async (p, action) => {
    const r = await resolveProposal(p.id, action);
    setMsg(r?.ok ? (action === "accept" ? `Accepted — ${r.detail || "applied"}.` : "Rejected.")
                 : `Couldn't ${action}: ${r?.detail || "unknown error"}`);
    load();
  };

  if (!data || !cfg) return <div className="text-sm text-fg-subtle">Loading…</div>;
  const snaps = data.snapshots || [];
  const cur = snaps[snaps.length - 1] || {};
  const prev = snaps[snaps.length - 2] || {};
  const pending = (data.proposals || []).filter((p) => p.status === "pending");
  const resolved = (data.proposals || []).filter((p) => p.status !== "pending");
  const sr = cfg.self_review || {};
  const room = cfg.learning || {};
  const atDraft = draft.at ?? sr.at ?? "18:00";
  const daysDraft = draft.nudge_after_days ?? String(room.nudge_after_days ?? 3);

  return (
    <>
      <Section title="Weekly self-review"
               hint="Once a week Namma Agent mines its own sessions (tool failures, corrections you made, repeated workflows), measures memory recall offline, and writes you a report with proposals. Changes apply live — no restart.">
        <Toggle label="Run the review every week and deliver the report"
                checked={!!sr.enabled}
                onChange={(v) => save({ self_review: { enabled: v } })} />
        <Field label="Day">
          <Select value={WEEKDAYS[sr.weekday ?? 6]}
                  onChange={(v) => save({ self_review: { weekday: WEEKDAYS.indexOf(v) } })}
                  options={WEEKDAYS} />
        </Field>
        <Field label="Time (HH:MM)">
          <div className="flex items-center gap-2">
            <Input value={atDraft}
                   onChange={(v) => setDraft((d) => ({ ...d, at: v }))}
                   onBlur={() => { if (draft.at != null && draft.at.trim() !== (sr.at ?? "")) save({ self_review: { at: draft.at.trim() } }); }}
                   onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                   placeholder="18:00" />
          </div>
        </Field>
        <div className="text-xs text-fg-subtle">
          {sr.enabled
            ? `Weekly runs on — next ${WEEKDAYS[sr.weekday ?? 6]} at ${sr.at || "18:00"} (${sr.runner_running ? "runner active" : "runner idle; fires while the app is running"}).`
            : "Weekly runs are off. The manual run below always works — turn this on once you like what it produces."}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={doRun} disabled={busy}
                  className="px-3 py-1.5 rounded-lg border border-border text-sm hover:border-brand/60 disabled:opacity-50">
            {busy ? "Reviewing…" : "Run review now"}
          </button>
          <span className="text-xs text-fg-subtle">
            One pass over the last 7 days — costs a single model call.
          </span>
        </div>
        {err && <div className="text-sm text-warning">{err}</div>}
      </Section>

      <Section title="Learning Room"
               hint="How the teacher agent follows up outside the chat: a ping when you finish a module, and a spaced-practice nudge when a topic goes cold.">
        <Toggle label="Tell me over messaging when I complete a module"
                checked={!!room.notify_progress}
                onChange={(v) => save({ learning: { notify_progress: v } })} />
        <Field label="Nudge me about idle topics after (days)">
          <div className="flex items-center gap-2">
            <Input type="number" min="0" value={daysDraft}
                   onChange={(v) => setDraft((d) => ({ ...d, nudge_after_days: v }))}
                   onBlur={() => {
                     if (draft.nudge_after_days == null || draft.nudge_after_days === String(room.nudge_after_days ?? 3)) return;
                     const n = parseFloat(draft.nudge_after_days);
                     if (!Number.isNaN(n)) save({ learning: { nudge_after_days: n } });
                   }}
                   onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
          </div>
        </Field>
        <div className="text-xs text-fg-subtle">
          {(room.nudge_after_days ?? 0) <= 0
            ? "Nudges are off (0 days)."
            : !room.background_on
              ? "Set scheduler.run_in_background to let the nudge thread run — it's off, so nothing is polling."
              : !room.comms_ready
                ? "Add a messaging channel under Settings → Messaging — there's nowhere to send a nudge yet."
                : `Nudges ${room.nudger_running ? "are running" : "will start with the next check"} — a topic is reminded at most once per window.`}
        </div>
      </Section>

      <Section title="What I learned"
               hint="The latest report and the metric trend behind it. Nothing here is ever applied without your yes.">
        {msg && <div className="text-sm text-fg-muted">{msg}</div>}
        {snaps.length > 0 && (
          <div className="flex flex-wrap gap-2.5">
            <StatCard label={`Memory recall@${cur.k ?? "?"}`} value={cur.recall_at_k} prev={prev.recall_at_k} fmt={pctFmt} />
            <StatCard label="Facts remembered" value={cur.facts} prev={prev.facts} />
            <StatCard label="Skills" value={cur.skills} prev={prev.skills} />
            <StatCard label="Tool failure rate" value={cur.failure_rate} prev={prev.failure_rate} fmt={pctFmt} />
          </div>
        )}
        {data.report?.text ? (
          <pre className="text-sm leading-relaxed whitespace-pre-wrap font-sans rounded-xl border border-border px-4 py-3 text-fg-muted">
            {data.report.text}
          </pre>
        ) : (
          <div className="text-sm text-fg-muted">
            No review yet — run one to get your first “what I learned this week” report.
          </div>
        )}
      </Section>

      <Section title={`Proposals${pending.length ? ` (${pending.length} waiting)` : ""}`}
               hint="Drafts from the review: new skills, routines, or watchers backed by what actually happened. Accepting applies through the normal stores (routines/watchers arrive disabled); rejecting remembers the no.">
        {pending.length === 0 && (
          <div className="text-sm text-fg-muted">Nothing waiting for a decision.</div>
        )}
        {pending.map((p) => (
          <div key={p.id} className="rounded-xl border border-border px-3.5 py-2.5 flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs rounded-full border border-border px-2 py-0.5 text-fg-subtle shrink-0">{p.kind}</span>
                <span className="text-base font-medium text-fg truncate">{p.title}</span>
              </div>
              {p.why && <div className="text-xs text-fg-subtle">{p.why}</div>}
            </div>
            <button onClick={() => doResolve(p, "accept")}
                    className="shrink-0 px-2.5 py-1 rounded-lg border border-success/40 text-success text-sm">
              Accept
            </button>
            <button onClick={() => doResolve(p, "reject")}
                    className="shrink-0 px-2.5 py-1 rounded-lg border border-border text-sm text-fg-subtle">
              Reject
            </button>
          </div>
        ))}
        {resolved.length > 0 && (
          <div className="text-xs text-fg-subtle">
            {resolved.filter((p) => p.status === "accepted").length} accepted · {resolved.filter((p) => p.status === "rejected").length} rejected previously
          </div>
        )}
      </Section>
    </>
  );
}
