import { IconCheck } from "@tabler/icons-react";
// Phase 9: the inline state of an autosaving surface ("Saving…", "Saved",
// "Couldn't save — Retry"). A polite live region, so screen readers hear it.
export default function SaveStatus({ status, onRetry, className = "" }) {
  return (
    <span role="status" aria-live="polite" className={`inline-flex items-center gap-1.5 text-sm ${className}`}>
      {status === "saving" && <span className="text-fg-muted">Saving…</span>}
      {status === "saved" && (
        <span className="inline-flex items-center gap-1 text-success">
          <IconCheck size={13} stroke={2.4} aria-hidden="true" />
          Saved
        </span>
      )}
      {status === "error" && (
        <span className="inline-flex items-center gap-1.5 text-danger">
          Couldn’t save.
          {onRetry && <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2">Retry</button>}
        </span>
      )}
    </span>
  );
}
