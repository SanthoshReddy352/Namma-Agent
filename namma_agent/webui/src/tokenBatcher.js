// Phase 6 chat performance: coalesce streamed `token` events and flush them as
// ONE state update per session every ~50 ms, instead of one React update per
// token. Any other event must call flush() first so ordering is preserved
// (e.g. a tool_started never lands before the text that preceded it).
// Browsers throw "Illegal invocation" when setTimeout is called as a method of
// another object, so the default timers are wrappers, never the bare functions.
const DEFAULT_TIMERS = { set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id) };

export function createTokenBatcher(onFlush, delay = 50, timers = DEFAULT_TIMERS) {
  const pending = new Map();   // session key -> concatenated text
  let timer = null;

  function flush() {
    if (timer !== null) { timers.clear(timer); timer = null; }
    if (!pending.size) return;
    const entries = [...pending];
    pending.clear();
    for (const [key, text] of entries) onFlush(key, text);
  }

  function push(key, text) {
    if (!text) return;
    pending.set(key, (pending.get(key) || "") + text);
    if (timer === null) timer = timers.set(flush, delay);
  }

  return { push, flush, get size() { return pending.size; } };
}
