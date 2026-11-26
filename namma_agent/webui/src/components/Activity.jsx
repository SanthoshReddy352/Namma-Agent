import { useEffect, useRef, useState } from "react";
import { copyText } from "../clipboard.js";
import { IconActivity, IconAlertTriangle, IconChevronDown, IconCircleCheck, IconCircleX, IconLoader2, IconMessage, IconSparkles } from "@tabler/icons-react";

// ── Friendly tool labels (Hermes-style: "Searched …", "Ran …", "Opened …") ──────
// Map a tool name + its args to a short human phrase. Unknown tools fall back to a
// humanized name. The detail (query / path / command) is pulled from common arg keys.
const VERBS = {
  web_search: "Searched the web", search_google: "Searched Google",
  web_extract: "Read a page", web_crawl: "Crawled the web", read_document: "Read a document",
  open_browser_url: "Opened a link", open_app: "Opened an app", list_open_apps: "Listed open apps",
  run_shell: "Ran a command",
  read_file: "Read a file", write_file: "Wrote a file", list_dir: "Listed a folder",
  move_path: "Moved a file", copy_path: "Copied a file", delete_path: "Deleted a file",
  make_dir: "Created a folder", find_files: "Searched files", organize_dir: "Organized a folder",
  take_screenshot: "Captured a screenshot", read_text_from_image: "Read text from an image",
  get_weather: "Checked the weather", get_news: "Fetched the news",
  send_notification: "Sent a message",
  gmail_list: "Checked Gmail", gmail_read: "Read an email", gmail_send: "Sent an email",
  calendar_agenda: "Checked the calendar", calendar_create_event: "Created an event",
  recall_facts: "Recalled memory", remember_fact: "Saved a memory", read_memory: "Read memory",
  recall_sessions: "Searched past chats",
  // Engram — the native memory engine.
  memory_search: "Searched memory", memory_save: "Saved to memory",
  memory_forget: "Forgot a memory", search_conversations: "Searched past chats",
  // Tool search (deferred tools).
  tool_search: "Searched tools", tool_describe: "Looked up tool", tool_call: "Ran tool",
  use_skill: "Used a skill", list_skills: "Listed skills",
  delegate_task: "Delegated to sub-agents", background_task: "Started a background task",
  check_background_task: "Checked a background task", cancel_background_task: "Cancelled a background task",
  add_task: "Added a task", list_tasks: "Listed tasks", complete_task: "Completed a task",
  add_reminder: "Set a reminder", list_reminders: "Listed reminders",
  render_diagram: "Drew a diagram", render_simulation: "Built a simulation",
  ping_host: "Pinged a host", public_ip: "Checked the public IP",
  update_todos: "Updated the todo plan",
};
const DETAIL_KEYS = ["query", "q", "url", "path", "file_path", "command", "cmd",
                     "pattern", "name", "place", "location", "topic", "to", "title"];

