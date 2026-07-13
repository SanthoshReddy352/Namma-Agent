import { useEffect, useMemo, useRef, useState } from "react";

// Cognee-inspired knowledge-graph views on a single <canvas> (no deps), mirroring
// the view types in Cognee's own visualizer (story/graph, schema, ranked layout):
//   • Graph  — force-directed "organic" layout (the classic Obsidian-style view)
//   • Schema — one node per entity TYPE, sized by instance count, with aggregated
//              relation-labelled edges (Cognee's schema view)
//   • Ranked — deterministic columns grouped by type, most-connected first
//              (Cognee's ranked layout — no physics, stable + readable)
// Interactions: hover-highlight neighbours, click → inspector panel, drag nodes,
// pan, wheel-zoom. Every panel setting persists across reloads via localStorage.

const PALETTE = [
  "#7cc4ff", "#c9a0ff", "#7ee787", "#ffa657", "#ff7b9c",
  "#79e0d8", "#f2cc60", "#a0b3ff", "#ff9bd2", "#9be37d",
];
function colorFor(type, cache) {
  if (!cache.map) { cache.map = {}; cache.i = 0; }
  if (!cache.map[type]) cache.map[type] = PALETTE[cache.i++ % PALETTE.length];
  return cache.map[type];
}

// slider (0..100) → physics value
const lin = (v, a, b) => a + (v / 100) * (b - a);

// ── Persistent view settings ─────────────────────────────────────────────────
const SETTINGS_KEY = "namma-memory-graph";
const DEFAULTS = {
  view: "graph",
  forces: { center: 40, repel: 55, link: 55, distance: 35 },
  showLabels: true, showEdgeLabels: true, hidden: {}, panel: true,
};
function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    return { ...DEFAULTS, ...s, forces: { ...DEFAULTS.forces, ...(s.forces || {}) },
             hidden: s.hidden || {} };
  } catch { return { ...DEFAULTS }; }
}

const VIEWS = [["graph", "Graph"], ["schema", "Schema"], ["ranked", "Ranked"]];

// Deterministic ranked layout: one column block per type (largest first), nodes
// sorted by degree, wrapping into sub-columns. Mutates node x/y and pins them.
function layoutRanked(ns, hiddenMap = {}) {
  const byType = {};
  for (const n of ns) {
    if (hiddenMap[n.type || "Entity"]) continue;
    (byType[n.type || "Entity"] ||= []).push(n);
  }
  const cols = Object.entries(byType).sort((a, b) => b[1].length - a[1].length);
  const subGap = 120, typeGap = 240, rowGap = 36, maxRows = 16;
  let x = 0;
  for (const [, arr] of cols) {
    arr.sort((a, b) => b.deg - a.deg);
    const sub = Math.ceil(arr.length / maxRows);
    arr.forEach((n, i) => {
      const c = Math.floor(i / maxRows), r = i % maxRows;
      const rows = Math.min(arr.length - c * maxRows, maxRows);
      n.x = x + c * subGap; n.y = (r - (rows - 1) / 2) * rowGap;
      n.vx = n.vy = 0; n.fixed = true;
    });
    x += (sub - 1) * subGap + typeGap;
  }
  const shift = Math.max(0, x - typeGap) / 2;
  for (const n of ns) { if (!hiddenMap[n.type || "Entity"]) n.x -= shift; }
}

