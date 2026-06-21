import React, { useEffect, useRef, useState } from "react";
import { Installer, ready, onEvents } from "./api.js";
import Welcome from "./screens/Welcome.jsx";
import Progress from "./screens/Progress.jsx";
import Provider from "./screens/Provider.jsx";
import Onboarding from "./screens/Onboarding.jsx";
import Done from "./screens/Done.jsx";

export default function App() {
  const [screen, setScreen] = useState("welcome"); // welcome|progress|provider|onboarding|done
  const [defaults, setDefaults] = useState(null);
  const [installDir, setInstallDir] = useState("");
  const [steps, setSteps] = useState([]);
  const [log, setLog] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [verifyState, setVerifyState] = useState("idle"); // idle|checking|ok|bad
  const dirRef = useRef("");

  // Load defaults + wire the Python→JS event channel once. Retries until the
  // bridge returns a populated payload, so the provider/onboarding screens are
  // never blank from a cold-start race.
  useEffect(() => {
    let live = true;
    const load = async (tries = 0) => {
      try {
        const d = await Installer.getDefaults();
        if (live && d && Array.isArray(d.providers) && d.providers.length) {
          setDefaults(d);
          setSteps(d.steps || []);
          setInstallDir(d.default_install_dir);
          dirRef.current = d.default_install_dir;
          return;
        }
      } catch {
        /* fall through to retry */
      }
      if (live && tries < 20) setTimeout(() => load(tries + 1), 250);
    };
    ready().then(() => load());
    onEvents({
      onSteps: (s) => setSteps(s),
      // Python batches log lines into an array (to avoid flooding the UI thread);
      // still accept a lone string from the browser dev-mock.
      onLog: (lines) => setLog((l) => [...l, ...(Array.isArray(lines) ? lines : [lines])]),
      onInstallDone: () => setScreen("provider"),
      onInstallError: (msg) => setError(msg || "Install failed."),
    });
    return () => {
      live = false;
    };
  }, []);

  const changeDir = async () => {
    const chosen = await Installer.chooseDir();
    if (!chosen) return;
    const resolved = await Installer.resolveDir(chosen);
    setInstallDir(resolved);
    dirRef.current = resolved;
  };

  const beginInstall = () => {
    setError("");
    setLog([]);
    setScreen("progress");
    Installer.startInstall(dirRef.current || installDir);
  };

  const saveProvider = async (provider) => {
    if (provider) {
      setBusy(true);
      await Installer.saveProvider(dirRef.current, provider);
      setBusy(false);
    }
    setScreen("onboarding");
  };

  const finishOnboarding = async (values) => {
    setBusy(true);
    await Installer.saveOnboarding(dirRef.current, values || {});
    setBusy(false);
    setScreen("done");
    // Background sanity check so "Launch" is known-good.
    setVerifyState("checking");
    Installer.verify(dirRef.current)
      .then((r) => setVerifyState(r && r.ok ? "ok" : "bad"))
      .catch(() => setVerifyState("bad"));
  };

  const launch = async () => {
    setLaunching(true);
    await Installer.launch(dirRef.current);
    setTimeout(() => Installer.close(), 1200);
  };

  return (
    <div className="h-full w-full bg-canvas">
      {screen === "welcome" && (
        <Welcome
          defaults={defaults}
          installDir={installDir}
          onChangeDir={changeDir}
          onInstall={beginInstall}
        />
      )}
      {screen === "progress" && (
        <Progress
          steps={steps}
          log={log}
          error={error}
          onRetry={beginInstall}
          onCancel={() => Installer.close()}
        />
      )}
      {screen === "provider" && (
        <Provider providers={defaults?.providers || []} onSave={saveProvider} busy={busy} />
      )}
      {screen === "onboarding" && (
        <Onboarding fields={defaults?.onboarding_fields || []} onFinish={finishOnboarding} busy={busy} />
      )}
      {screen === "done" && (
        <Done
          installDir={installDir}
          onLaunch={launch}
          onClose={() => Installer.close()}
          launching={launching}
          verifyState={verifyState}
        />
      )}
    </div>
  );
}
