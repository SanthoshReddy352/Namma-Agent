import { StepList } from "./Activity.jsx";

// Live "what the assistant is doing" panel during a turn: streamed thinking,
// spoken preambles, and tool steps (running/ok/fail). Shares its row renderer
// (StepList) with the persisted Activity strip so live and replayed look identical.
export default function Timeline({ items, onApprove }) {
  if (!items.length) return null;
  const awaitingApproval = items.some((it) => it.kind === "approval");
  const thinking = items.some((it) => it.kind === "thinking");
  const label = awaitingApproval ? "waiting for you" : thinking ? "thinking" : "working";
  return (
    <div className="flex gap-3 animate-rise">
      <div className="h-7 w-7 shrink-0" />
      <div className="flex-1 rounded-xl border border-line dark:border-night-line bg-paper-soft dark:bg-night-soft px-3.5 py-2.5">
        <div className="text-[10px] uppercase tracking-wider text-ink-faint dark:text-night-faint mb-1.5">
          {label}
        </div>
        <StepList items={items} onApprove={onApprove} />
      </div>
    </div>
  );
}
