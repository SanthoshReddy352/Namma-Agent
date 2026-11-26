"""Suite-wide test isolation."""
from __future__ import annotations

import os
import tempfile

import pytest

# The whole suite runs against a throwaway data dir. Set at import time (before
# any test module is collected) so paths computed at import — media and
# document output dirs — are isolated too. Without this, test runs left
# reminders, tool outputs and diagrams in the developer's real data/.
os.environ["NAMMA_DATA_DIR"] = tempfile.mkdtemp(prefix="namma-test-data-")
os.environ["NAMMA_WHATSAPP_SESSION"] = os.path.join(os.environ["NAMMA_DATA_DIR"],
                                                  "whatsapp_qr.sqlite3")
# The vault and .env too: a file vault in the throwaway dir (never the OS
# credential store the real app uses), and a throwaway .env.
os.environ["NAMMA_VAULT_BACKEND"] = "file"
os.environ["NAMMA_ENV_FILE"] = os.path.join(os.environ["NAMMA_DATA_DIR"], ".env")


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    """Point the user config at a throwaway file so no test can read, write or
    migrate the developer's real settings (data/user_config.yaml, or the legacy
    namma_agent/config.local.yaml)."""
    path = tmp_path_factory.mktemp("user_config") / "user_config.yaml"
    monkeypatch.setenv("NAMMA_USER_CONFIG", str(path))
    yield path
