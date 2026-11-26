import { useMemo, useState } from "react";
import { IconFile, IconFileText, IconPaperclip, IconPhoto, IconPlayerPlay, IconWorld } from "@tabler/icons-react";
import RunsPanel from "../RunsPanel.jsx";
import TodoPanel from "../TodoPanel.jsx";
import FilePreview from "./FilePreview.jsx";
import { collectChatFiles } from "../../chatFiles.js";
import { isDesktop } from "../../desktop.js";

// Phase 9 (Hermes layout): the right-hand working-context pane: the chat's
// sub-agent runs, its plan, the files it touched, and a preview of one of
// them. Panes keep their state while hidden. When open, the chat stops
// docking Runs/Plan above the composer.
export const RIGHT_PANE_TABS = [
  { id: "runs", label: "Runs" },
  { id: "plan", label: "Plan" },
  { id: "files", label: "Files" },
  { id: "preview", label: "Preview" },
];

const KIND_ICON = { image: IconPhoto, html: IconWorld, pdf: IconFileText, text: IconFileText, audio: IconPlayerPlay, video: IconPlayerPlay };

export default function RightPane({ runs = [], todos = [], messages = [], onClose }) {
  const files = useMemo(() => collectChatFiles(messages), [messages]);
  const [tab, setTab] = useState(runs.length || !todos.length ? "runs" : "plan");
  const [selected, setSelected] = useState(null);
  // Keep the preview on the same file while the list refreshes; drop it when
  // the chat changes and the file is gone.
  const current = selected && files.find((f) => f.key === selected);
  const counts = { runs: runs.length, plan: todos.length, files: files.length };
  const open = (f) => { setSelected(f.key); setTab("preview"); };

  return (
    // Wide windows: a column beside the chat. Below 1024px it floats over the
    // chat as a drawer instead, so it never squeezes the conversation.
    <aside aria-label="Side panel"
           className="w-80 max-w-[85vw] shrink-0 flex flex-col border-l border-border bg-surface max-lg:fixed max-lg:top-0 max-lg:bottom-7 max-lg:right-0 max-lg:z-30 max-lg:shadow-overlay">
      <div data-chrome className={`flex items-center gap-1 h-[var(--titlebar-height)] pl-2 pr-[var(--titlebar-reserve-right)] border-b border-border ${isDesktop() ? "app-drag" : ""}`}>
        <div role="tablist" aria-label="Side panel" className="flex items-center gap-0.5 min-w-0 overflow-x-auto">
          {RIGHT_PANE_TABS.map((t) => (
            <button key={t.id} role="tab" type="button" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                    className={`h-6 px-2 rounded-sm text-sm shrink-0 ${tab === t.id ? "bg-accent-wash text-fg font-medium" : "text-fg-muted hover:text-fg"}`}>
              {t.label}
              {counts[t.id] > 0 && <span className="ml-1 text-xs text-fg-subtle">{counts[t.id]}</span>}
            </button>
          ))}
        </div>
      </div>
      <div role="tabpanel" className="flex-1 min-h-0 overflow-y-auto p-3">
        {tab === "runs" && (runs.length
          ? <RunsPanel runs={runs} />
          : <p className="text-sm text-fg-muted">No sub-agents in this chat yet. When the agent delegates work, each Legatus shows up here.</p>)}
        {tab === "plan" && (todos.length
          ? <TodoPanel todos={todos} />
          : <p className="text-sm text-fg-muted">No plan yet. Multi-step tasks show their checklist here.</p>)}
        {tab === "files" && (files.length ? (
          <ul className="space-y-0.5" aria-label="Files in this chat">
            {files.map((f) => {
              const Icon = f.source === "attachment" ? IconPaperclip : (KIND_ICON[f.kind] || IconFile);
              return (
                <li key={f.key}>
                  <button type="button" onClick={() => open(f)} aria-current={current?.key === f.key ? "true" : undefined}
                          className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-sm hover:bg-surface-sunken ${current?.key === f.key ? "bg-accent-wash" : ""}`}>
                    <Icon size={15} stroke={1.7} className="shrink-0 text-fg-muted" aria-hidden="true" />
                    <span className="truncate flex-1 text-fg" title={f.name}>{f.name}</span>
                    <span className="shrink-0 text-2xs text-fg-subtle">{f.source === "attachment" ? "attached" : f.kind}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : <p className="text-sm text-fg-muted">No files yet. What you attach and what the agent makes (diagrams, images, pages, documents) gather here.</p>)}
        {tab === "preview" && <FilePreview file={current || null} />}
      </div>
    </aside>
  );
}
