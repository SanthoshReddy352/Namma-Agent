import { useState } from "react";

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
  use_skill: "Used a skill", list_skills: "Listed skills",
  delegate_task: "Delegated a subtask",
  add_task: "Added a task", list_tasks: "Listed tasks", complete_task: "Completed a task",
  add_reminder: "Set a reminder", list_reminders: "Listed reminders",
  render_diagram: "Drew a diagram", render_simulation: "Built a simulation",
  ping_host: "Pinged a host", public_ip: "Checked the public IP",
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

function Dot({ state }) {
  const color =
    state === "running" ? "bg-brand animate-pulse"
    : state === "ok" ? "bg-emerald-500"
    : state === "fail" ? "bg-red-500"
    : "bg-ink-faint";
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />;
}

// Inline tool-approval prompt (Hermes-style): shows what the assistant wants to run,
// right where it happens in the activity stream, with Approve / Deny actions. Used
// only in the LIVE timeline — persisted activity never carries an "approval" item
// (it's resolved before the turn ends). `onApprove(id, approved)` answers it.
function ApprovalCard({ item, onApprove }) {
  const [open, setOpen] = useState(false);
  const hasArgs = item.args && Object.keys(item.args).length > 0;
  return (
    <li className="rounded-lg border border-amber-300/70 dark:border-amber-500/40 bg-amber-50/80 dark:bg-amber-500/10 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <svg className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" width="15" height="15" viewBox="0 0 24 24"
             fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
          <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] text-ink dark:text-night-ink">
            Needs your approval to run <span className="font-medium">{toolLabel(item.tool, item.args)}</span>.
          </div>
          {hasArgs && (
            <button type="button" onClick={() => setOpen((o) => !o)}
                    className="mt-0.5 text-[11.5px] text-ink-faint dark:text-night-faint hover:text-ink dark:hover:text-night-ink">
              {open ? "Hide details" : "Show details"}
            </button>
          )}
          {open && hasArgs && (
            <pre className="mt-1.5 text-[11.5px] bg-paper-soft dark:bg-night rounded-md p-2.5 overflow-auto max-h-40 text-ink-soft dark:text-night-faint">
              {JSON.stringify(item.args, null, 2)}
            </pre>
          )}
          <div className="flex flex-wrap gap-2 mt-2">
            <button onClick={() => onApprove?.(item.id, true, "once")}
                    className="px-3 py-1 rounded-md bg-brand text-white hover:bg-brand-deep text-[12.5px] font-medium">
              Allow once
            </button>
            <button onClick={() => onApprove?.(item.id, true, "session")}
                    title="Don't ask again for this tool for the rest of this chat"
                    className="px-3 py-1 rounded-md border border-brand/60 text-brand-deep dark:text-brand hover:bg-brand-wash dark:hover:bg-night-soft text-[12.5px] font-medium">
              Allow for session
            </button>
            <button onClick={() => onApprove?.(item.id, false, "once")}
                    className="px-3 py-1 rounded-md text-ink-soft dark:text-night-ink border border-line dark:border-night-line hover:bg-paper-soft dark:hover:bg-night-soft text-[12.5px]">
              Deny
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}

// One row per activity item: a streamed Thinking block, a spoken preamble, a tool
// step (dot + friendly label + result summary), or an inline approval prompt.
export function StepList({ items, onApprove }) {
  return (
    <ul className="space-y-1.5">
      {items.map((it, i) => {
        if (it.kind === "approval") {
          return <ApprovalCard key={it.id ?? i} item={it} onApprove={onApprove} />;
        }
        if (it.kind === "thinking") {
          return (
            <li key={i} className="text-[12.5px] text-ink-soft dark:text-night-faint whitespace-pre-wrap leading-relaxed">
              {it.text}
            </li>
          );
        }
        if (it.kind === "preamble") {
          return (
            <li key={i} className="text-[13px] italic text-ink-soft dark:text-night-faint">“{it.text}”</li>
          );
        }
        return (
          <li key={i} className="flex items-start gap-2 text-[13px]">
            <span className="mt-1.5"><Dot state={it.state} /></span>
            <span className="text-ink-soft dark:text-night-ink">
              {toolLabel(it.tool, it.args)}
              {it.summary && it.state === "fail" && (
                <span className="ml-1.5 text-red-500">— {String(it.summary).slice(0, 80)}</span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// One-line summary of a finished activity timeline, e.g. "Thought · 2 tools".
function summarize(items) {
  const tools = items.filter((it) => it.kind === "tool");
  const thought = items.some((it) => it.kind === "thinking");
  const bits = [];
  if (thought) bits.push("Thought it through");
  if (tools.length) bits.push(`${tools.length} ${tools.length === 1 ? "step" : "steps"}`);
  return bits.join(" · ") || "Activity";
}

// Persisted activity shown UNDER an assistant reply: a compact, collapsible strip the
// user can expand to see the thinking + tool steps that produced the answer.
export default function Activity({ items }) {
  const [open, setOpen] = useState(false);
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-2 rounded-lg border border-line dark:border-night-line bg-paper-soft/60 dark:bg-night-soft/60">
      <button type="button" onClick={() => setOpen((o) => !o)}
              className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[12px] text-ink-faint dark:text-night-faint hover:text-ink dark:hover:text-night-ink">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
             strokeLinecap="round" strokeLinejoin="round"
             className={`transition-transform ${open ? "rotate-90" : ""}`}><path d="m9 18 6-6-6-6" /></svg>
        <span className="font-medium">{summarize(items)}</span>
      </button>
      {open && (
        <div className="px-3 pb-2.5 pt-0.5 border-t border-line/70 dark:border-night-line/70">
          <StepList items={items} />
        </div>
      )}
    </div>
  );
}
