# Namma Agent — Install, Run & Update

*Intelligence for Everyone.* This is the exact, step-by-step process to get the
**Namma Agent Desktop App** running on **Windows, macOS, and Linux**, and how
updates work once it's installed.

Namma Agent runs as a native desktop window (a Python backend + a React UI shown
in a pywebview window). The installers below **bootstrap everything on your
machine** — they create an isolated environment, install dependencies, configure
your first AI provider, add a desktop shortcut, and launch the app.

> On first launch the assistant is named **Namma Agent**. You can rename it any
> time in **Settings → Assistant** (or set the `ASSISTANT_NAME` env var).

---

## 0. What you need

| Requirement | Why | Notes |
|---|---|---|
| **Python 3.10–3.13** | the app runtime | the installer checks for it and tells you how to install it if missing |
| **An API key** (or a local model) | the "brain" | Anthropic / OpenAI / Google key, **or** a local Ollama/LM Studio server (no key) |
| **Ollama** | semantic memory recall | **required** — every installer installs it for you and pulls the 46 MB `all-minilm` model. See below |
| Git *(optional)* | one-command updates | if you `git clone`, updates are a single `git pull`-based step |
| Node 18+ *(optional)* | only to **build** the UI from source | release downloads ship the UI pre-built, so most users don't need Node |

### Memory embeddings — a required component

