import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { createProject, deleteProject } from "../api.js";
import Dialog from "../components/ui/Dialog.jsx";
import { IconArrowRight, IconFolder, IconFolders, IconMessages, IconPlus, IconSearch, IconTrash } from "@tabler/icons-react";
import PageShell, { PageAction, cardClass, timeAgo, toneFor } from "../components/shell/PageShell.jsx";

// Projects (Phase 9 redesign): a gallery of projects, each with its own
// dedicated, layered memory. Opening one shows its chats and memory panel.
const IDEAS = ["Rooftop garden", "Thesis research", "Job hunt", "Home renovation"];

export default function ProjectsView() {
  const { projects, refreshProjects, confirmAction } = useOutletContext();
  const [creating, setCreating] = useState(null);       // null | seed name
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const q = query.trim().toLowerCase();
  const shown = projects.filter((p) => `${p.name} ${p.description || ""}`.toLowerCase().includes(q));
  const chats = projects.reduce((n, p) => n + (p.chat_count || 0), 0);

  async function removeProject(p) {
    if (!(await confirmAction?.(`Delete “${p.name}”? Its chats are unfiled (kept); its memory is removed.`, "Delete project"))) return;
    await deleteProject(p.id);
    refreshProjects?.();
  }

  const stats = projects.length
    ? [{ label: projects.length === 1 ? "project" : "projects", value: projects.length },
       { label: chats === 1 ? "chat" : "chats", value: chats }]
    : [];

  return (
    <>
      <PageShell icon={IconFolders} title="Projects"
                 description="Group related chats into a project with its own memory, so context stays put and never mixes with casual tasks."
                 stats={stats}
                 action={<PageAction icon={IconPlus} onClick={() => setCreating("")}>New project</PageAction>}>
        {projects.length === 0 ? (
          <EmptyState onCreate={(seed) => setCreating(seed)} />
        ) : (
          <>
            {projects.length > 4 && (
              <label className="relative block mb-5 max-w-sm">
                <IconSearch size={15} stroke={1.8} aria-hidden="true" className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search projects" placeholder="Search projects"
                       className="w-full h-9 rounded-lg border border-border bg-surface-raised/80 backdrop-blur-md pl-9 pr-3 text-sm text-fg placeholder:text-fg-subtle outline-none focus:border-accent" />
              </label>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {shown.map((p) => <ProjectCard key={p.id} p={p} onOpen={() => navigate(`/projects/${p.id}`)} onDelete={() => removeProject(p)} />)}
              {shown.length === 0 && <p className="text-sm text-fg-muted">No project matches “{query}”.</p>}
            </div>
          </>
        )}
      </PageShell>

      {creating !== null && (
        <NewProjectModal seed={creating}
          onClose={() => setCreating(null)}
          onCreated={(p) => { setCreating(null); refreshProjects?.(); if (p?.id) navigate(`/projects/${p.id}`); }}
        />
      )}
    </>
  );
}

function ProjectCard({ p, onOpen, onDelete }) {
  const tone = toneFor(p.id);
  return (
    <div className="group relative" data-project={p.id}>
      <button onClick={onOpen} className={`${cardClass} w-full h-44 text-left overflow-hidden flex flex-col`}>
        <span aria-hidden="true" className="h-1 w-full shrink-0" style={{ backgroundColor: `rgb(var(${tone}))` }} />
        <span className="flex-1 flex flex-col p-4 min-h-0">
          <span className="flex items-center gap-2.5 mb-2">
            <span className="h-9 w-9 shrink-0 rounded-xl grid place-items-center"
                  style={{ backgroundColor: `rgb(var(${tone}) / 0.14)`, color: `rgb(var(${tone}))` }}>
              <IconFolder size={18} stroke={1.7} aria-hidden="true" />
            </span>
            <span className="font-semibold text-md text-fg truncate pr-6">{p.name}</span>
          </span>
          <span className="text-sm text-fg-muted line-clamp-2 flex-1">{p.description || "No description yet."}</span>
          <span className="mt-2 flex items-center gap-3 text-xs text-fg-subtle whitespace-nowrap overflow-hidden">
            <span className="inline-flex items-center gap-1">
              <IconMessages size={13} stroke={1.8} aria-hidden="true" />{p.chat_count} {p.chat_count === 1 ? "chat" : "chats"}
            </span>
            {p.updated_at && <span className="truncate">Updated {timeAgo(p.updated_at)}</span>}
            <span className="ml-auto inline-flex items-center gap-0.5 text-accent opacity-0 group-hover:opacity-100 transition">
              Open<IconArrowRight size={13} stroke={2} aria-hidden="true" />
            </span>
          </span>
        </span>
      </button>
      <button onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete project" aria-label={`Delete project ${p.name}`}
              className="absolute top-4 right-3 h-7 w-7 grid place-items-center rounded-full text-fg-subtle hover:text-danger hover:bg-surface-press opacity-0 group-hover:opacity-100 focus:opacity-100 transition">
        <IconTrash size={15} stroke={1.8} aria-hidden="true" />
      </button>
    </div>
  );
}

function EmptyState({ onCreate }) {
  return (
    <div className="rounded-2xl border border-border/80 bg-surface-raised/80 backdrop-blur-md shadow-soft text-center px-6 py-12">
      <span className="mx-auto mb-4 h-16 w-16 grid place-items-center rounded-full bg-accent-wash text-accent border border-accent/25">
        <IconFolders size={30} stroke={1.5} aria-hidden="true" />
      </span>
      <h2 className="text-md font-semibold text-fg">Start your first project</h2>
      <p className="mt-1 text-sm text-fg-muted max-w-md mx-auto">A project keeps its own chats and memory together. Try one of these, or name your own.</p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {IDEAS.map((idea) => (
          <button key={idea} type="button" onClick={() => onCreate(idea)}
                  className="h-8 px-3 rounded-full border border-border bg-surface text-sm text-fg-soft hover:border-accent hover:text-fg">
            {idea}
          </button>
        ))}
      </div>
    </div>
  );
}

function NewProjectModal({ seed = "", onClose, onCreated }) {
  const [name, setName] = useState(seed);
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
               className="w-full rounded-lg px-3 py-2 mb-3 bg-surface-sunken border border-border outline-none focus:border-accent" />
        <label className="block text-sm text-fg-muted mb-1">
          What's this project about? <span className="text-fg-subtle">(optional — guides the assistant)</span>
        </label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
               placeholder="A short brief so I always keep the right context."
               className="w-full rounded-lg px-3 py-2 bg-surface-sunken border border-border outline-none focus:border-accent resize-none" />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-fg-soft hover:bg-surface-hover">Cancel</button>
          <button onClick={submit} disabled={!name.trim() || busy}
                  className="px-4 py-2 rounded-lg bg-accent text-accent-fg hover:opacity-90 disabled:opacity-50">Create</button>
        </div>
    </Dialog>
  );
}
