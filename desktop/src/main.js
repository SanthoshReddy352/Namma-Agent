// Namma Agent desktop — the Electron main process (Phase 9 W3).
//
// Lifecycle: single instance → splash → start the Python backend on a free
// localhost port (NAMMA_DESKTOP=1, per-launch token) → wait for /api/health →
// load the web UI → stop the backend cleanly on quit.
//
// The window has no native title bar: the page draws a 34px band and Windows'
// own min/max/close are overlaid on it (titleBarOverlay), coloured to match the
// theme via window.nammaDesktop.setTitleBarOverlay (webui/src/desktop.js).
"use strict";

const { app, BrowserWindow, Menu, Notification, Tray, dialog, globalShortcut, ipcMain,
  nativeImage, nativeTheme, screen, session, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const { Backend, locate, pickPort } = require("./backend");
const { Bus } = require("./bus");
const { PROTOCOL, findDeepLink, parseDeepLink, safeRoute } = require("./deeplink");
const { Store } = require("./store");
const { createUpdater } = require("./updater");
const windowState = require("./windowState");

const APP_ID = "com.namma.agent";
const TITLEBAR_HEIGHT = 34;
const LOGIN_ITEM_NAME = "NammaAgent";   // same value name the backend's autostart writes
const RESOURCES = path.join(__dirname, "..", "resources");
const REPO_ROOT = path.resolve(__dirname, "..", "..");

// Scratch/dev isolation: a different userData keeps test runs away from the
// real profile (window state, Chromium storage, backend data).
if (process.env.NAMMA_DESKTOP_USER_DATA) app.setPath("userData", process.env.NAMMA_DESKTOP_USER_DATA);
// Development runs use their own AUMID: Windows caches an AUMID's display name
// from the first process that posts a toast under it, and electron.exe would
// otherwise make the installed app appear as "Electron" in Start and in toasts.
if (process.platform === "win32") app.setAppUserModelId(app.isPackaged ? APP_ID : `${APP_ID}.dev`);

// Windows names and badges a toast from the Start-menu shortcut carrying the
// app's AUMID. The installer creates "Namma Agent.lnk" for com.namma.agent; a
// development run has none, so Electron would create "Electron.lnk" (Electron's
// name and atom icon) on the first toast. Give dev runs their own shortcut with
// the brand icon instead, and remove an Electron.lnk that claimed our dev AUMID.
function ensureDevShortcut() {
  if (app.isPackaged || process.platform !== "win32") return;
  const dir = path.join(app.getPath("appData"), "Microsoft", "Windows", "Start Menu", "Programs");
  const aumid = `${APP_ID}.dev`;
  try {
    const ok = shell.writeShortcutLink(path.join(dir, "Namma Agent (dev).lnk"), "create", {
      target: process.execPath,
      args: `"${app.getAppPath()}"`,
      appUserModelId: aumid,
      icon: path.join(RESOURCES, "icon.ico"),
      iconIndex: 0,
      description: "Namma Agent (development run)",
    });
    if (!ok) log("dev shortcut: writeShortcutLink failed");
    const stray = path.join(dir, "Electron.lnk");
    if (fs.existsSync(stray) && shell.readShortcutLink(stray).appUserModelId === aumid) fs.unlinkSync(stray);
  } catch (e) { log(`dev shortcut: ${e.message}`); }
}

// ── single instance ─────────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

// A bug in a handler should be logged, not crash the shell or pop a dialog.
process.on("uncaughtException", (err) => { try { log(`uncaught: ${err && err.stack || err}`); } catch { /* ignore */ } });
process.on("unhandledRejection", (err) => { try { log(`unhandled rejection: ${err && err.stack || err}`); } catch { /* ignore */ } });

const userData = app.getPath("userData");
const logDir = path.join(userData, "logs");
const store = new Store(path.join(userData, "desktop-settings.json"), {
  closeToTray: true,
  port: null,
  theme: { bg: "#f6f8fc", fg: "#10131a", band: "#f6f8fc" },
  assistantName: "Namma Agent",
  trayHintShown: false,
});

let win = null;
let tray = null;
let backend = null;
let bus = null;
let quitting = false;
let bootError = null;
let pendingLink = findDeepLink(process.argv);
const startHidden = process.argv.includes("--hidden");

function log(msg) {
  try {
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, "desktop.log"), `${new Date().toISOString()} ${msg}\n`);
  } catch { /* best-effort */ }
}

