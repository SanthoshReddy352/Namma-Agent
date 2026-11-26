import { useEffect, useRef } from "react";
import { StepList, StatusIcon } from "./Activity.jsx";
import { IconClock } from "@tabler/icons-react";

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
      <div className="flex-1 min-w-0 rounded-2xl border border-border bg-surface-raised shadow-soft overflow-hidden">
        <div className="flex items-center gap-2 px-3.5 py-2 text-sm font-medium text-fg-soft border-b border-border/70">
          {awaitingApproval ? (
            <IconClock size={14} stroke={2} className="text-amber-500" aria-hidden="true" />
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
