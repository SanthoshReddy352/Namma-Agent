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

// /api/notify is auth-gated like every other route, so a self-hosted instance
// with server.auth_token set needs the token header — without it the POST 401s
// and every notification silently disappears. Read it from the same key api.js
// writes (importing api.js here would be a cycle: api.js imports this module).
function authHeaders() {
  try {
    const t = localStorage.getItem("namma_auth_token");
    return t ? { "X-Namma-Token": t } : {};
  } catch { return {}; }
}

// POST the toast. Resolves {ok, reason} — ok:false means the OS did NOT show
// anything (notifications switched off, no daemon, request failed).
async function postNotify(title, body) {
  try {
    const r = await fetch("/api/notify", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ title: title || _name, body: body || "" }),
    });
    const j = await r.json().catch(() => null);
    return { ok: !!j?.ok, reason: j?.reason || "" };
  } catch { return { ok: false, reason: "" }; }
}

// Whether this machine can render native toasts: {available, reason, platform}.
export async function notifyStatus() {
  try {
    const r = await fetch("/api/notify/status", { headers: authHeaders() });
    return (await r.json()) || { available: false, reason: "" };
  } catch { return { available: false, reason: "" }; }
}

// The in-app fallback. When the OS swallows the toast the notification would
// otherwise vanish, so we raise it inside the app instead — one code path that
// works identically in a browser tab and in the pywebview desktop window.
// NotifyToasts.jsx renders these.
export const INAPP_EVENT = "namma-inapp-notify";
export function showInAppNotification({ title, body, tone = "info" }) {
  window.dispatchEvent(new CustomEvent(INAPP_EVENT, {
    detail: { title: title || _name, body: body || "", tone, id: `${Date.now()}-${Math.random()}` },
  }));
}

// Fire a desktop notification for an event, honouring the master switch +
// per-event toggle. Falls back to the in-app banner when the OS shows nothing,
// so an enabled notification is never lost.
export function notify(event, { title, body } = {}) {
  if (!notifyEnabled() || !notifyEventEnabled(event)) return;
  postNotify(title, body).then(({ ok }) => {
    if (!ok) showInAppNotification({ title, body, tone: event === "error" ? "error" : "info" });
  });
}

// The "Send test notification" button — always fires (ignores the toggles), and
// reports what actually happened so Settings can tell the user the truth.
export async function sendTestNotification() {
  const r = await postNotify(_name, "Notifications are working.");
  if (!r.ok) showInAppNotification({ title: _name, body: "Notifications are working (shown in-app)." });
  return r;
}