const appName = () => store.get("assistantName") || "Namma Agent";
const getWindow = () => (win && !win.isDestroyed() ? win : null);
const pagesUrl = (file, extra = {}) => {
  const t = store.get("theme") || {};
  const q = new URLSearchParams({ bg: t.bg || "", fg: t.fg || "", name: appName(), ...extra });
  return `file://${path.join(__dirname, "pages", file).replace(/\\/g, "/")}?${q}`;
};
const isBootPage = (wc) => (wc.getURL() || "").startsWith("file://");
const isAppUrl = (url) => {
  if (!backend || !backend.port || typeof url !== "string") return false;
  return url === backend.url || url.startsWith(`${backend.url}/`);
};

// ── window ──────────────────────────────────────────────────────────────────

function createWindow() {
  const displays = screen.getAllDisplays().map((d) => d.workArea);
  const bounds = windowState.restoreBounds(store.get("window"), displays, screen.getPrimaryDisplay().workArea);
  const theme = store.get("theme") || {};
  win = new BrowserWindow({
    x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
    minWidth: windowState.MIN.width, minHeight: windowState.MIN.height,
    show: false,
    title: appName(),
    icon: path.join(RESOURCES, process.platform === "win32" ? "icon.ico" : "icon.png"),
    backgroundColor: theme.bg || "#f6f8fc",
    titleBarStyle: "hidden",
    titleBarOverlay: { color: theme.band || theme.bg || "#f6f8fc", symbolColor: theme.fg || "#10131a", height: TITLEBAR_HEIGHT },
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
    },
  });
  windowState.track(win, store);
  if (bounds.maximized) win.maximize();

  win.once("ready-to-show", () => { if (!startHidden) win.show(); });
  win.on("close", (e) => {
    if (quitting || !store.get("closeToTray") || !tray) return;
    e.preventDefault();
    win.hide();
    if (!store.get("trayHintShown") && Notification.isSupported()) {
      store.set("trayHintShown", true);
      new Notification({ title: appName(), body: "Still running in the tray. Right-click the tray icon to quit.",
        icon: path.join(RESOURCES, "icon.png") }).show();
    }
  });

  const wc = win.webContents;
  // Links: our own pages stay in-app; everything else opens in the browser.
  wc.setWindowOpenHandler(({ url }) => {
    if (isAppUrl(url)) {
      return { action: "allow", overrideBrowserWindowOptions: { autoHideMenuBar: true, icon: path.join(RESOURCES, "icon.png") } };
    }
    if (/^https?:\/\//i.test(url) || /^mailto:/i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  wc.on("will-navigate", (e, url) => {
    if (isAppUrl(url) || url.startsWith("file://")) return;
    e.preventDefault();
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
  });
  wc.on("before-input-event", (e, input) => {
    if (input.type !== "keyDown") return;
    const devtools = (input.control || input.meta) && input.shift && input.key.toLowerCase() === "i";
    if ((devtools || input.key === "F12") && (!app.isPackaged || process.env.NAMMA_DESKTOP_DEVTOOLS)) {
      wc.toggleDevTools(); e.preventDefault();
    }
    if (input.key === "F5" || ((input.control || input.meta) && input.key.toLowerCase() === "r")) {
      if (!isBootPage(wc)) { wc.reload(); e.preventDefault(); }
    }
  });
  wc.on("render-process-gone", (_e, d) => {
    log(`renderer gone: ${d.reason}`);
    if (!quitting && d.reason !== "clean-exit" && backend && backend.alive()) wc.loadURL(`${backend.url}/`);
  });
  wc.on("page-title-updated", (_e, title) => {
    // The web UI sets document.title from the configured assistant name.
    if (tray && title) tray.setToolTip(title);
  });
  return win;
}

function showWindow() {
  const w = getWindow();
  if (!w) return;
  if (w.isMinimized()) w.restore();
  w.show();
  w.focus();
}

function toggleWindow() {
  const w = getWindow();
  if (!w) return;
  if (w.isVisible() && w.isFocused()) w.hide(); else showWindow();
}

function sendToPage(ev) {
  const w = getWindow();
  if (!w || isBootPage(w.webContents)) { pendingLink = ev; return; }
  w.webContents.send("desktop:event", ev);
}

function handleDeepLink(raw) {
  const action = parseDeepLink(raw);
  log(`deep link ${raw} -> ${JSON.stringify(action)}`);
  showWindow();
  if (!action || action.type === "show") return;
  sendToPage(action);
}

