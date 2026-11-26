// Phase 10 — pure graph helpers for the Memory page (no DOM; unit-tested).
//
// Colours: each canonical entity type owns one theme chart token (--chart-N,
// defined per theme in index.css for light and dark), so a type keeps its
// colour across reloads and the legend, canvas and tables agree. Unknown
// types hash onto the same palette; "concept" is the neutral (fg-subtle).

export const TYPE_TOKENS = {
  person: "chart-1",
  organization: "chart-2",
  place: "chart-3",
  event: "chart-4",
  project: "chart-5",
  technology: "chart-6",
  animal: "chart-7",
  product: "chart-8",
  concept: "fg-subtle",
};
export const TYPE_ORDER = Object.keys(TYPE_TOKENS);

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** The CSS variable name (without --) that colours an entity type. */
export function typeToken(type) {
  const t = (type || "concept").toLowerCase();
  return TYPE_TOKENS[t] || `chart-${(hash(t) % 8) + 1}`;
}

/** A CSS colour string usable in style={{}} — follows the active theme. */
export function typeColor(type, alpha = 1) {
  return alpha === 1 ? `rgb(var(--${typeToken(type)}))` : `rgb(var(--${typeToken(type)}) / ${alpha})`;
}

/** Legend entries: types present in the data, canonical order first. */
export function typeGroups(nodes) {
  const counts = {};
  for (const n of nodes) counts[n.type || "concept"] = (counts[n.type || "concept"] || 0) + 1;
  return Object.entries(counts)
    .map(([type, count]) => ({ type, count, token: typeToken(type) }))
    .sort((a, b) => {
      const ia = TYPE_ORDER.indexOf(a.type), ib = TYPE_ORDER.indexOf(b.type);
      if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      return b.count - a.count;
    });
}

/** Ids of a node and its 1-hop neighbours over live edges. */
export function neighbourhood(id, edges) {
  const out = new Set(id ? [id] : []);
  if (!id) return out;
  for (const e of edges) {
    if (e.expired) continue;
    if (e.source === id) out.add(e.target);
    if (e.target === id) out.add(e.source);
  }
  return out;
}

/** Nodes whose label or an alias contains the query (prefix matches first). */
export function searchNodes(nodes, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return [];
  const hits = [];
  for (const n of nodes) {
    const names = [n.label, ...(n.aliases || [])].map((s) => (s || "").toLowerCase());
    const i = names.findIndex((s) => s.includes(q));
    if (i < 0) continue;
    hits.push({ node: n, prefix: names.some((s) => s.startsWith(q)) ? 0 : 1, via: i > 0 ? n.aliases[i - 1] : null });
  }
  hits.sort((a, b) => a.prefix - b.prefix || (b.node.score || 0) - (a.node.score || 0));
  return hits.map((h) => ({ ...h.node, via: h.via }));
}

/** Curvature offset per edge id so parallel edges between one pair fan out
 *  instead of drawing on top of each other. 0 = straight. */
export function edgeCurvature(edges, step = 26) {
  const groups = {};
  for (const e of edges) {
    const k = e.source < e.target ? `${e.source}|${e.target}` : `${e.target}|${e.source}`;
    (groups[k] ||= []).push(e);
  }
  const out = {};
  for (const list of Object.values(groups)) {
    const n = list.length;
    list.forEach((e, i) => {
      let off = (i - (n - 1) / 2) * step;
      // Keep the sign relative to a fixed direction so A→B and B→A don't cancel.
      if (e.source > e.target) off = -off;
      out[e.id] = off || 0;   // never -0
    });
  }
  return out;
}

/** Node radius from its rank score (0..1) — self gets a floor. */
export function nodeRadius(node) {
  const s = Math.max(0, Math.min(1, node.score || 0));
  return (node.is_self ? 12 : 6) + s * 14;
}

