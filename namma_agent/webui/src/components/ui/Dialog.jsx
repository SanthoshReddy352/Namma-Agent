import { useEffect, useId, useRef } from "react";

// Phase 6 primitive: a modal dialog with role="dialog", aria-modal, a focus
// trap, Escape to close, focus restore to the opener, and a SAFE initial focus:
// the element marked `data-autofocus`, else the first control that is not
// marked `data-destructive` — so Enter can never confirm a delete (BUG-12).
//
// Dialogs stack: only the top one handles Escape/Tab. `isDialogOpen()` lets
// global shortcuts (Escape = stop the turn) stand down while any dialog is up.

const stack = [];
export const isDialogOpen = () => stack.length > 0;

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", 'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])", "textarea:not([disabled])", '[tabindex]:not([tabindex="-1"])',
].join(", ");

function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)]
    .filter((el) => !el.closest("[inert]") && el.getAttribute("aria-hidden") !== "true");
}

export function pickInitialFocus(root) {
  const marked = root.querySelector("[data-autofocus]");
  if (marked) return marked;
  return focusables(root).find((el) => !el.hasAttribute("data-destructive")) || root;
}

export default function Dialog({
  open = true, onClose, title, description, children, footer,
  className = "", size = "md", dismissOnBackdrop = true, labelledBy,
}) {
  const panelRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const autoId = useId();
  const titleId = labelledBy || `${autoId}-title`;
  const descId = description ? `${autoId}-desc` : undefined;

  useEffect(() => {
    if (!open) return undefined;
    const token = {};
    stack.push(token);
    const opener = document.activeElement;
    const panel = panelRef.current;
    // Initial focus once children (inputs, lazy content) have mounted.
    const t = setTimeout(() => {
      if (panel && !panel.contains(document.activeElement)) pickInitialFocus(panel)?.focus?.();
    }, 0);

    function onKey(e) {
      if (stack[stack.length - 1] !== token || !panel) return;
      if (e.key === "Escape") {
        e.stopPropagation(); e.preventDefault();
        onCloseRef.current?.();
        return;
      }
      if (e.key !== "Tab") return;
      const els = focusables(panel);
      if (!els.length) { e.preventDefault(); panel.focus(); return; }
      const first = els[0], last = els[els.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panel.contains(active))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (active === last || !panel.contains(active))) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey, true);
      const i = stack.indexOf(token);
      if (i >= 0) stack.splice(i, 1);
      if (opener && typeof opener.focus === "function" && document.contains(opener)) opener.focus();
    };
  }, [open]);

  if (!open) return null;
  const width = size === "sm" ? "w-[400px]" : size === "lg" ? "w-[880px]" : "w-[480px]";
  return (
    <div className="fixed inset-0 z-modal grid place-items-center bg-black/40 p-4"
         onMouseDown={(e) => { if (dismissOnBackdrop && e.target === e.currentTarget) onClose?.(); }}>
      <div ref={panelRef} role="dialog" aria-modal="true"
           aria-labelledby={title != null || labelledBy ? titleId : undefined}
           aria-describedby={descId} tabIndex={-1}
           className={`${width} max-w-full rounded-lg bg-surface-raised text-fg border border-border shadow-overlay outline-none animate-rise ${className}`}>
        {title != null && (
          <div className="px-5 pt-5">
            <h2 id={titleId} className="text-md font-semibold">{title}</h2>
            {description && <p id={descId} className="mt-1 text-base text-fg-muted">{description}</p>}
          </div>
        )}
        {children}
        {footer && <div className="flex justify-end gap-2 px-5 pb-5 pt-4">{footer}</div>}
      </div>
    </div>
  );
}
