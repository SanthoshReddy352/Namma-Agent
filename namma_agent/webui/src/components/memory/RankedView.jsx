import { EmptyState } from "../ui/Misc.jsx";
import { relTime, typeColor } from "./graphModel.js";

// Phase 10 — entities by importance (/api/memory/graph/ranked). The score is
// computed server-side from three documented signals and every one is shown,
// so the order is explainable rather than "most connected first":
//   score = 0.45·centrality + 0.30·salience + 0.25·recency

function Bar({ value, label, tone = "accent" }) {
  const pct = Math.round(Math.max(0, Math.min(1, value || 0)) * 100);
  return (
    <div className="flex items-center gap-1.5 min-w-0" title={`${label}: ${pct}%`}>
      <div className="h-1.5 flex-1 rounded-full bg-surface-sunken overflow-hidden" aria-hidden="true">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: `rgb(var(--${tone}))` }} />
      </div>
      <span className="text-2xs tabular-nums text-fg-subtle w-7 text-right">{pct}</span>
    </div>
  );
}

export default function RankedView({ data, loading, selectedId, onPick }) {
  if (!data) return <div className="p-6 text-sm text-fg-subtle">{loading ? "Ranking…" : ""}</div>;
  const items = data.items || [];
  if (!items.length) {
    return <EmptyState title="Nothing to rank yet">Entities appear here once memory has learned a few facts.</EmptyState>;
  }
  const w = data.weights || { centrality: 0.45, salience: 0.3, recency: 0.25 };
  return (
    <div className="p-4 sm:p-5" data-testid="ranked-view">
      <p className="text-sm text-fg-muted mb-3">
        Score = <b className="text-fg">{w.centrality}</b>×centrality (PageRank over the relations) +{" "}
        <b className="text-fg">{w.salience}</b>×salience (importance and how often it comes up) +{" "}
        <b className="text-fg">{w.recency}</b>×recency (half-life {data.half_life_days ?? 30} days).
      </p>
      <div className="rounded-lg border border-border bg-surface/70 overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="text-left text-2xs uppercase tracking-wider text-fg-subtle border-b border-border">
              <th className="px-3 py-2 font-medium w-10">#</th>
              <th className="px-3 py-2 font-medium">Entity</th>
              <th className="px-3 py-2 font-medium w-40">Score</th>
              <th className="px-3 py-2 font-medium w-28">Centrality</th>
              <th className="px-3 py-2 font-medium w-28">Salience</th>
              <th className="px-3 py-2 font-medium w-28">Recency</th>
              <th className="px-3 py-2 font-medium text-right w-24">Links · facts</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r, i) => (
              <tr key={r.id} onClick={() => onPick?.(r.id)}
                  className={`border-b border-border last:border-0 cursor-pointer hover:bg-surface-hover ${selectedId === r.id ? "bg-accent-wash" : ""}`}>
                <td className="px-3 py-2 tabular-nums text-fg-subtle">{i + 1}</td>
                <td className="px-3 py-2">
                  <button type="button" className="flex items-center gap-2 min-w-0 text-left" onClick={(e) => { e.stopPropagation(); onPick?.(r.id); }}>
                    <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: typeColor(r.type) }} />
                    <span className="font-medium text-fg truncate">{r.name}</span>
                    {r.is_self && <span className="text-2xs px-1.5 rounded-full bg-accent-wash text-accent">you</span>}
                  </button>
                  <div className="text-2xs text-fg-subtle pl-[18px]">
                    <span className="capitalize">{r.type}</span>{r.last_seen ? ` · seen ${relTime(r.last_seen)}` : ""}
                  </div>
                </td>
                <td className="px-3 py-2"><Bar value={r.score} label="Score" /></td>
                <td className="px-3 py-2"><Bar value={r.centrality} label="Centrality" tone="chart-1" /></td>
                <td className="px-3 py-2"><Bar value={r.salience} label="Salience" tone="chart-2" /></td>
                <td className="px-3 py-2"><Bar value={r.recency} label="Recency" tone="chart-3" /></td>
                <td className="px-3 py-2 text-right tabular-nums text-fg-muted">{r.degree} · {r.facts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