[Ollama](https://ollama.com) plus the `all-minilm` model is what gives the
memory its *semantic* recall. Without it, memory search is keyword-only and
misses anything you phrase differently from how you stored it — "what is my
mother tongue?" never reaches the stored fact that says *Telugu*. That is the
difference between an assistant that remembers you and one that only remembers
your exact words, so it is treated as a real dependency, not a nicety.

**You do not install it yourself.** Every installer — `install.sh`,
`install.ps1`, the native `.exe`/`.dmg` from the releases tab, and the VPS
one-liner — detects whether Ollama is present and installs it automatically if
not (winget/choco on Windows, Homebrew on macOS, the official script on Linux),
then pulls the model. If that can't be done, **the install stops** with
instructions rather than silently leaving you with degraded memory.

| | |
|---|---|
| Disk | ~350 MB (Ollama ~300 MB + the 46 MB model) |
| RAM | ~150 MB resident while serving |
| Speed | ~10 ms per query |
| Cost | none — it never leaves your machine |
| Network | none after install |

#### Opting out (constrained hosts only)

If a machine genuinely cannot run it — air-gapped, locked-down corporate build,
unsupported architecture — you can install without it. Memory then falls back to
BM25 keyword recall; everything else works identically, the embedder
circuit-breaks so the missing endpoint costs nothing per turn, and Settings →
Memory shows **Vector recall: off**.

```bash
bash installers/install.sh --no-embeddings
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installers\install.ps1 -NoEmbeddings
```

For the native installer from the releases tab, set the environment variable
`NAMMA_NO_EMBEDDINGS=1` before running it.

To add it later, just pull the model — the shipped config already points at it:

```bash
ollama pull all-minilm
```

---

## 1. Get the files

Pick one:

**A. Download a release (recommended for users)**
1. Go to **https://github.com/SanthoshReddy352/Namma-Agent/releases/latest**
2. Download the `Namma-Agent-<version>.zip` asset and unzip it anywhere
   (e.g. `Documents/Namma Agent`). Release zips include the pre-built UI.

**B. Clone the repo (recommended if you want one-command updates)**
```bash
git clone https://github.com/SanthoshReddy352/Namma-Agent.git "Namma Agent"
cd "Namma Agent"
```

---

## 2. Install & first run

> **Easiest of all — native one-file installers.** If a packaged installer is
> attached to the [latest release](https://github.com/SanthoshReddy352/Namma-Agent/releases/latest),
> just download and run it: **`NammaAgent-Setup-<ver>.exe`** (Windows),
> **`NammaAgent-<ver>.dmg`** (macOS), or **`NammaAgent-<ver>-x86_64.AppImage`**
> (Linux). They do everything in this section automatically. The script installers
> below are the equivalent for a source download / git clone. (Maintainers: build
> these with [installers/native/README.md](../installers/native/README.md).)

### Windows
1. Open the folder from step 1.
2. Double-click **`installers\install.bat`** (or run
   `powershell -NoProfile -ExecutionPolicy Bypass -File installers\install.ps1`).
3. The installer will: find Python → create `.venv` → install dependencies →
   build the UI if needed → **ask you to pick your first AI provider and paste an
   API key** → add a **Namma Agent** shortcut to the Desktop and Start Menu →
   launch the app.

### macOS
1. Open the folder from step 1.
2. Double-click **`installers/Install Namma Agent.command`**
   (or run `bash installers/install.sh` in Terminal).
   - First time only: if macOS blocks it, right-click → **Open**, or run
     `chmod +x "installers/Install Namma Agent.command"`.
3. Same steps as above; it creates a double-clickable **`Namma Agent.command`**
   launcher in the project folder.

### Linux
```bash
bash installers/install.sh
```
It creates a **Namma Agent** entry in your applications menu (and you can launch
it any time with `.venv/bin/python -m namma_agent`).
- Native window needs a GTK/WebKit backend; on Debian/Ubuntu/Kali:
  `sudo apt install -y python3-gi gir1.2-webkit2-4.1`. Without it, the app opens
  in your browser instead.

### What "configure the first provider" does
The installer runs `python -m namma_agent --setup`, which writes your choice to
`namma_agent/config.local.yaml` (provider + model) and your API key to `.env`
(never committed). You can change all of it later in the app's **Settings**, or
re-run `python -m namma_agent --setup`.

---

## 3. Launch it afterwards

- **Windows:** the **Namma Agent** shortcut (Desktop / Start Menu).
- **macOS:** the **Namma Agent.command** file.
- **Linux:** the **Namma Agent** app-menu entry.
- **Any OS, from a terminal:** `python -m namma_agent` (native window) or
  `python -m namma_agent --server` (headless — open http://127.0.0.1:8000).

You don't need to activate the venv — the launcher re-execs into the project's
`.venv` automatically.

**Windows desktop niceties (Phase 5):**

- A **system-tray icon** appears while the app runs — double-click to show/hide
  the window; the menu shows live gateway status and has Open-in-browser and
  Quit. (Needs the `pystray` package, included in requirements; without it the
  app simply runs without a tray.)
- **Start when you sign in:** Settings → General → Behavior → *"Start when I
  sign in to this computer"* — a per-user registry entry (visible in Task
  Manager → Startup apps), no admin rights. On Linux the same toggle writes an
  XDG autostart entry.
- **Notifications** are real Action-Center toasts with **Reply** and **Open**
  buttons that jump into the chat UI.
- **winget:** once a release is published to the winget community repo,
  `winget install namma-agent` works too (maintainers: see
  `installers/winget/README.md`).

---

## 4. Updating an installed app

When the source code is updated, here's how an installed copy moves to the new
version.

### Option A — from inside the app (easiest)
The app checks GitHub for a newer published version and shows an **Update
available** prompt. Click **Update now** and the app fetches the new code,
reinstalls anything that changed, rebuilds the UI, and relaunches.

> Under the hood this calls `POST /api/update/apply`, which launches the platform
> update script detached so it can replace files while the app exits, then
> reopens it.

### Option B — run the updater yourself
- **Windows:** double-click **`installers\update.bat`** (or
  `powershell -ExecutionPolicy Bypass -File installers\update.ps1 -Relaunch`).
- **macOS / Linux:** `bash installers/update.sh --relaunch`

### Option C — manual (git clones)
```bash
git pull
.venv/bin/python -m pip install -r namma_agent/requirements.txt   # Windows: .venv\Scripts\python.exe
(cd namma_agent/webui && npm install && npm run build)            # if you build the UI from source
```

Your data and settings are preserved across updates: the SQLite database
(`data/namma_agent.db`), your `.env`, `config.local.yaml`, and `~/.namma_agent/`
(skills, tools, personas) are untouched by an update.

---

## 5. How updates work (architecture)

- **Version source of truth:** [`namma_agent/version.py`](../namma_agent/version.py)
  (`__version__`). Exposed at `GET /api/version`.
- **Check:** [`namma_agent/core/updater.py`](../namma_agent/core/updater.py)
  `check_for_update()` asks the GitHub API for the latest **release** (falling back
  to the latest **tag**) of `SanthoshReddy352/Namma-Agent`, compares it to the installed
  version, and returns `{current, latest, update_available, notes}`. It never
  raises — if GitHub is unreachable it returns `update_available: false`.
- **Apply:** `apply_update()` launches `installers/update.{sh,ps1}` **detached**
  (so it can overwrite files after the app closes), which does `git pull` (for
  clones) or points release-zip users at the latest release, reinstalls
  dependencies, rebuilds the UI, and relaunches.
- **Endpoints:** `GET /api/version`, `GET /api/update/check`,
  `POST /api/update/apply`.

---

## 6. For maintainers — cutting a release

**Full step-by-step (beginner-friendly): [docs/RELEASING.md](RELEASING.md).** A short
version follows.

When you change the source and want installed apps to be able to update:

1. **Bump the version** in [`namma_agent/version.py`](../namma_agent/version.py)
   (e.g. `2.2.0` → `2.3.0`) and add a `CHANGELOG.md` entry.
2. **Build the UI** so the release ships it pre-built:
   `cd namma_agent/webui && npm install && npm run build`.
3. **Tag and push:** `git tag v2.3.0 && git push --tags`.
4. **Publish a GitHub Release** for that tag. Attach a `Namma-Agent-2.3.0.zip`
   that contains the repo **including `namma_agent/webui/dist/`** (so users without
   Node can run it) but **excluding** `.venv/`, `.git/`, `data/*.db`, and `.env`.
5. Installed apps will now see the new version via `/api/update/check` and can
   update with one click.

> The version comparison is lenient (`v2.3.1`, `2.3`, `release-2.3.1` all parse),
> so tags like `v2.3.0` work fine. Until the **first** tag/release exists,
> `check_for_update()` simply reports "no update available".

### Native one-file installers (branded GUI)
A single double-clickable installer per OS with the Namma Agent **custom UI**
(big branded welcome + **Start installation**), which auto-installs Python/Git/Node,
downloads the app, sets up the environment, and runs provider + onboarding. It's the
Tkinter installer in `installer/` frozen with PyInstaller (bundling the prebuilt UI).

**You don't need all three OSes** — pushing a `v*` tag makes
[`.github/workflows/release.yml`](../.github/workflows/release.yml) build the `.exe`,
`.dmg`, and `.AppImage` on GitHub's runners and attach them to the Release. To build
one locally on that OS: `pip install pyinstaller && python installers/native/build.py`.
Full guide: [installers/native/README.md](../installers/native/README.md).

---

## 7. Troubleshooting

- **"Python 3.10+ not found"** — install it (`winget install Python.Python.3.12`
  on Windows, `brew install python@3.12` on macOS, `apt install python3 python3-venv`
  on Linux) and re-run the installer.
- **App opens in a browser instead of a window (Linux)** — install the GTK/WebKit
  backend (see Linux note in §2).
- **"could not reach the update server"** — GitHub was unreachable, or no release
  has been published yet. The app keeps working; try again later.
- **Provider/auth errors on first chat** — re-run `python -m namma_agent --setup`,
  or fix the key in `.env` / **Settings**.
