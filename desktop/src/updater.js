// Auto-update with electron-updater from GitHub Releases (configured in
// electron-builder.yml `publish:`; nothing is ever published by our build
// scripts: they pass --publish never).
//
// Policy: check quietly a while after start (packaged builds only), never
// download without asking, and show native notifications/dialogs. A failed
// check (offline, no desktop release yet) is silent unless the user asked.
"use strict";

const { app, dialog, Notification } = require("electron");

function createUpdater({ log, getWindow, beforeInstall, appName }) {
  let autoUpdater = null;
  let state = { status: "idle", version: null, progress: 0, error: null };
  let manual = false;

  function load() {
    if (autoUpdater) return autoUpdater;
    ({ autoUpdater } = require("electron-updater"));
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;
    // First lines only: a failed check otherwise dumps whole HTTP header sets.
    const first = (m) => log(`updater: ${String((m && m.message) || m).split("\n")[0].slice(0, 300)}`);
    autoUpdater.logger = { info: first, warn: first, error: first, debug: () => {} };
    autoUpdater.on("checking-for-update", () => { state = { ...state, status: "checking", error: null }; });
    autoUpdater.on("update-not-available", () => {
      state = { ...state, status: "current" };
      if (manual) info(`${appName()} is up to date (${app.getVersion()}).`);
    });
    autoUpdater.on("update-available", async (i) => {
      state = { ...state, status: "available", version: i.version };
      const win = getWindow();
      const { response } = await dialog.showMessageBox(win || undefined, {
        type: "info", buttons: ["Download", "Later"], defaultId: 0, cancelId: 1,
        title: "Update available",
        message: `${appName()} ${i.version} is available.`,
        detail: `You have ${app.getVersion()}. Download it now? It installs when you restart.`,
      });
      if (response === 0) autoUpdater.downloadUpdate().catch((e) => fail(e));
    });
    autoUpdater.on("download-progress", (p) => {
      state = { ...state, status: "downloading", progress: Math.round(p.percent || 0) };
      const win = getWindow();
      if (win && !win.isDestroyed()) win.setProgressBar((p.percent || 0) / 100);
    });
    autoUpdater.on("update-downloaded", async (i) => {
      state = { ...state, status: "ready", version: i.version, progress: 100 };
      const win = getWindow();
      if (win && !win.isDestroyed()) win.setProgressBar(-1);
      const { response } = await dialog.showMessageBox(win || undefined, {
        type: "info", buttons: ["Restart now", "Later"], defaultId: 0, cancelId: 1,
        title: "Update ready", message: `${appName()} ${i.version} is ready to install.`,
      });
      if (response === 0) install();
    });
    autoUpdater.on("error", (e) => fail(e));
    return autoUpdater;
  }

  function info(message) {
    if (Notification.isSupported()) new Notification({ title: appName(), body: message }).show();
  }

  function fail(e) {
    const msg = (e && e.message) || String(e);
    state = { ...state, status: "error", error: msg };
    log(`updater: ${msg.split("\n")[0].slice(0, 300)}`);
    const win = getWindow();
    if (win && !win.isDestroyed()) win.setProgressBar(-1);
    if (manual) {
      // No desktop release on GitHub yet is not an error the user can act on.
      const unpublished = /404|latest\.yml|Cannot find/i.test(msg);
      dialog.showMessageBox(win || undefined, unpublished ? {
        type: "info", title: "Check for updates",
        message: `${appName()} ${app.getVersion()} is the newest version.`,
        detail: "No newer desktop release has been published.",
      } : {
        type: "warning", title: "Update check failed",
        message: "Couldn't check for updates.",
        detail: msg.split("\n")[0].slice(0, 300),
      });
    }
  }

  async function check({ userInitiated = false } = {}) {
    manual = userInitiated;
    if (!app.isPackaged) {
      state = { ...state, status: "unsupported", error: "updates run only in the installed app" };
      if (userInitiated) info("Updates are checked in the installed app, not in a development run.");
      return state;
    }
    try { await load().checkForUpdates(); } catch (e) { fail(e); }
    return state;
  }

  async function install() {
    if (state.status !== "ready") return check({ userInitiated: true });
    await beforeInstall();
    load().quitAndInstall(false, true);
    return state;
  }

  return { check, install, state: () => state };
}

module.exports = { createUpdater };
