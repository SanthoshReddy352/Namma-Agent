import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { downloadChat, searchChats } from "../api.js";
import Logo from "./Logo.jsx";
import { isDesktop } from "../desktop.js";
import { IconAffiliate, IconChevronRight, IconDots, IconDownload, IconEdit, IconFolder, IconPencil, IconSchool, IconSearch, IconSettings, IconTrash, IconX } from "@tabler/icons-react";
import ProfileRail from "./shell/ProfileRail.jsx";

// Gemini-style navigation rail: a slim icon rail that expands on hover, or pins
// open via the hamburger. Icons are hand-drawn thin-stroke line marks in the
// spirit of claude.ai. Nav: New chat · Projects · Learning Room, then Recent
// chats, with Settings pinned to the bottom.
export default function Sidebar({ sessions, projects = [], onNew, onOpen, onDelete, onRename, onFile, onConfirm, onOpenSettings, onManagePersonas, collapsed, onToggle, name = "Namma Agent" }) {
  const [pinned, setPinned] = useState(() => localStorage.getItem("namma-sidebar-pinned") !== "false");
  const [hovered, setHovered] = useState(false);
  // Cross-chat search: ≥2 chars swaps the Recent list for grouped results.
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = not searching
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const expanded = pinned || hovered;

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setResults(null); return; }
    const t = setTimeout(async () => {
      const r = await searchChats(q);
      setResults(r?.results || []);
    }, 250); // debounce keystrokes
    return () => clearTimeout(t);
  }, [query]);

  function togglePin() {
    setPinned((p) => { localStorage.setItem("namma-sidebar-pinned", String(!p)); return !p; });
    onToggle?.();
  }
  // Phase 9: the titlebar's sidebar button (Hermes layout) toggles the pin.
  useEffect(() => {
    const on = () => togglePin();
    window.addEventListener("namma-toggle-sidebar", on);
    return () => window.removeEventListener("namma-toggle-sidebar", on);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const navItem = (to, icon, label, active) => (
    <button
      onClick={() => navigate(to)}
      title={label}
      className={`flex items-center gap-3 rounded-full h-10 transition-colors w-full
        ${expanded ? "px-3" : "px-0 justify-center"}
        ${active
          ? "bg-brand-wash text-brand-deep dark:bg-night-panel dark:text-brand-soft"
          : "text-fg-muted hover:bg-paper-sink dark:hover:bg-night-panel"}`}
    >
      <span className="shrink-0 grid place-items-center w-7">{icon}</span>
      {expanded && <span className="truncate text-base">{label}</span>}
    </button>
  );

  return (
    // Outer wrapper reserves rail width and grows whenever the sidebar is expanded
    // (pinned OR hovered), so the work area slides over smoothly and the panel never
    // covers the chat header / breadcrumbs.
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`relative shrink-0 transition-[width] duration-200 ${expanded ? "w-64" : "w-[68px]"}`}
    >
      <div
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        className={`absolute inset-y-0 left-0 z-30 flex flex-col
          bg-surface-hover          border-r border-border transition-[width] duration-200
          ${expanded ? "w-64" : "w-[68px]"} ${hovered && !pinned ? "shadow-pop" : ""}`}
      >
        {/* Header in the titlebar band (Hermes layout). The sidebar toggle is
            the fixed left titlebar cluster drawn over this row. */}
        <div data-chrome className={`flex items-center gap-2 shrink-0 h-[var(--titlebar-height)] pl-[var(--titlebar-reserve-left)] pr-3 ${isDesktop() ? "app-drag" : ""}`}>
          {expanded && (
            <button onClick={() => navigate("/")} className="flex items-center gap-2 min-w-0">
              <Logo size={18} />
              <span className="font-serif text-base tracking-tight truncate">{name}</span>
            </button>
          )}
        </div>

        {/* New chat — prominent pill */}
        <div className={`px-3 ${expanded ? "" : "flex justify-center"}`}>
          <button aria-label="New chat" onClick={onNew} title="New chat"
            className={`flex items-center gap-3 rounded-full bg-surface-raised border border-border hover:shadow-soft transition
              ${expanded ? "px-4 h-11 w-full" : "h-11 w-11 justify-center"}`}>
            <ComposeIcon />
            {expanded && <span className="text-base font-medium">New chat</span>}
          </button>
        </div>

        {/* Primary nav */}
        <nav className="px-3 mt-2 space-y-0.5">
          {navItem("/projects", <FolderIcon />, "Projects", pathname.startsWith("/projects"))}
          {navItem("/learning", <CapIcon />, "Learning Room", pathname.startsWith("/learning"))}
          {navItem("/memory", <MemoryIcon />, "Memory", pathname.startsWith("/memory"))}
        </nav>

        {/* Search + Recent chats (only when expanded) */}
        {expanded && (
          <>
            <div className="px-3 mt-3">
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle"><SearchIcon /></span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Escape") setQuery(""); }}
                  placeholder="Search chats…"
                  className="w-full h-9 rounded-full pl-9 pr-8 text-sm bg-paper-panel dark:bg-night-panel
                             border border-line dark:border-night-line outline-none
                             focus:border-brand-soft placeholder:text-ink-faint dark:placeholder:text-night-faint"
                />
                {query && (
                  <button onClick={() => setQuery("")} title="Clear search"
                          className="absolute right-2 top-1/2 -translate-y-1/2 h-5 w-5 grid place-items-center rounded-full
                                     text-ink-faint hover:text-ink dark:hover:text-night-ink">
                    <XIcon />
                  </button>
                )}
              </div>
            </div>
            <div className="mt-3 px-5 text-2xs uppercase tracking-wider text-fg-subtle">
              {results !== null ? "Search results" : "Recent"}
            </div>
            <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5 mt-1">
              {results !== null ? (
                <>
                  {results.length === 0 && (
                    <div className="px-3 py-4 text-sm text-fg-subtle">No chats match.</div>
                  )}
                  {results.map((r) => (
                    <button key={r.session_id} onClick={() => onOpen(r.session_id)}
                            className="w-full text-left rounded-xl px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-panel transition">
                      <div className="flex items-baseline gap-2">
                        <span className="truncate text-base text-fg-soft">{r.title}</span>
                        {r.date && <span className="ml-auto shrink-0 text-2xs text-fg-subtle">{r.date}</span>}
                      </div>
                      <div className="truncate text-xs text-fg-subtle">{r.snippet}</div>
                    </button>
                  ))}
                </>
              ) : (
                <>
                  {(!sessions || sessions.length === 0) && (
                    <div className="px-3 py-4 text-sm text-fg-subtle">No conversations yet.</div>
                  )}
                  {sessions?.map((s) => (
                    <ChatRow key={s.id} s={s} projects={projects}
                             onOpen={onOpen} onDelete={onDelete} onRename={onRename} onFile={onFile} onConfirm={onConfirm} />
                  ))}
                </>
              )}
            </div>
          </>
        )}
        {!expanded && <div className="flex-1" />}

        {/* Profile rail (Phase 9): who answers — switch persona in one click. */}
        <div className={`px-3 pt-2.5 pb-1 border-t border-border ${expanded ? "" : "flex justify-center"}`}>
          <ProfileRail expanded={expanded} onManage={onManagePersonas || onOpenSettings} />
        </div>

        {/* Settings pinned to bottom */}
        <div className="px-3 pb-3 pt-1">
          <button aria-label="Settings" onClick={onOpenSettings} title="Settings"
            className={`flex items-center gap-3 rounded-full h-10 text-fg-soft hover:bg-paper-sink dark:hover:bg-night-panel w-full
              ${expanded ? "px-3" : "px-0 justify-center"}`}>
            <span className="shrink-0 grid place-items-center w-7"><GearIcon /></span>
            {expanded && <span className="text-base">Settings</span>}
          </button>
        </div>
      </div>
    </div>
  );
}

