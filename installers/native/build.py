#!/usr/bin/env python3
"""Build the branded native installer for the CURRENT operating system.

It freezes the React/pywebview installer (`installer/`) with PyInstaller, bundling
the installer's own built UI (`installer/webui/dist`) and the app source (incl. the
app's prebuilt web UI) inside — so the resulting installer shows the modern Namma
Agent UI even on a machine with no Python, then installs everything silently.

On **Windows** it also bundles a relocatable CPython with every app dependency
pre-installed (see ``stage_runtime``), so the install is fully OFFLINE — no system
Python, no pip, no network — which is what winget's unattended sandbox validation
requires. macOS/Linux keep the venv-bootstrap path.

Outputs land in ``installers/native/dist/``:

    Windows -> NammaAgentInstaller-<ver>.exe               (single file)
    macOS   -> NammaAgent-<ver>-<arch>.dmg                 (arm64 = Apple Silicon,
               x86_64 = Intel — CI builds BOTH; pick the one matching your Mac)
    Linux   -> NammaAgentInstaller-<ver>-<arch>.AppImage   (or a raw binary)

Run it on each OS (CI does this automatically — see .github/workflows/release.yml):
    pip install pyinstaller
    python installers/native/build.py

Prereqs: Node 18+ (UI build), git; macOS needs hdiutil (built in); Linux needs
appimagetool on PATH for the .AppImage (otherwise the raw binary is produced).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "installers" / "native"
BUILD = NATIVE / "build"
DIST = NATIVE / "dist"
APP = BUILD / "app"
NAME = "NammaAgentInstaller"
INSTALLER_UI = ROOT / "installer" / "webui"
REQS = ROOT / "namma_agent" / "requirements.txt"

# ── self-contained runtime (Windows only) ───────────────────────────────────
# winget's sandbox validates installs OFFLINE with no system Python/pip/node. So on
# Windows we bundle a relocatable CPython (python-build-standalone — the same builds
# uv/rye use) with every app dependency pre-installed, and the installer just copies
# it into place. macOS/Linux keep the venv-bootstrap path (they don't go via winget).
# Cached under installers/native/ so local rebuilds don't re-download + re-pip.
RTCACHE = NATIVE / "runtime-win-x64"
_RT_TAG = "20241016"
_RT_PYVER = "3.12.7"
_RT_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{_RT_TAG}/cpython-{_RT_PYVER}+{_RT_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"
)


def version() -> str:
    t = (ROOT / "namma_agent" / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', t).group(1)


def run(cmd, cwd=None):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd and str(cwd), check=True)


def run_npm(args, cwd):
    # npm is npm.cmd on Windows — a batch file subprocess can't launch directly,
    # so go through cmd.exe there. On POSIX call npm normally.
    if os.name == "nt":
        run(["cmd", "/c", "npm", *args], cwd=cwd)
    else:
        run(["npm", *args], cwd=cwd)


def build_installer_ui():
    """Build the installer's own React UI (installer/webui) → dist/, so it can be
    bundled into the frozen installer and shown in the pywebview window."""
    if not (INSTALLER_UI / "dist" / "index.html").exists():
        run_npm(["install"], cwd=INSTALLER_UI)
        run_npm(["run", "build"], cwd=INSTALLER_UI)


def stage_app():
    """Stage a clean app copy (tracked files + the prebuilt UI) at build/app."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    APP.mkdir(parents=True)
    webui = ROOT / "namma_agent" / "webui"
    if not (webui / "dist" / "index.html").exists():
        run_npm(["install"], cwd=webui)
        run_npm(["run", "build"], cwd=webui)
    tar = BUILD / "src.tar"
    run(["git", "archive", "-o", tar, "HEAD"], cwd=ROOT)
    with tarfile.open(tar) as t:
        t.extractall(APP, filter="data")   # filter= silences the py3.14 tar warning
    tar.unlink()
    dst = APP / "namma_agent" / "webui" / "dist"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(webui / "dist", dst, dirs_exist_ok=True)

    # Never ship machine-specific overlays or secrets — a fresh install must use the
    # tracked defaults (assistant name "Namma Agent"), not a dev's local name/keys.
    for leak in ("namma_agent/config.local.yaml", "config.local.yaml", ".env"):
        p = APP / leak
        if p.exists():
            p.unlink()
            print(f"  (stripped {leak} from the bundle)", flush=True)


