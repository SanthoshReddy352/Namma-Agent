import { useCallback, useEffect, useRef, useState } from "react";

// Open the full-screen image viewer from anywhere (e.g. an inline diagram in a
// chat) without prop-drilling — InlineImage just fires this event.
export function viewImage(src, alt = "") {
  if (src) window.dispatchEvent(new CustomEvent("friday-view-image", { detail: { src, alt } }));
}

const MIN = 1, MAX = 6, STEP = 0.5;

// A top-layer image viewer: zoom in / out / reset, drag to pan when zoomed, a
// clear close button pinned top-right, click-outside-to-close, and Esc to close.
// Mounted once at the app root with the highest z-index so it always sits above
// every other modal. Theme-aware controls (paper/night tokens).
export default function ImageViewer() {
  const [img, setImg] = useState(null); // { src, alt }
  const [scale, setScale] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const drag = useRef(null);

  const close = useCallback(() => { setImg(null); setScale(1); setPos({ x: 0, y: 0 }); }, []);

  useEffect(() => {
    const onOpen = (e) => { setImg(e.detail); setScale(1); setPos({ x: 0, y: 0 }); };
    window.addEventListener("friday-view-image", onOpen);
    return () => window.removeEventListener("friday-view-image", onOpen);
  }, []);

  useEffect(() => {
    if (!img) return;
    const onKey = (e) => {
      if (e.key === "Escape") close();
      else if (e.key === "+" || e.key === "=") zoom(STEP);
      else if (e.key === "-") zoom(-STEP);
      else if (e.key === "0") reset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    /* eslint-disable-next-line */
  }, [img, close]);

  if (!img) return null;

  function zoom(delta) {
    setScale((s) => {
      const next = Math.min(MAX, Math.max(MIN, +(s + delta).toFixed(2)));
      if (next === MIN) setPos({ x: 0, y: 0 }); // snap back to centre at 1×
      return next;
    });
  }
  function reset() { setScale(1); setPos({ x: 0, y: 0 }); }

  function onWheel(e) {
    e.preventDefault();
    zoom(e.deltaY < 0 ? STEP : -STEP);
  }
  function onPointerDown(e) {
    if (scale <= 1) return;
    drag.current = { x: e.clientX, y: e.clientY, ox: pos.x, oy: pos.y };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }
  function onPointerMove(e) {
    if (!drag.current) return;
    setPos({ x: drag.current.ox + (e.clientX - drag.current.x),
             y: drag.current.oy + (e.clientY - drag.current.y) });
  }
  function onPointerUp() { drag.current = null; }

  return (
    // Highest layer in the app. Backdrop click closes; clicks on the image and
    // the controls stop propagation so they don't dismiss the viewer.
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center"
         onClick={close}>
      {/* Controls — pinned top-right, above the image */}
      <div className="absolute top-3 right-3 flex items-center gap-1.5 z-[101]"
           onClick={(e) => e.stopPropagation()}>
        <Ctrl title="Zoom out (-)" onClick={() => zoom(-STEP)} disabled={scale <= MIN}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="M8 11h6M21 21l-4.3-4.3" /></svg>
        </Ctrl>
        <span className="px-2 text-[12.5px] tabular-nums text-white/80 select-none w-12 text-center">{Math.round(scale * 100)}%</span>
        <Ctrl title="Zoom in (+)" onClick={() => zoom(STEP)} disabled={scale >= MAX}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="M11 8v6M8 11h6M21 21l-4.3-4.3" /></svg>
        </Ctrl>
        <Ctrl title="Reset (0)" onClick={reset} disabled={scale === 1 && pos.x === 0 && pos.y === 0}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
        </Ctrl>
        <a href={img.src} download title="Download" onClick={(e) => e.stopPropagation()}
           className="h-9 w-9 grid place-items-center rounded-lg text-white/90 bg-white/10 hover:bg-white/20 transition">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></svg>
        </a>
        <Ctrl title="Close (Esc)" onClick={close}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </Ctrl>
      </div>

      {/* White matte behind every image: diagrams are dark lines/text on white, so a
          light backdrop keeps the node-connection lines visible regardless of app
          theme (a dark backdrop would swallow them). */}
      <img src={img.src} alt={img.alt || "image"} draggable={false}
           onClick={(e) => e.stopPropagation()}
           onWheel={onWheel}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove}
           onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
           onDoubleClick={() => (scale > 1 ? reset() : zoom(STEP * 2))}
           style={{ transform: `translate(${pos.x}px, ${pos.y}px) scale(${scale})`,
                    cursor: scale > 1 ? (drag.current ? "grabbing" : "grab") : "zoom-in",
                    transition: drag.current ? "none" : "transform 0.12s ease-out" }}
           className="max-w-[92vw] max-h-[88vh] object-contain rounded-lg shadow-2xl select-none bg-white" />
    </div>
  );
}

function Ctrl({ onClick, title, disabled, children }) {
  return (
    <button title={title} onClick={onClick} disabled={disabled}
            className="h-9 w-9 grid place-items-center rounded-lg text-white/90 bg-white/10 hover:bg-white/20 disabled:opacity-30 disabled:hover:bg-white/10 transition">
      {children}
    </button>
  );
}
