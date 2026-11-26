// Small Phase 6 primitives: keyboard hint, empty and error states, skeleton.

export function Kbd({ children }) {
  return (
    <kbd className="inline-flex items-center rounded-sm border border-border bg-surface-sunken px-1.5 font-mono text-2xs text-fg-muted">
      {children}
    </kbd>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="flex flex-col items-center justify-center text-center gap-2 py-10 text-fg-muted">
      <div className="text-base font-medium text-fg">{title}</div>
      {children && <div className="text-sm max-w-sm">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", children, onRetry }) {
  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger/5 px-3.5 py-2.5 text-base">
      <div className="font-medium text-danger">{title}</div>
      {children && <div className="mt-0.5 text-fg-muted text-sm">{children}</div>}
      {onRetry && <button type="button" onClick={onRetry} className="mt-2 text-sm font-medium text-accent">Retry</button>}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full", lines = 1 }) {
  return (
    <div aria-hidden="true" className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`rounded-md bg-surface-sunken animate-pulse ${className}`} />
      ))}
    </div>
  );
}
