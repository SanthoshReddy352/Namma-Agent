// Phase 9: the same UI runs in the browser and inside the Electron desktop app
// (W3). The desktop preload exposes `window.nammaDesktop`; everything here
// feature-detects it, so the web build never assumes it exists.
export const desktop = () => (typeof window !== "undefined" ? window.nammaDesktop || null : null);
export const isDesktop = () => !!desktop();

// ── Title bar overlay ────────────────────────────────────────────────────────
// On desktop the OS's min/max/close are drawn over our 34px band
// (Electron `titleBarOverlay`). Their background must be the colour of whatever
// panel sits under them (chat, a page, the side panel) and their glyphs the
// theme ink, or a solid strip shows. We re-send both whenever the theme class
// changes (theme-* / dark), the layout under the controls changes, or the
// window resizes. Only changes are sent.

// "246 248 252" (our token format), "rgb(…)/rgba(…)" or "#rrggbb" → "#rrggbb",
// or null for transparent / unparseable values.
export function toHex(value) {
  const v = String(value || "").trim();
  if (/^#[0-9a-f]{6}$/i.test(v)) return v.toLowerCase();
  let parts = null;
  const fn = v.match(/^rgba?\(([^)]+)\)$/i);
  if (fn) parts = fn[1].split(/[\s,/]+/).filter(Boolean);
  else if (/^\d+(\.\d+)?\s+\d+(\.\d+)?\s+\d+(\.\d+)?$/.test(v)) parts = v.split(/\s+/);
  if (!parts || parts.length < 3) return null;
  if (parts.length >= 4 && parseFloat(parts[3]) === 0) return null;
  const hex = parts.slice(0, 3).map((n) => Math.max(0, Math.min(255, Math.round(parseFloat(n)))).toString(16).padStart(2, "0"));
  return hex.some((h) => h === "NaN") ? null : `#${hex.join("")}`;
}

// The opaque background colour actually painted at (x, y): the first ancestor
// of the element there with a non-transparent background.
export function paintedColorAt(x, y, doc = document) {
  let el = doc.elementFromPoint?.(x, y) || null;
  while (el && el.nodeType === 1) {
    const hex = toHex(getComputedStyle(el).backgroundColor);
    if (hex) return hex;
    el = el.parentElement;
  }
  return null;
}

export function titleBarColors(win = window) {
  const doc = win.document;
  const root = getComputedStyle(doc.documentElement);
  const bg = toHex(root.getPropertyValue("--bg")) || toHex(getComputedStyle(doc.body).backgroundColor) || "#ffffff";
  const fg = toHex(root.getPropertyValue("--fg")) || "#111111";
  // Sample just left of the controls' area, vertically centred in the band.
  const reserve = (win.navigator?.windowControlsOverlay?.getTitlebarAreaRect?.() || null);
  const x = reserve && reserve.width ? Math.max(0, reserve.x + reserve.width + 4) : Math.max(0, win.innerWidth - 40);
  const band = paintedColorAt(Math.min(x, win.innerWidth - 1), 17, doc) || bg;
  return { color: band, symbolColor: fg, background: bg, dark: doc.documentElement.classList.contains("dark") };
}

let last = "";
let raf = 0;
let idle = 0;

function syncTitleBar() {
  raf = 0;
  const api = desktop();
  if (!api?.setTitleBarOverlay || !document.body) return;
  const c = titleBarColors(window);
  const key = JSON.stringify(c);
  if (key === last) return;
  last = key;
  api.setTitleBarOverlay({ ...c, height: 34 });
}

const scheduleSync = () => { if (raf) return; raf = -1; requestAnimationFrame(syncTitleBar); };
// Layout churn (streaming tokens, panel toggles) is debounced harder.
const scheduleSyncIdle = () => { clearTimeout(idle); idle = setTimeout(scheduleSync, 150); };

// ── Shell → page events (deep links, tray "New chat", notification clicks) ──

function navigate(route) {
  if (typeof route !== "string" || !route.startsWith("/")) return;
  if (location.pathname + location.search === route) return;
  // react-router's BrowserRouter follows history + popstate.
  const idx = (window.history.state && window.history.state.idx) || 0;
  window.history.pushState({ usr: null, key: Math.random().toString(36).slice(2, 10), idx: idx + 1 }, "", route);
  window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
}

function newChat() {
  navigate("/");
  const started = Date.now();
  const tryClick = () => {
    const btn = document.querySelector('button[aria-label="New chat"]');
    if (btn) { btn.click(); return; }
    if (Date.now() - started < 5000) setTimeout(tryClick, 100);
  };
  tryClick();
}

export function handleShellEvent(ev) {
  if (!ev || typeof ev !== "object") return;
  if (ev.type === "navigate") navigate(ev.route);
  else if (ev.type === "new-chat") newChat();
}

let started = false;

export function initDesktop() {
  const api = desktop();
  if (started || !api || typeof document === "undefined") return false;
  started = true;
  new MutationObserver(scheduleSync).observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
  const watchRoot = () => {
    const root = document.getElementById("root") || document.body;
    if (root) new MutationObserver(scheduleSyncIdle).observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { watchRoot(); scheduleSync(); }, { once: true });
  else { watchRoot(); scheduleSync(); }
  window.addEventListener("resize", scheduleSyncIdle);
  api.onEvent?.(handleShellEvent);
  return true;
}

initDesktop();
