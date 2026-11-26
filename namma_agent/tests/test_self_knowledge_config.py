"""Phase 2: live self-knowledge, the "about you" prompt block, config/.env paths
in the data volume (BUG-11), and Settings secrets going to the vault."""
from __future__ import annotations

import os

import pytest

from namma_agent import config as cfg
from namma_agent.core import self_knowledge as sk
from namma_agent.core.memory import Database
from namma_agent.core.tools import ToolRegistry

# ── self-knowledge ───────────────────────────────────────────────────────────

def test_about_block_names_real_paths_and_no_stale_identity():
    block = sk.about_block({"assistant": {"name": "Jarvis"}}, "")
    assert "you are Jarvis" in block
    assert cfg.config_file().name in block
    assert "mcp.servers" in block and "about_namma" in block
    assert "FRIDAY" not in block


def test_render_is_live_and_never_leaks_secret_values(monkeypatch):
    monkeypatch.setenv("SECRET_GH_TOKEN", "ghp_supersecretvalue123")
    conf = {
        "assistant": {"name": "Jarvis"},
        "mcp": {"servers": [{"name": "github", "command": ["npx", "gh-mcp"],
                             "env": {"GITHUB_TOKEN": "ghp_supersecretvalue123"}},
                            {"name": "off", "command": "x", "enabled": False}]},
        "providers": [{"id": "oc", "type": "opencode", "api_key_env": "OPENAI_API_KEY"}],
        "models": [{"id": "m1", "provider": "oc", "model": "gpt-5"}],
    }
    reg = ToolRegistry()
    with reg.categorize("web"):
        reg.register("web_search", "Search.", {"type": "object", "properties": {}}, lambda a: "")
    text = sk.render(conf, reg)
    assert "# About Jarvis (live)" in text
    assert "github (enabled)" in text and "off (disabled)" in text
    assert "GITHUB_TOKEN" in text and "ghp_supersecretvalue123" not in text
    assert "model `m1`: gpt-5 via oc" in text and "$OPENAI_API_KEY" in text
    assert "- web: web_search" in text
    assert "{name}" not in text and "FRIDAY" not in text
    mcp_only = sk.render(conf, reg, topic="mcp")
    assert mcp_only.startswith("## MCP servers")


def test_about_namma_tool_uses_the_live_render():
    from namma_agent.tools import selfdoc

    reg = ToolRegistry()
    selfdoc.register(reg)
    out = reg.execute("about_namma", {"topic": "paths"})
    assert out.ok and "config_file" in out.content and "install_dir" in out.content


def test_service_injects_about_block_into_the_prompt():
    from namma_agent.core.providers.base import LLMResponse, Provider
    from namma_agent.service import NammaAgentService

    class P(Provider):
        name = "p"

        def __init__(self):
            super().__init__(model="p")
            self.seen = []

        def is_available(self):
            return True

        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            self.seen.append(messages)
            return LLMResponse(content="ok")

    prov = P()
    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=prov, registry=ToolRegistry(), db=Database(":memory:"))
    svc.agent.process_turn("hi")
    assert "ABOUT YOU" in prov.seen[0][0]["content"]


# ── config / env paths ───────────────────────────────────────────────────────

def test_env_file_follows_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("NAMMA_ENV_FILE", raising=False)
    monkeypatch.delenv("NAMMA_DATA_DIR", raising=False)
    assert cfg.env_file() == cfg._REPO_ROOT / ".env"
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path / "state"))
    assert cfg.env_file() == tmp_path / "state" / ".env"
    monkeypatch.setenv("NAMMA_ENV_FILE", str(tmp_path / "x.env"))
    assert cfg.env_file() == tmp_path / "x.env"


# ── one user config in the data dir (owner decision 2026-11-25) ──────────────

def _app_layout(monkeypatch, tmp_path, legacy: str = ""):
    """A fake install: base config in pkg/, state in data/, no explicit override."""
    base = tmp_path / "pkg" / "config.yaml"
    base.parent.mkdir(parents=True)
    base.write_text("a: 1\nprovider:\n  model: base-model\n", encoding="utf-8")
    if legacy:
        (base.parent / "config.local.yaml").write_text(legacy, encoding="utf-8")
    monkeypatch.setattr(cfg, "_config_path", lambda: base)
    monkeypatch.delenv("NAMMA_USER_CONFIG", raising=False)
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path / "data"))
    return base


def test_settings_edits_go_to_the_user_config_and_base_is_untouched(monkeypatch, tmp_path):
    base = _app_layout(monkeypatch, tmp_path)
    before = base.read_text(encoding="utf-8")
    merged = cfg.update_config({"provider": {"model": "picked"}})
    target = tmp_path / "data" / "user_config.yaml"
    assert cfg.overlay_file() == target and target.exists()
    assert merged["provider"]["model"] == "picked" and merged["a"] == 1
    assert base.read_text(encoding="utf-8") == before
    assert not (base.parent / "config.local.yaml").exists()
    assert cfg.load_config()["provider"]["model"] == "picked"


