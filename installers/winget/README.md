# winget packaging

Makes `winget install namma-agent` possible (Phase 5 — Windows first-class).

winget doesn't host binaries — it's a manifest index ([microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs))
pointing at our GitHub-release installer (`NammaAgentInstaller-<ver>.exe`, built
by `.github/workflows/release.yml`). A manifest must embed the SHA-256 of the
real released asset, so it's generated per release, not hand-kept:

```powershell
# after the GitHub release for the current version.py exists:
python installers/winget/generate.py
# or against a local build / different version:
python installers/winget/generate.py --version 2.3.0 --exe installers\native\dist\NammaAgentInstaller-2.3.0.exe
```

That writes the three-file set (version / installer / locale, schema 1.6) under
`manifests/s/SanthoshReddy352/NammaAgent/<ver>/` — the exact folder layout
winget-pkgs expects.

## Submitting

1. `winget validate manifests\s\SanthoshReddy352\NammaAgent\<ver>` — schema check.
2. `winget install --manifest manifests\s\SanthoshReddy352\NammaAgent\<ver>` —
   real local install test (needs `winget settings` → enable
   `LocalManifestFiles`).
3. Fork microsoft/winget-pkgs, copy the folder in under the same path, open the
   PR (or use `wingetcreate submit`). Moderation bots re-validate the hash and
   the silent install.

Notes:

- The **silent switch is `--cli`** — the installer app's unattended mode
  (`installer/__main__.py`), same flow as the GUI without a window. Moderation
  requires a working silent install; this is it.
- The installer registers **"Namma Agent"** in Add/Remove Programs
  (`installer/core.py:register_windows_app`), which winget uses to detect the
  installed version — keep `AppsAndFeaturesEntries.DisplayName` in sync if that
  name ever changes.
- Generated `manifests/` output and downloaded `.exe`s are disposable release
  artifacts; only `generate.py` and this README live in git.
