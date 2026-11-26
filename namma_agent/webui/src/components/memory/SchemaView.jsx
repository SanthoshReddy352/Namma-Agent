import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyState } from "../ui/Misc.jsx";
import { relLabel, typeColor, typeGroups } from "./graphModel.js";

// Phase 10 — the schema DERIVED from what memory actually holds
// (/api/memory/graph/schema): entity types with counts, the attributes seen on
// them and examples; relation types with the (source type → target type) pairs
// they really connect. The diagram is SVG so it themes through tokens.

function TypeDot({ type, size = 10 }) {
  return <span className="inline-block rounded-full shrink-0" style={{ width: size, height: size, background: typeColor(type) }} />;
}

export function TypeChip({ type }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 h-5 text-2xs text-fg-muted capitalize whitespace-nowrap">
      <TypeDot type={type} size={7} />{type}
    </span>
  );
}

// type → type aggregate edges for the diagram
function aggregate(relations) {
  const pairs = {};
  for (const r of relations) {
    for (const p of r.pairs || []) {
      const k = `${p.source}→${p.target}`;
      (pairs[k] ||= { source: p.source, target: p.target, count: 0, rels: [] });
      pairs[k].count += p.count;
      pairs[k].rels.push(relLabel(r.rel));
    }
  }
  return Object.values(pairs);
}

function SchemaDiagram({ types, relations }) {
  // Drawn at the container's real pixel width (1 unit = 1px) so text and
  // arrowheads keep their size on any screen.
  const ref = useRef(null);
  const [W, setW] = useState(720);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => setW(Math.max(420, Math.round(el.getBoundingClientRect().width) || 720));
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);
  const H = 400, cx = W / 2, cy = H / 2 + 8;
  const RY = H / 2 - 72, RX = Math.min(W / 2 - 120, RY * 1.9);
  const placed = useMemo(() => {
    const out = {};
    types.forEach((t, i) => {
      const a = -Math.PI / 2 + (i / Math.max(1, types.length)) * Math.PI * 2;
      out[t.type] = { x: types.length === 1 ? cx : cx + Math.cos(a) * RX,
                      y: types.length === 1 ? cy : cy + Math.sin(a) * RY,
                      r: 14 + Math.sqrt(t.count) * 5 };
    });
    return out;
  }, [types, W]); // eslint-disable-line react-hooks/exhaustive-deps
  const links = useMemo(() => aggregate(relations), [relations]);
  return (
    <div ref={ref} className="w-full">
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block max-w-full" role="img"
         aria-label={`Schema diagram: ${types.length} entity types, ${links.length} type-to-type links`}>
      <defs>
        <marker id="schema-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" style={{ fill: "rgb(var(--canvas-edge) / 0.7)" }} />
        </marker>
      </defs>
      {links.map((l) => {
        const a = placed[l.source], b = placed[l.target];
        if (!a || !b) return null;
        const label = l.rels.length > 2 ? `${l.rels.slice(0, 2).join(", ")} +${l.rels.length - 2}` : l.rels.join(", ");
        const sw = Math.min(3, 1 + Math.log2(1 + l.count) * 0.6);
        if (l.source === l.target) {
          // self-type relations (person → person) as a loop outside the circle
          const ang = Math.atan2(a.y - cy, a.x - cx) || -Math.PI / 2;
          const ux = Math.cos(ang), uy = Math.sin(ang), d = a.r + 26;
          const px = a.x + ux * d, py = a.y + uy * d;
          return (
            <g key={`${l.source}-${l.target}`}>
              <path d={`M ${a.x + ux * a.r - uy * 8} ${a.y + uy * a.r + ux * 8} Q ${px - uy * 28} ${py + ux * 28} ${px} ${py} Q ${px + uy * 28} ${py - ux * 28} ${a.x + ux * a.r + uy * 8} ${a.y + uy * a.r - ux * 8}`}
                    fill="none" strokeWidth={sw} markerEnd="url(#schema-arrow)" style={{ stroke: "rgb(var(--canvas-edge) / 0.55)" }} />
              <text x={Math.min(W - 60, Math.max(60, px + ux * 16))} y={Math.min(H - 8, Math.max(12, py + uy * 16))}
                    textAnchor="middle" dominantBaseline="middle" className="text-2xs"
                    style={{ fill: "rgb(var(--fg-muted))", paintOrder: "stroke", stroke: "rgb(var(--surface))", strokeWidth: 3 }}>{label}</text>
            </g>
          );
        }
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, ux = dx / d, uy = dy / d;
        const x1 = a.x + ux * (a.r + 2), y1 = a.y + uy * (a.r + 2), x2 = b.x - ux * (b.r + 4), y2 = b.y - uy * (b.r + 4);
        const reverse = links.some((o) => o.source === l.target && o.target === l.source);
        const bend = reverse ? 22 : 0;
        const mx = (x1 + x2) / 2 - uy * bend, my = (y1 + y2) / 2 + ux * bend;
        return (
          <g key={`${l.source}-${l.target}`}>
            <path d={`M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`} fill="none" strokeWidth={sw} markerEnd="url(#schema-arrow)"
                  style={{ stroke: "rgb(var(--canvas-edge) / 0.55)" }} />
            <text x={mx} y={my - 6} textAnchor="middle" className="text-2xs" style={{ fill: "rgb(var(--fg-muted))", paintOrder: "stroke", stroke: "rgb(var(--surface))", strokeWidth: 3 }}>
              {label}
            </text>
          </g>
        );
      })}
      {types.map((t) => {
        const p = placed[t.type];
        return (
          <g key={t.type}>
            <circle cx={p.x} cy={p.y} r={p.r} style={{ fill: typeColor(t.type), stroke: "rgb(var(--surface))", strokeWidth: 2 }} />
            <text x={p.x} y={p.y + 1} textAnchor="middle" dominantBaseline="middle" className="text-xs font-semibold" style={{ fill: "rgb(var(--surface))" }}>{t.count}</text>
            <text x={p.x} y={p.y + p.r + 13} textAnchor="middle" className="text-xs font-medium capitalize" style={{ fill: "rgb(var(--fg))", paintOrder: "stroke", stroke: "rgb(var(--surface))", strokeWidth: 3 }}>{t.type}</text>
          </g>
        );
      })}
    </svg>
    </div>
  );
}

