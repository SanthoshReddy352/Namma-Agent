import { modeById } from "../../roles.js";
import RoleEmblem from "../RoleEmblem.jsx";

// Phase 9 (Hermes layout): a thin status bar along the bottom — connection,
// the active role/mode, the current model (click to switch), and the running
// turn. Everything here is a shortcut to something that also lives elsewhere.
export default function StatusBar({ connected, mode, modelLabel, busy, onOpenModelPicker, onOpenPalette }) {
  const role = modeById(mode);
  return (
    <div data-chrome role="contentinfo"
         className="flex items-center gap-3 h-7 shrink-0 px-3 border-t border-border bg-surface-sunken text-xs text-fg-muted">
      <span className="inline-flex items-center gap-1.5" title={connected ? "Connected to the agent" : "Reconnecting…"}>
        <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-success" : "bg-danger animate-pulse"}`} />
        {connected ? "Connected" : "Reconnecting…"}
      </span>
      <span aria-hidden="true">·</span>
      <span title={role.description} className="inline-flex items-center gap-1">
        <RoleEmblem role={role.emblem} size={13} className="text-accent" />{role.role} · {role.label}
      </span>
      <span aria-hidden="true">·</span>
      <button type="button" onClick={onOpenModelPicker} className="truncate max-w-[220px] hover:text-fg"
              aria-label={`Model: ${modelLabel || "choose a model"}`}>
        {modelLabel || "Choose a model"}
      </button>
      {busy && <span className="inline-flex items-center gap-1 text-accent"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />Working…</span>}
      <button type="button" onClick={onOpenPalette} className="ml-auto hover:text-fg">Commands · Ctrl K</button>
    </div>
  );
}
