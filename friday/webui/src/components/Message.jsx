import { useState } from "react";
import Logo from "./Logo.jsx";
import Markdown from "./Markdown.jsx";
import ReadAloud from "./ReadAloud.jsx";
import { copyText } from "../clipboard.js";

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
    <button onClick={copy} title="Copy"
            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-ink-faint dark:text-night-faint hover:text-ink dark:hover:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft transition ${className}`}>
      {copied ? (
        <><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Copied</>
      ) : (
        <><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>Copy</>
      )}
    </button>
  );
}

// claude.ai-style: user messages in a soft bubble on the right; assistant
// messages as full-width rich text (no bubble), with an "F" avatar. Each shows time.
export default function Message({ role, content, tools, attachments, at }) {
  const isUser = role === "user";
  const isError = role === "error";
  const time = fmtTime(at);

  if (isUser) {
    return (
      <div className="group flex flex-col items-end animate-rise">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-brand-wash dark:bg-night-soft border border-line dark:border-night-line px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap">
          {content}
          {attachments?.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {attachments.map((a, i) => (
                <span key={i} className="text-[12px] bg-paper dark:bg-night px-2 py-0.5 rounded-md border border-line dark:border-night-line text-ink-soft dark:text-night-faint">
                  📎 {a.name}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 mt-1 mr-1 text-[10.5px] text-ink-faint dark:text-night-faint">
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
        {isError ? (
          <div className="text-[15px] text-brand-deep bg-brand-wash border border-brand-soft/50 rounded-xl px-3 py-2">
            {content}
          </div>
        ) : content ? (
          <Markdown>{content}</Markdown>
        ) : (
          <span className="inline-block h-4 w-2 bg-ink-faint animate-blink rounded-sm" />
        )}
        <div className="mt-2 flex items-center gap-2 text-[10.5px] text-ink-faint dark:text-night-faint">
          {content && !isError && <ReadAloud text={content} />}
          {content && !isError && <CopyButton text={content} className="opacity-0 group-hover:opacity-100 focus:opacity-100" />}
          {time && <span>{time}</span>}
          {tools?.length > 0 && <span>· used: {tools.join(", ")}</span>}
        </div>
      </div>
    </div>
  );
}
