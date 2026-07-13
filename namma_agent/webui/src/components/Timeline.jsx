import { useEffect, useRef } from "react";
import { StepList, StatusIcon } from "./Activity.jsx";

// Live "what the assistant is doing" panel during a turn: streamed thinking,
// spoken preambles, tool steps (running/ok/fail), and inline approval prompts.
// Shares its row renderer (StepList) with the persisted Activity strip so live
// and replayed look identical, and wears the same premium card as the TodoPanel.
// The body scrolls inside a safety height and follows the newest step.
export default function Timeline({ items, onApprove }) {
  const bodyRef = useRef(null);
  const stickRef = useRef(true); // follow the stream only while the user is at the bottom

  useEffect(() => {
    const el = bodyRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [items]);

  if (!items.length) return null;
  const awaitingApproval = items.some((it) => it.kind === "approval");
  const thinking = items.length && items[items.length - 1].kind === "thinking";
  const label = awaitingApproval ? "Waiting for you" : thinking ? "Thinking" : "Working";

  function onScroll() {
    const el = bodyRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  return (
    <div className="flex gap-3 animate-rise">
      <div className="h-7 w-7 shrink-0" />
      <div className="flex-1 min-w-0 rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel shadow-soft overflow-hidden">
        <div className="flex items-center gap-2 px-3.5 py-2 text-[12.5px] font-medium text-ink-soft dark:text-night-ink border-b border-line/70 dark:border-night-line/70">
          {awaitingApproval ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round" className="text-amber-500">
              <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" />
            </svg>
          ) : (
            <StatusIcon state="running" />
          )}
          {label}
          <span className="inline-flex items-center gap-1 ml-0.5">
            <span className="thinking-dot" style={{ animationDelay: "0ms" }} />
            <span className="thinking-dot" style={{ animationDelay: "160ms" }} />
            <span className="thinking-dot" style={{ animationDelay: "320ms" }} />
          </span>
        </div>
        <div ref={bodyRef} onScroll={onScroll} className="max-h-[260px] overflow-y-auto px-3.5 py-2.5">
          <StepList items={items} onApprove={onApprove} />
        </div>
      </div>
    </div>
  );
}
