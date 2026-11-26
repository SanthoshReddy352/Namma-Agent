import { useCallback, useEffect, useRef, useState } from "react";

// Phase 9: settings save themselves — no Save button. Edits are applied to
// the view at once (optimistic), batched, and written after a short pause.
// `save(batch)` must resolve truthy on success; a falsy result or a throw marks
// the batch failed: `onError(batch)` lets the caller roll back, and `retry()`
// re-sends the same batch.
//
//   const auto = useAutosave(save, { delay: 400, merge });
//   auto.queue(patch)   // schedule (merged with anything still pending)
//   auto.flush()        // write now (e.g. on blur for secrets)
//   auto.status         // "idle" | "saving" | "saved" | "error"
export const isSaveOk = (r) => !!r && r.ok !== false && !r.detail && !r.error;

const shallowMerge = (a, b) => ({ ...(a || {}), ...(b || {}) });

export function useAutosave(save, { delay = 400, merge = shallowMerge, onError, onSaved } = {}) {
  const [status, setStatus] = useState("idle");
  const pending = useRef(null);
  const failed = useRef(null);
  const timer = useRef(null);
  const savedTimer = useRef(null);
  const latest = useRef({ save, merge, onError, onSaved });
  latest.current = { save, merge, onError, onSaved };

  const run = useCallback(async (batch) => {
    setStatus("saving");
    let ok = false;
    try { ok = isSaveOk(await latest.current.save(batch)); } catch { ok = false; }
    if (ok) {
      failed.current = null;
      latest.current.onSaved?.(batch);
      // A newer edit may already be queued; only show "Saved" when idle.
      if (!pending.current) {
        setStatus("saved");
        clearTimeout(savedTimer.current);
        savedTimer.current = setTimeout(() => setStatus((s) => (s === "saved" ? "idle" : s)), 2000);
      }
    } else {
      failed.current = batch;
      setStatus("error");
      latest.current.onError?.(batch);
    }
    return ok;
  }, []);

  const flush = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = null;
    const batch = pending.current;
    pending.current = null;
    return batch ? run(batch) : Promise.resolve(true);
  }, [run]);

  const queue = useCallback((patch, { immediate = false } = {}) => {
    pending.current = pending.current ? latest.current.merge(pending.current, patch) : patch;
    clearTimeout(timer.current);
    if (immediate) return flush();
    timer.current = setTimeout(flush, delay);
    return undefined;
  }, [delay, flush]);

  const retry = useCallback(() => (failed.current ? run(failed.current) : Promise.resolve(true)), [run]);

  // Write anything still pending when the surface closes.
  useEffect(() => () => {
    clearTimeout(savedTimer.current);
    if (pending.current) { clearTimeout(timer.current); const b = pending.current; pending.current = null; latest.current.save(b); }
  }, []);

  return { status, queue, flush, retry };
}