// Deterministic PRNG so the same graph always lays out the same way.
function rng(seed) {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Force-directed layout (Fruchterman–Reingold with cooling), computed up
 * front so the graph appears settled and stable — no jittering simulation.
 * Highest-ranked nodes start near the centre (golden-angle spiral). Returns
 * { [id]: {x, y} } centred on the origin.
 */
export function layoutGraph(nodes, edges, { iterations, spacing = 90 } = {}) {
  const n = nodes.length;
  const pos = {};
  if (!n) return pos;
  const order = [...nodes].sort((a, b) => (b.is_self ? 1 : 0) - (a.is_self ? 1 : 0) || (b.score || 0) - (a.score || 0)
    || String(a.id).localeCompare(String(b.id)));
  const rand = rng(hash(order.map((x) => x.id).join(",")) || 1);
  const golden = Math.PI * (3 - Math.sqrt(5));
  order.forEach((node, i) => {
    const r = spacing * 0.6 * Math.sqrt(i + 0.5);
    pos[node.id] = { x: Math.cos(i * golden) * r + (rand() - 0.5), y: Math.sin(i * golden) * r + (rand() - 0.5) };
  });
  const ids = order.map((x) => x.id);
  const links = edges.filter((e) => !e.expired && pos[e.source] && pos[e.target] && e.source !== e.target);
  const k = spacing;
  const iters = iterations ?? (n > 250 ? 120 : 260);
  let temp = spacing * 1.5;
  const disp = {};
  for (let it = 0; it < iters; it++) {
    for (const id of ids) disp[id] = { x: 0, y: 0 };
    for (let i = 0; i < n; i++) {
      const a = pos[ids[i]];
      for (let j = i + 1; j < n; j++) {
        const b = pos[ids[j]];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) { dx = rand() - 0.5; dy = rand() - 0.5; d2 = 0.25; }
        const d = Math.sqrt(d2), f = (k * k) / d;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        disp[ids[i]].x += fx; disp[ids[i]].y += fy;
        disp[ids[j]].x -= fx; disp[ids[j]].y -= fy;
      }
    }
    for (const e of links) {
      const a = pos[e.source], b = pos[e.target];
      const dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d * d) / k;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      disp[e.source].x -= fx; disp[e.source].y -= fy;
      disp[e.target].x += fx; disp[e.target].y += fy;
    }
    for (const id of ids) {
      const p = pos[id], v = disp[id];
      // Gentle gravity keeps disconnected islands from drifting off; weaker
      // sideways so the picture is landscape, like the canvas it fills.
      v.x -= p.x * 0.011 * k / 10; v.y -= p.y * 0.024 * k / 10;
      const len = Math.sqrt(v.x * v.x + v.y * v.y) || 1;
      const step = Math.min(len, temp);
      p.x += (v.x / len) * step; p.y += (v.y / len) * step;
    }
    temp = Math.max(1, temp * 0.975);
  }
  let cx = 0, cy = 0;
  for (const id of ids) { cx += pos[id].x; cy += pos[id].y; }
  cx /= n; cy /= n;
  for (const id of ids) { pos[id].x -= cx; pos[id].y -= cy; }
  return pos;
}

/** Bounding box of positioned nodes (with radius padding). */
export function bounds(nodes, pos) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const n of nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const r = nodeRadius(n);
    x0 = Math.min(x0, p.x - r); x1 = Math.max(x1, p.x + r);
    y0 = Math.min(y0, p.y - r); y1 = Math.max(y1, p.y + r);
  }
  if (!Number.isFinite(x0)) return { x0: -1, y0: -1, x1: 1, y1: 1 };
  return { x0, y0, x1, y1 };
}

/** "3 days ago" style relative time for fact/rank chips. */
export function relTime(iso, now = Date.now()) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const d = Math.max(0, (now - t) / 86400000);
  if (d < 1 / 24) return "just now";
  if (d < 1) return `${Math.round(d * 24)} h ago`;
  if (d < 45) return `${Math.round(d)} d ago`;
  if (d < 365) return `${Math.round(d / 30)} mo ago`;
  return `${(d / 365).toFixed(1)} y ago`;
}

/** Human label for a canonical snake_case relation. */
export const relLabel = (rel) => (rel || "").replace(/_/g, " ");
