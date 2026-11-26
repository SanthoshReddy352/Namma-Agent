// Auto-update with electron-updater from GitHub Releases (electron-builder.yml
// `publish:`; the release workflow uploads NammaAgentSetup-<v>.exe, its
// .blockmap and latest.yml to the GitHub release of the tag).
//
// Three ways in:
//   check()                   quiet: at start-up and when the web UI asks
//                             (/api/update/check). Says nothing unless an update
//                             exists, then shows a notification.
//   check({userInitiated})    the tray's "Check for updates…": dialogs either way.
//   apply()                   the web UI's "Update now" (/api/update/apply) or the
//                             tray dialog: download if needed (progress in the
//                             banner, Settings → About and the taskbar), then quit
//                             and run the installer VISIBLY (its progress page),
//                             which reopens the app, with no further questions.
//
// Every state change is reported through onState, which the shell forwards to
// the backend (/api/desktop/update-state) so the web UI's update banner and
// Settings → About can show "Update available" and the progress.
//
// NAMMA_DESKTOP_UPDATE_URL points the updater at a generic feed (a folder with
// latest.yml + the installer) instead of GitHub; used to test the flow locally.
"use strict";

const { app, dialog, Notification } = require("electron");

function createUpdater({ log, getWindow, beforeInstall, appName, onState = () => {}, onShow = () => {} }) {
  let autoUpdater = null;
  let state = { status: "idle", version: null, progress: 0, error: null };
  let manual = false;          // the current check was user-initiated (tray)
  let applyRequested = false;  // install as soon as the download finishes
  let notified = null;         // version a quiet check already announced

  const setState = (patch) => {
    state = { ...state, ...patch };
    try { onState({ ...state, current: app.getVersion() }); } catch { /* best-effort */ }
  };

  function notify(body, onClick) {
    if (!Notification.isSupported()) return;
    const n = new Notification({ title: appName(), body });
    if (onClick) n.on("click", onClick);
    n.show();
  }

  function load() {
    if (autoUpdater) return autoUpdater;
    ({ autoUpdater } = require("electron-updater"));
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;
    // First lines only: a failed check otherwise dumps whole HTTP header sets.
    const first = (m) => log(`updater: ${String((m && m.message) || m).split("\n")[0].slice(0, 300)}`);
    autoUpdater.logger = { info: first, warn: first, error: first, debug: () => {} };
    if (process.env.NAMMA_DESKTOP_UPDATE_URL) {
      autoUpdater.setFeedURL({ provider: "generic", url: process.env.NAMMA_DESKTOP_UPDATE_URL });
      log(`updater: feed overridden to ${process.env.NAMMA_DESKTOP_UPDATE_URL}`);
    }

    autoUpdater.on("checking-for-update", () => setState({ status: "checking", error: null }));
    autoUpdater.on("update-not-available", (i) => {
      applyRequested = false;
      setState({ status: "current", version: (i && i.version) || app.getVersion() });
      if (manual) {
        dialog.showMessageBox(getWindow() || undefined, {
          type: "info", title: "Check for updates",
          message: `${appName()} ${app.getVersion()} is the newest version.`,
        });
      }
    });
    autoUpdater.on("update-available", async (i) => {
      setState({ status: "available", version: i.version, progress: 0 });
      if (applyRequested) { download(); return; }
      if (!manual) {
        if (notified !== i.version) {
          notified = i.version;
          notify(`Version ${i.version} is available. Open the app to update.`, onShow);
        }
        return;
      }
      const { response } = await dialog.showMessageBox(getWindow() || undefined, {
        type: "info", buttons: ["Update now", "Later"], defaultId: 0, cancelId: 1,
        title: "Update available",
        message: `${appName()} ${i.version} is available.`,
        detail: `You have ${app.getVersion()}. Update now? It downloads, then the app restarts.`,
      });
      if (response === 0) apply();
    });
    autoUpdater.on("download-progress", (p) => {
      const pct = Math.round(p.percent || 0);
      if (pct !== state.progress) setState({ status: "downloading", progress: pct });
      const win = getWindow();
      if (win && !win.isDestroyed()) win.setProgressBar((p.percent || 0) / 100);
    });
    autoUpdater.on("update-downloaded", async (i) => {
      setState({ status: "ready", version: i.version, progress: 100 });
      const win = getWindow();
      if (win && !win.isDestroyed()) win.setProgressBar(-1);
      if (applyRequested) { install(); return; }
      notify(`Version ${i.version} is ready. It installs when you restart.`, () => install());
    });
    autoUpdater.on("error", (e) => fail(e));
    return autoUpdater;
  }

  function fail(e) {
    const msg = (e && e.message) || String(e);
    const wasApplying = applyRequested;
    applyRequested = false;
    setState({ status: "error", error: msg.split("\n")[0].slice(0, 300) });
    log(`updater: ${msg.split("\n")[0].slice(0, 300)}`);
    const win = getWindow();
    if (win && !win.isDestroyed()) win.setProgressBar(-1);
    if (manual || wasApplying) {
      // No desktop release on GitHub yet is not an error the user can act on.
      const unpublished = /404|latest\.yml|Cannot find/i.test(msg);
      dialog.showMessageBox(win || undefined, unpublished ? {
        type: "info", title: "Check for updates",
        message: `${appName()} ${app.getVersion()} is the newest version.`,
        detail: "No newer desktop release has been published.",
      } : {
        type: "warning", title: "Update failed",
        message: wasApplying ? "Couldn't download the update." : "Couldn't check for updates.",
        detail: msg.split("\n")[0].slice(0, 300),
      });
    }
  }

  function download() {
    setState({ status: "downloading", progress: state.progress || 0 });
    load().downloadUpdate().catch((e) => fail(e));
  }

  async function check({ userInitiated = false } = {}) {
    manual = userInitiated;
    if (!app.isPackaged && !process.env.NAMMA_DESKTOP_UPDATE_URL) {
      setState({ status: "unsupported", error: "updates run only in the installed app" });
      if (userInitiated) notify("Updates are checked in the installed app, not in a development run.");
      return state;
    }
    if (["downloading", "ready", "installing"].includes(state.status)) return state;   // under way
    try { await load().checkForUpdates(); } catch (e) { fail(e); }
    return state;
  }

  // "Update now": whatever state we're in, end with the new version installed.
  async function apply() {
    applyRequested = true;
    if (state.status === "ready") return install();
    if (state.status === "available") { download(); return state; }
    if (state.status === "downloading") return state;
    return check({ userInitiated: false });   // the update-available handler continues
  }

  async function install() {
    applyRequested = false;
    // Tell the UI first (banner / Settings → About show "Installing…"), give it
    // a moment to poll, then stop the backend and hand over to the installer.
    setState({ status: "installing", progress: 100 });
    notify(`Installing ${appName()} ${state.version || ""}. The installer shows its progress; the app reopens when it's done.`.replace("  ", " "));
    await new Promise((r) => setTimeout(r, 2500));
    await beforeInstall();
    // NOT silent: the installer's progress page is on screen the whole time (an
    // invisible multi-minute install looks like the app just died), and its
    // update-mode finish step reopens the app (resources/installer.nsh).
    load().quitAndInstall(false, true);
    return state;
  }

  return { check, apply, install, state: () => state };
}

module.exports = { createUpdater };
