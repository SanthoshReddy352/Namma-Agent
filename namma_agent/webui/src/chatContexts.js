import { createContext } from "react";

// Chat views provide `send(text)` so a secret card can tell the agent "saved".
// Kept in its own tiny module so the chat shell does not pull SetupUI (and the
// rest of the setup wizard) into the core bundle (Phase 6).
export const ChatSendContext = createContext(null);