function humanize(name = "") {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function toolLabel(tool, args = {}) {
  const verb = VERBS[tool] || humanize(tool);
  let detail = "";
  for (const k of DETAIL_KEYS) {
    const v = args && args[k];
    if (typeof v === "string" && v.trim()) { detail = v.trim(); break; }
  }
  if (detail.length > 60) detail = detail.slice(0, 59) + "…";
  return detail ? `${verb} — ${detail}` : verb;
}

// Status icon — the same visual language as the TodoPanel: spinning ring while a
// step runs, green check when it succeeded, red cross when it failed.
export function StatusIcon({ state, size = 14 }) {
  if (state === "running") {
    return (
      <IconLoader2 size={size} stroke={2.4} className="text-brand animate-spin" style={{ animationDuration: "1.2s" }} aria-hidden="true" />
    );
  }
  if (state === "ok") {
    return (
      <IconCircleCheck size={size} stroke={2.2} className="text-emerald-500" aria-hidden="true" />
    );
  }
  if (state === "fail") {
    return (
      <IconCircleX size={size} stroke={2.2} className="text-red-500" aria-hidden="true" />
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         className="text-fg-subtle">
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

const SparkIcon = ({ size = 12 }) => (
  <IconSparkles size={size} stroke={1.8} aria-hidden="true" />
);

// Streamed model reasoning — an inset "Thinking" panel, capped at a safety height
// (it can run long) with internal scroll, so it never swallows the screen.
function ThinkingBlock({ text }) {
  return (
    <li className="rounded-xl bg-surface-hover border-l-2 border-brand/50 px-3 py-2">
      <div className="flex items-center gap-1.5 text-2xs uppercase tracking-wider font-medium text-brand-deep dark:text-brand mb-1">
        <SparkIcon />
        Thinking
      </div>
      <div className="max-h-[160px] overflow-y-auto text-sm text-fg-muted whitespace-pre-wrap leading-relaxed">
        {text}
      </div>
    </li>
  );
}

// Mini terminal — a shell step rendered as a collapsible terminal panel: the command
// as the header line, merged stdout/stderr in a dark monospace body. Auto-opens and
// follows the tail while the command streams; the user can pin it open/closed.
function TerminalBlock({ item }) {
  const [userOpen, setUserOpen] = useState(null); // null = auto (open while running)
  const running = item.state === "running";
  const open = userOpen === null ? running : userOpen;
  const cmd = (item.args && (item.args.command || item.args.cmd)) || "";
  const out = item.output || "";
  const declined = item.state === "fail" && item.summary === "declined";
  const bodyRef = useRef(null);
  useEffect(() => {
    // Follow the live tail (like a real terminal) while output streams in.
    if (running && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [out, running]);
  return (
    <li className="rounded-xl overflow-hidden border border-border bg-zinc-900">
      <button type="button" onClick={() => setUserOpen(!open)}
              title={open ? "Collapse the terminal output" : "Show the terminal output"}
              className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-zinc-800 transition">
        <span className="shrink-0"><StatusIcon state={item.state} /></span>
        <code className="min-w-0 flex-1 truncate font-mono text-sm text-zinc-100">
          <span className="text-emerald-400 select-none">$ </span>{cmd}
        </code>
        {declined && (
          <span className="shrink-0 text-2xs font-medium text-amber-400">declined</span>
        )}
        <Chevron open={open} />
      </button>
      {open && (out || running) && (
        <pre ref={bodyRef}
             className="max-h-[240px] overflow-y-auto px-3 pb-2.5 pt-1 border-t border-zinc-700/60 font-mono text-xs leading-relaxed text-zinc-300 whitespace-pre-wrap break-words">
          {out || (running ? "…" : "")}
        </pre>
      )}
    </li>
  );
}

// Inline tool-approval prompt (Hermes-style): shows what the assistant wants to run,
// right where it happens in the activity stream, with Approve / Deny actions. Used
// only in the LIVE timeline — persisted activity records the outcome as a tool step.
function ApprovalCard({ item, onApprove }) {
  const [open, setOpen] = useState(false);
  const hasArgs = item.args && Object.keys(item.args).length > 0;
  return (
    <li className="rounded-xl border border-amber-300/70 dark:border-amber-500/40 bg-amber-50/80 dark:bg-amber-500/10 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <IconAlertTriangle size={15} stroke={2} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-sm text-fg">
            Needs your approval to run <span className="font-medium">{toolLabel(item.tool, item.args)}</span>.
          </div>
          {hasArgs && (
            <button type="button" onClick={() => setOpen((o) => !o)}
                    className="mt-0.5 text-xs text-fg-subtle hover:text-fg">
              {open ? "Hide details" : "Show details"}
            </button>
          )}
          {open && hasArgs && (
            <pre className="mt-1.5 text-xs bg-surface-sunken rounded-md p-2.5 overflow-auto max-h-40 text-fg-muted">
              {JSON.stringify(item.args, null, 2)}
            </pre>
          )}
          <div className="flex flex-wrap gap-2 mt-2">
            <button onClick={() => onApprove?.(item.id, true, "once")}
                    className="px-3 py-1 rounded-md bg-brand text-white hover:bg-brand-deep text-sm font-medium">
              Allow once
            </button>
            <button onClick={() => onApprove?.(item.id, true, "session")}
                    title="Don't ask again for this tool for the rest of this chat"
                    className="px-3 py-1 rounded-md border border-brand/60 text-brand-deep dark:text-brand hover:bg-accent-wash text-sm font-medium">
              Allow for session
            </button>
            <button onClick={() => onApprove?.(item.id, false, "once")}
                    className="px-3 py-1 rounded-md text-fg-soft border border-border hover:bg-surface-hover text-sm">
              Deny
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}

// Step inspector (Phase 4): click a tool step to see its full input and output,
// how long it took, and copy either.
function Inspector({ item }) {
  const args = JSON.stringify(item.args || {}, null, 2);
  const out = item.output || item.summary || "";
  return (
    <div className="mt-1.5 ml-5 space-y-1.5 text-xs">
      <div className="flex items-center gap-3 text-fg-subtle">
        <span className="font-mono">{item.tool}</span>
        {typeof item.ms === "number" && <span>{item.ms < 1000 ? `${item.ms} ms` : `${(item.ms / 1000).toFixed(1)} s`}</span>}
        <span>{item.state}</span>
      </div>
      <InspectorPane label="Input" text={args} />
      {out && <InspectorPane label="Output" text={out} />}
    </div>
  );
}

function InspectorPane({ label, text }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <div className="flex items-center justify-between px-2 py-1 bg-surface-hover text-2xs text-fg-subtle">
        <span>{label}</span>
        <button type="button" aria-label={`Copy ${label.toLowerCase()}`}
                onClick={async () => { if (await copyText(text)) { setCopied(true); setTimeout(() => setCopied(false), 1200); } }}
                className="hover:text-fg">{copied ? "Copied" : "Copy"}</button>
      </div>
      <pre className="max-h-48 overflow-auto px-2 py-1.5 text-xs whitespace-pre-wrap break-words">{text}</pre>
    </div>
  );
}

function PlanCard({ plan }) {
  const done = plan.filter((t) => t.status === "done").length;
  return (
    <li className="rounded-lg border border-border px-2.5 py-1.5 text-sm">
      <div className="text-fg-subtle mb-0.5">Plan · {done}/{plan.length} done</div>
      <ul className="space-y-0.5">
        {plan.map((t, i) => (
          <li key={i} className={t.status === "done" ? "line-through text-fg-subtle" : "text-fg"}>
            {t.status === "done" ? "✓" : t.status === "in_progress" ? "▸" : "○"} {t.text}
          </li>
        ))}
      </ul>
    </li>
  );
}

function ToolRow({ it }) {
  const [open, setOpen] = useState(false);
  const declined = it.state === "fail" && it.summary === "declined";
  return (
    <li className="text-base">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
              title={open ? "Hide details" : "Show input, output and timing"}
              className="flex items-start gap-2 text-left w-full rounded hover:bg-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
        <span className="mt-[2.5px] shrink-0"><StatusIcon state={it.state} /></span>
        <span className={it.state === "running"
          ? "text-fg font-medium"
          : "text-fg-soft"}>
          {toolLabel(it.tool, it.args)}
          {declined && (
            <span className="ml-1.5 text-xs font-medium text-warning">— you declined this</span>
          )}
          {it.summary && it.state === "fail" && !declined && (
            <span className="ml-1.5 text-red-500">— {String(it.summary).slice(0, 80)}</span>
          )}
          {typeof it.ms === "number" && it.ms >= 1000 && (
            <span className="ml-1.5 text-xs text-fg-subtle">{(it.ms / 1000).toFixed(1)} s</span>
          )}
        </span>
      </button>
      {open && <Inspector item={it} />}
    </li>
  );
}

// One row per activity item: a streamed Thinking block, a spoken preamble, a tool
// step (status icon + friendly label + result summary), or an inline approval prompt.
export function StepList({ items, onApprove }) {
  return (
    <ul className="space-y-1.5">
      {items.map((it, i) => {
        if (it.kind === "approval") {
          return <ApprovalCard key={it.id ?? i} item={it} onApprove={onApprove} />;
        }
        if (it.kind === "thinking") {
          return <ThinkingBlock key={i} text={it.text} />;
        }
        if (it.kind === "preamble") {
          return (
            <li key={i} className="flex items-start gap-2 text-sm italic text-fg-muted">
              <IconMessage size={13} stroke={1.8} className="mt-[3px] shrink-0" aria-hidden="true" />
              <span>“{it.text}”</span>
            </li>
          );
        }
        if (it.kind === "notice") {
          return (
            <li key={i} role="note" className="flex items-start gap-2 text-sm text-warning">
              <span aria-hidden="true">ⓘ</span><span>{it.text}</span>
            </li>
          );
        }
        if (it.kind === "plan") {
          return <PlanCard key={i} plan={it.plan || []} />;
        }
        if (it.tool === "run_shell") {
          return <TerminalBlock key={i} item={it} />;
        }
        return <ToolRow key={i} it={it} />;
      })}
    </ul>
  );
}

// One-line summary of a finished activity timeline, e.g. "Thought it through · 3 steps".
function summarize(items) {
  const tools = items.filter((it) => it.kind === "tool");
  const thought = items.some((it) => it.kind === "thinking");
  const bits = [];
  if (thought) bits.push("Thought it through");
  if (tools.length) bits.push(`${tools.length} ${tools.length === 1 ? "step" : "steps"}`);
  return bits.join(" · ") || "Activity";
}

const ActivityIcon = () => (
  <IconActivity size={14} stroke={2} className="text-brand-deep" aria-hidden="true" />
);

const Chevron = ({ open }) => (
  <IconChevronDown size={16} stroke={2} className={`text-ink-faint dark:text-night-faint transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
);

// Persisted activity shown UNDER an assistant reply: the same premium card as the
// TodoPanel — a header bar (icon + summary + chevron) that expands into the
// thinking + tool steps that produced the answer, scrolling inside a safety height.
export default function Activity({ items }) {
  const [open, setOpen] = useState(false);
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-2 rounded-2xl border border-border bg-surface-raised shadow-soft overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)}
              title={open ? "Collapse the activity" : "Show the thinking and tool steps behind this reply"}
              className="w-full flex items-center justify-between px-3.5 py-2 text-left hover:bg-surface-hover transition">
        <span className="flex items-center gap-2 text-sm font-medium text-fg-soft">
          <ActivityIcon />
          {summarize(items)}
        </span>
        <Chevron open={open} />
      </button>
      {open && (
        <div className="max-h-[260px] overflow-y-auto px-3.5 pb-2.5 pt-0.5 border-t border-border/70">
          <StepList items={items} />
        </div>
      )}
    </div>
  );
}