// One recent-chat row: open on click, with a ⋯ menu for rename / add-to-project /
// delete. Rename swaps the label for an inline input.
function ChatRow({ s, projects, onOpen, onDelete, onRename, onFile, onConfirm }) {
  const [menu, setMenu] = useState(null); // null | {top, left}
  const [sub, setSub] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.title);
  const btnRef = useRef(null);

  function openMenu(e) {
    e.stopPropagation();
    if (menu) { setMenu(null); setSub(false); return; }
    const r = btnRef.current.getBoundingClientRect();
    // Fixed-positioned so the menu escapes the Recent list's overflow clip.
    setMenu({ top: r.bottom + 4, left: Math.max(8, r.right - 176) });
    setSub(false);
  }
  function closeMenu() { setMenu(null); setSub(false); }

  function commit() {
    const t = draft.trim();
    if (t && t !== s.title) onRename?.(s.id, t);
    setEditing(false);
  }

  if (editing) {
    return (
      <div className="px-2 py-1">
        <input
          autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
          className="w-full rounded-lg px-3 py-1.5 text-base bg-paper-panel dark:bg-night border border-brand-soft outline-none"
        />
      </div>
    );
  }

  return (
    <div className="group relative flex items-center rounded-full hover:bg-paper-sink dark:hover:bg-night-panel transition">
      <button onClick={() => onOpen(s.id)}
              className="flex-1 text-left truncate pl-4 pr-2 py-2 text-base text-fg-soft">
        {s.title}
      </button>
      <button aria-label="More" ref={btnRef} title="More" onClick={openMenu}
              className={`pr-3 pl-1 text-ink-faint hover:text-fg transition ${menu ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
        <MoreIcon />
      </button>

      {menu && (
        <>
          <div className="fixed inset-0 z-40" onClick={closeMenu} />
          <div style={{ position: "fixed", top: menu.top, left: menu.left }}
               className="z-50 w-44 rounded-xl bg-surface-raised border border-border shadow-pop py-1 text-sm animate-rise">
            <button onClick={() => { setEditing(true); closeMenu(); }}
                    className="w-full text-left px-3 py-2 hover:bg-surface-press flex items-center gap-2">
              <PencilIcon /> Rename
            </button>
            <button onClick={() => { downloadChat(s.id); closeMenu(); }}
                    title="Download this chat as a zip (transcript + media)"
                    className="w-full text-left px-3 py-2 hover:bg-surface-press flex items-center gap-2">
              <DownloadIcon /> Download chat
            </button>
            <div className="relative" onMouseEnter={() => setSub(true)} onMouseLeave={() => setSub(false)}>
              <button className="w-full text-left px-3 py-2 hover:bg-surface-press flex items-center justify-between gap-2">
                <span className="flex items-center gap-2"><FolderIcon size={15} /> Add to project</span>
                <ChevronRight />
              </button>
              {sub && (
                <div className="absolute left-full top-0 ml-1 w-44 max-h-60 overflow-y-auto rounded-xl bg-surface-raised border border-border shadow-pop py-1">
                  {projects.length === 0 && <div className="px-3 py-2 text-ink-faint">No projects yet</div>}
                  {projects.map((p) => (
                    <button key={p.id} onClick={() => { onFile?.(s.id, p.id); closeMenu(); }}
                            className="w-full text-left px-3 py-2 truncate hover:bg-surface-press">
                      {p.name}
                    </button>
                  ))}
                  {s.project_id && (
                    <button onClick={() => { onFile?.(s.id, null); closeMenu(); }}
                            className="w-full text-left px-3 py-2 hover:bg-surface-press border-t border-border text-ink-faint">
                      Remove from project
                    </button>
                  )}
                </div>
              )}
            </div>
            <button onClick={async () => { closeMenu(); if (await onConfirm?.("Delete this chat? This can't be undone.")) onDelete(s.id); }}
                    className="w-full text-left px-3 py-2 hover:bg-surface-press flex items-center gap-2 text-brand-deep">
              <TrashIcon /> Delete
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Icons (thin-stroke line marks, claude.ai-inspired) ───────────────────────
const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" };
const ComposeIcon = () => (<IconEdit size={18} stroke={1.7} aria-hidden="true" />);
const FolderIcon = ({ size = 20 }) => (<IconFolder size={size} stroke={1.7} aria-hidden="true" />);
const MoreIcon = () => (<IconDots size={16} stroke={1.7} aria-hidden="true" />);
const PencilIcon = () => (<IconPencil size={15} stroke={1.7} aria-hidden="true" />);
const ChevronRight = () => (<IconChevronRight size={14} stroke={1.7} aria-hidden="true" />);
const CapIcon = () => (<IconSchool size={20} stroke={1.7} aria-hidden="true" />);
// Memory = a small knowledge-graph mark (nodes + links).
const MemoryIcon = () => (<IconAffiliate size={20} stroke={1.7} aria-hidden="true" />);
const TrashIcon = () => (<IconTrash size={14} stroke={1.7} aria-hidden="true" />);
const DownloadIcon = () => (<IconDownload size={15} stroke={1.7} aria-hidden="true" />);
const SearchIcon = () => (<IconSearch size={15} stroke={1.7} aria-hidden="true" />);
const XIcon = () => (<IconX size={13} stroke={1.7} aria-hidden="true" />);
const GearIcon = () => (<IconSettings size={19} stroke={1.7} aria-hidden="true" />);
