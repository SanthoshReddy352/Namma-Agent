import { useEffect, useId, useMemo, useRef, useState } from "react";
import Dialog from "./Dialog.jsx";

// Phase 9: the model picker overlay (Hermes-style), opened from the composer's
// model chip, the status bar or the command palette — no longer a <select> in
// the page header. Search treats hyphens, dots, underscores and spaces as
// equivalent ("gpt41mini" finds "gpt-4.1-mini").
export const loose = (s) => String(s || "").toLowerCase().replace(/[-._\s/]+/g, "");

export function matchModels(models, query) {
  const q = loose(query);
  if (!q) return models;
  return models.filter((m) => loose(`${m.label} ${m.model || ""} ${m.provider || ""}`).includes(q));
}

export default function ModelPicker({ models = [], current, onPick, onClose, onManage }) {
  const [query, setQuery] = useState("");
  const results = useMemo(() => matchModels(models, query), [models, query]);
  const [index, setIndex] = useState(0);
  const listRef = useRef(null);
  const id = useId();

  useEffect(() => {
    const at = results.findIndex((m) => m.id === current);
    setIndex(at >= 0 ? at : 0);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [index]);

  function pick(m) {
    if (!m) return;
    onClose();
    if (m.id !== current) onPick(m.id);
  }
  function onKeyDown(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(results.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(results[index]); }
  }

  return (
    <Dialog onClose={onClose} labelledBy={`${id}-title`} className="self-start mt-[14vh] overflow-hidden">
      <div className="flex items-center justify-between px-4 pt-3.5">
        <h2 id={`${id}-title`} className="text-base font-semibold">Choose a model</h2>
        {onManage && (
          <button type="button" onClick={() => { onClose(); onManage(); }} className="text-sm text-accent hover:underline">
            Manage models
          </button>
        )}
      </div>
      <div className="px-4 pt-2 pb-2 border-b border-border">
        <input data-autofocus autoFocus value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKeyDown}
               role="combobox" aria-expanded="true" aria-controls={id} aria-label="Search models"
               aria-activedescendant={results[index] ? `${id}-${index}` : undefined}
               placeholder="Search models…"
               className="w-full h-9 rounded-md border border-border bg-surface px-3 text-base text-fg placeholder:text-fg-subtle" />
      </div>
      <ul ref={listRef} id={id} role="listbox" aria-label="Models" className="max-h-[50vh] overflow-y-auto p-1.5">
        {models.length === 0 && (
          <li className="px-3 py-6 text-center text-base text-fg-muted">
            No models yet.{onManage && <> <button type="button" className="text-accent hover:underline" onClick={() => { onClose(); onManage(); }}>Add one</button></>}
          </li>
        )}
        {models.length > 0 && results.length === 0 && (
          <li className="px-3 py-6 text-center text-base text-fg-muted">No model matches “{query}”</li>
        )}
        {results.map((m, i) => (
          <li key={m.id} id={`${id}-${i}`} role="option" aria-selected={m.id === current} data-index={i}
              onMouseMove={() => setIndex(i)} onClick={() => pick(m)}
              className={`flex items-center justify-between gap-3 rounded-md px-3 py-2 cursor-pointer ${i === index ? "bg-accent-wash" : ""}`}>
            <span className="min-w-0">
              <span className="block truncate text-base text-fg">{m.label}</span>
              {(m.model || m.provider) && m.model !== m.label && (
                <span className="block truncate text-sm text-fg-muted">{[m.provider, m.model].filter(Boolean).join(" · ")}</span>
              )}
            </span>
            {m.id === current && <span className="shrink-0 text-xs font-medium text-accent">Current</span>}
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
