import { isDesktop } from "../../desktop.js";
import { IconLayoutSidebarLeftCollapse, IconLayoutSidebarLeftExpand, IconLayoutSidebarRight, IconSettings } from "@tabler/icons-react";

// Phase 9 — the titlebar the Hermes way. There is no full-width titlebar row:
// every top-edge panel (sidebar, main view, side panel) draws its own 34px
// header inside the window's titlebar band, and two small fixed tool
// clusters float on top of it:
//   left  — the sidebar toggle;
//   right — Settings and the side-panel toggle, pinned left of the native
//           window controls (Electron's titleBarOverlay on Windows/Linux;
//           the space is reserved with the `titlebar-area-*` env vars).
// Nothing sits in the centre. Empty band space drags the window on desktop.


// The band's tools match the sidebar's own icons: a 28px rounded hit area with
// a 17px icon at the same stroke, centred in the 34px band. The sidebar toggle
// sits on the same vertical axis as the logo and the collapsed rail's icons
// (34px from the left edge), and its icon says what it will do.
function ToolButton({ label, onClick, pressed, children }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label} aria-pressed={pressed}
            className={`app-no-drag grid place-items-center h-7 w-7 rounded-lg transition-colors duration-fast hover:bg-surface-press ${pressed ? "text-accent bg-accent-wash" : "text-fg-muted hover:text-fg"}`}>
      {children}
    </button>
  );
}

const ICON = { size: 17, stroke: 1.75, "aria-hidden": true };

export function TitlebarClusters({ onToggleSidebar, sidebarCollapsed = false, onOpenSettings, rightPaneOpen, onToggleRightPane }) {
  const SidebarIcon = sidebarCollapsed ? IconLayoutSidebarLeftExpand : IconLayoutSidebarLeftCollapse;
  return (
    <>
      <div data-chrome data-titlebar-cluster="left" className="titlebar-cluster-left fixed z-[35] flex items-center gap-1">
        <ToolButton label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={onToggleSidebar}>
          <SidebarIcon {...ICON} />
        </ToolButton>
      </div>
      <div data-chrome data-titlebar-cluster="right" className="titlebar-cluster-right fixed z-[35] flex items-center gap-1">
        <ToolButton label="Settings" onClick={onOpenSettings}>
          <IconSettings {...ICON} />
        </ToolButton>
        <ToolButton label={rightPaneOpen ? "Hide side panel" : "Show side panel"} onClick={onToggleRightPane} pressed={rightPaneOpen}>
          <IconLayoutSidebarRight {...ICON} />
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
         className={`panel-titlebar relative flex items-center gap-2 shrink-0 h-[var(--titlebar-height)] min-w-0 border-b border-border/60 ${surface === "chat" ? "bg-bg/45 backdrop-blur-md" : "bg-surface-sunken"} ${isDesktop() ? "app-drag" : ""} ${reserveLeft ? "pl-[var(--titlebar-reserve-left)]" : "pl-4"} ${reserveRight ? "pr-[var(--titlebar-reserve-right)]" : "pr-3"} ${className}`}>
      <div ref={slotRef} className="flex items-center gap-2 min-w-0 flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
