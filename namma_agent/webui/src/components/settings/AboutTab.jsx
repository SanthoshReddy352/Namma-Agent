// Settings → AboutTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useRef, useState } from "react";
import { Dialog } from "../ui/index.js";
import { applyUpdate, checkUpdate, fetchVersion, uninstallApp } from "../../api.js";
import { Section } from "./shared.jsx";
import { UPDATE_ACTIVE, describeUpdate, followUpdate } from "../../updateProgress.js";

// About / Updates / Danger-zone (uninstall) — mirrors Hermes' Settings → About.
export function AboutTab() {
  const [version, setVersion] = useState("");
  const [upd, setUpd] = useState(null);
  const [updating, setUpdating] = useState(false);
  const [confirm, setConfirm] = useState(null); // {scope, label}
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const [following, setFollowing] = useState(false);
  const stopRef = useRef(null);
  const follow = () => {
    setFollowing(true);
    stopRef.current?.();
    stopRef.current = followUpdate((r) => setUpd((cur) => ({ ...cur, ...r })));
  };

  useEffect(() => {
    fetchVersion().then((r) => setVersion(r?.version || "")).catch(() => {});
    checkUpdate().then((r) => {
      setUpd(r);
      if (r?.managed_by === "desktop" && UPDATE_ACTIVE.includes(r.status)) follow();
    }).catch(() => {});
    return () => stopRef.current?.();
  }, []);

  const doUpdate = async () => {
    setUpdating(true);
    const r = await applyUpdate().catch(() => null);
    if (r?.managed_by === "desktop" && r.started) { follow(); return; }
    setMsg(r?.started === false ? `Couldn't start the update: ${r.error || "unknown error"}` : "Updating… the app will relaunch shortly.");
  };
  const progress = following && upd ? describeUpdate(upd) : null;

  const doUninstall = async () => {
    setBusy(true);
    const r = await uninstallApp(confirm.scope).catch((e) => ({ started: false, error: String(e) }));
    if (r?.started) {
      setMsg("Uninstalling… this window will close in a moment.");
    } else {
      setMsg("Could not start the uninstaller: " + (r?.error || "unknown error"));
      setBusy(false);
      setConfirm(null);
    }
  };

  return (
    <>
      <Section title="About">
        <div className="text-base font-medium text-fg">Namma Agent</div>
        <div className="text-sm text-fg-muted">Version {version || "…"}</div>
      </Section>

      <Section title="Updates" hint="Pull the latest version and relaunch automatically.">
        {progress ? (
          <div role="status" aria-live="polite" className="space-y-2">
            <div className={`text-sm ${progress.failed ? "text-danger" : "text-fg"}`}>{progress.label}</div>
            {progress.pct != null && (
              <div className="h-1.5 w-full max-w-sm rounded-full bg-surface-sunken overflow-hidden"
                   role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.pct}>
                <div className="h-full bg-brand transition-[width] duration-300" style={{ width: `${progress.pct}%` }} />
              </div>
            )}
            {progress.failed && (
              <button onClick={doUpdate} className="px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand-deep">Try again</button>
            )}
          </div>
        ) : upd?.update_available ? (
          <button onClick={doUpdate} disabled={updating}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">
            {updating ? "Updating…" : `Update to ${upd.latest}`}
          </button>
        ) : (
          <div className="text-sm text-fg-muted">
            {upd ? "You’re on the latest version." : "Checking for updates…"}
          </div>
        )}
      </Section>

      <Section title="Danger zone" hint="Remove Namma Agent from this computer.">
        <div className="flex flex-wrap gap-2">
          <button onClick={() => { setConfirm({ scope: "keep-data", label: "Uninstall, keep my data" }); setTyped(""); setMsg(""); }}
                  className="px-3 py-1.5 rounded-lg border border-danger/40 text-danger hover:bg-danger/10">Uninstall, keep my data</button>
          <button onClick={() => { setConfirm({ scope: "all", label: "Uninstall everything" }); setTyped(""); setMsg(""); }}
                  className="px-3 py-1.5 rounded-lg bg-danger text-white hover:opacity-90">Uninstall everything</button>
        </div>
        {msg && <div className="mt-2 text-sm text-fg-muted">{msg}</div>}
      </Section>

      {confirm && (
        <Dialog onClose={() => !busy && setConfirm(null)} size="md" labelledBy="uninstall-title" className="p-5" dismissOnBackdrop={false}>
            <h3 className="text-md font-semibold text-fg" id="uninstall-title">{confirm.label}</h3>
            <p className="mt-2 text-base leading-relaxed text-fg-muted">
              {confirm.scope === "all"
                ? "This permanently deletes the app AND all your chats, settings, and data. This cannot be undone."
                : "This removes the app, but first backs up your chats & settings to your user folder so you can restore them later."}
            </p>
            <p className="mt-3 text-sm text-fg-muted">Type <b>UNINSTALL</b> to confirm:</p>
            <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)}
                   className="mt-1 w-full rounded-lg border border-border bg-transparent px-3 py-2 outline-none focus:border-brand text-fg" />
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setConfirm(null)} disabled={busy}
                      className="px-4 py-2 rounded-lg text-fg-soft hover:bg-surface-hover">Cancel</button>
              <button onClick={doUninstall} disabled={busy || typed.trim().toUpperCase() !== "UNINSTALL"}
                      className="px-4 py-2 rounded-lg bg-danger text-white hover:opacity-90 disabled:opacity-40">{busy ? "Uninstalling…" : "Uninstall"}</button>
            </div>
        </Dialog>
      )}
    </>
  );
}
