import { memo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
// Side-effect: register the mhchem extension on the shared KaTeX instance so
// chemistry equations written as \ce{...} / \pu{...} render too (e.g.
// $\ce{2H2 + O2 -> 2H2O}$). Must load before any KaTeX render runs.
import "katex/contrib/mhchem";
import { copyText } from "../clipboard.js";
import { viewImage } from "./ImageViewer.jsx";
import SimulationCard from "./SimulationCard.jsx";

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
const KATEX_OPTS = { throwOnError: false, errorColor: "#dc2626", strict: false };

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
      <span className="inline-flex items-center gap-1.5 my-1 px-2.5 py-1.5 rounded-lg border border-dashed border-line dark:border-night-line text-[12.5px] text-ink-faint dark:text-night-faint">
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
           className="max-w-full max-h-[460px] rounded-xl border border-line dark:border-night-line bg-white" />
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
      <button onClick={copy} title="Copy code"
              className="absolute top-2 right-2 z-10 flex items-center gap-1 px-2 py-1 rounded-md text-[11.5px]
                         border border-line dark:border-night-line bg-paper-panel/90 dark:bg-night-panel/90
                         text-ink-soft dark:text-night-faint hover:text-ink dark:hover:text-night-ink
                         opacity-0 group-hover:opacity-100 focus:opacity-100 transition">
        {copied ? (
          <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Copied</>
        ) : (
          <><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>Copy</>
        )}
      </button>
      <pre ref={ref} {...props}>{children}</pre>
    </div>
  );
}

// Renders the model's markdown as clean rich text (no raw * or ### shown).
// Links open in a new tab; code gets syntax highlighting; GFM tables/lists work.
export default function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, KATEX_OPTS], [rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          a: ({ node, href, children, ...props }) =>
            isSimUrl(href)
              ? <SimulationCard src={href} title={childText(children) || "Interactive simulation"} />
              : <a href={href} target="_blank" rel="noreferrer noopener" {...props}>{children}</a>,
          img: ({ node, ...props }) => <InlineImage {...props} />,
          pre: ({ node, ...props }) => <CodeBlock {...props} />,
          // Unwrap a paragraph that only carries a simulation card (a <div> can't
          // be nested in a <p>).
          p: ({ node, children }) => (pHasSim(node) ? <>{children}</> : <p>{children}</p>),
        }}
      >
        {children || ""}
      </ReactMarkdown>
    </div>
  );
}
