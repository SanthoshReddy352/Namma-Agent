import { useEffect, useRef, useState } from "react";
import { checkUpdate, applyUpdate } from "../api.js";
import { UPDATE_ACTIVE, describeUpdate, followUpdate } from "../updateProgress.js";

// Slim top bar that appears only when a newer Namma Agent version is published.
// "Update now":
//  - desktop app: the shell downloads the new installer (the bar shows the
//    percentage), then the app closes and the installer's own window shows the
//    install progress and reopens the app;
//  - source/server installs: the detached updater pulls, reinstalls, rebuilds
//    and relaunches.
// "Later" hides the bar for that specific version (remembered in localStorage).
const DISMISS_KEY = "namma-update-dismissed";

export default function UpdateBanner() {
  const [info, setInfo] = useState(null);        // the /api/update/check answer
  const [status, setStatus] = useState("idle");  // idle | updating | following | error
  const stopRef = useRef(null);

  const follow = () => {
    setStatus("following");
    stopRef.current?.();
    stopRef.current = followUpdate((r) => setInfo((cur) => ({ ...cur, ...r })));
  };

  useEffect(() => {
    let alive = true;
    checkUpdate().then((r) => {
      if (!alive || !r || !r.update_available) return;
      setInfo(r);
      // Already under way (started from the tray or Settings): show progress.
      if (r.managed_by === "desktop" && UPDATE_ACTIVE.includes(r.status)) { follow(); return; }
      if (localStorage.getItem(DISMISS_KEY) === r.latest) setInfo(null); // dismissed this version
    });
    return () => { alive = false; stopRef.current?.(); };
  }, []);

  if (!info) return null;

  const dismiss = () => { localStorage.setItem(DISMISS_KEY, info.latest); setInfo(null); };
  const update = async () => {
    setStatus("updating");
    const r = await applyUpdate();
    if (!r || r.started === false) { setStatus("error"); return; }
    if (r.managed_by === "desktop") follow();
    // Source installs: the updater shuts this app down and relaunches it, so
    // the "updating" message stays on screen until the window closes.
  };

  const progress = status === "following" ? describeUpdate(info) : null;

  return (
    <div role="status" aria-live="polite"
         className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm bg-brand text-white shadow-sm">
      {progress ? (
        <>
          <span className="font-medium">{progress.label}</span>
          {progress.pct != null && (
            <span className="flex-1 min-w-[8rem] max-w-xs h-1.5 rounded-full bg-white/25 overflow-hidden"
                  role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.pct}>
              <span className="block h-full bg-white transition-[width] duration-300" style={{ width: `${progress.pct}%` }} />
            </span>
          )}
          {progress.failed && (
            <>
              <span className="flex-1" />
              <button onClick={update} className="px-3 py-1 rounded-md bg-white text-brand-deep font-medium hover:bg-white/90">Try again</button>
              <button onClick={dismiss} className="px-2 py-1 rounded-md text-white/90 hover:bg-white/10">Dismiss</button>
            </>
          )}
        </>
      ) : status === "updating" ? (
        <span className="font-medium">Updating to {info.latest}… the app will close and reopen automatically.</span>
      ) : status === "error" ? (
        <>
          <span className="font-medium">Couldn’t start the update.</span>
          <span className="opacity-90">Run the updater for your OS — see docs/INSTALL.md.</span>
          <span className="flex-1" />
          <button onClick={dismiss} className="px-2 py-1 rounded-md text-white/90 hover:bg-white/10">Dismiss</button>
        </>
      ) : (
        <>
          <span className="font-semibold">Update available</span>
          <span className="opacity-90">
            Namma Agent {info.latest} is ready{info.current ? ` (you have ${info.current})` : ""}.
          </span>
          {info.html_url && (
            <a href={info.html_url} target="_blank" rel="noreferrer"
               className="underline opacity-90 hover:opacity-100">What’s new</a>
          )}
          <span className="flex-1" />
          <button onClick={update}
                  className="px-3 py-1 rounded-md bg-white text-brand-deep font-medium hover:bg-white/90">
            Update now
          </button>
          <button onClick={dismiss} className="px-2 py-1 rounded-md text-white/90 hover:bg-white/10">Later</button>
        </>
      )}
    </div>
  );
}
