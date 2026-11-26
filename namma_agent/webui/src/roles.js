// Phase 9: the three conversation modes, each presented as a Roman role.
// Roles are a display layer only — the engine still sees "agent" | "chat" |
// "setup" (the websocket `mode` field). W4 adds portraits; until then each
// role shows its initial in a tile.
export const MODES = [
  {
    id: "agent",
    label: "Agent",
    role: "Imperator",
    description: "Plans and acts with tools: files, web, shell. Asks before anything risky.",
  },
  {
    id: "chat",
    label: "Chat",
    role: "Scriba",
    description: "Talks it through. No tools, just conversation.",
  },
  {
    id: "setup",
    label: "Setup",
    role: "Architectus",
    description: "Connects models, MCP servers, email and messaging for you.",
  },
];

export const modeById = (id) => MODES.find((m) => m.id === id) || MODES[0];
