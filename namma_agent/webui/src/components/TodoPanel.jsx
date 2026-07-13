import { useState } from "react";

// The agent's live TODO plan, docked above the message bar. Driven entirely by
// `todo_updated` events from the update_todos tool: the list is a full-state
// replace, so this just renders the latest snapshot. Collapsible — the collapsed
// bar shows "Todos (x/X done)" left + an expand arrow right; expanded, the list
// scrolls inside a safety height (like the composer) so a huge plan never pushes
// the message bar off screen.
export default function TodoPanel({ todos = [] }) {
  const [collapsed, setCollapsed] = useState(false);
  if (!todos.length) return null;
  const done = todos.filter((t) => t.status === "done").length;
  const label = `Todos (${done}/${todos.length} done)`;

  return (
    <div className="mb-2 rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel shadow-soft overflow-hidden animate-rise">
      <button
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? "Expand the todo list" : "Collapse the todo list"}
        className="w-full flex items-center justify-between px-3.5 py-2 text-left hover:bg-paper-soft dark:hover:bg-night-soft transition">
        <span className="flex items-center gap-2 text-[12.5px] font-medium text-ink-soft dark:text-night-ink">
          <ChecklistIcon />
          {label}
        </span>
        <span className="text-ink-faint dark:text-night-faint">
          {collapsed ? <ChevronUpIcon /> : <ChevronDownIcon />}
        </span>
      </button>
      {!collapsed && (
        <ul className="max-h-[200px] overflow-y-auto px-3.5 pb-2.5 space-y-1">
          {todos.map((t, i) => (
            <li key={i}>
              <TodoRow item={t} />
              {(t.subtasks || []).length > 0 && (
                <ul className="ml-6 mt-1 space-y-1">
                  {t.subtasks.map((s, j) => (
                    <li key={j}><TodoRow item={s} small /></li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TodoRow({ item, small }) {
  const { text, status } = item;
  return (
    <div className={`flex items-start gap-2 ${small ? "text-[12.5px]" : "text-[13.5px]"}`}>
      <span className={`shrink-0 ${small ? "mt-[3px]" : "mt-[2.5px]"}`}><StatusIcon status={status} small={small} /></span>
      <span className={
        status === "done"
          ? "line-through text-ink-faint dark:text-night-faint"
          : status === "in_progress"
            ? "text-ink dark:text-night-ink font-medium"
            : "text-ink-soft dark:text-night-faint"
      }>
        {text}
      </span>
    </div>
  );
}

function StatusIcon({ status, small }) {
  const s = small ? 12 : 14;
  if (status === "done") {
    return (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
           strokeLinecap="round" strokeLinejoin="round" className="text-emerald-500">
        <circle cx="12" cy="12" r="9" /><path d="m8.5 12.5 2.5 2.5 5-5.5" />
      </svg>
    );
  }
  if (status === "in_progress") {
    // A spinning half-ring: the "working on this now" marker.
    return (
      <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
           strokeLinecap="round" className="text-brand animate-spin" style={{ animationDuration: "1.2s" }}>
        <path d="M21 12a9 9 0 1 1-9-9" />
      </svg>
    );
  }
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         className="text-ink-faint dark:text-night-faint">
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

const ChecklistIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" className="text-brand-deep">
    <path d="m3 6 2 2 3.5-4" /><path d="M11 6h10" />
    <path d="m3 14 2 2 3.5-4" /><path d="M11 14h10" />
  </svg>
);
const ChevronDownIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
);
const ChevronUpIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round"><path d="m18 15-6-6-6 6" /></svg>
);
