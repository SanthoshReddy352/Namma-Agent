import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconArrowsMinimize, IconFocusCentered, IconTag, IconTagOff, IconZoomIn, IconZoomOut,
} from "@tabler/icons-react";
import IconButton from "./ui/IconButton.jsx";
import {
  bounds, edgeCurvature, layoutGraph, neighbourhood, nodeRadius, relLabel, typeGroups, typeToken,
} from "./memory/graphModel.js";

// Phase 10 — the Memory knowledge graph on one <canvas> (no graph library).
//
// The layout is computed up front (graphModel.layoutGraph — deterministic
// force-directed) so the picture is stable: the same memory always draws the
// same way, and nothing jitters. Entities are coloured by TYPE with the
// theme's chart tokens; edges are typed (labelled), directed (arrowheads;
// symmetric relations have none) and fan out when two entities share several
// relations. Click a node to focus it (its neighbourhood stays lit, the rest
// dims) — the parent shows its facts. Drag nodes, drag the background to pan,
// wheel/buttons to zoom, Fit to frame everything.

const LABEL_ALL_ZOOM = 1.25;

// Canvas can't resolve var(); read the token from the canvas itself so a theme
// class on any ancestor applies.
function token(el, name, alpha = 1) {
  const v = el ? getComputedStyle(el).getPropertyValue(`--${name}`).trim() : "";
  if (!v) return alpha === 1 ? "rgb(128 128 128)" : `rgb(128 128 128 / ${alpha})`;
  return alpha === 1 ? `rgb(${v})` : `rgb(${v} / ${alpha})`;
}

