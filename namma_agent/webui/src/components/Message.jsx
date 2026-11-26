import { createContext, memo, useContext, useState } from "react";
import Activity from "./Activity.jsx";
import Logo from "./Logo.jsx";
import Markdown from "./Markdown.jsx";
import ReadAloud from "./ReadAloud.jsx";
import { copyText } from "../clipboard.js";
import { IconCheck, IconCopy } from "@tabler/icons-react";

const fmtTime = (at) => {
  if (!at) return "";
  try { return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  catch { return ""; }
};

// One-click copy of a message's text — theme-aware, and reliable even where the
// host webview hasn't wired Ctrl+C.
function CopyButton({ text, className = "" }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (await copyText(text)) { setCopied(true); setTimeout(() => setCopied(false), 1400); }
  }
  return (
    <button aria-label="Copy" onClick={copy} title="Copy"
            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-fg-subtle hover:text-fg hover:bg-surface-hover transition ${className}`}>
      {copied ? (
        <><IconCheck size={13} stroke={2.4} className="text-success" aria-hidden="true" />Copied</>
      ) : (
        <><IconCopy size={13} stroke={2} aria-hidden="true" />Copy</>
      )}
    </button>
  );
}

// Message actions (Phase 4): regenerate, edit-and-resend, branch, delete.
// ChatView provides the handlers; a message without a database id (still
// streaming, or a local-only note) shows no actions.
export const MessageActionsContext = createContext(null);

function ActionButton({ label, onClick, children, danger }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-fg-subtle hover:bg-surface-hover transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand ${danger ? "hover:text-red-600" : "hover:text-fg"}`}>
      {children}
    </button>
  );
}

function Actions({ msg, isUser, onEdit }) {
  const actions = useContext(MessageActionsContext);
  if (!actions || !msg.dbId || actions.busy) return null;
  return (
    <span className="inline-flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition">
      {!isUser && msg.isLastAssistant && <ActionButton label="Regenerate this reply" onClick={() => actions.regenerate(msg)}>↻ Regenerate</ActionButton>}
      {isUser && <ActionButton label="Edit and resend" onClick={onEdit}>✎ Edit</ActionButton>}
      <ActionButton label="Branch a new chat from here" onClick={() => actions.branch(msg)}>⑂ Branch</ActionButton>
      <ActionButton label="Delete this message" danger onClick={() => actions.remove(msg)}>Delete</ActionButton>
    </span>
  );
}

function EditBox({ initial, onCancel, onSave }) {
  const [text, setText] = useState(initial);
  return (
    <div className="w-full max-w-[80%] self-end">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={Math.min(8, Math.max(2, text.split("\n").length))}
                aria-label="Edit your message" autoFocus
                onKeyDown={(e) => { if (e.key === "Escape") onCancel(); if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSave(text); }}
                className="w-full rounded-xl border border-border bg-surface-raised px-3 py-2 text-prose" />
      <div className="flex justify-end gap-2 mt-1 text-sm">
        <button type="button" onClick={onCancel} className="px-2.5 py-1 rounded-md text-fg-muted hover:bg-surface-hover">Cancel</button>
        <button type="button" onClick={() => onSave(text)} disabled={!text.trim()}
                className="px-2.5 py-1 rounded-md bg-brand text-white disabled:opacity-40">Send</button>
      </div>
    </div>
  );
}

// claude.ai-style: user messages in a soft bubble on the right; assistant
// messages as full-width rich text (no bubble), with an "F" avatar. Each shows time.
// "responded in 2.4s · 1,318 tokens" — per-turn stats shown under an assistant reply.
function TurnStats({ meta }) {
  if (!meta) return null;
  const bits = [];
  if (typeof meta.ttft === "number") bits.push(`${meta.ttft.toFixed(1)}s to first token`);
  if (meta.tokens) bits.push(`${meta.tokens.toLocaleString()} tokens`);
  if (!bits.length) return null;
  const tip = meta.cached
    ? `Time to first token · new tokens billed this request (fresh input + output); ${meta.cached.toLocaleString()} more re-read from cache`
    : "Time to first token · total tokens for this request";
  return <span title={tip}>· {bits.join(" · ")}</span>;
}

// Memoised (Phase 6): while a reply streams, only the message whose props
// changed re-renders; earlier messages keep their parsed markdown. Message
// objects are immutable in the store, so a shallow prop compare is exact.
function Message(msg) {
  const { role, content, attachments, at, meta, steps } = msg;
  const isUser = role === "user";
  const isError = role === "error";
  const time = fmtTime(at);
  const actions = useContext(MessageActionsContext);
  const [editing, setEditing] = useState(false);

  if (isUser) {
    if (editing) {
      return (
        <div className="flex flex-col items-end">
          <EditBox initial={content} onCancel={() => setEditing(false)}
                   onSave={(text) => { setEditing(false); actions?.editResend(msg, text); }} />
        </div>
      );
    }
    return (
      <div className="group flex flex-col items-end animate-rise">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-accent-wash/85 backdrop-blur-sm border border-border/80 px-4 py-2.5 text-prose leading-relaxed whitespace-pre-wrap">
          {content}
          {attachments?.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {attachments.map((a, i) => (
                <span key={i} className="text-xs bg-bg px-2 py-0.5 rounded-md border border-border text-fg-muted">
                  📎 {a.name}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 mt-1 mr-1 text-2xs text-fg-subtle">
          <Actions msg={msg} isUser onEdit={() => setEditing(true)} />
          {content && <CopyButton text={content} className="opacity-0 group-hover:opacity-100 focus:opacity-100" />}
          {time && <span>{time}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="group flex gap-3 animate-rise">
      <div className="mt-0.5 h-7 w-7 shrink-0 grid place-items-center"><Logo size={26} /></div>
      <div className="flex-1 min-w-0">
        {!isError && steps?.length > 0 && <Activity items={steps} />}
        {isError ? (
          <div className="text-prose text-brand-deep bg-brand-wash border border-brand-soft/50 rounded-xl px-3 py-2">
            {content}
          </div>
        ) : content ? (
          <Markdown>{content}</Markdown>
        ) : (
          <span className="inline-block h-4 w-2 bg-ink-faint animate-blink rounded-sm" />
        )}
        <div className="mt-2 flex items-center gap-2 text-2xs text-fg-subtle">
          {content && !isError && <ReadAloud text={content} />}
          {content && !isError && <CopyButton text={content} />}
          {time && <span>{time}</span>}
          <TurnStats meta={meta} />
          {!isError && <Actions msg={msg} />}
        </div>
      </div>
    </div>
  );
}

export default memo(Message);
