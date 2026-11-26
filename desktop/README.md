# Namma Agent desktop (Electron)

The native Windows app (Phase 9 W3). It is a thin Electron shell around the same
Python backend and web UI that `python -m namma_agent serve` runs. Linux builds
are configured but not verified.

```
desktop/
├── src/main.js        main process: single instance, window, tray, deep links, IPC, boot
├── src/backend.js     the Python backend as a supervised child (spawn, health, stop)
├── src/bus.js         subscribes to the backend's /ws for desktop_notify / desktop_command
├── src/updater.js     electron-updater (GitHub Releases), ask before download/install
├── src/preload.js     window.nammaDesktop (the only bridge; contextIsolation on, no Node)
├── src/deeplink.js    namma:// → in-app route (strict allowlist)
├── src/windowState.js remembered size/position, never off-screen
├── src/pages/         splash + error page (logs, Retry, Open logs folder)
├── resources/         icons + installer.nsh (NSIS hooks)
├── scripts/stage.js   stages the backend + bundled Python for packaging
└── electron-builder.yml
```

## Run it (development)

```powershell
cd namma_agent/webui; npm ci; npm run build      # the backend serves webui/dist
cd ../../desktop; npm ci; npm start
```

In development the shell finds the nearest `.venv` walking up from the repo (a git
worktree uses the main checkout's), and sets `PYTHONPATH` to the repo.
`NAMMA_DESKTOP_PYTHON` overrides the interpreter.

Isolate a test run from your real profile with environment variables:
- `NAMMA_DESKTOP_USER_DATA`: Electron's userData (window state, Chromium storage, logs);
- the backend's own `NAMMA_DATA_DIR`, `NAMMA_USER_CONFIG`, `NAMMA_ENV_FILE`,
  `NAMMA_VAULT_BACKEND=file` and `NAMMA_WHATSAPP_SESSION` are passed through.

Development runs use the AUMID `com.namma.agent.dev`, not the installed app's
`com.namma.agent`. Windows names and badges a toast from the Start-menu shortcut
that carries the app's AUMID. The installer creates `Namma Agent.lnk`, and a dev run
writes `Namma Agent (dev).lnk` (brand icon) at start-up. Without it, Electron creates
`Electron.lnk` on the first toast, and toasts would say "Electron" with its atom icon.
A leftover `Electron.lnk` claiming the dev AUMID is removed.

`NAMMA_DESKTOP_DEBUG=1` exposes `globalThis.__nammaDesktop` in the main process for
driving it from a Node inspector (`electron --inspect=9339 .`). Leave it off normally.

## Build the installer

```powershell
cd desktop
npm run dist          # → out/NammaAgentSetup-<version>.exe (never published)
```

`npm run dist` runs `scripts/stage.js` and then `electron-builder --win nsis --publish never`.

**What's bundled** (`resources/` inside the install dir):
- `backend/namma_agent/`: the Python app from this checkout, including uncommitted
  files, plus the built web UI. Tests, web UI sources, `data/`, `.env` and
  `config.local.yaml` are left out.
- `python/`: a relocatable CPython 3.12 (python-build-standalone), the same runtime
  the self-contained 2.3.1 installer ships (`installers/native/build.py
  stage_runtime`). Every dependency is pre-installed, topped up to the current
  `namma_agent/requirements.txt`, so installing needs no Python, pip or network.
  The cache is `$NAMMA_RUNTIME_CACHE` or `installers/native/runtime-win-x64` in
  this checkout or the main one. Without a cache it is downloaded and built once.
  Playwright's browsers are not bundled: they are fetched on first use, as before.

**The installer** (NSIS, per user, no admin):
- installs to `%LOCALAPPDATA%\Programs\Namma Agent`;
- adds an Add/Remove Programs entry, plus Start-menu and desktop shortcuts carrying
  the AUMID `com.namma.agent` (toasts are attributed to the app);
- registers `namma://`.

**The uninstaller:**
- stops a still-running backend;
- removes the shortcuts, the `namma://` handler and the start-at-login entry;
- asks whether to also delete chats, settings and keys (`%APPDATA%\Namma Agent`).
  The default is to keep them. The silent uninstall that an update runs never asks
  and never deletes.

## How the shell and the backend talk

The shell spawns `python -m namma_agent serve --host 127.0.0.1 --port <port>`. The
port is the last one used, else 47821 upward, else any free port. A stable port
keeps the page's origin stable, so its localStorage (theme, preferences) persists.
The child gets this environment:

| Variable | Meaning |
|---|---|
| `NAMMA_DESKTOP=1` | desktop mode (see `namma_agent/core/desktop.py`) |
| `NAMMA_AUTH_TOKEN` | per-launch secret; the shell adds it as `X-Namma-Token` to every request the page makes, the `/ws` upgrade included, so the page never holds it and no other local program or web page can drive the agent |
| `NAMMA_DATA_DIR` | `%APPDATA%\Namma Agent\data`, unless already set |
| `NAMMA_DESKTOP_PARENT_PID` | the backend exits if the shell dies without stopping it |
| `NAMMA_DESKTOP_EXE`, `NAMMA_DESKTOP_UNINSTALLER`, `NAMMA_DESKTOP_VERSION` | for start-at-login, uninstall and diagnostics |

The backend's working directory is userData, so `logs/` land there. The shell's own
logs are `logs/desktop.log` (shell) and `logs/backend.log` (the child's output).

**Events** (backend → shell, on the event bus, which the shell receives over `/ws`):
- `desktop_notify {title, body, action}`: replaces the PowerShell toast. The shell
  shows a native notification. Clicking it opens `action` (an in-app route) or just
  focuses the window.
- `desktop_command {action}`: `focus` · `update_check` · `update_apply` ·
  `uninstall {scope}`.

**`window.nammaDesktop`** (preload), all feature-detected by `webui/src/desktop.js`:
- `setTitleBarOverlay({color, symbolColor, background, dark})`
- `notify`, `openExternal`
- `getAutostart` / `setAutostart`
- `checkForUpdates` / `installUpdate`
- `appInfo`, `revealLogs`
- `onEvent(cb)`, which delivers `{type: "navigate", route}` and `{type: "new-chat"}`.

**Title bar.** The window uses `titleBarStyle: "hidden"` with `titleBarOverlay`, so
Windows draws min/max/close over the page's 34px band. `desktop.js` samples the
colour actually painted under the controls (compositing any translucent dialog
scrim) and the theme ink, and sends both whenever the theme, the layout or the
window size changes.

## Updates

`electron-updater` reads `latest.yml` from the newest published GitHub Release of
`SanthoshReddy352/Namma-Agent`. The release workflow uploads it with the installer and
its `.blockmap` (installed builds only).

- **Checks:** quietly at start-up, every 6 h, and whenever the web UI asks
  (`/api/update/check`). A quiet check speaks up only when an update exists, with one
  notification per version. The tray's **Check for updates…** answers with a dialog
  either way.
- **State → web UI:** every updater state change (`checking`, `available`, `downloading`
  with progress, `ready`, `current`, `error`) is POSTed to the backend at
  `/api/desktop/update-state`. `/api/update/check` waits up to 8 s for a fresh answer
  and returns `{update_available, latest, current, status, progress}`. So the web UI's
  existing **Update available** banner and Settings → About work unchanged.
- **Update now** (`/api/update/apply` → `desktop_command update_apply`, or the tray
  dialog): downloads if needed, with taskbar progress. It then stops the backend, quits,
  runs the NSIS installer silently and relaunches the new version. A downloaded update
  also installs on the next quit.
- **Local test feed:** `NAMMA_DESKTOP_UPDATE_URL=http://127.0.0.1:47900/` points the updater
  at a folder with `latest.yml` plus the installer (a generic feed), instead of GitHub.
  The steps are in the root README under *Developing the desktop app*.
