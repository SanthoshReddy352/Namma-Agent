// The only bridge between the page and the shell: `window.nammaDesktop`.
// contextIsolation is on, the renderer has no Node, and every call is a narrow
// IPC message the main process validates. The web UI feature-detects this object
// (webui/src/desktop.js), so the same build runs in a browser tab unchanged.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

// Shell → page events (deep links, tray "New chat", notification clicks). They
// can arrive before the app has mounted and subscribed, so buffer until then.
const listeners = new Set();
const pending = [];
ipcRenderer.on("desktop:event", (_e, ev) => {
  if (listeners.size === 0) { pending.push(ev); return; }
  for (const cb of listeners) { try { cb(ev); } catch { /* one bad listener can't block others */ } }
});

contextBridge.exposeInMainWorld("nammaDesktop", {
  platform: process.platform,
  // Window chrome: native min/max/close are drawn over the page's 34px band; the
  // page tells us its colours so they blend in (and the window background
  // matches the theme on the next launch, with no light flash).
  setTitleBarOverlay: (opts) => ipcRenderer.send("titlebar:set", opts),
  notify: (opts) => ipcRenderer.invoke("notify", opts),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  getAutostart: () => ipcRenderer.invoke("autostart:get"),
  setAutostart: (on) => ipcRenderer.invoke("autostart:set", !!on),
  checkForUpdates: () => ipcRenderer.invoke("update:check"),
  installUpdate: () => ipcRenderer.invoke("update:install"),
  appInfo: () => ipcRenderer.invoke("app:info"),
  revealLogs: () => ipcRenderer.invoke("logs:reveal"),
  onEvent: (cb) => {
    if (typeof cb !== "function") return () => {};
    listeners.add(cb);
    while (pending.length) { const ev = pending.shift(); try { cb(ev); } catch { /* ignore */ } }
    return () => listeners.delete(cb);
  },
  // Boot pages (splash / error) only; the main process ignores these from the app.
  boot: {
    info: () => ipcRenderer.invoke("boot:info"),
    retry: () => ipcRenderer.invoke("boot:retry"),
    quit: () => ipcRenderer.invoke("boot:quit"),
  },
});
