# Native one-file installers (branded GUI)

These produce a **single double-clickable installer per OS** with the Namma Agent
**custom UI** — a big branded welcome screen and a **Start installation** button.
When the user clicks Start it: installs Python/Git/Node if missing, downloads the
app to the Desktop, creates the environment, installs dependencies, then asks for
the AI provider + a few onboarding questions — all inside the branded window.

It's the Tkinter installer in [`installer/`](../../installer/) frozen with
PyInstaller (the app source, incl. the prebuilt web UI, is bundled inside), so the
installer's UI runs even on a machine with no Python.

| OS | Output | Built by |
|----|--------|----------|
| Windows | `NammaAgentInstaller-<ver>.exe` | PyInstaller (single file) |
| macOS | `NammaAgent-<ver>.dmg` (contains the `.app`) | PyInstaller `.app` → `hdiutil` |
| Linux | `NammaAgentInstaller-<ver>-x86_64.AppImage` | PyInstaller → `appimagetool` |

## Don't have all three OSes? Use CI (recommended)

You **can't** build all three from one machine — a `.exe` needs Windows, a `.dmg`
needs macOS, an `.AppImage` needs Linux. The repo includes
[`.github/workflows/release.yml`](../../.github/workflows/release.yml), which builds
**all three on GitHub's free runners** and attaches them to the Release
automatically when you push a `v*` tag. See [docs/RELEASING.md](../../docs/RELEASING.md).
You don't need to own any of the machines.

## Building one locally (on that OS)

```bash
pip install pyinstaller          # build-only dependency
python installers/native/build.py
```
Outputs land in `installers/native/dist/`. Prereqs: Node 18+ and git; macOS uses the
built-in `hdiutil`; Linux needs [`appimagetool`](https://github.com/AppImage/AppImageKit/releases)
on PATH for the `.AppImage` (otherwise it leaves the raw binary).

## Requirement on the end user's machine

- **Windows:** none. The installer is **self-contained** — it bundles a relocatable
  CPython with every dependency pre-installed (`stage_runtime` in `build.py`) and
  copies it into place, so the app runs with no system Python, no pip, and no network
  at install time. This is what lets `--cli` pass winget's offline sandbox validation.
- **macOS / Linux:** the installer still needs **Python 3.10+** *for the app's own
  environment* (it auto-installs it if missing) and builds a `.venv` on first install.
  The frozen installer itself bundles its own Python, so its UI always opens.
