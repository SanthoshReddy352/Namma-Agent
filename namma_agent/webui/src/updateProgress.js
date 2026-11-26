// Update progress for the banner and Settings → About.
//
// Desktop app: "Update now" hands the update to the shell's electron-updater,
// which reports its state to the backend; /api/update/check returns it with
// `managed_by: "desktop"`, `status` and `progress`. We poll that while an
// update is under way so the user always sees what's happening:
//   downloading 0–100 %  →  installing (the installer window takes over, then
//   the app reopens). Server/source installs have no status; nothing to follow.
import { checkUpdate } from "./api.js";

export const UPDATE_ACTIVE = ["downloading", "ready", "installing"];

// { label, pct|null, busy, failed } for an /api/update/check answer.
export function describeUpdate(info, name = "Namma Agent") {
  const v = info?.latest ? ` ${info.latest}` : "";
  const status = info?.status;
  if (status === "downloading") {
    const pct = Math.max(0, Math.min(100, Math.round(info.progress || 0)));
    return { label: `Downloading ${name}${v}… ${pct}%`, pct, busy: true, failed: false };
  }
  if (status === "ready" || status === "installing") {
    return {
      label: `Installing ${name}${v}. The installer shows its progress, and ${name} reopens when it's done.`,
      pct: 100, busy: true, failed: false,
    };
  }
  if (status === "error") {
    return { label: `The update failed: ${info.error || "unknown error"}`, pct: null, busy: false, failed: true };
  }
  return { label: `Starting the update to${v || " the new version"}…`, pct: null, busy: true, failed: false };
}

// Poll /api/update/check until the update stops being "under way". Calls
// onState with each answer; returns a stop function. Once the backend goes away
// (the app is closing to install), polling just keeps failing quietly.
export function followUpdate(onState, { interval = 1000, check = checkUpdate } = {}) {
  let stopped = false;
  let timer = null;
  const tick = async () => {
    if (stopped) return;
    let info = null;
    try { info = await check(); } catch { /* backend restarting / gone */ }
    if (stopped) return;
    if (info) onState(info);
    if (info && info.status === "error") return;
    timer = setTimeout(tick, interval);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}
