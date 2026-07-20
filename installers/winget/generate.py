"""Generate the winget manifest set for a released Namma Agent version.

winget manifests must carry the SHA-256 of the *actual* release asset, so they
can only be produced after the GitHub release exists. This script does the
whole job:

    python installers/winget/generate.py                 # current version.py, downloads the asset
    python installers/winget/generate.py --version 2.3.0
    python installers/winget/generate.py --exe path\\to\\NammaAgentInstaller-2.3.0.exe

It writes the three-file manifest set (version / installer / locale, schema
1.6) under ``installers/winget/manifests/s/SanthoshReddy352/NammaAgent/<ver>/``
— the exact layout the microsoft/winget-pkgs repo expects, so submission is:
validate with ``winget validate <dir>``, test with
``winget install --manifest <dir>``, then PR the folder into winget-pkgs.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "SanthoshReddy352/Namma-Agent"
PKG_ID = "SanthoshReddy352.NammaAgent"

_VERSION_MANIFEST = """\
# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.1.6.0.schema.json
PackageIdentifier: {pkg}
PackageVersion: "{ver}"
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
"""

_INSTALLER_MANIFEST = """\
# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.6.0.schema.json
PackageIdentifier: {pkg}
PackageVersion: "{ver}"
Platform:
  - Windows.Desktop
MinimumOSVersion: 10.0.17763.0
InstallerType: exe
Scope: user
InstallModes:
  - interactive
  - silent
InstallerSwitches:
  # The installer app's unattended mode (no GUI, same flow) — see installer/__main__.py.
  Silent: --cli
  SilentWithProgress: --cli
UpgradeBehavior: install
Installers:
  - Architecture: x64
    InstallerUrl: https://github.com/{repo}/releases/download/v{ver}/NammaAgentInstaller-{ver}.exe
    InstallerSha256: {sha}
AppsAndFeaturesEntries:
  # installer/core.py:register_windows_app writes this Add/Remove entry.
  - DisplayName: Namma Agent
ManifestType: installer
ManifestVersion: 1.6.0
"""

_LOCALE_MANIFEST = """\
# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.1.6.0.schema.json
PackageIdentifier: {pkg}
PackageVersion: "{ver}"
PackageLocale: en-US
Publisher: Santhosh Reddy
PublisherUrl: https://github.com/SanthoshReddy352
PublisherSupportUrl: https://github.com/{repo}/issues
PackageName: Namma Agent
PackageUrl: https://github.com/{repo}
License: MIT
LicenseUrl: https://github.com/{repo}/blob/main/LICENSE
ShortDescription: The trustworthy personal AI agent that measurably knows you — first-class on Windows.
Description: >-
  Namma Agent is a self-hosted personal AI agent. Any cloud brain (Anthropic,
  OpenAI, Google, or any OpenAI-compatible endpoint), ~90 native tools, an
  in-process memory engine with a published recall benchmark, event-driven
  watchers, and a layered trust model (per-channel sender trust, injection
  screening, sandboxed shell, secrets vault) that is on by default and visible
  in the UI.
Moniker: namma-agent
Tags:
  - ai
  - agent
  - assistant
  - llm
  - personal-assistant
  - self-hosted
ReleaseNotesUrl: https://github.com/{repo}/releases/tag/v{ver}
ManifestType: defaultLocale
ManifestVersion: 1.6.0
"""


def current_version() -> str:
    text = (ROOT / "namma_agent" / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=None, help="release version (default: namma_agent/version.py)")
    ap.add_argument("--exe", default=None, help="local installer exe (skips the download)")
    args = ap.parse_args()

    ver = args.version or current_version()
    asset = f"NammaAgentInstaller-{ver}.exe"
    if args.exe:
        exe = Path(args.exe)
    else:
        url = f"https://github.com/{REPO}/releases/download/v{ver}/{asset}"
        exe = Path(__file__).parent / asset
        print(f"downloading {url} …")
        try:
            urllib.request.urlretrieve(url, exe)  # noqa: S310 — fixed https host
        except Exception as e:  # noqa: BLE001
            print(f"error: could not fetch the release asset ({e}).\n"
                  f"Publish the v{ver} release first, or pass --exe <path>.")
            return 1
    if not exe.is_file():
        print(f"error: {exe} not found")
        return 1
    sha = sha256_of(exe)

    out = Path(__file__).parent / "manifests" / "s" / "SanthoshReddy352" / "NammaAgent" / ver
    out.mkdir(parents=True, exist_ok=True)
    ctx = {"pkg": PKG_ID, "ver": ver, "sha": sha, "repo": REPO}
    (out / f"{PKG_ID}.yaml").write_text(_VERSION_MANIFEST.format(**ctx), encoding="utf-8")
    (out / f"{PKG_ID}.installer.yaml").write_text(_INSTALLER_MANIFEST.format(**ctx), encoding="utf-8")
    (out / f"{PKG_ID}.locale.en-US.yaml").write_text(_LOCALE_MANIFEST.format(**ctx), encoding="utf-8")
    print(f"wrote manifest set -> {out}")  # ASCII — cp1252 consoles choke on arrows
    print("next: winget validate", out)
    print("      winget install --manifest", out)
    print("      then PR the folder into microsoft/winget-pkgs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
