import { createContext, memo, useContext, useEffect, useId, useRef, useState } from "react";
import { reportRenderError } from "../api.js";

// Inline visuals in chat messages (Phase 4):
//   ```mermaid  → diagram, rendered client-side (mermaid, securityLevel "strict")
//   ```chart    → JSON spec → SVG bar / line / pie chart (no chart library)
//   ```visual   → {"id": …} from the render_visual tool → sandboxed iframe
// Each renders only once its fence has closed (a placeholder shows while the
// block is still streaming) and falls back to the source on error. Render
// errors are reported to the server, which tells the model on its next turn.

// The chat session a message belongs to — so render errors reach the right chat.
export const RenderSessionContext = createContext(null);

function useReport(kind, source) {
  const sessionId = useContext(RenderSessionContext);
  const sent = useRef(false);
  return (error) => {
    if (sent.current) return;
    sent.current = true;
    reportRenderError({ session_id: sessionId, kind, error: String(error?.message || error).slice(0, 500),
                        snippet: String(source || "").slice(0, 400) });
  };
}

function Placeholder({ label }) {
  return (
    <div role="status" className="my-2 h-24 rounded-xl border border-dashed border-border grid place-items-center text-sm text-ink-faint dark:text-night-faint">
      {label}…
    </div>
  );
}

function Fallback({ source, error, lang }) {
  return (
    <div className="my-2">
      <div className="text-xs text-warning mb-1">Couldn't render this {lang}: {String(error?.message || error).slice(0, 160)}</div>
      <pre className="text-sm"><code>{source}</code></pre>
    </div>
  );
}

// ── mermaid ───────────────────────────────────────────────────────────────────

let mermaidPromise = null;
function loadMermaid() {
  // Lazy: the ~MBs of mermaid load only when a chat actually contains a diagram.
  mermaidPromise ||= import("mermaid").then((m) => m.default);
  return mermaidPromise;
}

const isDark = () => document.documentElement.classList.contains("dark");

export const MermaidBlock = memo(function MermaidBlock({ code }) {
  const [svg, setSvg] = useState("");
  const [error, setError] = useState(null);
  const id = "m" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const report = useReport("mermaid", code);
  useEffect(() => {
    let live = true;
    loadMermaid().then(async (mermaid) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict",
                           theme: isDark() ? "dark" : "default", fontFamily: "inherit" });
      try {
        const { svg: out } = await mermaid.render(id, code);
        if (live) setSvg(out);
      } catch (e) {
        document.getElementById("d" + id)?.remove();   // mermaid leaves an error node behind
        if (live) { setError(e); report(e); }
      }
    }).catch((e) => { if (live) { setError(e); report(e); } });
    return () => { live = false; };
  }, [code]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <Fallback source={code} error={error} lang="diagram" />;
  if (!svg) return <Placeholder label="Rendering diagram" />;
  return (
    <figure className="my-2 overflow-x-auto rounded-xl border border-border bg-white dark:bg-night-soft p-3"
            aria-label="Diagram"
            // securityLevel "strict" makes mermaid sanitize the SVG (DOMPurify).
            dangerouslySetInnerHTML={{ __html: svg }} />
  );
}, (a, b) => a.code === b.code);

// ── chart ─────────────────────────────────────────────────────────────────────

const PALETTE = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => `rgb(var(--chart-${i}))`);

export function parseChart(source) {
  const spec = JSON.parse(source);
  const type = spec.type || "bar";
  if (!["bar", "line", "pie"].includes(type)) throw new Error(`unknown chart type "${type}" (bar, line or pie)`);
  const labels = spec.labels;
  if (!Array.isArray(labels) || !labels.length) throw new Error('"labels" must be a non-empty array');
  const series = spec.series || (spec.data ? [{ name: spec.title || "", data: spec.data }] : null);
  if (!Array.isArray(series) || !series.length) throw new Error('"series" must be a non-empty array of {name, data}');
  for (const s of series) {
    if (!Array.isArray(s.data) || s.data.length !== labels.length || s.data.some((v) => typeof v !== "number" || !isFinite(v)))
      throw new Error(`series "${s.name || "?"}" needs ${labels.length} numbers, one per label`);
  }
  return { type, title: spec.title || "", labels, series, unit: spec.unit || "" };
}

const fmt = (v) => (Math.abs(v) >= 1000 ? v.toLocaleString() : String(Math.round(v * 100) / 100));

