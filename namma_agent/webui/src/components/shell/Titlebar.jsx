import { isDesktop } from "../../desktop.js";
import { IconLayoutSidebar, IconLayoutSidebarRight, IconSettings } from "@tabler/icons-react";

// Phase 9 — the titlebar the Hermes way. There is no full-width titlebar row:
// every top-edge panel (sidebar, main view, side panel) draws its own 34px
// header inside the window's titlebar band, and two small fixed tool
// clusters float on top of it:
//   left  — the sidebar toggle;
//   right — Settings and the side-panel toggle, pinned left of the native
//           window controls (Electron's titleBarOverlay on Windows/Linux;
//           the space is reserved with the `titlebar-area-*` env vars).
// Nothing sits in the centre. Empty band space drags the window on desktop.


function ToolButton({ label, onClick, pressed, children }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label} aria-pressed={pressed}
            className={`app-no-drag grid place-items-center h-6 w-6 rounded-sm transition-colors duration-fast hover:bg-surface-sunken ${pressed ? "text-accent" : "text-fg-muted hover:text-fg"}`}>
      {children}
    </button>
  );
}

export function TitlebarClusters({ onToggleSidebar, onOpenSettings, rightPaneOpen, onToggleRightPane }) {
  return (
    <>
      <div data-chrome data-titlebar-cluster="left" className="titlebar-cluster-left fixed z-[35] flex items-center gap-1">
        <ToolButton label="Toggle sidebar" onClick={onToggleSidebar}>
          <IconLayoutSidebar size={14} stroke={1.8} aria-hidden="true" />
        </ToolButton>
      </div>
      <div data-chrome data-titlebar-cluster="right" className="titlebar-cluster-right fixed z-[35] flex items-center gap-1">
        <ToolButton label="Settings" onClick={onOpenSettings}>
          <IconSettings size={14} stroke={1.8} aria-hidden="true" />
        </ToolButton>
        <ToolButton label={rightPaneOpen ? "Hide side panel" : "Show side panel"} onClick={onToggleRightPane} pressed={rightPaneOpen}>
          <IconLayoutSidebarRight size={14} stroke={1.8} aria-hidden="true" />
        </ToolButton>
      </div>
    </>
  );
}

// One panel's header inside the titlebar band. `reserveRight` keeps clear of
// the right tool cluster (+ native window controls) when this panel is the
// rightmost one; `reserveLeft` clears the left cluster.
export function PanelTitlebar({ children, reserveLeft = false, reserveRight = false, className = "", slotRef, surface = "chat" }) {
  return (
    <div data-chrome
         className={`panel-titlebar relative flex items-center gap-2 shrink-0 h-[var(--titlebar-height)] min-w-0 border-b border-border ${surface === "chat" ? "bg-bg" : "bg-surface-sunken"} ${isDesktop() ? "app-drag" : ""} ${reserveLeft ? "pl-[var(--titlebar-reserve-left)]" : "pl-4"} ${reserveRight ? "pr-[var(--titlebar-reserve-right)]" : "pr-3"} ${className}`}>
      <div ref={slotRef} className="flex items-center gap-2 min-w-0 flex-1 overflow-hidden">{children}</div>
      {surface === "chat" && <div aria-hidden="true" className="pointer-events-none absolute left-0 right-0 top-full h-4 bg-gradient-to-b from-bg to-transparent" />}
    </div>
  );
}