export default function MemoryGraph({ nodes = [], edges = [], dark = true, height = 560 }) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const sim = useRef({ nodes: [], edges: [], cam: { x: 0, y: 0, k: 1 }, alpha: 1 });
  const size = useRef({ W: 0, H: 0 });
  const drag = useRef(null);
  const hover = useRef(null);
  const [hud, setHud] = useState(null);
  const [selected, setSelected] = useState(null);

  // Settings — restored from localStorage, saved on every change (the fix for
  // "graph settings reset on every visit").
  const saved = useMemo(loadSettings, []);
  const [view, setView] = useState(saved.view);
  const [panel, setPanel] = useState(saved.panel);
  const [forces, setForces] = useState(saved.forces);
  const [showLabels, setShowLabels] = useState(saved.showLabels);
  const [showEdgeLabels, setShowEdgeLabels] = useState(saved.showEdgeLabels);
  const [hidden, setHidden] = useState(saved.hidden);
  useEffect(() => {
    localStorage.setItem(SETTINGS_KEY,
      JSON.stringify({ view, forces, showLabels, showEdgeLabels, hidden, panel }));
  }, [view, forces, showLabels, showEdgeLabels, hidden, panel]);

  // Redraw-on-demand: the RAF loop skips painting when the physics is asleep and
  // nothing changed — an idle Memory tab must not burn CPU at 60fps.
  const redraw = useRef(true);
  useEffect(() => { redraw.current = true; },
    [selected, hidden, showLabels, showEdgeLabels, forces, view, nodes, edges, dark]);

  const forcesRef = useRef(forces); forcesRef.current = forces;
  const labelsRef = useRef(showLabels); labelsRef.current = showLabels;
  const edgeLabelsRef = useRef(showEdgeLabels); edgeLabelsRef.current = showEdgeLabels;
  const hiddenRef = useRef(hidden); hiddenRef.current = hidden;
  const viewRef = useRef(view); viewRef.current = view;
  const selRef = useRef(null); selRef.current = selected?.id ?? null;

  // Groups = distinct node types, each with a colour + visibility toggle.
  const groups = useMemo(() => {
    const cache = {}; const seen = {};
    for (const n of nodes) {
      const t = n.type || "Entity";
      if (!seen[t]) seen[t] = { type: t, color: n.color || colorFor(t, cache), count: 0 };
      seen[t].count++;
    }
    return Object.values(seen).sort((a, b) => b.count - a.count);
  }, [nodes]);

  // Schema aggregation — one node per type, edges rolled up between type pairs
  // with their dominant relation name (Cognee's schema-view contract).
  const schema = useMemo(() => {
    const cache = {}; const types = {}; const typeOf = {}; const agg = {};
    for (const n of nodes) {
      const t = n.type || "Entity";
      typeOf[n.id] = t;
      if (!types[t]) types[t] = { id: t, label: t, type: t, count: 0, color: n.color || colorFor(t, cache) };
      types[t].count++;
    }
    for (const e of edges) {
      const a = typeOf[e.source], b = typeOf[e.target];
      if (!a || !b || a === b) continue;                 // self-type loops add noise
      const k = `${a}→${b}`;
      if (!agg[k]) agg[k] = { source: a, target: b, count: 0, rels: {} };
      agg[k].count++;
      const r = (e.relation || "").trim();
      if (r) agg[k].rels[r] = (agg[k].rels[r] || 0) + 1;
    }
    const aggEdges = Object.values(agg).map((e) => {
      const top = Object.entries(e.rels).sort((x, y) => y[1] - x[1])[0];
      const others = Object.keys(e.rels).length - 1;
      return { ...e,
        rel: top ? (others > 0 ? `${top[0]} +${others}` : top[0]) : `${e.count} link${e.count > 1 ? "s" : ""}` };
    });
    return { nodes: Object.values(types), edges: aggEdges };
  }, [nodes, edges]);

  // Fit the camera to the visible nodes (used by the ⤢ button and after
  // switching to the deterministic Ranked view).
  const fitView = (hiddenMap = hiddenRef.current) => {
    const { W, H } = size.current; const S = sim.current;
    const vis = S.nodes.filter((n) => !hiddenMap[n.type || "Entity"]);
    if (!W || !vis.length) { S.cam = { x: 0, y: 0, k: 1 }; return; }
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (const n of vis) {
      x0 = Math.min(x0, n.x - n.r); x1 = Math.max(x1, n.x + n.r);
      y0 = Math.min(y0, n.y - n.r); y1 = Math.max(y1, n.y + n.r);
    }
    const bw = Math.max(80, x1 - x0), bh = Math.max(80, y1 - y0);
    const k = Math.min(2.2, Math.max(0.12, Math.min(W / (bw + 150), H / (bh + 150))));
    S.cam = { k, x: -(x0 + x1) / 2, y: -(y0 + y1) / 2 };
    redraw.current = true;
  };

  // (Re)build the simulation when the data OR the view type changes.
  useEffect(() => {
    const cache = {};
    let simNodes = [], simEdges = [];
    if (view === "schema") {
      const deg = {};
      schema.edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
      const R = 180;
      simNodes = schema.nodes.map((n, i) => {
        const a = (i / Math.max(1, schema.nodes.length)) * Math.PI * 2;
        return { ...n, x: Math.cos(a) * R, y: Math.sin(a) * R, vx: 0, vy: 0,
                 deg: deg[n.id] || 0, r: Math.min(38, 10 + Math.sqrt(n.count) * 3.4), fixed: false };
      });
      const byId = Object.fromEntries(simNodes.map((n) => [n.id, n]));
      simEdges = schema.edges.map((e) => ({ s: byId[e.source], t: byId[e.target], rel: e.rel, count: e.count }))
        .filter((e) => e.s && e.t);
    } else {
      const deg = {};
      edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
      const R = 260;
      simNodes = nodes.map((n, i) => {
        const a = (i / Math.max(1, nodes.length)) * Math.PI * 2;
        return {
          ...n, x: Math.cos(a) * R * (0.4 + Math.random() * 0.3), y: Math.sin(a) * R * (0.4 + Math.random() * 0.3),
          vx: 0, vy: 0, deg: deg[n.id] || 0, r: 4 + Math.sqrt(deg[n.id] || 0) * 2.6,
          col: n.color || colorFor(n.type || "Entity", cache), fixed: false,
        };
      });
      const byId = Object.fromEntries(simNodes.map((n) => [n.id, n]));
      simEdges = edges.map((e) => ({ s: byId[e.source], t: byId[e.target], rel: (e.relation || "").trim() }))
        .filter((e) => e.s && e.t);
      if (view === "ranked") layoutRanked(simNodes, hiddenRef.current);
    }
    for (const n of simNodes) if (!n.col) n.col = n.color || colorFor(n.type || "Entity", cache);
    sim.current.nodes = simNodes; sim.current.edges = simEdges;
    sim.current.alpha = view === "ranked" ? 0 : 1;
    setSelected(null);
    if (view === "ranked") fitView();
    else sim.current.cam = { x: 0, y: 0, k: 1 };
  }, [nodes, edges, view, schema]);

  useEffect(() => {
    const canvas = canvasRef.current, wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    let raf; const dpr = Math.max(1, window.devicePixelRatio || 1);
    const resize = () => {
      const r = wrap.getBoundingClientRect();
      size.current.W = r.width; size.current.H = r.height;
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      redraw.current = true;
    };
    resize(); const ro = new ResizeObserver(resize); ro.observe(wrap);

    const isHidden = (n) => !!hiddenRef.current[n.type || "Entity"];
    const toWorld = (sx, sy) => {
      const { cam } = sim.current; const { W, H } = size.current;
      return { x: (sx - W / 2) / cam.k - cam.x, y: (sy - H / 2) / cam.k - cam.y };
    };
    const nodeAt = (sx, sy) => {
      const w = toWorld(sx, sy); let best = null, bd = 1e9;
      for (const n of sim.current.nodes) {
        if (isHidden(n)) continue;
        const dx = n.x - w.x, dy = n.y - w.y, d = dx * dx + dy * dy, rr = (n.r + 6) ** 2;
        if (d < rr && d < bd) { bd = d; best = n; }
      } return best;
    };

    const step = () => {
      if (viewRef.current === "ranked") return;          // deterministic layout — no physics
      const S = sim.current, ns = S.nodes; if (S.alpha <= 0.004) return;
      const f = forcesRef.current, k = S.alpha;
      const gravity = lin(f.center, 0.0006, 0.006), repel = lin(f.repel, 300, 3200);
      const spring = lin(f.link, 0.004, 0.06), rest = lin(f.distance, 30, 240);
      for (let i = 0; i < ns.length; i++) {
        const a = ns[i]; if (isHidden(a)) continue;
        for (let j = i + 1; j < ns.length; j++) {
          const b = ns[j]; if (isHidden(b)) continue;
          let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 0.01;
          const force = (repel * k) / d2, d = Math.sqrt(d2), fx = (dx / d) * force, fy = (dy / d) * force;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        }
        a.vx += -a.x * gravity * k; a.vy += -a.y * gravity * k;
      }
      for (const e of S.edges) {
        if (isHidden(e.s) || isHidden(e.t)) continue;
        let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 0.01;
        const force = (d - rest) * spring * k, fx = (dx / d) * force, fy = (dy / d) * force;
        if (!e.s.fixed) { e.s.vx += fx; e.s.vy += fy; }
        if (!e.t.fixed) { e.t.vx -= fx; e.t.vy -= fy; }
      }
      for (const n of ns) { if (n.fixed) { n.vx = n.vy = 0; continue; } n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy; }
      S.alpha *= 0.993;
    };

    const draw = () => {
      const S = sim.current, { cam } = S; const { W, H } = size.current;
      const vw = viewRef.current;
      ctx.fillStyle = dark ? "#070a10" : "#fbfcfe"; ctx.fillRect(0, 0, W, H);
      ctx.save(); ctx.translate(W / 2, H / 2); ctx.scale(cam.k, cam.k); ctx.translate(cam.x, cam.y);
      const hv = hover.current; const sel = selRef.current; const neigh = new Set();
      const focus = hv || sel;
      if (focus) {
        neigh.add(focus);
        for (const e of S.edges) { if (e.s.id === focus) neigh.add(e.t.id); if (e.t.id === focus) neigh.add(e.s.id); }
      }
      // Edge label budget: always in Schema (few edges), otherwise only when
      // zoomed in or tracing a focused node — keeps big graphs readable.
      const wantEdgeLabels = edgeLabelsRef.current && (vw === "schema" || cam.k > 1.25 || !!focus);
      for (const e of S.edges) {
        if (isHidden(e.s) || isHidden(e.t)) continue;
        const on = !focus || (neigh.has(e.s.id) && neigh.has(e.t.id));
        ctx.strokeStyle = dark ? (on ? "rgba(148,163,184,0.45)" : "rgba(148,163,184,0.07)") : (on ? "rgba(100,116,139,0.4)" : "rgba(100,116,139,0.07)");
        ctx.lineWidth = vw === "schema" ? Math.min(4, 0.8 + Math.log2(1 + e.count) * 0.7) * (on ? 1 : 0.5) : (on ? 1 : 0.5);
        let mx = (e.s.x + e.t.x) / 2, my = (e.s.y + e.t.y) / 2;
        ctx.beginPath(); ctx.moveTo(e.s.x, e.s.y);
        if (vw === "ranked") {
          // Gentle curve so parallel column-to-column edges don't stack.
          const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 1;
          const off = Math.min(48, d * 0.14), nx = -dy / d, ny = dx / d;
          const cx = mx + nx * off, cy = my + ny * off;
          ctx.quadraticCurveTo(cx, cy, e.t.x, e.t.y);
          mx = (mx + cx) / 2; my = (my + cy) / 2;
        } else {
          ctx.lineTo(e.t.x, e.t.y);
        }
        ctx.stroke();
        // Direction arrow (schema view) — aggregated edges are directional.
        if (vw === "schema" && on) {
          const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.hypot(dx, dy) || 1;
          const ux = dx / d, uy = dy / d, tipx = e.t.x - ux * (e.t.r + 3), tipy = e.t.y - uy * (e.t.r + 3);
          ctx.fillStyle = ctx.strokeStyle;
          ctx.beginPath(); ctx.moveTo(tipx, tipy);
          ctx.lineTo(tipx - ux * 8 - uy * 3.5, tipy - uy * 8 + ux * 3.5);
          ctx.lineTo(tipx - ux * 8 + uy * 3.5, tipy - uy * 8 - ux * 3.5);
          ctx.closePath(); ctx.fill();
        }
        if (wantEdgeLabels && e.rel && (on || vw === "schema")) {
          ctx.globalAlpha = on ? 0.85 : 0.25;
          ctx.font = `${vw === "schema" ? 10.5 : 9.5}px ui-sans-serif, system-ui`;
          ctx.textAlign = "center"; ctx.textBaseline = "bottom";
          ctx.fillStyle = dark ? "#8fa3bd" : "#64748b";
          ctx.fillText(e.rel.slice(0, 28), mx, my - 2);
          ctx.globalAlpha = 1;
        }
      }
      for (const n of S.nodes) {
        if (isHidden(n)) continue;
        const on = !focus || neigh.has(n.id);
        ctx.globalAlpha = on ? 1 : 0.15;
        ctx.shadowColor = n.col; ctx.shadowBlur = (n.id === hv || n.id === sel) ? 24 : 9;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fillStyle = n.col; ctx.fill(); ctx.shadowBlur = 0;
        ctx.lineWidth = 1.4; ctx.strokeStyle = dark ? "#070a10" : "#ffffff"; ctx.stroke();
        if (n.id === sel) {                              // selection ring
          ctx.lineWidth = 2; ctx.strokeStyle = dark ? "#e2e8f0" : "#334155";
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 4, 0, Math.PI * 2); ctx.stroke();
        }
        const always = vw !== "graph";                    // schema/ranked labels always on
        if (labelsRef.current && (always || cam.k > 1.15 || n.id === hv || neigh.has(n.id) || n.deg >= 5)) {
          const label = (n.label || "").slice(0, 26);
          if (label) {
            ctx.globalAlpha = on ? 0.95 : 0.2;
            ctx.font = vw === "schema" ? "600 12px ui-sans-serif, system-ui" : "11px ui-sans-serif, system-ui";
            ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = dark ? "#c7d2e0" : "#334155";
            ctx.fillText(label, n.x, n.y + n.r + 3);
            if (vw === "schema") {
              ctx.globalAlpha = on ? 0.6 : 0.15; ctx.font = "10px ui-sans-serif, system-ui";
              ctx.fillText(`${n.count}`, n.x, n.y + n.r + 17);
            }
          }
        }
        ctx.globalAlpha = 1;
      }
      ctx.restore();
    };

    const loop = () => {
      step();
      if (sim.current.alpha > 0.004 || redraw.current) { draw(); redraw.current = false; }
      raf = requestAnimationFrame(loop);
    };
    loop();

    // Build the inspector payload for a clicked node from the live sim edges.
    const selectNode = (n) => {
      if (!n) { setSelected(null); return; }
      const links = [];
      for (const e of sim.current.edges) {
        if (e.s.id === n.id) links.push({ rel: e.rel || "", dir: "→", other: e.t.label, count: e.count });
        else if (e.t.id === n.id) links.push({ rel: e.rel || "", dir: "←", other: e.s.label, count: e.count });
      }
      setSelected({ id: n.id, label: n.label, type: n.type, count: n.count, deg: n.deg,
                    links: links.slice(0, 14), total: links.length });
    };

    const pos = (ev) => { const r = canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
    const onDown = (ev) => {
      redraw.current = true;
      const [sx, sy] = pos(ev); const n = nodeAt(sx, sy);
      if (n) {
        n.fixed = true;
        drag.current = { node: n, sx, sy, moved: false };
        if (viewRef.current !== "ranked") sim.current.alpha = Math.max(sim.current.alpha, 0.4);
      } else {
        const c = sim.current.cam;
        drag.current = { pan: true, sx, sy, cx: c.x, cy: c.y, moved: false };
      }
    };
    const onMove = (ev) => {
      redraw.current = true;
      const [sx, sy] = pos(ev); const d = drag.current;
      if (d && Math.hypot(sx - d.sx, sy - d.sy) > 4) d.moved = true;
      if (d?.node) {
        const w = toWorld(sx, sy); d.node.x = w.x; d.node.y = w.y;
        if (viewRef.current !== "ranked") sim.current.alpha = Math.max(sim.current.alpha, 0.3);
      } else if (d?.pan) {
        const { cam } = sim.current; cam.x = d.cx + (sx - d.sx) / cam.k; cam.y = d.cy + (sy - d.sy) / cam.k;
      } else {
        const n = nodeAt(sx, sy); hover.current = n ? n.id : null;
        setHud(n ? { label: n.label, type: n.type, count: n.count } : null);
        canvas.style.cursor = n ? "pointer" : "grab";
      }
    };
    const onUp = () => {
      redraw.current = true;
      const d = drag.current; drag.current = null;
      if (!d) return;
      if (d.node) {
        d.node.fixed = viewRef.current === "ranked";    // ranked keeps its pinned layout
        if (!d.moved) selectNode(d.node);               // plain click → inspect
      } else if (d.pan && !d.moved) {
        setSelected(null);                              // click empty space → clear
      }
    };
    const onWheel = (ev) => {
      ev.preventDefault(); redraw.current = true;
      const { cam } = sim.current; const [sx, sy] = pos(ev); const b = toWorld(sx, sy);
      cam.k = Math.min(4, Math.max(0.12, cam.k * (ev.deltaY < 0 ? 1.12 : 0.89))); const a = toWorld(sx, sy);
      cam.x += a.x - b.x; cam.y += a.y - b.y;
    };
    canvas.addEventListener("mousedown", onDown); window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp); canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); canvas.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [dark]);

  const reheat = () => { if (viewRef.current !== "ranked") sim.current.alpha = Math.max(sim.current.alpha, 0.5); redraw.current = true; };
  const setForce = (key, v) => { setForces((f) => ({ ...f, [key]: v })); reheat(); };
  const zoom = (f) => { sim.current.cam.k = Math.min(4, Math.max(0.12, sim.current.cam.k * f)); redraw.current = true; };
  const toggleType = (t) => {
    const nh = { ...hidden, [t]: !hidden[t] };
    setHidden(nh);
    if (view === "ranked") { layoutRanked(sim.current.nodes, nh); fitView(nh); }
    else reheat();
  };

  // Theme-aware overlay surfaces (controls / HUD / panel) — adapt to the app theme.
  const ovBtn = dark
    ? "bg-black/40 border-white/10 text-white/80 hover:text-white"
    : "bg-white/70 border-line text-ink-soft hover:text-ink";
  const ovBtnOn = dark
    ? "bg-white/20 border-white/20 text-white"
    : "bg-brand/10 border-brand/40 text-brand-deep";
  const ovPanel = dark ? "bg-black/55 border-white/10 text-white/85" : "bg-white/85 border-line text-ink shadow-soft";
  const ovSub = dark ? "text-white/50" : "text-ink-faint";
  const ovDim = dark ? "text-white/40" : "text-ink-faint";
  const ovDiv = dark ? "border-white/10" : "border-line";
  const ovHover = dark ? "hover:bg-white/10" : "hover:bg-paper-sink";
  const ovLbl = dark ? "text-white/70" : "text-ink-soft";

  return (
    <div ref={wrapRef} className="relative rounded-2xl overflow-hidden border border-line dark:border-night-line" style={{ height }}>
      <canvas ref={canvasRef} className="block w-full h-full" />

      {nodes.length === 0 && (
        <div className="absolute inset-0 grid place-items-center text-[13px] text-ink-faint dark:text-night-faint">
          No memories yet — add something below, then refresh.
        </div>
      )}

      {/* view switcher (top-left) — Cognee-style multiple visualization types */}
      <div className={`absolute top-3 left-3 flex rounded-lg backdrop-blur border overflow-hidden ${ovPanel}`}>
        {VIEWS.map(([id, label]) => (
          <button key={id} onClick={() => setView(id)}
                  className={`px-3 h-8 text-[12px] ${view === id ? ovBtnOn : `${ovHover} ${ovLbl}`}`}>
            {label}
          </button>
        ))}
      </div>

      {/* zoom controls (bottom-left) */}
      <div className="absolute bottom-3 left-3 flex gap-1.5">
        {[["+", () => zoom(1.2)], ["−", () => zoom(0.83)], ["⤢", () => fitView()]].map(([t, fn]) => (
          <button key={t} onClick={fn}
                  className={`h-8 w-8 grid place-items-center rounded-lg backdrop-blur border text-[15px] ${ovBtn}`}>{t}</button>
        ))}
      </div>

      {/* hovered-node HUD (bottom-center) */}
      {hud?.label && !selected && (
        <div className={`absolute bottom-3 left-1/2 -translate-x-1/2 max-w-[50%] rounded-lg backdrop-blur border px-3 py-1.5 ${ovPanel}`}>
          <div className="text-[13px] font-medium truncate">{hud.label}</div>
          <div className={`text-[11px] ${ovSub}`}>{hud.type}{hud.count != null ? ` · ${hud.count} instances` : ""}</div>
        </div>
      )}

      {/* inspector — click a node to trace its relations (Cognee-style) */}
      {selected && (
        <div className={`absolute bottom-3 left-1/2 -translate-x-1/2 w-[340px] max-w-[80%] max-h-[45%] overflow-y-auto rounded-xl backdrop-blur border p-3 ${ovPanel}`}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[13.5px] font-medium">{selected.label}</div>
              <div className={`text-[11px] ${ovSub}`}>
                {selected.type}{selected.count != null ? ` · ${selected.count} instances` : ""} · {selected.total} connection{selected.total === 1 ? "" : "s"}
              </div>
            </div>
            <button onClick={() => setSelected(null)} className={`text-[13px] leading-none px-1 ${ovDim} hover:opacity-80`}>✕</button>
          </div>
          {selected.links.length > 0 && (
            <ul className="mt-2 space-y-1">
              {selected.links.map((l, i) => (
                <li key={i} className="text-[12px] flex items-baseline gap-1.5">
                  <span className={ovDim}>{l.dir}</span>
                  {l.rel && <span className="text-brand-deep dark:text-brand">{l.rel}</span>}
                  <span className="truncate">{l.other}</span>
                  {l.count > 1 && <span className={ovDim}>×{l.count}</span>}
                </li>
              ))}
              {selected.total > selected.links.length && (
                <li className={`text-[11.5px] ${ovDim}`}>…and {selected.total - selected.links.length} more</li>
              )}
            </ul>
          )}
        </div>
      )}

      {/* panel toggle */}
      <button onClick={() => setPanel((p) => !p)} title="Controls"
              className={`absolute top-3 right-3 h-8 w-8 grid place-items-center rounded-lg backdrop-blur border ${ovBtn}`}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
      </button>

      {/* Obsidian-style control panel */}
      {panel && (
        <div className={`absolute top-3 right-12 w-56 max-h-[calc(100%-24px)] overflow-y-auto rounded-xl backdrop-blur border p-3 text-[12px] space-y-3 ${ovPanel}`}>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className={`uppercase tracking-wider text-[10.5px] ${ovSub}`}>Groups</span>
              <span className={`text-[10.5px] ${ovDim}`}>{groups.length}</span>
            </div>
            <div className="space-y-1">
              {groups.map((g) => (
                <button key={g.type} onClick={() => toggleType(g.type)}
                        className={`w-full flex items-center gap-2 px-1.5 py-1 rounded-md ${ovHover} ${hidden[g.type] ? "opacity-40" : ""}`}>
                  <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: g.color }} />
                  <span className="truncate flex-1 text-left">{g.type}</span>
                  <span className={ovDim}>{g.count}</span>
                </button>
              ))}
              {groups.length === 0 && <div className={`px-1.5 ${ovDim}`}>No groups yet</div>}
            </div>
          </div>

          <div className={`border-t pt-2 ${ovDiv}`}>
            <div className={`uppercase tracking-wider text-[10.5px] mb-1.5 ${ovSub}`}>Display</div>
            <label className="flex items-center gap-2 px-1.5 cursor-pointer">
              <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
              Node labels
            </label>
            <label className="flex items-center gap-2 px-1.5 mt-1 cursor-pointer">
              <input type="checkbox" checked={showEdgeLabels} onChange={(e) => setShowEdgeLabels(e.target.checked)} />
              Relation labels
            </label>
          </div>

          {view !== "ranked" && (
            <div className={`border-t pt-2 space-y-2.5 ${ovDiv}`}>
              <div className={`uppercase tracking-wider text-[10.5px] ${ovSub}`}>Forces</div>
              {[["Center force", "center"], ["Repel force", "repel"], ["Link force", "link"], ["Link distance", "distance"]].map(([label, key]) => (
                <div key={key}>
                  <div className={`mb-0.5 ${ovLbl}`}>{label}</div>
                  <input type="range" min="0" max="100" value={forces[key]}
                         onChange={(e) => setForce(key, +e.target.value)} className="w-full accent-brand" />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
