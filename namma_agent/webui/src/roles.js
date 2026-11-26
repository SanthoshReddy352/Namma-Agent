// Phase 9: the three conversation modes, each presented as a Roman role.
// Roles are a display layer only — the engine still sees "agent" | "chat" |
// "setup" (the websocket `mode` field). W4: each role has an emblem
// (components/RoleEmblem.jsx), and Legatus names delegated sub-agents.
export const MODES = [
  {
    id: "agent",
    label: "Agent",
    role: "Imperator",
    emblem: "imperator",
    description: "Plans and acts with tools: files, web, shell. Asks before anything risky.",
  },
  {
    id: "chat",
    label: "Chat",
    role: "Scriba",
    emblem: "scriba",
    description: "Talks it through. No tools, just conversation.",
  },
  {
    id: "setup",
    label: "Setup",
    role: "Architectus",
    emblem: "architectus",
    description: "Connects models, MCP servers, email and messaging for you.",
  },
];

export const modeById = (id) => MODES.find((m) => m.id === id) || MODES[0];

// Delegated sub-agents (delegate_task) are the Imperator's legates. A display
// layer only, shown in the Runs pane.
export const LEGATUS = {
  role: "Legatus",
  emblem: "legatus",
  description: "A sub-agent the Imperator sent to handle part of the task.",
};
