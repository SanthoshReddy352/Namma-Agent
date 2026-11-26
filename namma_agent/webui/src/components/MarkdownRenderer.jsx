import { createContext, memo, useContext, useRef, useState, useSyncExternalStore } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { copyText } from "../clipboard.js";
import { viewImage } from "./ImageViewer.jsx";
import SimulationCard from "./SimulationCard.jsx";
import { ChartBlock, MermaidBlock, VisualBlock } from "./Visuals.jsx";
import A2uiBlock from "./A2uiBlock.jsx";
import { SecretCard } from "./SetupUI.jsx";

// Fenced languages rendered as visuals instead of code (Phase 4).
// ```secret is the setup agent's secure key field (Phase 5).
const VISUAL_LANGS = new Set(["mermaid", "chart", "visual", "a2ui", "secret"]);

function hastText(node) {
  if (!node) return "";
  if (node.type === "text") return node.value || "";
  return (node.children || []).map(hastText).join("");
}

function fenceLang(node) {
  const code = (node?.children || []).find((c) => c.tagName === "code");
  const cls = code?.properties?.className || [];
  const lang = (Array.isArray(cls) ? cls : [cls]).map(String).find((c) => c.startsWith("language-"));
  return lang ? { lang: lang.slice(9).toLowerCase(), code } : null;
}

