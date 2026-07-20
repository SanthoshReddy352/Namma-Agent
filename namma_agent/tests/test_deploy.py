"""Phase 6b — deployment artifacts stay valid (offline checks).

Docker can't run in CI-offline tests, but the expensive mistakes here are
textual: a compose file that doesn't parse, a unit file missing its memory
guard, an installer that isn't idempotent-safe (`set -e` lost in an edit).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_parses_and_is_bounded():
    cfg = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = cfg["services"]["namma-agent"]
    assert svc["build"] == "."
    assert svc["restart"] == "unless-stopped"
    # The 1 GB-box guard and the not-silently-public default.
    assert svc["mem_limit"] == "900m"
    assert svc["ports"] == ["127.0.0.1:8000:8000"]
    assert "namma_data:/app/data" in svc["volumes"]
    assert "namma_data" in cfg["volumes"]


def test_dockerfile_essentials():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in text and "/api/health" in text
    assert "USER namma" in text                      # non-root
    assert "NAMMA_DATA_DIR=/app/data" in text        # volume-backed state
    assert "NAMMA_HOST=0.0.0.0" in text              # container binds all ifaces
    assert 'VOLUME ["/app/data"]' in text
    assert "--server" in text                        # headless entrypoint


def test_systemd_unit_essentials():
    text = (ROOT / "deploy" / "namma-agent.service").read_text(encoding="utf-8")
    assert "MemoryMax=" in text                      # OOM guard for the 1 GB box
    assert "Restart=on-failure" in text
    assert "EnvironmentFile=-__INSTALL_DIR__/.env" in text
    assert "-m namma_agent --server" in text
    assert "User=namma" in text
    assert "WantedBy=multi-user.target" in text


def test_install_sh_safety_rails():
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    assert "--dry-run" in text                       # documented + parsed
    assert "swapon" in text and "/swapfile" in text  # the survival step
    assert "token_urlsafe" in text                   # generates the access token
    assert "systemctl enable --now namma-agent" in text
    assert "\r" not in text                          # CRLF would break bash on the box


def test_install_sh_bash_syntax():
    bash = shutil.which("bash")
    if not bash:
        import pytest
        pytest.skip("no bash on this machine")
    r = subprocess.run([bash, "-n", str(ROOT / "deploy" / "install.sh")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_server_lite_profile_is_valid_overlay():
    cfg = yaml.safe_load((ROOT / "deploy" / "config.server-lite.yaml").read_text(encoding="utf-8"))
    # Loopback by default — exposing is an explicit, documented step.
    assert cfg["server"]["host"] == "127.0.0.1"
    conv = cfg["conversation"]
    assert conv["max_history_turns"] <= 12 and conv["tool_result_max_chars"] <= 8000
