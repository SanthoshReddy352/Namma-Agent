import { useEffect, useState } from "react";

// Phase 6 primitive: app-wide feedback. Call `toast("Saved")` from anywhere;
// the one <Toaster/> in the shell renders them in a polite live region.
const listeners = new Set();
let nextId = 1;

export function toast(message, { tone = "neutral", duration = 3500, action } = {}) {
  const t = { id: nextId++, message, tone, duration, action };
  listeners.forEach((fn) => fn(t));
  return t.id;
}

const TONES = {
  neutral: "border-border",
  success: "border-success/50",
  danger: "border-danger/60",
  warning: "border-warning/60",
};

export function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const on = (t) => {
      setItems((xs) => [...xs.slice(-3), t]);
      if (t.duration > 0) setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), t.duration);
    };
    listeners.add(on);
    return () => listeners.delete(on);
  }, []);
  const drop = (id) => setItems((xs) => xs.filter((x) => x.id !== id));
  return (
    <div role="status" aria-live="polite" className="fixed bottom-4 right-4 z-toast flex flex-col gap-2 pointer-events-none">
      {items.map((t) => (
        <div key={t.id} className={`pointer-events-auto flex items-center gap-3 rounded-lg border bg-surface-raised text-fg shadow-overlay px-3.5 py-2.5 text-base animate-rise ${TONES[t.tone] || TONES.neutral}`}>
          <span className={t.tone === "danger" ? "text-danger" : ""}>{t.message}</span>
          {t.action && (
            <button type="button" className="text-accent font-medium"
                    onClick={() => { t.action.onClick(); drop(t.id); }}>{t.action.label}</button>
          )}
          <button type="button" aria-label="Dismiss" className="text-fg-subtle hover:text-fg" onClick={() => drop(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