// A fence is "closed" when the source slice it came from ends with its closing
// marker — until then (mid-stream) a visual shows a placeholder, not a half-
// parsed diagram.
function fenceClosed(source, node) {
  const start = node?.position?.start?.offset, end = node?.position?.end?.offset;
  if (start == null || end == null) return true;
  const slice = source.slice(start, end).trimEnd();
  const marker = slice.match(/^\s*(`{3,}|~{3,})/)?.[1];
  return !!marker && slice.length > marker.length * 2 && slice.endsWith(marker);
}

function VisualFence({ lang, text }) {
  if (lang === "mermaid") return <MermaidBlock code={text} />;
  if (lang === "chart") return <ChartBlock source={text} />;
  if (lang === "visual") return <VisualBlock source={text} />;
  if (lang === "secret") return <SecretCard source={text} />;
  return <A2uiBlock source={text} />;
}

// A generated HTML simulation lives at /api/media/sims/<id>.html — render those
// links as a playable inline card instead of a plain "open in new tab" link.
const isSimUrl = (href) => typeof href === "string" && /\/api\/media\/sims\/[^/]+\.html?$/i.test(href);
// A simulation renders as a block-level card, which can't live inside a <p>;
// detect a paragraph whose link is a sim so we can unwrap it.
const pHasSim = (node) => (node?.children || []).some((c) => c.tagName === "a" && isSimUrl(c.properties?.href));

// Flatten a React markdown child into plain text, then strip the tool's
// "▶ Open interactive simulation — " lead-in so only the real title remains.
function childText(children) {
  const flat = (n) =>
    n == null ? "" :
    typeof n === "string" || typeof n === "number" ? String(n) :
    Array.isArray(n) ? n.map(flat).join("") :
    n?.props?.children ? flat(n.props.children) : "";
  return flat(children).replace(/^[▶►\s]*open\s+interactive\s+simulation\s*[—–-]?\s*/i, "").trim();
}

// Math + chemistry rendering, applied in EVERY chat (this component backs all
// assistant messages). remark-math picks up `$…$` / `$$…$$`; rehype-katex turns
// them into KaTeX, with mhchem enabling `\ce{}` for chemical equations. A
// malformed expression renders in red rather than throwing, so a bad formula
// never blanks the whole message.
const KATEX_OPTS = { throwOnError: false, errorColor: "rgb(200 30 30)" /* = --katex-error (KaTeX needs a literal colour) */, strict: false };

// Cross-render cache of image URLs the browser has already decoded. The diagram
// PNGs are rendered AND verified server-side, so once one paints we treat it as
// permanently good — this keeps a re-render from flashing the "unavailable" chip
// or re-triggering a load transition.
const LOADED = new Set();

// Inline diagram/image (render_diagram, fetch_image) — framed, capped, and
// click-to-open full size. A dead link (404 from a failed/fabricated render)
// degrades to a quiet "unavailable" chip instead of the browser's broken icon.
//
// Wrapped in React.memo keyed on the src/alt: when the surrounding markdown
// re-renders (e.g. a streamed reply growing token by token), an image whose
// source is unchanged is never re-created, so the server-rendered diagram stays
// rock-steady and does not flicker. We also drop native lazy-loading, which
// could unload/reload the image as the layout reflows.
const InlineImage = memo(function InlineImage(props) {
  const { src, alt } = props;
  const [broken, setBroken] = useState(false);
  if (broken && !LOADED.has(src)) {
    return (
      <span className="inline-flex items-center gap-1.5 my-1 px-2.5 py-1.5 rounded-lg border border-dashed border-border text-sm text-fg-subtle">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.5-3.5L9 20" /><path d="m2 2 20 20" /></svg>
        {alt || "image"} — unavailable
      </span>
    );
  }
  // Click opens the full-screen viewer (zoom / pan / download) instead of leaving
  // the app for a new browser tab.
  return (
    <button type="button" onClick={() => viewImage(src, alt)}
            className="block my-2 cursor-zoom-in" title="Click to view — zoom, pan, download">
      <img src={src} alt={alt} decoding="async"
           onLoad={() => LOADED.add(src)} onError={() => setBroken(true)}
           className="max-w-full max-h-[460px] rounded-xl border border-border bg-white" />
    </button>
  );
}, (a, b) => a.src === b.src && a.alt === b.alt);

// A theme-aware "copy" button for fenced code blocks: replaces the default <pre>
// so multi-line code/terminal output is one click to the clipboard (works even
// where the host webview hasn't wired Ctrl+C).
function CodeBlock({ children, ...props }) {
  const ref = useRef(null);
  const [copied, setCopied] = useState(false);
  async function copy() {
    const text = ref.current?.innerText ?? "";
    if (await copyText(text)) { setCopied(true); setTimeout(() => setCopied(false), 1400); }
  }
  return (
    <div className="relative group">
      <button aria-label="Copy code" onClick={copy} title="Copy code"
              className="absolute top-2 right-2 z-10 flex items-center gap-1 px-2 py-1 rounded-md text-xs
                         border border-line dark:border-night-line bg-paper-panel/90 dark:bg-night-panel/90
                         text-ink-soft dark:text-night-faint hover:text-ink dark:hover:text-night-ink
                         opacity-0 group-hover:opacity-100 focus:opacity-100 transition">
        {copied ? (
          <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" className="text-success" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Copied</>
        ) : (
          <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>Copy</>
        )}
      </button>
      <pre ref={ref} {...props}>{children}</pre>
    </div>
  );
}

const REMARK = [remarkGfm, remarkMath];
const HIGHLIGHT_OPTS = { detect: true, ignoreMissing: true, plainText: [...VISUAL_LANGS] };

// Heavy rehype plugins are code-split (Phase 6) and load the first time a
// message needs them; every Markdown then re-renders with them:
//  - math: KaTeX (~260 KB) plus mhchem, which registers \ce{...} / \pu{...} on
//    the same KaTeX instance (chemistry, e.g. $\ce{2H2 + O2 -> 2H2O}$);
//  - code: highlight.js (~165 KB) for fenced code.
// Until a plugin lands, math shows as source text and code is unhighlighted.
const HAS_MATH = /\$|\\\(|\\\[/;
const HAS_CODE = /```|~~~|<pre/;
const LOADERS = {
  math: () => Promise.all([
    import("rehype-katex"), import("katex/dist/katex.min.css"), import("katex/contrib/mhchem"),
  ]).then(([m]) => [m.default, KATEX_OPTS]),
  code: () => import("rehype-highlight").then((m) => [m.default, HIGHLIGHT_OPTS]),
};
const plugins = { math: null, code: null };
const loading = {};
const pluginSubs = new Set();
let pluginVersion = 0;
function loadPlugin(kind) {
  if (plugins[kind] || loading[kind]) return;
  loading[kind] = LOADERS[kind]().then((plugin) => {
    plugins[kind] = plugin;
    pluginVersion += 1;
    pluginSubs.forEach((fn) => fn());
  }).catch(() => { loading[kind] = null; });
}
const subscribePlugins = (fn) => { pluginSubs.add(fn); return () => pluginSubs.delete(fn); };
const getPluginVersion = () => pluginVersion;
// Stable plugin arrays (KaTeX before highlight, as the pipeline expects).
const REHYPE_CACHE = new Map();
function rehypeFor(math, code) {
  const useMath = math && !!plugins.math, useCode = code && !!plugins.code;
  const key = `${useMath ? 1 : 0}${useCode ? 1 : 0}`;
  if (!REHYPE_CACHE.has(key)) {
    REHYPE_CACHE.set(key, [useMath && plugins.math, useCode && plugins.code].filter(Boolean));
  }
  return REHYPE_CACHE.get(key);
}

// Renders the model's markdown as clean rich text (no raw * or ### shown).
// Links open in a new tab; code gets syntax highlighting; GFM tables/lists work.
// Memoised on the source text (Phase 6): a re-render with the same markdown
// never re-runs the remark/rehype pipeline.
export default memo(function Markdown({ children }) {
  const source = children || "";
  useSyncExternalStore(subscribePlugins, getPluginVersion, getPluginVersion);
  const wantsMath = HAS_MATH.test(source), wantsCode = HAS_CODE.test(source);
  if (wantsMath) loadPlugin("math");
  if (wantsCode) loadPlugin("code");
  return (
    <MdSourceContext.Provider value={source}>
    <div className="md">
      <ReactMarkdown
        remarkPlugins={REMARK}
        rehypePlugins={rehypeFor(wantsMath, wantsCode)}
        components={COMPONENTS}
        urlTransform={urlTransform}
      >
        {source}
      </ReactMarkdown>
    </div>
    </MdSourceContext.Provider>
  );
}, (a, b) => a.children === b.children);

// The markdown source, for the fence renderer (is this fence closed yet?).
const MdSourceContext = createContext("");

// ```mermaid / ```chart / ```visual / ```a2ui render as visuals once their
// fence closes; every other fence is a copy-enabled code block.
function Pre({ node, ...props }) {
  const source = useContext(MdSourceContext);
  const fence = fenceLang(node);
  if (fence && VISUAL_LANGS.has(fence.lang)) {
    if (!fenceClosed(source, node)) {
      return <div role="status" className="my-2 h-24 rounded-xl border border-dashed border-border grid place-items-center text-sm text-ink-faint dark:text-night-faint">{fence.lang === "secret" ? "Preparing a secure field…" : `Drawing ${fence.lang === "a2ui" ? "interface" : fence.lang}…`}</div>;
    }
    return <VisualFence lang={fence.lang} text={hastText(fence.code).replace(/\n$/, "")} />;
  }
  return <CodeBlock {...props} />;
}

// Module-level and therefore STABLE: an inline object would hand react-markdown
// new component types on every render, remounting every block — resetting an
// interactive visual or an A2UI card each time a token streamed in.
// Some models (OpenAI's especially) write download links as "sandbox:/api/…".
// Map those back onto our own server path; everything else gets the safe default.
export function urlTransform(url) {
  const m = /^sandbox:(\/.*)$/i.exec(url || "");
  return defaultUrlTransform(m ? m[1] : url);
}

const COMPONENTS = {
  a: ({ node, href, children, ...props }) =>
    isSimUrl(href)
      ? <SimulationCard src={href} title={childText(children) || "Interactive simulation"} />
      : <a href={href} target="_blank" rel="noreferrer noopener" {...props}>{children}</a>,
  img: ({ node, ...props }) => <InlineImage {...props} />,
  pre: Pre,
  // Unwrap a paragraph that only carries a simulation card (a <div> can't be
  // nested in a <p>).
  p: ({ node, children }) => (pHasSim(node) ? <>{children}</> : <p>{children}</p>),
};