export default function MemoryGraph({
  nodes = [], edges = [], selectedId = null, onSelect, query = "", matches = null,
  height = 560, themeKey = "",
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const cam = useRef({ x: 0, y: 0, k: 1 });
  const size = useRef({ W: 0, H: 0 });
  const drag = useRef(null);
  const hoverRef = useRef(null);
  const posOverride = useRef({});
  const [hover, setHover] = useState(null);
  const [hidden, setHidden] = useState({});
  const [labelsAll, setLabelsAll] = useState(false);
  const [tick, setTick] = useState(0);                 // bump → redraw
  const redraw = useCallback(() => setTick((t) => t + 1), []);

  const groups = useMemo(() => typeGroups(nodes), [nodes]);
  const visibleNodes = useMemo(() => nodes.filter((n) => !hidden[n.type || "concept"]), [nodes, hidden]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)), [edges, visibleIds]);

  // Layout depends on the graph's structure only (not on hover/selection).
  const layoutKey = useMemo(
    () => nodes.map((n) => n.id).join(",") + "|" + edges.map((e) => e.id || `${e.source}${e.rel}${e.target}`).join(","),
    [nodes, edges]);
  const basePos = useMemo(() => layoutGraph(nodes, edges), [layoutKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const pos = useMemo(() => { posOverride.current = {}; return basePos; }, [basePos]);
  const P = (id) => posOverride.current[id] || pos[id];

  const curv = useMemo(() => edgeCurvature(visibleEdges), [visibleEdges]);
  const focusId = selectedId || hover;
  const lit = useMemo(() => neighbourhood(focusId, visibleEdges), [focusId, visibleEdges]);
  const topLabels = useMemo(() => {
    const ranked = [...visibleNodes].sort((a, b) => (b.score || 0) - (a.score || 0));
    return new Set(ranked.slice(0, 14).map((n) => n.id));
  }, [visibleNodes]);
  const matchSet = useMemo(() => (matches && query ? new Set(matches.map((m) => m.id)) : null), [matches, query]);

  const fit = useCallback(() => {
    const { W, H } = size.current;
    if (!W || !visibleNodes.length) { cam.current = { x: 0, y: 0, k: 1 }; redraw(); return; }
    const merged = {};
    for (const n of visibleNodes) merged[n.id] = P(n.id);
    const b = bounds(visibleNodes, merged);
    const bw = Math.max(120, b.x1 - b.x0), bh = Math.max(120, b.y1 - b.y0);
    const k = Math.min(1.8, Math.max(0.2, Math.min((W - 80) / (bw + 120), (H - 80) / (bh + 80))));
    cam.current = { k, x: -(b.x0 + b.x1) / 2, y: -(b.y0 + b.y1) / 2 };
    redraw();
  }, [visibleNodes, pos, redraw]); // eslint-disable-line react-hooks/exhaustive-deps

  const fitRef = useRef(fit); fitRef.current = fit;
  // Re-frame whenever the graph (or the visible type set) changes.
  useEffect(() => { fit(); }, [layoutKey, hidden]); // eslint-disable-line react-hooks/exhaustive-deps

  // An entity focused from outside (search, Ranked, a relation link) comes into view.
  useEffect(() => {
    if (!selectedId) return;
    const p = P(selectedId);
    if (!p) return;
    const { W, H } = size.current;
    const c = cam.current;
    const sx = (p.x + c.x) * c.k + W / 2, sy = (p.y + c.y) * c.k + H / 2;
    if (sx < 60 || sx > W - 60 || sy < 60 || sy > H - 60) {
      cam.current = { ...c, x: -p.x, y: -p.y, k: Math.max(c.k, 0.9) };
    }
    redraw();
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Resize + theme changes (a theme/dark class flip changes every token).
  useEffect(() => {
    const wrap = wrapRef.current, canvas = canvasRef.current;
    if (!wrap || !canvas) return undefined;
    const resize = () => {
      const r = wrap.getBoundingClientRect();
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const prevW = size.current.W;
      size.current = { W: r.width, H: r.height };
      canvas.width = Math.max(1, r.width * dpr); canvas.height = Math.max(1, r.height * dpr);
      canvas.style.width = `${r.width}px`; canvas.style.height = `${r.height}px`;
      // A big width change (the details panel opening/closing) re-frames.
      if (prevW && Math.abs(prevW - r.width) > 80) fitRef.current();
      else redraw();
    };
    resize();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    ro?.observe(wrap);
    const mo = typeof MutationObserver !== "undefined" ? new MutationObserver(redraw) : null;
    mo?.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    mo?.observe(document.body, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => { ro?.disconnect(); mo?.disconnect(); };
  }, [redraw]);

  // ── paint ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext?.("2d");
    if (!ctx) return;
    const { W, H } = size.current;
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const c = cam.current;
    ctx.save();
    ctx.translate(W / 2, H / 2); ctx.scale(c.k, c.k); ctx.translate(c.x, c.y);
    const col = {
      edge: token(canvas, "canvas-edge", 0.55), edgeDim: token(canvas, "canvas-edge", 0.12),
      label: token(canvas, "fg"), halo: token(canvas, "surface", 0.92), muted: token(canvas, "fg-muted"),
      pill: token(canvas, "surface", 0.94), border: token(canvas, "border"), accent: token(canvas, "accent"),
      ring: token(canvas, "surface"),
    };
    const byId = Object.fromEntries(visibleNodes.map((n) => [n.id, n]));
    const focused = !!focusId;
    const dimByMatch = (id) => matchSet && !matchSet.has(id);
    // Text stays ~constant on screen whatever the zoom (world units = px / k).
    const ts = 1 / Math.max(0.55, Math.min(1.6, c.k));
    const showEdgeLabel = (e) => labelsAll || (focused && lit.has(e.source) && lit.has(e.target))
      || (!focused && visibleEdges.length <= 40) || (c.k >= LABEL_ALL_ZOOM && visibleEdges.length <= 80);
    const labelsToDraw = [];

    // edges
    for (const e of visibleEdges) {
      const a = P(e.source), b = P(e.target), na = byId[e.source], nb = byId[e.target];
      if (!a || !b || !na || !nb) continue;
      const on = (!focused || (lit.has(e.source) && lit.has(e.target))) && !(dimByMatch(e.source) && dimByMatch(e.target));
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
      const nx = -dy / d, ny = dx / d, off = curv[e.id || ""] || 0;
      const cx = (a.x + b.x) / 2 + nx * off, cy = (a.y + b.y) / 2 + ny * off;
      ctx.strokeStyle = on ? col.edge : col.edgeDim;
      ctx.lineWidth = (on && focused ? 1.6 : 1.1) * Math.max(0.8, Math.min(2.2, 0.6 + (e.confidence || 0.7)));
      ctx.setLineDash(e.expired ? [5, 4] : []);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(cx, cy, b.x, b.y); ctx.stroke();
      ctx.setLineDash([]);
      if (e.directed !== false) {
        // arrowhead at the target's rim, along the curve's end tangent
        const tx = b.x - cx, ty = b.y - cy, tl = Math.hypot(tx, ty) || 1;
        const ux = tx / tl, uy = ty / tl, r = nodeRadius(nb) + 2;
        const px = b.x - ux * r, py = b.y - uy * r, s = 7;
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath(); ctx.moveTo(px, py);
        ctx.lineTo(px - ux * s - uy * s * 0.5, py - uy * s + ux * s * 0.5);
        ctx.lineTo(px - ux * s + uy * s * 0.5, py - uy * s - ux * s * 0.5);
        ctx.closePath(); ctx.fill();
      }
      if (on && showEdgeLabel(e)) {
        labelsToDraw.push({ text: relLabel(e.rel || e.relation) + (e.expired ? " (superseded)" : ""),
                            x: 0.25 * a.x + 0.5 * cx + 0.25 * b.x, y: 0.25 * a.y + 0.5 * cy + 0.25 * b.y });
      }
    }
    // relation labels as pills (drawn after all edges so lines never cross text)
    ctx.font = `500 ${10.5 * ts}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    // Collision avoidance: a pill may not sit on a node or another pill — try
    // nudging it along the edge's normal, else leave it out (focus shows all).
    const occupied = [];
    for (const n of visibleNodes) {
      const p = P(n.id); if (!p) continue;
      const r = nodeRadius(n) + 2 * ts, lw = Math.min(28, (n.label || "").length) * 3.4 * ts;
      occupied.push([p.x - r, p.y - r, p.x + r, p.y + r]);
      occupied.push([p.x - lw, p.y + r, p.x + lw, p.y + r + 16 * ts]);   // its name below
    }
    const hits = (b) => occupied.some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]);
    for (const l of labelsToDraw) {
      const w = ctx.measureText(l.text).width + 10 * ts, h = 16 * ts;
      const shifts = [0, 1, -1, 2, -2].map((m) => m * h * 0.9);
      let placed = null;
      for (const sh of shifts) {
        const box = [l.x - w / 2, l.y + sh - h / 2, l.x + w / 2, l.y + sh + h / 2];
        if (!hits(box)) { placed = sh; occupied.push(box); break; }
      }
      if (placed === null) { if (!focused) continue; placed = 0; }
      l.y += placed;
      ctx.fillStyle = col.pill; ctx.strokeStyle = col.border; ctx.lineWidth = 0.8 * ts;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(l.x - w / 2, l.y - h / 2, w, h, h / 2); else ctx.rect(l.x - w / 2, l.y - h / 2, w, h);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = col.muted; ctx.fillText(l.text, l.x, l.y + 0.5);
    }
    // nodes
    for (const n of visibleNodes) {
      const p = P(n.id);
      if (!p) continue;
      const on = (!focused || lit.has(n.id)) && !dimByMatch(n.id);
      const r = nodeRadius(n);
      ctx.globalAlpha = on ? 1 : 0.18;
      ctx.fillStyle = token(canvas, typeToken(n.type));
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = col.ring; ctx.stroke();
      if (n.is_self || n.id === selectedId || (matchSet && matchSet.has(n.id))) {
        ctx.lineWidth = n.id === selectedId ? 2.5 : 1.8;
        ctx.strokeStyle = n.id === selectedId ? col.label : col.accent;
        ctx.beginPath(); ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    // node labels (halo for legibility on any surface)
    for (const n of visibleNodes) {
      const p = P(n.id);
      if (!p) continue;
      const on = (!focused || lit.has(n.id)) && !dimByMatch(n.id);
      const want = labelsAll || n.is_self || n.id === hover || n.id === selectedId
        || (focused && lit.has(n.id)) || (matchSet && matchSet.has(n.id))
        || (!focused && (topLabels.has(n.id) || c.k >= LABEL_ALL_ZOOM));
      if (!want) continue;
      const text = (n.label || "").length > 28 ? `${n.label.slice(0, 27)}…` : n.label;
      ctx.globalAlpha = on ? 1 : 0.3;
      ctx.font = `${n.is_self || n.id === selectedId ? "600" : "500"} ${12 * ts}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.lineWidth = 3.5 * ts; ctx.strokeStyle = col.halo; ctx.lineJoin = "round";
      const ty = p.y + nodeRadius(n) + 4 * ts;
      ctx.strokeText(text, p.x, ty);
      ctx.fillStyle = col.label; ctx.fillText(text, p.x, ty);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }, [tick, visibleNodes, visibleEdges, pos, curv, lit, focusId, selectedId, hover, labelsAll, topLabels, matchSet, themeKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── interaction ────────────────────────────────────────────────────────────
  const toWorld = (sx, sy) => {
    const { W, H } = size.current, c = cam.current;
    return { x: (sx - W / 2) / c.k - c.x, y: (sy - H / 2) / c.k - c.y };
  };
  const nodeAt = (sx, sy) => {
    const w = toWorld(sx, sy);
    let best = null, bd = Infinity;
    for (const n of visibleNodes) {
      const p = P(n.id); if (!p) continue;
      const d = (p.x - w.x) ** 2 + (p.y - w.y) ** 2, r = (nodeRadius(n) + 5) ** 2;
      if (d < r && d < bd) { bd = d; best = n; }
    }
    return best;
  };
  const local = (ev) => {
    const r = canvasRef.current.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  };
  const onPointerDown = (ev) => {
    const [sx, sy] = local(ev);
    const n = nodeAt(sx, sy);
    drag.current = n ? { node: n.id, sx, sy, moved: false }
      : { pan: true, sx, sy, cx: cam.current.x, cy: cam.current.y, moved: false };
    canvasRef.current.setPointerCapture?.(ev.pointerId);
  };
  const onPointerMove = (ev) => {
    const [sx, sy] = local(ev);
    const d = drag.current;
    if (d) {
      if (Math.hypot(sx - d.sx, sy - d.sy) > 4) d.moved = true;
      if (d.node && d.moved) { posOverride.current[d.node] = toWorld(sx, sy); redraw(); }
      else if (d.pan && d.moved) {
        const c = cam.current;
        cam.current = { ...c, x: d.cx + (sx - d.sx) / c.k, y: d.cy + (sy - d.sy) / c.k };
        redraw();
      }
      return;
    }
    const n = nodeAt(sx, sy);
    const id = n ? n.id : null;
    if (id !== hoverRef.current) { hoverRef.current = id; setHover(id); }
    canvasRef.current.style.cursor = n ? "pointer" : "grab";
  };
  const onPointerUp = () => {
    const d = drag.current; drag.current = null;
    if (!d || d.moved) return;
    if (d.node) onSelect?.(d.node === selectedId ? null : d.node);
    else onSelect?.(null);
  };
  const zoomBy = (f, sx, sy) => {
    const { W, H } = size.current;
    const px = sx ?? W / 2, py = sy ?? H / 2;
    const before = toWorld(px, py);
    const c = cam.current;
    const k = Math.min(4, Math.max(0.15, c.k * f));
    cam.current = { ...c, k };
    const after = toWorld(px, py);
    cam.current = { k, x: c.x + after.x - before.x, y: c.y + after.y - before.y };
    redraw();
  };
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (ev) => { ev.preventDefault(); const [sx, sy] = local(ev); zoomBy(ev.deltaY < 0 ? 1.12 : 0.89, sx, sy); };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  });
  const onKeyDown = (ev) => {
    if (ev.key === "Escape") onSelect?.(null);
    else if (ev.key === "+" || ev.key === "=") zoomBy(1.2);
    else if (ev.key === "-") zoomBy(0.83);
    else if (ev.key === "0") fit();
  };

  const hovered = hover && !selectedId ? nodes.find((n) => n.id === hover) : null;

  return (
    <div ref={wrapRef} className="relative overflow-hidden" style={{ height }} data-testid="memory-graph">
      <canvas ref={canvasRef} tabIndex={0} role="img" onKeyDown={onKeyDown}
              aria-label={`Knowledge graph: ${visibleNodes.length} entities, ${visibleEdges.length} relations. Use the search box or the Ranked tab to browse them as a list.`}
              className="block w-full h-full outline-none focus-visible:ring-2 focus-visible:ring-focus/40 rounded-lg"
              onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
              onPointerLeave={() => { if (!drag.current && hoverRef.current) { hoverRef.current = null; setHover(null); } }} />

      {/* type legend — click a type to hide/show it */}
      {groups.length > 0 && (
        <div className="absolute top-3 left-3 flex flex-wrap gap-1.5 max-w-[70%]" aria-label="Entity types">
          {groups.map((g) => (
            <button key={g.type} type="button" onClick={() => setHidden((h) => ({ ...h, [g.type]: !h[g.type] }))}
                    aria-pressed={!hidden[g.type]}
                    title={hidden[g.type] ? `Show ${g.type}` : `Hide ${g.type}`}
                    className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border border-border bg-surface/85 backdrop-blur text-xs text-fg-muted hover:text-fg transition-opacity ${hidden[g.type] ? "opacity-45" : ""}`}>
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: `rgb(var(--${g.token}))` }} />
              <span className="capitalize">{g.type}</span>
              <span className="text-fg-subtle">{g.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* zoom / fit / labels */}
      <div className="absolute bottom-3 right-3 flex gap-1 rounded-lg border border-border bg-surface/85 backdrop-blur p-1">
        <IconButton label="Zoom in" onClick={() => zoomBy(1.2)}><IconZoomIn size={17} stroke={1.7} /></IconButton>
        <IconButton label="Zoom out" onClick={() => zoomBy(0.83)}><IconZoomOut size={17} stroke={1.7} /></IconButton>
        <IconButton label="Fit to view" onClick={fit}><IconFocusCentered size={17} stroke={1.7} /></IconButton>
        <IconButton label={labelsAll ? "Show fewer labels" : "Show all labels"} onClick={() => setLabelsAll((v) => !v)}
                    aria-pressed={labelsAll}>
          {labelsAll ? <IconTagOff size={17} stroke={1.7} /> : <IconTag size={17} stroke={1.7} />}
        </IconButton>
        {selectedId && (
          <IconButton label="Clear focus" onClick={() => onSelect?.(null)}><IconArrowsMinimize size={17} stroke={1.7} /></IconButton>
        )}
      </div>

      {hovered && (
        <div className="absolute bottom-3 left-3 max-w-[50%] rounded-lg border border-border bg-surface/90 backdrop-blur px-3 py-1.5 pointer-events-none">
          <div className="text-sm font-medium text-fg truncate">{hovered.label}</div>
          <div className="text-2xs text-fg-subtle capitalize">
            {hovered.type} · {hovered.degree ?? 0} relation{hovered.degree === 1 ? "" : "s"} · click to focus
          </div>
        </div>
      )}
    </div>
  );
}