def stage_runtime():
    """Windows only: produce a relocatable CPython with all app deps pre-installed, so
    the installer can drop a ready-to-run environment OFFLINE (no system Python, no
    pip, no network) — what winget's unattended sandbox validation requires. Returns
    the runtime dir (contains python.exe) or None on non-Windows. Cached across builds.

    Playwright's browser binaries are deliberately NOT fetched here — they're large and
    already installed on first use (`playwright install chromium`); keeping them out
    keeps the installer small and the offline install fast."""
    if os.name != "nt":
        return None
    if (RTCACHE / "python.exe").exists():
        print(f"+ reusing cached runtime at {RTCACHE}", flush=True)
        return RTCACHE
    BUILD.mkdir(parents=True, exist_ok=True)
    tar = BUILD / "runtime.tar.gz"
    print(f"+ downloading standalone CPython {_RT_PYVER} …\n  {_RT_URL}", flush=True)
    urllib.request.urlretrieve(_RT_URL, tar)  # noqa: S310 — fixed https GitHub asset
    extract = BUILD / "_rt"
    if extract.exists():
        shutil.rmtree(extract)
    with tarfile.open(tar) as t:
        t.extractall(extract, filter="data")   # install_only tarballs unpack to python/
    tar.unlink()
    if RTCACHE.exists():
        shutil.rmtree(RTCACHE)
    (extract / "python").rename(RTCACHE)
    shutil.rmtree(extract, ignore_errors=True)
    print("+ installing app dependencies into the bundled runtime …", flush=True)
    run([RTCACHE / "python.exe", "-m", "pip", "install", "--no-warn-script-location",
         "--no-cache-dir", "-r", REQS])
    return RTCACHE


def _icon():
    """A natively-valid PyInstaller icon for THIS OS, or None. Windows uses .ico;
    macOS needs .icns for the .app (skip if absent — avoids a Pillow dependency for
    png->icns conversion); Linux ignores executable icons."""
    assets = ROOT / "namma_agent" / "assets"
    if os.name == "nt":
        p = assets / "sparkle.ico"
        return p if p.exists() else None
    if platform.system() == "Darwin":
        p = assets / "sparkle.icns"
        return p if p.exists() else None
    return None


def freeze(ver: str, runtime: "Path | None" = None):
    """PyInstaller-freeze installer/ with the staged app bundled in."""
    sep = ";" if os.name == "nt" else ":"
    onefile = platform.system() != "Darwin"   # macOS wants a .app (onedir) for the .dmg
    # `python -m PyInstaller` (not the `pyinstaller` script) so it works regardless
    # of whether the Scripts/bin dir is on PATH.
    ui_dist = INSTALLER_UI / "dist"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
            "--add-data", f"{APP}{sep}app",
            # The installer's React UI, shown in the pywebview window.
            "--add-data", f"{ui_dist}{sep}installer_ui",
            # pywebview's backend (incl. the Windows EdgeChromium/pythonnet bits) is
            # loaded dynamically — pull it all in so the frozen installer can render.
            "--collect-all", "webview",
            "--distpath", DIST, "--workpath", BUILD / "pyi", "--specpath", BUILD]
    if runtime:
        # The self-contained CPython+deps → <_MEIPASS>/runtime; the installer copies it
        # into the install dir so the app runs with no system Python (winget offline).
        args += ["--add-data", f"{runtime}{sep}runtime"]
    if onefile:
        args.append("--onefile")
    ico = _icon()
    if ico:
        args += ["--icon", ico]
    args.append(ROOT / "installer" / "__main__.py")
    run(args, cwd=ROOT)


def _arch() -> str:
    """Normalized CPU architecture for asset names — an unlabeled binary is how
    Apple-Silicon users end up with an Intel build (or vice versa)."""
    m = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64",
            "arm64": "arm64", "aarch64": "arm64"}.get(m, m or "unknown")


def package(ver: str):
    DIST.mkdir(parents=True, exist_ok=True)
    sysname = platform.system()
    if sysname == "Windows":
        src = DIST / f"{NAME}.exe"
        out = DIST / f"{NAME}-{ver}.exe"
        if src.exists():
            src.replace(out)
        print(f"\nBuilt: {out}")
    elif sysname == "Darwin":
        appbundle = DIST / f"{NAME}.app"
        dmg = DIST / f"NammaAgent-{ver}-{_arch()}.dmg"
        if dmg.exists():
            dmg.unlink()
        run(["hdiutil", "create", "-volname", "Namma Agent", "-srcfolder", appbundle,
             "-ov", "-format", "UDZO", dmg])
        print(f"\nBuilt: {dmg}")
    else:  # Linux
        binary = DIST / NAME
        if shutil.which("appimagetool"):
            appdir = BUILD / "NammaAgent.AppDir"
            (appdir / "usr" / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, appdir / "usr" / "bin" / NAME)
            (appdir / "AppRun").write_text(
                f'#!/bin/bash\nexec "$(dirname "$(readlink -f "$0")")/usr/bin/{NAME}" "$@"\n')
            os.chmod(appdir / "AppRun", 0o755)
            (appdir / "namma-agent.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Namma Agent\n"
                f"Exec={NAME}\nIcon=namma-agent\nCategories=Utility;\nTerminal=false\n")
            icon = ROOT / "namma_agent" / "assets" / "sparkle.png"
            if icon.exists():
                shutil.copy2(icon, appdir / "namma-agent.png")
            out = DIST / f"{NAME}-{ver}-{_arch()}.AppImage"
            run(["appimagetool", appdir, out], cwd=BUILD)
            print(f"\nBuilt: {out}")
        else:
            print(f"\nappimagetool not found — raw binary is at {binary}")


def main():
    ver = version()
    print(f"== Building Namma Agent installer {ver} on {platform.system()} ==")
    build_installer_ui()
    stage_app()
    runtime = stage_runtime()
    freeze(ver, runtime)
    package(ver)


if __name__ == "__main__":
    sys.exit(main())