export default function SchemaView({ schema, loading }) {
  if (!schema) {
    return <div className="p-6 text-sm text-fg-subtle">{loading ? "Reading the schema…" : ""}</div>;
  }
  const types = schema.types || [];
  const relations = schema.relations || [];
  if (!types.length) {
    return (
      <EmptyState title="No schema yet">
        The schema is derived from the entities and relations memory has learned — chat a little
        or use “Remember something”, and it appears here.
      </EmptyState>
    );
  }
  const order = typeGroups(types.flatMap((t) => Array(t.count).fill({ type: t.type }))).map((g) => g.type);
  const sortedTypes = [...types].sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type));
  return (
    <div className="p-4 sm:p-5 space-y-5" data-testid="schema-view">
      <div className="text-sm text-fg-muted">
        {schema.counts?.entities ?? 0} entities of <b className="text-fg">{types.length}</b> types, joined by{" "}
        {schema.counts?.edges ?? 0} relations of <b className="text-fg">{relations.length}</b> kinds — derived from
        what memory actually holds, not a fixed template.
      </div>
      <div className="rounded-xl border border-border bg-surface/60 p-2">
        <SchemaDiagram types={sortedTypes} relations={relations} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <section className="lg:col-span-2">
          <h3 className="text-xs uppercase tracking-wider text-fg-subtle mb-2">Entity types</h3>
          <ul className="space-y-2">
            {sortedTypes.map((t) => (
              <li key={t.type} className="rounded-lg border border-border bg-surface/70 px-3 py-2">
                <div className="flex items-center gap-2">
                  <TypeDot type={t.type} />
                  <span className="text-base font-medium capitalize text-fg">{t.type}</span>
                  <span className="ml-auto text-sm text-fg-subtle">{t.count}</span>
                </div>
                {t.examples?.length > 0 && (
                  <div className="mt-0.5 text-sm text-fg-muted truncate" title={t.examples.join(", ")}>{t.examples.join(" · ")}</div>
                )}
                {t.attributes?.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {t.attributes.map((a) => (
                      <span key={a} className="text-2xs px-1.5 h-5 inline-flex items-center rounded bg-surface-sunken text-fg-muted">{relLabel(a)}</span>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
        <section className="lg:col-span-3">
          <h3 className="text-xs uppercase tracking-wider text-fg-subtle mb-2">Relation types</h3>
          <div className="rounded-lg border border-border bg-surface/70 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-2xs uppercase tracking-wider text-fg-subtle border-b border-border">
                  <th className="px-3 py-2 font-medium">Relation</th>
                  <th className="px-3 py-2 font-medium">Connects</th>
                  <th className="px-3 py-2 font-medium text-right">Count</th>
                </tr>
              </thead>
              <tbody>
                {relations.map((r) => (
                  <tr key={r.rel} className="border-b border-border last:border-0 align-top">
                    <td className="px-3 py-2">
                      <div className="font-medium text-fg">{r.label || relLabel(r.rel)}</div>
                      <div className="flex gap-1 mt-0.5">
                        {r.symmetric && <span className="text-2xs text-fg-subtle" title="Same in both directions">↔ mutual</span>}
                        {r.functional && <span className="text-2xs text-fg-subtle" title="One current value — a new one supersedes the old">one at a time</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-col gap-1">
                        {(r.pairs || []).map((p) => (
                          <div key={`${p.source}-${p.target}`} className="flex items-center gap-1.5 flex-wrap">
                            <TypeChip type={p.source} />
                            <span className="text-fg-subtle" aria-label={r.symmetric ? "with" : "to"}>{r.symmetric ? "↔" : "→"}</span>
                            <TypeChip type={p.target} />
                            {(r.pairs || []).length > 1 && <span className="text-2xs text-fg-subtle">×{p.count}</span>}
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-fg-muted">{r.count}</td>
                  </tr>
                ))}
                {!relations.length && (
                  <tr><td colSpan={3} className="px-3 py-4 text-fg-subtle">No relations yet — only attributes.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
