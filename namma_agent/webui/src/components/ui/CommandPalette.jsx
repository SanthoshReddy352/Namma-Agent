import { useEffect, useId, useMemo, useRef, useState } from "react";
import Dialog from "./Dialog.jsx";
import { Kbd } from "./Misc.jsx";

// Ctrl/Cmd+K command palette. `commands` is [{id, label, group, keywords?,
// hint?, run}] supplied by the shell. Arrow keys move, Enter runs, Escape closes
// (via Dialog). Matching: every typed word must appear in label/group/keywords.
export function matchCommands(commands, query) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return commands;
  return commands.filter((c) => {
    const hay = `${c.label} ${c.group || ""} ${c.keywords || ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

export default function CommandPalette({ commands, onClose }) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const listRef = useRef(null);
  const listId = useId();
  const results = useMemo(() => matchCommands(commands, query).slice(0, 50), [commands, query]);

  useEffect(() => { setIndex(0); }, [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [index]);

  function run(cmd) {
    if (!cmd) return;
    onClose();
    // Let the palette unmount (and restore focus) before the command acts.
    setTimeout(() => cmd.run(), 0);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(results.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setIndex(0); }
    else if (e.key === "End") { e.preventDefault(); setIndex(results.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); run(results[index]); }
  }

  let lastGroup = null;
  return (
    <Dialog onClose={onClose} labelledBy={`${listId}-label`} className="self-start mt-[12vh] overflow-hidden">
      <span id={`${listId}-label`} className="sr-only">Command palette</span>
      <div className="flex items-center gap-2 border-b border-border px-4">
        <input data-autofocus autoFocus value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKeyDown}
               role="combobox" aria-expanded="true" aria-controls={listId} aria-label="Search commands"
               aria-activedescendant={results[index] ? `${listId}-${index}` : undefined}
               placeholder="Type a command or search…"
               className="flex-1 h-12 bg-transparent text-md text-fg placeholder:text-fg-subtle outline-none focus-visible:outline-none" />
        <Kbd>Esc</Kbd>
      </div>
      <ul ref={listRef} id={listId} role="listbox" aria-label="Commands" className="max-h-[50vh] overflow-y-auto p-1.5">
        {results.length === 0 && <li className="px-3 py-6 text-center text-base text-fg-muted">No matching commands</li>}
        {results.map((c, i) => {
          const header = c.group && c.group !== lastGroup ? c.group : null;
          lastGroup = c.group;
          return (
            <li key={c.id} role="presentation">
              {header && <div className="px-3 pt-2 pb-1 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">{header}</div>}
              <div id={`${listId}-${i}`} role="option" aria-selected={i === index} data-index={i}
                   onMouseMove={() => setIndex(i)} onClick={() => run(c)}
                   className={`flex items-center justify-between gap-3 rounded-md px-3 py-2 text-base cursor-pointer ${i === index ? "bg-accent-wash text-fg" : "text-fg-muted"}`}>
                <span className="truncate">{c.label}</span>
                {c.hint && <Kbd>{c.hint}</Kbd>}
              </div>
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}