def test_legacy_overlay_is_migrated_once_and_renamed(monkeypatch, tmp_path):
    base = _app_layout(monkeypatch, tmp_path, legacy="assistant:\n  name: Aria\n")
    data = cfg.load_config()
    assert data["assistant"]["name"] == "Aria" and data["a"] == 1
    target = tmp_path / "data" / "user_config.yaml"
    assert target.read_text(encoding="utf-8") == "assistant:\n  name: Aria\n"
    assert not (base.parent / "config.local.yaml").exists()
    assert (base.parent / "config.local.yaml.migrated").exists()
    # A legacy file that reappears later (e.g. a fresh image layer) is ignored.
    (base.parent / "config.local.yaml").write_text("assistant:\n  name: Old\n", encoding="utf-8")
    assert cfg.load_config()["assistant"]["name"] == "Aria"


def test_docker_seed_and_state_dir_overlay_are_migrated(monkeypatch, tmp_path):
    _app_layout(monkeypatch, tmp_path, legacy="conversation:\n  max_history_turns: 8\n")
    state_overlay = tmp_path / "data" / "config.local.yaml"
    state_overlay.parent.mkdir(parents=True)
    state_overlay.write_text("profile: from-volume\n", encoding="utf-8")
    data = cfg.load_config()
    assert data.get("profile") == "from-volume"          # the state-dir copy wins
    assert "conversation" not in data


def test_explicit_base_path_keeps_a_sibling_overlay(monkeypatch, tmp_path):
    """Tests and portable tools pass a base path explicitly; they must never touch
    the user's real settings."""
    _app_layout(monkeypatch, tmp_path)
    other = tmp_path / "elsewhere" / "config.yaml"
    other.parent.mkdir()
    other.write_text("x: 1\n", encoding="utf-8")
    assert cfg._local_overrides_path(other) == other.parent / "config.local.yaml"
    cfg.update_config({"y": 2}, path=str(other))
    assert not (tmp_path / "data" / "user_config.yaml").exists()


def test_user_config_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMMA_USER_CONFIG", str(tmp_path / "mine.yaml"))
    assert cfg.user_config_file() == tmp_path / "mine.yaml"


def test_about_block_points_at_the_user_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMMA_USER_CONFIG", str(tmp_path / "mine.yaml"))
    assert "mine.yaml" in sk.about_block({}, "X")


def test_load_dotenv_reads_data_dir_then_repo_fallback(monkeypatch, tmp_path):
    primary = tmp_path / "a.env"
    primary.write_text("NAMMA_T_ONE=from-data\n", encoding="utf-8")
    monkeypatch.setenv("NAMMA_ENV_FILE", str(primary))
    monkeypatch.delenv("NAMMA_T_ONE", raising=False)
    cfg.load_dotenv()
    assert os.environ["NAMMA_T_ONE"] == "from-data"
    monkeypatch.delenv("NAMMA_T_ONE", raising=False)


def test_remove_env_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keep\nA_KEY=1\nB=2\n", encoding="utf-8")
    assert cfg.remove_env_values(["A_KEY", "MISSING"], path=str(env)) == ["A_KEY"]
    assert env.read_text(encoding="utf-8") == "# keep\nB=2\n"


# ── Settings secrets → vault ─────────────────────────────────────────────────

class _MemBackend:
    name = "memory"

    def __init__(self):
        self.data = {}

    def set(self, k, v):
        self.data[k] = v
        return True

    def get(self, k):
        return self.data.get(k)

    def delete(self, k):
        return self.data.pop(k, None) is not None


@pytest.fixture
def vault(tmp_path, monkeypatch):
    from namma_agent.core import secrets

    store = secrets.SecretStore(str(tmp_path), backend=_MemBackend())
    secrets.set_store(store)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=stale-old\nNAMMA_LOG_LEVEL=info\n", encoding="utf-8")
    monkeypatch.setenv("NAMMA_ENV_FILE", str(env))
    yield store, env
    secrets.set_store(None)
    for k in ("OPENAI_API_KEY", "NAMMA_LOG_LEVEL"):
        os.environ.pop(k, None)


def test_settings_secrets_go_to_the_vault_and_leave_env(vault):
    from namma_agent.core.secrets import save_settings_env

    store, env = vault
    out = save_settings_env({"OPENAI_API_KEY": "sk-new-value-1234", "NAMMA_LOG_LEVEL": "debug"})
    assert out == {"vault": ["OPENAI_API_KEY"], "env": ["NAMMA_LOG_LEVEL"]}
    assert store.get("OPENAI_API_KEY") == "sk-new-value-1234"
    assert os.environ["OPENAI_API_KEY"] == "sk-new-value-1234"
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in text            # stale copy can't shadow the vault
    assert "NAMMA_LOG_LEVEL=debug" in text


def test_clearing_a_secret_removes_it_from_the_vault(vault):
    from namma_agent.core.secrets import save_settings_env

    store, _ = vault
    save_settings_env({"OPENAI_API_KEY": "sk-new-value-1234"})
    save_settings_env({"OPENAI_API_KEY": ""})
    assert store.get("OPENAI_API_KEY") is None and "OPENAI_API_KEY" not in store.names()


def test_bad_values_are_rejected_before_anything_is_written(vault):
    from namma_agent.core.secrets import save_settings_env

    store, _ = vault
    with pytest.raises(ValueError):
        save_settings_env({"OPENAI_API_KEY": "sk\nNAMMA_API_TOKEN="})
    with pytest.raises(ValueError):
        save_settings_env({"bad key": "x"})
    assert store.names() == []
