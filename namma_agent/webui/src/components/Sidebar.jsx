import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { downloadChat, searchChats } from "../api.js";
import Logo from "./Logo.jsx";

// Gemini-style navigation rail: a slim icon rail that expands on hover, or pins
// open via the hamburger. Icons are hand-drawn thin-stroke line marks in the
// spirit of claude.ai. Nav: New chat · Projects · Learning Room, then Recent
// chats, with Settings pinned to the bottom.
export default function Sidebar({ sessions, projects = [], onNew, onOpen, onDelete, onRename, onFile, onConfirm, onOpenSettings, collapsed, onToggle, name = "Namma Agent" }) {
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

  const navItem = (to, icon, label, active) => (
    <button
      onClick={() => navigate(to)}
      title={label}
      className={`flex items-center gap-3 rounded-full h-10 transition-colors w-full
        ${expanded ? "px-3" : "px-0 justify-center"}
        ${active
          ? "bg-brand-wash text-brand-deep dark:bg-night-panel dark:text-brand-soft"
          : "text-ink-soft dark:text-night-faint hover:bg-paper-sink dark:hover:bg-night-panel"}`}
    >
      <span className="shrink-0 grid place-items-center w-7">{icon}</span>
      {expanded && <span className="truncate text-[14px]">{label}</span>}
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
          bg-paper-soft dark:bg-night-soft
          border-r border-line dark:border-night-line transition-[width] duration-200
          ${expanded ? "w-64" : "w-[68px]"} ${hovered && !pinned ? "shadow-pop" : ""}`}
      >
        {/* Header. Collapsed: the brand logo (click to open). Expanded: hamburger
            (pin/collapse) + logo + name. */}
        <div className="flex items-center h-14 px-3.5 gap-2">
          {expanded ? (
            <>
              <button onClick={togglePin} title={pinned ? "Collapse menu" : "Pin menu open"}
                      className="h-9 w-9 shrink-0 grid place-items-center rounded-full hover:bg-paper-sink dark:hover:bg-night-panel text-ink-soft dark:text-night-faint">
                <MenuIcon />
              </button>
              <button onClick={() => navigate("/")} className="flex items-center gap-2 min-w-0">
                <Logo size={24} />
                <span className="font-serif text-[17px] tracking-tight truncate">{name}</span>
              </button>
            </>
          ) : (
            <button onClick={togglePin} title="Open menu"
                    className="h-9 w-9 mx-auto grid place-items-center rounded-full hover:bg-paper-sink dark:hover:bg-night-panel">
              <Logo size={24} />
            </button>
          )}
        </div>

        {/* New chat — prominent pill */}
        <div className={`px-3 ${expanded ? "" : "flex justify-center"}`}>
          <button onClick={onNew} title="New chat"
            className={`flex items-center gap-3 rounded-full bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line hover:shadow-soft transition
              ${expanded ? "px-4 h-11 w-full" : "h-11 w-11 justify-center"}`}>
            <ComposeIcon />
            {expanded && <span className="text-[14px] font-medium">New chat</span>}
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
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint dark:text-night-faint"><SearchIcon /></span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Escape") setQuery(""); }}
                  placeholder="Search chats…"
                  className="w-full h-9 rounded-full pl-9 pr-8 text-[13px] bg-paper-panel dark:bg-night-panel
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
            <div className="mt-3 px-5 text-[11px] uppercase tracking-wider text-ink-faint dark:text-night-faint">
              {results !== null ? "Search results" : "Recent"}
            </div>
            <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5 mt-1">
              {results !== null ? (
                <>
                  {results.length === 0 && (
                    <div className="px-3 py-4 text-[13px] text-ink-faint dark:text-night-faint">No chats match.</div>
                  )}
                  {results.map((r) => (
                    <button key={r.session_id} onClick={() => onOpen(r.session_id)}
                            className="w-full text-left rounded-xl px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-panel transition">
                      <div className="flex items-baseline gap-2">
                        <span className="truncate text-[13.5px] text-ink-soft dark:text-night-ink">{r.title}</span>
                        {r.date && <span className="ml-auto shrink-0 text-[11px] text-ink-faint dark:text-night-faint">{r.date}</span>}
                      </div>
                      <div className="truncate text-[12px] text-ink-faint dark:text-night-faint">{r.snippet}</div>
                    </button>
                  ))}
                </>
              ) : (
                <>
                  {(!sessions || sessions.length === 0) && (
                    <div className="px-3 py-4 text-[13px] text-ink-faint dark:text-night-faint">No conversations yet.</div>
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

        {/* Settings pinned to bottom */}
        <div className="p-3 border-t border-line dark:border-night-line">
          <button onClick={onOpenSettings} title="Settings"
            className={`flex items-center gap-3 rounded-full h-10 text-ink-soft dark:text-night-ink hover:bg-paper-sink dark:hover:bg-night-panel w-full
              ${expanded ? "px-3" : "px-0 justify-center"}`}>
            <span className="shrink-0 grid place-items-center w-7"><GearIcon /></span>
            {expanded && <span className="text-[14px]">Settings</span>}
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
          className="w-full rounded-lg px-3 py-1.5 text-[13.5px] bg-paper-panel dark:bg-night border border-brand-soft outline-none"
        />
      </div>
    );
  }

  return (
    <div className="group relative flex items-center rounded-full hover:bg-paper-sink dark:hover:bg-night-panel transition">
      <button onClick={() => onOpen(s.id)}
              className="flex-1 text-left truncate pl-4 pr-2 py-2 text-[13.5px] text-ink-soft dark:text-night-ink">
        {s.title}
      </button>
      <button ref={btnRef} title="More" onClick={openMenu}
              className={`pr-3 pl-1 text-ink-faint hover:text-ink dark:hover:text-night-ink transition ${menu ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
        <MoreIcon />
      </button>

      {menu && (
        <>
          <div className="fixed inset-0 z-40" onClick={closeMenu} />
          <div style={{ position: "fixed", top: menu.top, left: menu.left }}
               className="z-50 w-44 rounded-xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop py-1 text-[13px] animate-rise">
            <button onClick={() => { setEditing(true); closeMenu(); }}
                    className="w-full text-left px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-soft flex items-center gap-2">
              <PencilIcon /> Rename
            </button>
            <button onClick={() => { downloadChat(s.id); closeMenu(); }}
                    title="Download this chat as a zip (transcript + media)"
                    className="w-full text-left px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-soft flex items-center gap-2">
              <DownloadIcon /> Download chat
            </button>
            <div className="relative" onMouseEnter={() => setSub(true)} onMouseLeave={() => setSub(false)}>
              <button className="w-full text-left px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-soft flex items-center justify-between gap-2">
                <span className="flex items-center gap-2"><FolderIcon size={15} /> Add to project</span>
                <ChevronRight />
              </button>
              {sub && (
                <div className="absolute left-full top-0 ml-1 w-44 max-h-60 overflow-y-auto rounded-xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop py-1">
                  {projects.length === 0 && <div className="px-3 py-2 text-ink-faint">No projects yet</div>}
                  {projects.map((p) => (
                    <button key={p.id} onClick={() => { onFile?.(s.id, p.id); closeMenu(); }}
                            className="w-full text-left px-3 py-2 truncate hover:bg-paper-sink dark:hover:bg-night-soft">
                      {p.name}
                    </button>
                  ))}
                  {s.project_id && (
                    <button onClick={() => { onFile?.(s.id, null); closeMenu(); }}
                            className="w-full text-left px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-soft border-t border-line dark:border-night-line text-ink-faint">
                      Remove from project
                    </button>
                  )}
                </div>
              )}
            </div>
            <button onClick={async () => { closeMenu(); if (await onConfirm?.("Delete this chat? This can't be undone.")) onDelete(s.id); }}
                    className="w-full text-left px-3 py-2 hover:bg-paper-sink dark:hover:bg-night-soft flex items-center gap-2 text-brand-deep">
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
const MenuIcon = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...stroke}><path d="M3 6h18M3 12h18M3 18h18" /></svg>);
const ComposeIcon = () => (<svg width="18" height="18" viewBox="0 0 24 24" {...stroke}><path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" /><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L13 14l-4 1 1-4 8.5-8.5Z" /></svg>);
const FolderIcon = ({ size = 20 }) => (<svg width={size} height={size} viewBox="0 0 24 24" {...stroke}><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" /></svg>);
const MoreIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...stroke}><circle cx="5" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="19" cy="12" r="1.3" /></svg>);
const PencilIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" {...stroke}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z" /></svg>);
const ChevronRight = () => (<svg width="14" height="14" viewBox="0 0 24 24" {...stroke}><path d="m9 6 6 6-6 6" /></svg>);
const CapIcon = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...stroke}><path d="M2 9 12 4l10 5-10 5L2 9Z" /><path d="M6 11v5c0 1 2.7 2.5 6 2.5s6-1.5 6-2.5v-5" /><path d="M22 9v5" /></svg>);
// Memory = a small knowledge-graph mark (nodes + links).
const MemoryIcon = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...stroke}><circle cx="6" cy="7" r="2.2" /><circle cx="18" cy="8" r="2.2" /><circle cx="12" cy="17" r="2.2" /><path d="M7.8 8.4 10.4 15M16.7 9.7 13.3 15.6M8 7.4 16 8" /></svg>);
const TrashIcon = () => (<svg width="14" height="14" viewBox="0 0 24 24" {...stroke}><path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>);
const DownloadIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" {...stroke}><path d="M21 15v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3" /><path d="M7 10l5 5 5-5M12 15V3" /></svg>);
const SearchIcon = () => (<svg width="15" height="15" viewBox="0 0 24 24" {...stroke}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>);
const XIcon = () => (<svg width="13" height="13" viewBox="0 0 24 24" {...stroke}><path d="M18 6 6 18M6 6l12 12" /></svg>);
const GearIcon = () => (<svg width="19" height="19" viewBox="0 0 24 24" {...stroke}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" /></svg>);
