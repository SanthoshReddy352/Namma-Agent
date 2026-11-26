import { useState } from "react";
import { IconChevronDown, IconChevronUp, IconCircleCheck, IconListCheck, IconLoader2 } from "@tabler/icons-react";

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
    <div className="mb-2 rounded-2xl border border-border bg-surface-raised shadow-soft overflow-hidden animate-rise">
      <button
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? "Expand the todo list" : "Collapse the todo list"}
        className="w-full flex items-center justify-between px-3.5 py-2 text-left hover:bg-surface-hover transition">
        <span className="flex items-center gap-2 text-sm font-medium text-fg-soft">
          <ChecklistIcon />
          {label}
        </span>
        <span className="text-fg-subtle">
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
    <div className={`flex items-start gap-2 ${small ? "text-sm" : "text-base"}`}>
      <span className={`shrink-0 ${small ? "mt-[3px]" : "mt-[2.5px]"}`}><StatusIcon status={status} small={small} /></span>
      <span className={
        status === "done"
          ? "line-through text-fg-subtle"
          : status === "in_progress"
            ? "text-fg font-medium"
            : "text-fg-muted"
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
      <IconCircleCheck size={s} stroke={2.2} className="text-emerald-500" aria-hidden="true" />
    );
  }
  if (status === "in_progress") {
    // A spinning half-ring: the "working on this now" marker.
    return (
      <IconLoader2 size={s} stroke={2.4} className="text-brand animate-spin" style={{ animationDuration: "1.2s" }} aria-hidden="true" />
    );
  }
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         className="text-fg-subtle">
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

const ChecklistIcon = () => (
  <IconListCheck size={14} stroke={2} className="text-brand-deep" aria-hidden="true" />
);
const ChevronDownIcon = () => (
  <IconChevronDown size={16} stroke={2} aria-hidden="true" />
);
const ChevronUpIcon = () => (
  <IconChevronUp size={16} stroke={2} aria-hidden="true" />
);
