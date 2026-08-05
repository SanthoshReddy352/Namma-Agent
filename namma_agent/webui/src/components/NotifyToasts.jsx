import { useEffect, useState } from "react";
import { INAPP_EVENT } from "../notify.js";

// In-app notification banners — the fallback for when the OS won't show a real
// toast (Windows notifications switched off, no Linux notify daemon, a 401 on a
// token-protected server). Without this, an enabled notification whose OS toast
// gets swallowed simply vanishes, which is exactly how "notifications don't
// work" looks from the outside — in the browser tab and the desktop window
// alike. notify.js dispatches INAPP_EVENT; we stack, auto-dismiss and render.
const TTL_MS = 6000;
const MAX = 4; // keep the newest few — a burst shouldn't cover the app

export default function NotifyToasts() {
  const [items, setItems] = useState([]);

  useEffect(() => {
    const timers = new Map();
    const drop = (id) => {
      setItems((list) => list.filter((n) => n.id !== id));
      clearTimeout(timers.get(id));
      timers.delete(id);
    };
    const on = (e) => {
      const n = e.detail;
      if (!n?.id) return;
      setItems((list) => [...list, n].slice(-MAX));
      timers.set(n.id, setTimeout(() => drop(n.id), TTL_MS));
    };
    window.addEventListener(INAPP_EVENT, on);
    return () => {
      window.removeEventListener(INAPP_EVENT, on);
      timers.forEach(clearTimeout);
    };
  }, []);

  if (!items.length) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-[320px] max-w-[calc(100vw-2rem)]"
         role="status" aria-live="polite">
      {items.map((n) => (
        <div key={n.id}
             onClick={() => setItems((list) => list.filter((x) => x.id !== n.id))}
             className={`cursor-pointer rounded-xl border shadow-pop px-4 py-3 animate-rise
                         bg-paper-panel dark:bg-night-panel
                         ${n.tone === "error"
                           ? "border-red-400/60 dark:border-red-500/50"
                           : "border-line dark:border-night-line"}`}>
          <div className="text-sm font-medium text-ink dark:text-night-ink">{n.title}</div>
          {n.body && (
            <div className="mt-0.5 text-[12px] leading-snug text-ink-soft dark:text-night-faint line-clamp-3">
              {n.body}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
