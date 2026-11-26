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

// "rgb(a)(…)" / triplet / hex → {r, g, b, a}, or null when fully transparent.
export function toRGBA(value) {
  const v = String(value || "").trim();
  const hex = toHex(v);
  if (!hex) return null;
  const fn = v.match(/^rgba?\(([^)]+)\)$/i);
  const parts = fn ? fn[1].split(/[\s,/]+/).filter(Boolean) : [];
  let a = parts.length >= 4 ? parseFloat(parts[3]) : 1;
  if (parts[3] && parts[3].endsWith("%")) a = parseFloat(parts[3]) / 100;
  const n = parseInt(hex.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: Number.isFinite(a) ? Math.min(1, a) : 1 };
}

const over = (top, below) => ({
  r: top.r * top.a + below.r * (1 - top.a),
  g: top.g * top.a + below.g * (1 - top.a),
  b: top.b * top.a + below.b * (1 - top.a),
  a: 1,
});

// The colour actually painted at (x, y): every layer there, top to bottom
// (a dialog's translucent backdrop over the band, the band over the page…),
// composited until an opaque one. Taking just the first non-transparent layer
// would paint the controls black under a modal's rgba(0,0,0,.4) scrim.
export function paintedColorAt(x, y, doc = document, fallback = "255 255 255") {
  let stack = [];
  if (typeof doc.elementsFromPoint === "function") stack = doc.elementsFromPoint(x, y) || [];
  if (!stack.length) {
    for (let el = doc.elementFromPoint?.(x, y) || null; el && el.nodeType === 1; el = el.parentElement) stack.push(el);
  }
  const layers = [];
  for (const el of stack) {
    const c = toRGBA(getComputedStyle(el).backgroundColor);
    if (!c) continue;
    layers.push(c);
    if (c.a >= 1) break;
  }
  if (!layers.length) return null;
  let color = layers[layers.length - 1].a >= 1 ? layers.pop() : toRGBA(fallback) || { r: 255, g: 255, b: 255, a: 1 };
  while (layers.length) color = over(layers.pop(), color);
  return toHex(`rgb(${color.r}, ${color.g}, ${color.b})`);
}

export function titleBarColors(win = window) {
  const doc = win.document;
  const root = getComputedStyle(doc.documentElement);
  const bg = toHex(root.getPropertyValue("--bg")) || toHex(getComputedStyle(doc.body).backgroundColor) || toHex("255 255 255");
  const fg = toHex(root.getPropertyValue("--fg")) || toHex("17 17 17");
  // Sample just left of the controls' area, vertically centred in the band.
  const reserve = (win.navigator?.windowControlsOverlay?.getTitlebarAreaRect?.() || null);
  const x = reserve && reserve.width ? Math.max(0, reserve.x + reserve.width + 4) : Math.max(0, win.innerWidth - 40);
  const band = paintedColorAt(Math.min(x, win.innerWidth - 1), 17, doc, bg) || bg;
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

// ── Drag regions ─────────────────────────────────────────────────────────────
// Chromium applies `app-region` rectangles in document order, so a later drag
// region overrides an earlier no-drag one. The band's fixed tool clusters
// (.titlebar-cluster-left/right, from Titlebar.jsx) render BEFORE the panel
// headers that carry .app-drag, so their buttons were swallowed as window
// drags. These no-drag boxes come last in the document (#root::after and
// body::after) and sit exactly over the clusters, using the same CSS variables,
// so they always win. pointer-events: none lets clicks reach the buttons.
// (Cleaner long term: render the clusters after the headers in Titlebar.jsx.)
export const DRAG_FIX_CSS = `
#root::after, body::after {
  content: ""; position: fixed; z-index: 2147483647; pointer-events: none;
  top: 5px; height: 24px; -webkit-app-region: no-drag; app-region: no-drag;
}
#root::after { left: 14px; width: 24px; }
body::after { right: var(--titlebar-tools-right, 0.75rem); width: var(--titlebar-tools-width, 52px); }
`;

function installDragFix() {
  if (document.getElementById("namma-desktop-drag-fix")) return;
  const style = document.createElement("style");
  style.id = "namma-desktop-drag-fix";
  style.textContent = DRAG_FIX_CSS;
  document.head.appendChild(style);
}

let started = false;

export function initDesktop() {
  const api = desktop();
  if (started || !api || typeof document === "undefined") return false;
  started = true;
  installDragFix();
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
