import { useEffect, useId, useRef, useState } from "react";
import { IconCheck, IconChevronDown } from "@tabler/icons-react";

// Phase 9 primitive: a button that opens an anchored list to pick one option
// (role="listbox"). Arrow keys / Home / End move, Enter or Space picks, Escape
// or a click outside closes and returns focus to the button. Opens upward by
// default because it lives in the composer at the bottom of the window.
//
// options: [{ id, label, description?, leading? }]
export default function SelectMenu({
  value, options, onChange, label, renderTrigger, placement = "top", className = "", menuClassName = "",
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const btnRef = useRef(null);
  const listRef = useRef(null);
  const id = useId();
  const current = options.find((o) => o.id === value) || options[0];

  useEffect(() => {
    if (!open) return undefined;
    setActive(Math.max(0, options.findIndex((o) => o.id === value)));
    const t = setTimeout(() => listRef.current?.focus(), 0);
    const onDown = (e) => {
      if (!listRef.current?.contains(e.target) && !btnRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => { clearTimeout(t); document.removeEventListener("mousedown", onDown); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function close(refocus = true) {
    setOpen(false);
    if (refocus) btnRef.current?.focus();
  }
  function pick(opt) {
    if (opt) onChange(opt.id);
    close();
  }
  function onKeyDown(e) {
    const last = options.length - 1;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => (i >= last ? 0 : i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i <= 0 ? last : i - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(last); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(options[active]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Tab") { close(false); }
  }

  return (
    <div className={`relative ${className}`}>
      <button ref={btnRef} type="button" aria-haspopup="listbox" aria-expanded={open}
              aria-controls={open ? id : undefined} aria-label={label ? `${label}: ${current?.label}` : undefined}
              onClick={() => setOpen((o) => !o)}
              onKeyDown={(e) => { if (!open && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); setOpen(true); } }}
              className="inline-flex items-center gap-1.5 h-8 rounded-md px-2 text-sm text-fg-muted hover:text-fg hover:bg-surface-sunken transition-colors duration-fast">
        {renderTrigger ? renderTrigger(current, open) : current?.label}
        <IconChevronDown size={12} stroke={2} className={`transition-transform duration-fast ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <ul ref={listRef} id={id} role="listbox" tabIndex={-1} aria-label={label}
            aria-activedescendant={`${id}-${active}`} onKeyDown={onKeyDown}
            className={`absolute z-dropdown ${placement === "top" ? "bottom-full mb-2" : "top-full mt-2"} left-0 w-72 rounded-lg border border-border bg-surface-raised text-fg shadow-overlay p-1 outline-none animate-rise ${menuClassName}`}>
          {options.map((o, i) => (
            <li key={o.id} id={`${id}-${i}`} role="option" aria-selected={o.id === value}
                onMouseMove={() => setActive(i)} onClick={() => pick(o)}
                className={`flex items-start gap-2.5 rounded-md px-2.5 py-2 cursor-pointer ${i === active ? "bg-accent-wash" : ""}`}>
              {o.leading}
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2 text-base font-medium">
                  {o.label}
                  {o.id === value && (
                    <IconCheck size={14} stroke={2.4} className="text-accent shrink-0" aria-hidden="true" />
                  )}
                </span>
                {o.description && <span className="block text-sm text-fg-muted">{o.description}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
