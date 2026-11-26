import { useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";
import {
  addProjectMemory, deleteProject, deleteProjectDocument, deleteScopeMemory,
  deleteSession, getProject, newProjectSession, renameSession, trustProjectDocument,
  updateProject, uploadProjectDocument,
} from "../api.js";
import { IconPencil, IconTrash, IconX } from "@tabler/icons-react";

const MAX_DOCS = 25;

// A single project: editable name/brief, its dedicated memory (add/remove), its
// chats, and a button to start a new chat inside the project.
export default function ProjectDetailView() {
  const { id } = useParams();
  const { openChat, refreshProjects, confirmAction } = useOutletContext();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [memDraft, setMemDraft] = useState("");

  const load = () => getProject(id).then(setData);
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  if (!data) return <div className="flex-1 grid place-items-center text-ink-faint">Loading…</div>;
  if (!data.project) {
    return (
      <div className="flex-1 grid place-items-center text-ink-faint">
        Project not found. <button className="ml-2 text-brand-deep underline" onClick={() => navigate("/projects")}>Back</button>
      </div>
    );
  }

  const { project, sessions, memory, documents = [] } = data;

  async function saveField(fields) {
    await updateProject(id, fields);
    load(); refreshProjects?.();
  }
  async function addMem() {
    const c = memDraft.trim();
    if (!c) return;
    setMemDraft("");
    await addProjectMemory(id, c);
    load();
  }
  async function removeMem(entryId) {
    await deleteScopeMemory(entryId);
    load();
  }
  async function startChat() {
    const r = await newProjectSession(id);
    if (r?.session_id) { openChat(r.session_id); refreshProjects?.(); }
  }
  async function removeProject() {
    if (!(await confirmAction?.("Delete this project? Its chats are unfiled (kept) and its memory is removed.", "Delete project"))) return;
    await deleteProject(id);
    refreshProjects?.();
    navigate("/projects");
  }
  async function renameChat(sid, title) {
    await renameSession(sid, title);
    load();
  }
  async function removeChat(sid) {
    if (!(await confirmAction?.("Delete this chat? This can't be undone."))) return;
    await deleteSession(sid);
    load(); refreshProjects?.();
  }

  return (
    <>
      <header className="flex items-center justify-between px-6 h-12 border-b border-border">
        <div className="flex items-center gap-2 text-sm text-fg-subtle">
          <button onClick={() => navigate("/projects")} className="hover:text-fg">Projects</button>
          <span>/</span>
          <span className="text-fg truncate max-w-[40ch]">{project.name}</span>
        </div>
        <button onClick={removeProject} className="text-sm text-ink-faint hover:text-brand-deep">Delete project</button>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {/* Editable header */}
          <div>
            <EditableText value={project.name} onSave={(v) => saveField({ name: v })}
                          className="font-serif text-2xl" placeholder="Project name" />
            <EditableText value={project.description} onSave={(v) => saveField({ description: v })}
                          className="text-fg-muted mt-1 text-base" multiline
                          placeholder="Add a short brief so I always keep the right context…" />
          </div>

          {/* Documents (multi-document knowledge base) */}
          <DocumentsPanel projectId={id} documents={documents} onChanged={load}
                          confirmAction={confirmAction} />

          {/* Dedicated memory */}
          <section className="rounded-2xl border border-border bg-surface-raised p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-medium">Project memory</h2>
              <span className="text-xs text-fg-subtle">{memory.length} {memory.length === 1 ? "note" : "notes"}</span>
            </div>
            <p className="text-sm text-fg-subtle mb-3">
              Facts I always keep for this project. I add to it as we work; you can curate it here.
            </p>
            <div className="space-y-1.5 mb-3">
              {memory.length === 0 && <div className="text-sm text-fg-subtle">No saved memory yet.</div>}
              {memory.map((m) => (
                <div key={m.id} className="group flex items-start gap-2 rounded-lg px-3 py-2 bg-surface-sunken text-base">
                  <span className="flex-1">{m.content}</span>
                  <button onClick={() => removeMem(m.id)} className="opacity-0 group-hover:opacity-100 text-ink-faint hover:text-brand-deep">
                    <IconX size={14} stroke={2} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input value={memDraft} onChange={(e) => setMemDraft(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") addMem(); }}
                     placeholder="Add a memory note…"
                     className="flex-1 rounded-lg px-3 py-2 text-base bg-surface-sunken border border-border outline-none focus:border-brand" />
              <button onClick={addMem} disabled={!memDraft.trim()}
                      className="px-3 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50 text-base">Add</button>
            </div>
          </section>

          {/* Chats */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-medium">Chats</h2>
              <button onClick={startChat} className="flex items-center gap-1.5 text-sm text-brand-deep hover:underline">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                New chat in project
              </button>
            </div>
            <div className="space-y-1">
              {sessions.length === 0 && <div className="text-sm text-fg-subtle">No chats filed here yet.</div>}
              {sessions.map((s) => (
                <ProjectChatRow key={s.id} s={s} onOpen={() => openChat(s.id)}
                                onRename={(t) => renameChat(s.id, t)} onDelete={() => removeChat(s.id)} />
              ))}
            </div>
          </section>
        </div>
      </main>
    </>
  );
}

// The project's knowledge base: upload up to 25 documents (10MB each). Every
// file is indexed for retrieval and screened for prompt injection — flagged
// files are quarantined out of answers until explicitly trusted or removed.
function DocumentsPanel({ projectId, documents, onChanged, confirmAction }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef(null);

  async function upload(files) {
    if (!files?.length || busy) return;
    setBusy(true); setError("");
    for (const f of files) {
      const r = await uploadProjectDocument(projectId, f);
      if (!r?.ok) { setError(r?.error || `Upload of ${f.name} failed.`); break; }
    }
    setBusy(false);
    onChanged?.();
  }
  async function remove(doc) {
    if (!(await confirmAction?.(`Remove “${doc.name}” from this project's knowledge base?`, "Remove"))) return;
    await deleteProjectDocument(projectId, doc.id);
    onChanged?.();
  }
  async function trust(doc) {
    const ok = await confirmAction?.(
      `“${doc.name}” was flagged for possible prompt-injection content. Trust it anyway and include it in answers?`,
      "Trust document");
    if (!ok) return;
    await trustProjectDocument(projectId, doc.id);
    onChanged?.();
  }

  const fmtSize = (b) => (b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

  return (
    <section className="rounded-2xl border border-border bg-surface-raised p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="font-medium">Documents</h2>
        <span className="text-xs text-fg-subtle">{documents.length}/{MAX_DOCS} files · 10 MB each</span>
      </div>
      <p className="text-sm text-fg-subtle mb-3">
        I index these and ground my answers in them across every chat in this project. Each upload is
        screened for prompt injection; flagged files stay quarantined until you trust them.
      </p>

      <div className="space-y-1.5 mb-3">
        {documents.length === 0 && <div className="text-sm text-fg-subtle">No documents yet.</div>}
        {documents.map((d) => (
          <div key={d.id} className="group rounded-lg px-3 py-2 bg-surface-sunken text-base">
            <div className="flex items-center gap-2">
              <DocIcon status={d.status} />
              <span className="flex-1 truncate">{d.name}</span>
              <span className="text-xs text-fg-subtle shrink-0">
                {fmtSize(d.bytes)}{d.status === "ready" || d.status === "trusted" ? ` · ${d.chunk_count} chunks` : ""}
              </span>
              {d.status === "flagged" && (
                <span className="shrink-0 text-2xs font-medium px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-500/15 text-red-700 dark:text-red-300">⚠ flagged</span>
              )}
              {d.status === "trusted" && (
                <span className="shrink-0 text-2xs px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300">trusted</span>
              )}
              {d.status === "error" && (
                <span className="shrink-0 text-2xs px-1.5 py-0.5 rounded bg-surface-press text-ink-faint">couldn't index</span>
              )}
              {d.status === "flagged" && (
                <button onClick={() => trust(d)} className="shrink-0 text-xs text-brand-deep hover:underline opacity-0 group-hover:opacity-100">Trust</button>
              )}
              <button onClick={() => remove(d)} title="Remove document"
                      className="shrink-0 text-ink-faint hover:text-brand-deep opacity-0 group-hover:opacity-100">
                <IconX size={14} stroke={2} aria-hidden="true" />
              </button>
            </div>
            {d.status === "flagged" && d.flag_reasons?.length > 0 && (
              <div className="mt-1.5 ml-6 text-xs text-red-700/80 dark:text-red-300/80">
                {d.flag_reasons.slice(0, 2).map((r, i) => <div key={i} className="truncate">• {r}</div>)}
              </div>
            )}
          </div>
        ))}
      </div>

      {error && <div className="mb-2 text-sm text-red-700 dark:text-red-300">{error}</div>}

      <input ref={fileRef} type="file" multiple className="hidden"
             accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.html,.json,.yaml,.log,.epub"
             onChange={(e) => { upload([...(e.target.files || [])]); e.target.value = ""; }} />
      <button onClick={() => fileRef.current?.click()} disabled={busy || documents.length >= MAX_DOCS}
              className="w-full rounded-xl border border-dashed border-border px-3 py-2.5 text-sm text-fg-muted hover:border-brand hover:text-brand-deep transition disabled:opacity-50">
        {busy ? "Uploading & indexing…"
          : documents.length >= MAX_DOCS ? "Document limit reached (25)" : "+ Add documents"}
      </button>
    </section>
  );
}

function DocIcon({ status }) {
  const cls = status === "flagged" ? "text-red-500"
    : status === "error" ? "text-ink-faint"
    : "text-brand-deep";
  return (
    <svg className={`shrink-0 ${cls}`} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" />
    </svg>
  );
}

// One chat filed in a project: open on click; hover reveals rename / delete.
// (Project chats are hidden from the sidebar, so this is where they're managed.)
function ProjectChatRow({ s, onOpen, onRename, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.title);
  const ref = useRef(null);

  function commit() {
    const t = draft.trim();
    if (t && t !== s.title) onRename(t);
    setEditing(false);
  }

  if (editing) {
    return (
      <input ref={ref} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
             onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
             className="w-full rounded-lg px-3 py-2 text-base bg-surface-sunken border border-brand-soft outline-none" />
    );
  }

  return (
    <div className="group flex items-center rounded-lg bg-surface-sunken hover:bg-surface-press">
      <button onClick={onOpen} className="flex-1 text-left truncate px-3 py-2 text-base">{s.title}</button>
      <button aria-label="Rename" title="Rename" onClick={(e) => { e.stopPropagation(); setDraft(s.title); setEditing(true); }}
              className="px-1 text-ink-faint hover:text-fg opacity-0 group-hover:opacity-100">
        <IconPencil size={14} stroke={1.8} aria-hidden="true" />
      </button>
      <button aria-label="Delete" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(); }}
              className="pr-3 pl-1 text-ink-faint hover:text-brand-deep opacity-0 group-hover:opacity-100">
        <IconTrash size={14} stroke={1.8} aria-hidden="true" />
      </button>
    </div>
  );
}

// Click-to-edit text (name / brief). Saves on blur or Enter.
function EditableText({ value, onSave, className = "", placeholder = "", multiline = false }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  useEffect(() => { setDraft(value || ""); }, [value]);

  function commit() { setEditing(false); if ((draft || "") !== (value || "")) onSave(draft); }

  if (editing) {
    const common = {
      autoFocus: true, value: draft, onChange: (e) => setDraft(e.target.value), onBlur: commit,
      className: `w-full bg-transparent border-b border-brand-soft outline-none ${className}`,
    };
    return multiline
      ? <textarea {...common} rows={2} onKeyDown={(e) => { if (e.key === "Escape") setEditing(false); }} />
      : <input {...common} onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }} />;
  }
  return (
    <div onClick={() => setEditing(true)} className={`cursor-text ${className} ${!value ? "text-fg-subtle italic" : ""}`}>
      {value || placeholder}
    </div>
  );
}
