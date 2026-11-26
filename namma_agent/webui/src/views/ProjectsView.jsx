import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { createProject, deleteProject } from "../api.js";
import Dialog from "../components/ui/Dialog.jsx";
import { IconFolder, IconTrash } from "@tabler/icons-react";

// Project gallery: a card per project + a "New project" card. Each project owns
// dedicated, layered memory; opening one shows its chats and memory panel.
export default function ProjectsView() {
  const { projects, refreshProjects, confirmAction } = useOutletContext();
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  async function removeProject(p) {
    if (!(await confirmAction?.(`Delete “${p.name}”? Its chats are unfiled (kept); its memory is removed.`, "Delete project"))) return;
    await deleteProject(p.id);
    refreshProjects?.();
  }

  return (
    <>
      <header className="flex items-center px-6 h-12 border-b border-border">
        <h1 className="font-serif text-lg">Projects</h1>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-fg-muted mb-5 text-base">
            Group related chats into a project with its own dedicated memory — context stays
            put and never mixes with casual tasks.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <button onClick={() => setCreating(true)}
              className="h-36 rounded-2xl border border-dashed border-border grid place-items-center text-fg-muted hover:border-brand hover:text-brand-deep transition">
              <div className="text-center">
                <div className="mx-auto mb-2 h-9 w-9 rounded-full bg-brand-wash dark:bg-night-panel grid place-items-center text-brand-deep">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                </div>
                New project
              </div>
            </button>

            {projects.map((p) => (
              <div key={p.id} className="group relative">
                <button onClick={() => navigate(`/projects/${p.id}`)}
                  className="h-36 w-full text-left rounded-2xl border border-border bg-surface-raised p-4 hover:shadow-soft transition flex flex-col">
                  <div className="h-9 w-9 rounded-xl bg-accent-wash grid place-items-center text-brand-deep mb-2">
                    <IconFolder size={18} stroke={1.7} aria-hidden="true" />
                  </div>
                  <div className="font-medium truncate pr-6">{p.name}</div>
                  <div className="text-sm text-fg-subtle line-clamp-2 flex-1">
                    {p.description || "No description"}
                  </div>
                  <div className="text-xs text-fg-subtle mt-1">
                    {p.chat_count} {p.chat_count === 1 ? "chat" : "chats"}
                  </div>
                </button>
                <button onClick={(e) => { e.stopPropagation(); removeProject(p); }} title="Delete project"
                  className="absolute top-3 right-3 h-7 w-7 grid place-items-center rounded-full text-ink-faint hover:text-brand-deep hover:bg-surface-press opacity-0 group-hover:opacity-100 transition">
                  <IconTrash size={15} stroke={1.8} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </main>

      {creating && (
        <NewProjectModal
          onClose={() => setCreating(false)}
          onCreated={(p) => { setCreating(false); refreshProjects?.(); if (p?.id) navigate(`/projects/${p.id}`); }}
        />
      )}
    </>
  );
}

function NewProjectModal({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim() || busy) return;
    setBusy(true);
    const r = await createProject(name.trim(), description.trim());
    onCreated(r?.project);
  }

  return (
    <Dialog onClose={onClose} size="md" labelledBy="new-project-title" className="p-5">
        <h3 className="font-serif text-lg mb-3" id="new-project-title">New project</h3>
        <label className="block text-sm text-fg-muted mb-1">Name</label>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
               placeholder="e.g. Rooftop Garden"
               className="w-full rounded-lg px-3 py-2 mb-3 bg-surface-sunken border border-border outline-none focus:border-brand" />
        <label className="block text-sm text-fg-muted mb-1">
          What's this project about? <span className="text-ink-faint">(optional — guides the assistant)</span>
        </label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
               placeholder="A short brief so I always keep the right context."
               className="w-full rounded-lg px-3 py-2 bg-surface-sunken border border-border outline-none focus:border-brand resize-none" />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-fg-soft hover:bg-surface-hover">Cancel</button>
          <button onClick={submit} disabled={!name.trim() || busy}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">Create</button>
        </div>
    </Dialog>
  );
}
