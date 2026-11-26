import { Suspense, createContext, lazy, memo } from "react";

// A2UI spike (Phase 4): an ```a2ui fence (written by the show_ui tool, already
// validated server-side) renders as an interactive card with the OFFICIAL
// renderer — @a2ui/react + @a2ui/web_core's v0.9 basic catalogue. It loads
// lazily, in its own chunk, so the core bundle doesn't pay for it until a chat
// actually shows a UI. Button presses go back to the chat as a "[ui action]"
// message via UiActionContext.
export const UiActionContext = createContext(null);

const SurfaceImpl = lazy(() => import("./A2uiSurfaceImpl.jsx"));

function Shell({ children }) {
  return <div className="my-2 rounded-xl border border-border p-3 bg-surface-raised">{children}</div>;
}

function A2uiBlock({ source }) {
  let payload = null, error = null;
  try {
    payload = JSON.parse(source);
    if (!Array.isArray(payload?.messages)) throw new Error("no messages");
  } catch (e) { error = e; }
  if (error) {
    return (
      <div className="my-2 text-sm">
        <div className="text-warning mb-1">Couldn't show this interface: {String(error.message)}</div>
        <pre><code>{source}</code></pre>
      </div>
    );
  }
  return (
    <Shell>
      {payload.title && <div className="text-sm font-medium mb-2 text-fg">{payload.title}</div>}
      <Suspense fallback={<div role="status" className="text-sm text-fg-subtle">Loading interface…</div>}>
        <SurfaceImpl messages={payload.messages} source={source} />
      </Suspense>
    </Shell>
  );
}

export default memo(A2uiBlock, (a, b) => a.source === b.source);