function ChartSvg({ c }) {
  const W = 560, H = 260, pad = { l: 44, r: 12, t: 12, b: 34 };
  if (c.type === "pie") {
    const vals = c.series[0].data, total = vals.reduce((a, b) => a + Math.max(0, b), 0) || 1;
    let a0 = -Math.PI / 2;
    const cx = 130, cy = 130, r = 110;
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={c.title || "Pie chart"}>
        {vals.map((v, i) => {
          const a1 = a0 + (Math.max(0, v) / total) * Math.PI * 2;
          const large = a1 - a0 > Math.PI ? 1 : 0;
          const d = `M${cx},${cy} L${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${large} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)} Z`;
          a0 = a1;
          return <path key={i} d={d} fill={PALETTE[i % PALETTE.length]}><title>{`${c.labels[i]}: ${fmt(v)}${c.unit}`}</title></path>;
        })}
        {c.labels.map((l, i) => (
          <g key={l + i} transform={`translate(280, ${24 + i * 22})`}>
            <rect width="12" height="12" rx="2" fill={PALETTE[i % PALETTE.length]} />
            <text x="18" y="10" className="fill-current text-xs">{l} — {fmt(vals[i])}{c.unit} ({Math.round((Math.max(0, vals[i]) / total) * 100)}%)</text>
          </g>
        ))}
      </svg>
    );
  }
  const all = c.series.flatMap((s) => s.data);
  const max = Math.max(0, ...all), min = Math.min(0, ...all), span = max - min || 1;
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const y = (v) => pad.t + ih - ((v - min) / span) * ih;
  const step = iw / c.labels.length;
  const ticks = [min, min + span / 2, max];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={c.title || `${c.type} chart`}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="stroke-current opacity-15" />
          <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="fill-current text-2xs opacity-70">{fmt(t)}</text>
        </g>
      ))}
      {c.labels.map((l, i) => (
        <text key={l + i} x={pad.l + step * i + step / 2} y={H - 12} textAnchor="middle" className="fill-current text-2xs opacity-80">{String(l).slice(0, 14)}</text>
      ))}
      {c.type === "bar" && c.series.map((s, si) => {
        const bw = (step * 0.7) / c.series.length;
        return s.data.map((v, i) => (
          <rect key={`${si}-${i}`} x={pad.l + step * i + step * 0.15 + bw * si} width={bw - 2}
                y={Math.min(y(v), y(0))} height={Math.abs(y(v) - y(0))} rx="2" fill={PALETTE[si % PALETTE.length]}>
            <title>{`${s.name ? s.name + " · " : ""}${c.labels[i]}: ${fmt(v)}${c.unit}`}</title>
          </rect>
        ));
      })}
      {c.type === "line" && c.series.map((s, si) => (
        <g key={si}>
          <polyline fill="none" strokeWidth="2.2" stroke={PALETTE[si % PALETTE.length]}
                    points={s.data.map((v, i) => `${pad.l + step * i + step / 2},${y(v)}`).join(" ")} />
          {s.data.map((v, i) => (
            <circle key={i} cx={pad.l + step * i + step / 2} cy={y(v)} r="3.2" fill={PALETTE[si % PALETTE.length]}>
              <title>{`${s.name ? s.name + " · " : ""}${c.labels[i]}: ${fmt(v)}${c.unit}`}</title>
            </circle>
          ))}
        </g>
      ))}
    </svg>
  );
}

export const ChartBlock = memo(function ChartBlock({ source }) {
  const report = useReport("chart", source);
  let chart = null, error = null;
  try { chart = parseChart(source); } catch (e) { error = e; }
  useEffect(() => { if (error) report(error); }, [source]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <Fallback source={source} error={error} lang="chart" />;
  return (
    <figure className="my-2 rounded-xl border border-border p-3 text-ink dark:text-night-ink">
      {chart.title && <figcaption className="text-sm font-medium mb-1">{chart.title}</figcaption>}
      <ChartSvg c={chart} />
      {chart.type !== "pie" && chart.series.length > 1 && (
        <div className="flex flex-wrap gap-3 mt-1 text-xs">
          {chart.series.map((s, i) => (
            <span key={i} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} aria-hidden="true" />{s.name}
            </span>
          ))}
        </div>
      )}
    </figure>
  );
}, (a, b) => a.source === b.source);

// ── sandboxed HTML/SVG visual (render_visual) ─────────────────────────────────

// Prepended to the agent's HTML: no network at all, inline script/style only;
// errors and the content height are posted to the parent (postMessage is the
// one channel a null-origin sandboxed frame has).
const FRAME_HEAD = (id) => `<!doctype html><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'">
<style>html,body{margin:0;font-family:system-ui,sans-serif}</style>
<script>(function(){var id=${JSON.stringify(id)};
function post(m){try{parent.postMessage(Object.assign({source:"namma-visual",id:id},m),"*")}catch(e){}}
window.addEventListener("error",function(e){post({type:"error",message:String(e.message||e)})});
window.addEventListener("load",function(){post({type:"height",height:document.body.scrollHeight})});
})();</script>`;

export const VisualBlock = memo(function VisualBlock({ source }) {
  const [html, setHtml] = useState(null);
  const [error, setError] = useState(null);
  const [height, setHeight] = useState(320);
  const report = useReport("visual", source);
  let spec = null;
  try { spec = JSON.parse(source); } catch { /* handled below */ }
  const id = spec?.id;
  useEffect(() => {
    if (!id || !/^[a-f0-9]{8,32}$/.test(id)) { setError(new Error("invalid visual id")); return; }
    let live = true;
    fetch(`/api/visuals/${id}`).then((r) => (r.ok ? r.text() : Promise.reject(new Error(`visual ${id} not found`))))
      .then((t) => { if (live) setHtml(t); })
      .catch((e) => { if (live) setError(e); });
    const onMsg = (e) => {
      const d = e.data;
      if (!d || d.source !== "namma-visual" || d.id !== id) return;
      if (d.type === "height") setHeight(Math.min(Math.max(120, d.height + 8), spec?.max_height || 900));
      if (d.type === "error") report(d.message);
    };
    window.addEventListener("message", onMsg);
    return () => { live = false; window.removeEventListener("message", onMsg); };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <Fallback source={source} error={error} lang="visual" />;
  if (html == null) return <Placeholder label="Loading visual" />;
  return (
    <figure className="my-2 rounded-xl border border-border overflow-hidden bg-white">
      {spec?.title && <figcaption className="px-3 py-1.5 text-sm font-medium text-ink-soft border-b border-line">{spec.title}</figcaption>}
      {/* allow-scripts WITHOUT allow-same-origin: an opaque (null) origin, no access
          to the app, its cookies or storage; CSP above blocks all network. */}
      <iframe title={spec?.title || "Interactive visual"} sandbox="allow-scripts"
              srcDoc={FRAME_HEAD(id) + html} style={{ width: "100%", height, border: 0 }} />
    </figure>
  );
}, (a, b) => a.source === b.source);