// ── tray ────────────────────────────────────────────────────────────────────

function trayIcon() {
  const img = nativeImage.createFromPath(path.join(RESOURCES, process.platform === "win32" ? "icon.ico" : "tray.png"));
  return process.platform === "win32" ? img.resize({ width: 16, height: 16 }) : img;
}

function buildTrayMenu() {
  const login = loginItem();
  return Menu.buildFromTemplate([
    { label: `Show ${appName()}`, click: showWindow },
    { label: "New chat", click: () => { showWindow(); sendToPage({ type: "new-chat" }); } },
    { type: "separator" },
    { label: "Start at login", type: "checkbox", checked: login, click: (i) => setLoginItem(i.checked) },
    { label: "Keep running when the window is closed", type: "checkbox", checked: !!store.get("closeToTray"),
      click: (i) => store.set("closeToTray", i.checked) },
    { label: "Check for updates…", click: () => updater.check({ userInitiated: true }) },
    { label: "Open logs folder", click: () => shell.openPath(logDir) },
    { type: "separator" },
    { label: "Quit", click: () => { quitting = true; app.quit(); } },
  ]);
}

function createTray() {
  tray = new Tray(trayIcon());
  tray.setToolTip(appName());
  tray.setContextMenu(buildTrayMenu());
  tray.on("click", toggleWindow);
  tray.on("double-click", showWindow);
}

const refreshTray = () => { if (tray) { tray.setContextMenu(buildTrayMenu()); tray.setToolTip(appName()); } };

// ── start at login ──────────────────────────────────────────────────────────

function loginSettings() {
  return { path: process.execPath, args: ["--hidden"], name: LOGIN_ITEM_NAME };
}

function loginItem() {
  if (process.platform === "linux") return false;
  try {
    const s = app.getLoginItemSettings(loginSettings());
    // On Windows `openAtLogin` compares the arguments too and reads our quoted
    // "--hidden" back as none, so find our own Run entry by name instead.
    if (Array.isArray(s.launchItems)) return s.launchItems.some((i) => i.name === LOGIN_ITEM_NAME && i.enabled !== false);
    return !!s.openAtLogin;
  } catch { return false; }
}

function setLoginItem(on) {
  if (process.platform === "linux") return false;
  if (!app.isPackaged && on) {
    dialog.showMessageBox({ type: "info", message: "Start at login is available in the installed app.",
      detail: "A development run would register electron.exe, so it's left off here." });
    refreshTray();
    return false;
  }
  app.setLoginItemSettings({ openAtLogin: !!on, ...loginSettings() });
  refreshTray();
  return loginItem();
}

// ── native notifications (desktop_notify from the backend) ──────────────────

function showNotification({ title, body, action }) {
  if (!Notification.isSupported()) return false;
  const n = new Notification({
    title: String(title || appName()).slice(0, 200),
    body: String(body || "").slice(0, 1000),
    icon: path.join(RESOURCES, "icon.png"),
  });
  n.on("click", () => {
    showWindow();
    const route = safeRoute(action);
    if (route) sendToPage({ type: "navigate", route });
  });
  n.show();
  return true;
}

function onBusEvent(msg) {
  if (msg.type === "desktop_notify") {
    log(`notify: ${String(msg.title || "").slice(0, 80)}`);
    showNotification(msg);
    return;
  }
  if (msg.type !== "desktop_command") return;
  log(`command ${msg.action}`);
  if (msg.action === "focus") showWindow();
  // The web UI checks on its own (update banner, About tab), so a forwarded
  // check is quiet: the shell only speaks up when an update actually exists.
  else if (msg.action === "update_check") updater.check();
  else if (msg.action === "update_apply") updater.apply();
  else if (msg.action === "uninstall") runUninstaller(msg.scope);
}

// ── uninstall (from Settings → About → Danger zone) ─────────────────────────

function uninstallerPath() {
  if (!app.isPackaged || process.platform !== "win32") return null;
  const p = path.join(path.dirname(process.execPath), `Uninstall ${app.getName()}.exe`);
  return fs.existsSync(p) ? p : null;
}

