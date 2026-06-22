// Desktop notifications — backend-delivered.
//
// The browser Notification API doesn't surface as a real toast inside the
// pywebview / WebView2 desktop window, so notifications silently did nothing in
// the desktop app. Since Namma's server runs on the same machine, we deliver the
// toast from the *backend* (POST /api/notify → native OS notification) — reliable
// in both the desktop window and a plain browser tab.
//
// This module owns only the client-side preferences (master switch + per-event
// toggles, localStorage like the theme) and decides *whether* to fire; the server
// shows it. There's no OS-permission dance and no focus gating — if you turned an
// event on, it notifies.

const LS_ENABLED = "namma-notify-enabled";
const LS_EVENTS = "namma-notify-events"; // JSON: { approval, input, response, error, background }

export const NOTIFY_EVENTS = [
  { id: "response", label: "Response ready" },
  { id: "approval", label: "Approval needed" },
  { id: "input", label: "Input needed" },
  { id: "error", label: "Turn failed" },
  { id: "background", label: "Background task finished" },
];

// Master switch defaults OFF — desktop toasts are opt-in.
export const notifyEnabled = () => localStorage.getItem(LS_ENABLED) === "1";
export const setNotifyEnabled = (on) => localStorage.setItem(LS_ENABLED, on ? "1" : "0");

function evPrefs() {
  const base = { response: true, approval: true, input: true, error: true, background: true };
  try { return { ...base, ...JSON.parse(localStorage.getItem(LS_EVENTS) || "{}") }; }
  catch { return base; }
}
export const notifyEventEnabled = (id) => evPrefs()[id] !== false;
export const setNotifyEventEnabled = (id, on) =>
  localStorage.setItem(LS_EVENTS, JSON.stringify({ ...evPrefs(), [id]: !!on }));

// The assistant's (configurable) name — used as the toast title fallback. App.jsx
// feeds it in once /api/config resolves so toasts read "Aria", not "Namma Agent".
let _name = "Namma Agent";
export const setNotifyAppName = (n) => { if (n) _name = n; };

async function postNotify(title, body) {
  try {
    const r = await fetch("/api/notify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title || _name, body: body || "" }),
    });
    const j = await r.json().catch(() => null);
    return !!j?.ok;
  } catch { return false; }
}

// Fire a desktop notification for an event, honouring the master switch +
// per-event toggle. Fire-and-forget.
export function notify(event, { title, body } = {}) {
  if (!notifyEnabled() || !notifyEventEnabled(event)) return;
  postNotify(title, body);
}

// The "Send test notification" button — always fires (ignores the toggles), and
// reports whether the OS actually dispatched one.
export async function sendTestNotification() {
  return postNotify(_name, "Notifications are working.");
}
