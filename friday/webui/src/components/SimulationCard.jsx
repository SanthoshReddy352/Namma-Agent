import { useEffect, useState } from "react";

// Plays a generated HTML/JS simulation INLINE in the chat — no detour to a
// separate browser tab. The sim runs in a sandboxed iframe (scripts allowed, but
// isolated from the app's origin), with an "expand" control that blows it up to a
// top-layer modal for a roomier hands-on session, and a quiet "open in new tab"
// escape hatch. Click-outside / Esc closes the expanded view.
//
// `src` is a same-origin /api/media/sims/<id>.html URL; `title` is the caption.
export default function SimulationCard({ src, title = "Interactive simulation" }) {
  const [full, setFull] = useState(false);

  useEffect(() => {
    if (!full) return;
    const onKey = (e) => { if (e.key === "Escape") setFull(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);

  const frame = (className, extra) => (
    <iframe src={src} title={title} loading="lazy"
            sandbox="allow-scripts allow-pointer-lock allow-popups allow-forms allow-modals"
            className={className} {...extra} />
  );

  return (
    <>
      <div className="my-3 rounded-xl border border-line dark:border-night-line overflow-hidden bg-white dark:bg-night-panel">
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-line dark:border-night-line bg-paper-soft dark:bg-night-soft">
          <div className="flex items-center gap-2 min-w-0 text-[13px] text-ink-soft dark:text-night-ink">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-brand-deep"><path d="m5 3 14 9-14 9V3Z" /></svg>
            <span className="truncate font-medium">{title}</span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button title="Expand" onClick={() => setFull(true)}
                    className="h-7 w-7 grid place-items-center rounded-md text-ink-soft dark:text-night-faint hover:bg-paper-sink dark:hover:bg-night hover:text-ink dark:hover:text-night-ink transition">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
            </button>
            <a href={src} target="_blank" rel="noreferrer noopener" title="Open in new tab"
               className="h-7 w-7 grid place-items-center rounded-md text-ink-soft dark:text-night-faint hover:bg-paper-sink dark:hover:bg-night hover:text-ink dark:hover:text-night-ink transition">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6M10 14 21 3" /></svg>
            </a>
          </div>
        </div>
        {frame("w-full h-[420px] bg-white")}
      </div>

      {full && (
        <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
             onClick={() => setFull(false)}>
          <div className="absolute top-3 right-3 z-[101]" onClick={(e) => e.stopPropagation()}>
            <button title="Close (Esc)" onClick={() => setFull(false)}
                    className="h-9 w-9 grid place-items-center rounded-lg text-white/90 bg-white/10 hover:bg-white/20 transition">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
            </button>
          </div>
          <div className="w-[92vw] h-[88vh] rounded-xl overflow-hidden bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            {frame("w-full h-full bg-white")}
          </div>
        </div>
      )}
    </>
  );
}