async function runUninstaller(scope) {
  const exe = uninstallerPath();
  if (!exe) {
    dialog.showMessageBox(getWindow() || undefined, { type: "info", message: "Nothing to uninstall here.",
      detail: "This is not an installed copy. Use Windows Settings → Apps for installed copies." });
    return;
  }
  // The choice was already made in Settings → About (keep my data / everything),
  // so pass it on and the uninstaller doesn't ask again (resources/installer.nsh).
  // Quit first so our files unlock; the uninstaller waits for the app to exit.
  const dataFlag = scope === "all" ? "--delete-app-data" : "--keep-app-data";
  log(`uninstall: ${exe} ${dataFlag}`);
  require("child_process").spawn(exe, ["/currentuser", dataFlag], { detached: true, stdio: "ignore" }).unref();
  quitting = true;
  app.quit();
}

// ── boot ────────────────────────────────────────────────────────────────────

const updater = createUpdater({
  log, getWindow, appName,
  beforeInstall: async () => { quitting = true; await shutdownBackend(); },
  onShow: () => showWindow(),
  // Tell the backend, so the web UI's update banner and Settings → About can
  // show "Update available" and drive "Update now" (/api/update/apply).
  onState: (st) => {
    if (backend && backend.alive()) {
      backend.api("/api/desktop/update-state", { method: "POST", body: st }).catch(() => {});
    }
  },
});

function injectToken(b) {
  // Every request the page makes to its backend (fetch, <img>, the /ws upgrade)
  // carries the per-launch token, so the page itself never has to hold it.
  const filter = { urls: [`http://127.0.0.1:${b.port}/*`, `ws://127.0.0.1:${b.port}/*`] };
  session.defaultSession.webRequest.onBeforeSendHeaders(filter, (d, cb) => {
    cb({ requestHeaders: { ...d.requestHeaders, "X-Namma-Token": b.token } });
  });
}

function permissions() {
  const allowed = new Set(["media", "clipboard-read", "clipboard-sanitized-write", "notifications", "fullscreen"]);
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb, details) => {
    const origin = details.requestingUrl || wc.getURL();
    if (!isAppUrl(origin)) return cb(false);
    if (perm === "media") return cb(!(details.mediaTypes || []).includes("video"));
    cb(allowed.has(perm));
  });
}

async function startBackend() {
  bootError = null;
  const loc = locate({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, repoRoot: REPO_ROOT });
  const port = await pickPort(store.get("port"));
  store.set("port", port);
  backend = new Backend({
    ...loc,
    dataRoot: userData,
    logDir,
    env: {
      NAMMA_DESKTOP_VERSION: app.getVersion(),
      ...(app.isPackaged ? { NAMMA_DESKTOP_EXE: process.execPath } : {}),
      ...(uninstallerPath() ? { NAMMA_DESKTOP_UNINSTALLER: uninstallerPath() } : {}),
    },
    onExit: ({ expected }) => {
      if (bus) bus.stop();
      if (expected || quitting) return;
      bootError = "The local engine stopped unexpectedly.";
      const w = getWindow();
      if (w) w.loadURL(pagesUrl("error.html"));
      showWindow();
    },
  });
  log(`backend: ${loc.python} (app ${loc.appRoot}) port ${port}`);
  await backend.start(port);
  injectToken(backend);
  const healthy = await backend.waitHealthy();
  if (!healthy) {
    bootError = backend.exitInfo
      ? `The local engine exited during start-up (${backend.exitInfo.error || `code ${backend.exitInfo.code}`}).`
      : "The local engine didn't respond within 90 seconds.";
    log(`boot failed: ${bootError}`);
    if (backend.alive()) await backend.stop(1000);
    return false;
  }
  bus = new Bus({ url: backend.url, token: backend.token, onEvent: onBusEvent, isAlive: () => backend.alive(), log });
  bus.start();
  // Check for updates right away (quiet), so the answer is ready when the web
  // UI's banner asks via /api/update/check.
  if (app.isPackaged || process.env.NAMMA_DESKTOP_UPDATE_URL) updater.check();
  // The configured assistant name (assistant.name) for the tray and splash.
  backend.api("/api/config").then((r) => {
    const name = r.json && (r.json.assistant_name || r.json.name);
    if (name) { store.set("assistantName", name); refreshTray(); }
  }).catch(() => {});
  return true;
}

async function boot() {
  const w = getWindow();
  w.loadURL(pagesUrl("splash.html"));
  const ok = await startBackend();
  if (!getWindow()) return;
  if (!ok) { win.loadURL(pagesUrl("error.html")); showWindow(); return; }
  await win.loadURL(`${backend.url}/`);
  if (pendingLink) {
    const link = pendingLink;
    pendingLink = null;
    if (typeof link === "string") handleDeepLink(link); else sendToPage(link);
  }
}

