// Settings sections, shared by the (lazy-loaded) Settings overlay, the router
// (/settings/:section) and the command palette — kept out of Settings.jsx so the
// palette doesn't pull the whole Settings chunk into the core bundle.
export const SETTINGS_GROUPS = [
  { label: "General", tabs: ["Behavior", "Persona", "Appearance", "Notifications"] },
  { label: "Intelligence", tabs: ["Model"] },
  { label: "Capabilities", tabs: ["Skills", "Toolsets", "MCP", "Routines", "Watchers", "Packs", "Browser"] },
  { label: "Channels", tabs: ["Messaging"] },
  { label: "System", tabs: ["Memory", "Security", "Checkpoints", "Learning", "Status", "About"] },
];
export const SETTINGS_TABS = SETTINGS_GROUPS.flatMap((g) => g.tabs);
export const DEFAULT_SETTINGS_TAB = "Behavior";

export const sectionSlug = (tab) => String(tab || "").toLowerCase();
// Old deep links keep working: Providers + Models merged into "Model", and the
// two MCP tabs (Config, Servers) into "MCP".
const SLUG_ALIASES = { providers: "Model", models: "Model", servers: "MCP", config: "MCP" };
export const tabForSlug = (slug) => {
  const s = String(slug || "").toLowerCase();
  return SETTINGS_TABS.find((t) => sectionSlug(t) === s) || SLUG_ALIASES[s] || null;
};
export const settingsPath = (tab) => `/settings/${sectionSlug(tab || DEFAULT_SETTINGS_TAB)}`;
