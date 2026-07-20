"""winget manifest generator (Phase 5) — offline, against a local fake asset."""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "installers" / "winget" / "generate.py"


def _load_gen():
    spec = importlib.util.spec_from_file_location("winget_generate", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_manifest_set_from_local_exe(tmp_path, monkeypatch):
    exe = tmp_path / "NammaAgentInstaller-0.0.1.exe"
    exe.write_bytes(b"not really an installer")
    expected_sha = hashlib.sha256(exe.read_bytes()).hexdigest().upper()

    r = subprocess.run([sys.executable, str(GEN), "--version", "0.0.1",
                        "--exe", str(exe)],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    try:
        assert r.returncode == 0, r.stderr
        out = GEN.parent / "manifests" / "s" / "SanthoshReddy352" / "NammaAgent" / "0.0.1"
        files = {p.name for p in out.iterdir()}
        assert files == {"SanthoshReddy352.NammaAgent.yaml",
                         "SanthoshReddy352.NammaAgent.installer.yaml",
                         "SanthoshReddy352.NammaAgent.locale.en-US.yaml"}
        installer = (out / "SanthoshReddy352.NammaAgent.installer.yaml").read_text(encoding="utf-8")
        assert expected_sha in installer                 # the real asset hash
        assert "Silent: --cli" in installer              # unattended mode wired
        assert "NammaAgentInstaller-0.0.1.exe" in installer
        version = (out / "SanthoshReddy352.NammaAgent.yaml").read_text(encoding="utf-8")
        assert 'PackageVersion: "0.0.1"' in version
    finally:
        shutil.rmtree(GEN.parent / "manifests", ignore_errors=True)


def test_current_version_matches_version_py():
    mod = _load_gen()
    from namma_agent.version import __version__
    assert mod.current_version() == __version__