async function shutdownBackend() {
  if (bus) bus.stop();
  if (backend) await backend.stop();
}

// ── IPC (window.nammaDesktop) ───────────────────────────────────────────────

const HEX = /^#[0-9a-f]{6}([0-9a-f]{2})?$/i;

function registerIpc() {
  ipcMain.on("titlebar:set", (e, opts = {}) => {
    const w = BrowserWindow.fromWebContents(e.sender);
    if (!w || w !== getWindow()) return;
    const color = HEX.test(opts.color || "") ? opts.color : null;
    const symbolColor = HEX.test(opts.symbolColor || "") ? opts.symbolColor : null;
    const bg = HEX.test(opts.background || "") ? opts.background : null;
    if (!color || !symbolColor) return;
    try { w.setTitleBarOverlay({ color, symbolColor, height: TITLEBAR_HEIGHT }); } catch (err) { log(`overlay: ${err.message}`); }
    if (bg) w.setBackgroundColor(bg);
    store.set("theme", { band: color, fg: symbolColor, bg: bg || color });
    if (typeof opts.dark === "boolean") nativeTheme.themeSource = opts.dark ? "dark" : "light";
  });
  ipcMain.handle("notify", (_e, opts = {}) => showNotification(opts));
  ipcMain.handle("open-external", (_e, url) => {
    if (typeof url === "string" && /^(https?:|mailto:)/i.test(url)) { shell.openExternal(url); return true; }
    return false;
  });
  ipcMain.handle("autostart:get", () => ({ supported: process.platform !== "linux", enabled: loginItem() }));
  ipcMain.handle("autostart:set", (_e, on) => ({ enabled: setLoginItem(!!on) }));
  ipcMain.handle("update:check", () => updater.check({ userInitiated: true }));
  ipcMain.handle("update:install", () => updater.apply());
  ipcMain.handle("app:info", () => ({
    version: app.getVersion(), electron: process.versions.electron, platform: process.platform,
    packaged: app.isPackaged, userData, logDir, port: backend && backend.port,
  }));
  ipcMain.handle("logs:reveal", () => shell.openPath(logDir));
  ipcMain.handle("boot:info", (e) => (isBootPage(e.sender) ? {
    name: appName(), detail: bootError, tail: backend ? backend.tail() : "",
    logFile: backend ? backend.logFile : path.join(logDir, "backend.log"),
  } : null));
  ipcMain.handle("boot:retry", async (e) => {
    if (!isBootPage(e.sender)) return false;
    if (backend && backend.alive()) await backend.stop(1000);
    boot();
    return true;
  });
  ipcMain.handle("boot:quit", (e) => { if (isBootPage(e.sender)) { quitting = true; app.quit(); } });
}

// ── app events ──────────────────────────────────────────────────────────────

app.on("second-instance", (_e, argv) => {
  const link = findDeepLink(argv);
  if (link) handleDeepLink(link); else showWindow();
});

app.on("open-url", (e, url) => { e.preventDefault(); if (app.isReady()) handleDeepLink(url); else pendingLink = url; });

app.whenReady().then(() => {
  if (app.isPackaged) app.setAsDefaultProtocolClient(PROTOCOL);
  ensureDevShortcut();
  Menu.setApplicationMenu(null);
  registerIpc();
  permissions();
  createWindow();
  createTray();
  // Show/hide from anywhere. Best-effort: another app may own the chord.
  try { globalShortcut.register("CommandOrControl+Alt+N", toggleWindow); } catch { /* taken */ }
  boot();
  // And again every 6 hours for long-running sessions (quiet; notifies once).
  if (app.isPackaged) setInterval(() => updater.check(), 6 * 60 * 60 * 1000);
});

// Test hook for driving the shell from a Node inspector session (verification
// of the tray menu etc.). Off unless NAMMA_DESKTOP_DEBUG=1.
if (process.env.NAMMA_DESKTOP_DEBUG === "1") {
  globalThis.__nammaDesktop = {
    get tray() { return tray; }, get win() { return win; }, get backend() { return backend; },
    store, showNotification, handleDeepLink, buildTrayMenu, setLoginItem, loginItem, updater,
  };
}

let finalQuit = false;
app.on("before-quit", (e) => {
  quitting = true;
  if (finalQuit) return;
  e.preventDefault();
  finalQuit = true;
  globalShortcut.unregisterAll();
  shutdownBackend().finally(() => app.quit());
});

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
