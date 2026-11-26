// Settings → StatusTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { fetchStatus } from "../../api.js";
import { agoIso, fmtTokens, Section } from "./shared.jsx";

export function StatusRow({ label, on, detail }) {
  return (
    <div className="rounded-xl border border-border px-3.5 py-2.5 flex items-center gap-3">
      <span className={`h-2 w-2 rounded-full shrink-0 ${on ? "bg-emerald-500" : "bg-border"}`} />
      <span className="text-base font-medium text-fg w-44 shrink-0">{label}</span>
      <span className="text-sm text-fg-muted truncate">{detail}</span>
    </div>
  );
}

export function StatusTab() {
  const [st, setSt] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => fetchStatus().then((r) => { if (live && r) setSt(r); });
    load();
    const t = setInterval(load, 5000);
    return () => { live = false; clearInterval(t); };
  }, []);

  if (!st) return <div className="text-sm text-fg-subtle">Loading…</div>;
  const mem = st.memory || {}, rout = st.routines || {}, bg = st.background_tasks || {};
  const cons = mem.last_consolidation;
  const usage = st.usage || {}; const total = usage.total || {};
  return (
    <>
      <Section title="Background activity"
               hint="Live view of everything running behind the scenes — refreshes every few seconds.">
        <StatusRow label="Memory writer" on={(mem.pending_writes || 0) > 0}
                   detail={mem.pending_writes ? `${mem.pending_writes} turn(s) queued for extraction` : "idle — all turns processed"} />
        <StatusRow label="Consolidator" on={!!mem.consolidator_running}
                   detail={(mem.consolidator_running ? "scheduled (idle + daily) · " : "scheduler off · ")
                           + (cons ? `last improved ${agoIso(cons.at)} (${cons.reason})` : "never run yet")} />
        <StatusRow label="Context compaction" on={(mem.compacting_sessions || 0) > 0}
                   detail={mem.compacting_sessions ? `summarizing ${mem.compacting_sessions} long chat(s)` : "idle"} />
        <StatusRow label="Vector recall" on={!!mem.embeddings}
                   detail={mem.embeddings ? "embeddings configured — semantic channel on" : "off — BM25 keyword recall only (configure memory.embeddings)"} />
        <StatusRow label="Routines" on={!!rout.runner_running}
                   detail={rout.total ? `${rout.enabled}/${rout.total} enabled · runner ${rout.runner_running ? "running" : "stopped"}` : "none created yet"} />
        <StatusRow label="Watchers" on={!!(st.watchers || {}).runner_running}
                   detail={(st.watchers || {}).total
                     ? `${st.watchers.enabled}/${st.watchers.total} enabled · runner ${st.watchers.runner_running ? "running" : "stopped"}`
                     : "none created yet"} />
        <StatusRow label="Background tasks" on={(bg.running || 0) > 0}
                   detail={bg.running ? `${bg.running} running` : (bg.items?.length ? `none running · ${bg.items.length} finished kept` : "none started")} />
        <StatusRow label="Self-review" on={!!st.self_review?.runner_running}
                   detail={(st.self_review?.enabled
                             ? `weekly runs on · runner ${st.self_review.runner_running ? "running" : "stopped"}`
                             : "weekly runs off (self_review.enabled)")
                           + (st.self_review?.last_snapshot ? ` · last snapshot ${st.self_review.last_snapshot}` : "")
                           + (st.self_review?.pending_proposals ? ` · ${st.self_review.pending_proposals} proposal(s) waiting` : "")} />
        <StatusRow label="Reminders" on={!!st.reminders?.running}
                   detail={st.reminders?.enabled ? (st.reminders.running ? "polling" : "enabled, thread stopped") : "off (scheduler.run_in_background)"} />
        <StatusRow label="Learning nudges" on={!!st.learning_nudger?.running}
                   detail={st.learning_nudger?.running ? "watching idle topics" : "off"} />
        <StatusRow label="Comms gateway" on={!!st.comms?.running}
                   detail={st.comms?.configured ? (st.comms.running ? "listening for messages" : "configured, stopped") : "no channels configured"} />
      </Section>

      <Section title="Token usage"
               hint="Summed from the per-turn stats under each reply (cache reads shown separately — they cost far less).">
        <div className="flex flex-wrap gap-2.5">
          {[["Total", total.tokens], ["Cached reads", total.cached], ["Turns", total.turns]].map(([label, v]) => (
            <div key={label} className="rounded-xl border border-border px-4 py-2.5 min-w-[110px]">
              <div className="text-xs text-fg-subtle">{label}</div>
              <div className="text-md font-semibold text-fg">{fmtTokens(v || 0)}</div>
            </div>
          ))}
        </div>
        {(usage.days || []).length > 0 && (
          <div className="rounded-xl border border-border overflow-hidden">
            {(usage.days || []).map((d) => (
              <div key={d.date} className="flex items-center justify-between px-3.5 py-1.5 text-sm odd:bg-surface-hover">
                <span className="text-fg-muted">{d.date}</span>
                <span className="text-fg">{fmtTokens(d.tokens)} tokens · {fmtTokens(d.cached)} cached · {d.turns} turns</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Every model call (last 7 days)"
               hint="Includes background work — memory writer, compaction, titles, summaries, watcher checks, sub-agents. Cache-read ratio = share of prompt tokens served from the provider's cache.">
        {(() => {
          const req = usage.requests || {}; const rt = req.total || {};
          if (!rt.calls) return <div className="text-sm text-fg-subtle">No calls logged yet.</div>;
          return (
            <>
              <div className="flex flex-wrap gap-2.5">
                {[["Calls", rt.calls], ["Fresh input", rt.input_tokens], ["Output", rt.output_tokens],
                  ["Cache reads", rt.cache_read_tokens]].map(([label, v]) => (
                  <div key={label} className="rounded-xl border border-border px-4 py-2.5 min-w-[110px]">
                    <div className="text-xs text-fg-subtle">{label}</div>
                    <div className="text-md font-semibold text-fg">{fmtTokens(v || 0)}</div>
                  </div>
                ))}
                <div className="rounded-xl border border-border px-4 py-2.5 min-w-[110px]">
                  <div className="text-xs text-fg-subtle">Cache-read ratio</div>
                  <div className="text-md font-semibold text-fg">{Math.round((rt.cache_read_ratio || 0) * 100)}%</div>
                </div>
              </div>
              <div className="rounded-xl border border-border overflow-hidden">
                {(req.kinds || []).map((k) => (
                  <div key={k.kind} className="flex items-center justify-between px-3.5 py-1.5 text-sm odd:bg-surface-hover">
                    <span className="text-fg-muted">{k.kind}</span>
                    <span className="text-fg">
                      {k.calls} calls · {fmtTokens(k.input_tokens)} in · {fmtTokens(k.output_tokens)} out · {fmtTokens(k.cache_read_tokens)} cached
                    </span>
                  </div>
                ))}
              </div>
            </>
          );
        })()}
      </Section>
    </>
  );
}
