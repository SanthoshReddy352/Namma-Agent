"""Phase 7d — shell execution backends (core/shell_backends.py).

Docker and SSH are exercised with a fake ``subprocess.run`` so the suite stays
offline and runs on any machine. The load-bearing assertions are the safety
ones: the local path is unchanged, and a chosen-but-broken backend fails loudly
instead of quietly running on the user's own machine.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from namma_agent.core import shell_backends as sb


@pytest.fixture(autouse=True)
def _reset_module_state():
    sb.configure_backend(None)
    yield
    sb.configure_backend(None)


@pytest.fixture
def fake_run(monkeypatch):
    """Record every subprocess.run and answer from a scripted table."""
    calls: list[list[str]] = []
    table: dict = {"default": (0, "", "")}

    def _run(argv, **kwargs):
        calls.append(list(argv))
        for needle, result in table.items():
            if needle != "default" and needle in " ".join(argv):
                code, out, err = result
                return SimpleNamespace(returncode=code, stdout=out, stderr=err)
        code, out, err = table["default"]
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)

    monkeypatch.setattr(sb.subprocess, "run", _run)
    monkeypatch.setattr(sb.shutil, "which", lambda name: f"/usr/bin/{name}")
    return SimpleNamespace(calls=calls, table=table)


# ── selection ────────────────────────────────────────────────────────────────

def test_default_is_local():
    assert sb.build_backend(None).name == "local"
    assert sb.build_backend({"shell": {}}).name == "local"


def test_backend_is_selected_by_name():
    assert sb.build_backend({"shell": {"backend": "docker"}}).name == "docker"
    assert sb.build_backend({"shell": {"backend": "ssh"}}).name == "ssh"
    assert sb.build_backend({"shell": {"backend": "LOCAL"}}).name == "local"


def test_unknown_backend_degrades_to_local():
    """A typo must not disable the shell — nor silently pick something odd."""
    assert sb.build_backend({"shell": {"backend": "kubernetes"}}).name == "local"


def test_configure_and_current():
    sb.configure_backend({"shell": {"backend": "ssh", "ssh": {"host": "box"}}})
    assert sb.current_backend().name == "ssh"
    assert sb.status()["backend"] == "ssh"


# ── local: nothing about it may change ───────────────────────────────────────

def test_local_backend_matches_the_pre_phase7_behaviour():
    from namma_agent.core.shell_session import (_find_shell, _POSIX_DRIVER,
                                                _PS_DRIVER, IS_WINDOWS)
    backend = sb.ShellBackend()
    assert backend.driver_text() == (_PS_DRIVER if IS_WINDOWS else _POSIX_DRIVER)
    assert backend.script_ext() == (".ps1" if IS_WINDOWS else ".sh")
    assert backend.argv("/tmp/driver.sh") == _find_shell() + ["/tmp/driver.sh"]
    # The identity function: the driver reads the very file we wrote.
    assert backend.materialize("/tmp/cmd_abc.sh") == "/tmp/cmd_abc.sh"
    assert backend.check() is None


def test_local_popen_kwargs_carry_cwd_and_env():
    kwargs = sb.ShellBackend().popen_kwargs("/some/dir")
    assert kwargs["cwd"] == "/some/dir" and "PATH" in kwargs["env"]


def test_local_status():
    assert sb.ShellBackend().status()["isolation"] == "os-sandbox"


# ── docker ───────────────────────────────────────────────────────────────────

def _docker(**cfg):
    return sb.DockerBackend({"container": "namma-shell", **cfg})


def test_docker_always_uses_the_posix_driver():
    """The container is Linux even when the host is Windows — sending it a
    PowerShell driver would be an instant, confusing failure."""
    from namma_agent.core.shell_session import _POSIX_DRIVER
    backend = _docker()
    assert backend.windows_shell is False
    assert backend.driver_text() == _POSIX_DRIVER
    assert backend.script_ext() == ".sh"
    assert backend.script_encoding() == "utf-8"


def test_docker_check_passes_for_a_running_container(fake_run):
    fake_run.table["inspect"] = (0, "true\n", "")
    _docker().check()
    assert any("inspect" in " ".join(c) for c in fake_run.calls)


def test_docker_check_starts_a_stopped_container(fake_run):
    fake_run.table["inspect"] = (0, "false\n", "")
    _docker().check()
    assert any(c[:2] == ["/usr/bin/docker", "start"] for c in fake_run.calls)


def test_docker_creates_a_missing_container_with_hardening(fake_run):
    fake_run.table["inspect"] = (1, "", "No such object")
    _docker(image="debian:bookworm-slim", workspace=".", memory="1g",
            cpus="2", pids_limit=64).check()

    run_call = next(c for c in fake_run.calls if c[1] == "run")
    joined = " ".join(run_call)
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--pids-limit 64" in joined
    assert "--memory 1g" in joined and "--cpus 2" in joined
    assert "-w /workspace" in joined


def test_docker_without_an_image_refuses_instead_of_guessing(fake_run):
    fake_run.table["inspect"] = (1, "", "No such object")
    with pytest.raises(sb.BackendError) as exc:
        _docker().check()
    assert "no container named" in str(exc.value)
    assert "image" in str(exc.value)


def test_docker_missing_binary_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(sb.shutil, "which", lambda name: None)
    with pytest.raises(sb.BackendError) as exc:
        _docker().check()
    assert "isn't on PATH" in str(exc.value)
    assert "'local'" in str(exc.value)      # tells the user the way out


def test_docker_argv_execs_into_the_container(fake_run):
    argv = _docker(workspace=".").argv("/tmp/driver.sh")
    assert argv[1:4] == ["exec", "-i", "-w"]
    assert "namma-shell" in argv
    assert argv[-2:] == ["/bin/sh", f"{sb.REMOTE_DIR}/driver.sh"]


def test_docker_ignores_the_local_cwd(fake_run):
    """`docker exec -w` sets the directory inside the container; passing a
    local cwd would be meaningless and could break the spawn outright."""
    assert _docker().popen_kwargs("D:/some/local/dir") == {}


def test_docker_prepare_copies_the_driver_in(fake_run):
    _docker().prepare("/local/driver.sh")
    cp = next(c for c in fake_run.calls if c[1] == "cp")
    assert cp[2] == "/local/driver.sh"
    assert cp[3] == f"namma-shell:{sb.REMOTE_DIR}/driver.sh"


def test_docker_materialize_ships_each_command(fake_run):
    remote = _docker().materialize("/local/tmp/cmd_abc.sh")
    assert remote == f"{sb.REMOTE_DIR}/cmd_abc.sh"
    assert any(c[1] == "cp" and c[2] == "/local/tmp/cmd_abc.sh"
               for c in fake_run.calls)


def test_docker_materialize_failure_raises(fake_run):
    fake_run.table["default"] = (1, "", "no such container")
    with pytest.raises(sb.BackendError) as exc:
        _docker().materialize("/local/tmp/cmd_abc.sh")
    assert "no such container" in str(exc.value)


def test_docker_status_reports_the_hardening(fake_run):
    fake_run.table["inspect"] = (0, "true\n", "")
    status = _docker(workspace="/work", memory="2g").status()
    assert status["isolation"] == "container"
    assert status["state"] == "running"
    assert "cap-drop ALL" in status["caps"] and "no-new-privileges" in status["caps"]


# ── ssh ──────────────────────────────────────────────────────────────────────

def _ssh(**cfg):
    return sb.SshBackend({"host": "devbox", **cfg})


def test_ssh_needs_a_host():
    with pytest.raises(sb.BackendError) as exc:
        sb.SshBackend({}).check()
    assert "needs security.shell.ssh.host" in str(exc.value)


def test_ssh_uses_batchmode_so_it_never_prompts(fake_run):
    """Namma does not handle SSH passwords — key/agent only. BatchMode makes a
    misconfiguration fail fast instead of hanging on a hidden prompt."""
    args = _ssh().argv("/tmp/driver.sh")
    assert "BatchMode=yes" in " ".join(args)


def test_ssh_argv_targets_the_remote_driver(fake_run):
    args = _ssh(user="san", port="2222", cwd="/home/san/work").argv("/tmp/d.sh")
    joined = " ".join(args)
    assert "san@devbox" in joined
    assert "-p 2222" in joined
    assert args[-1] == f"cd /home/san/work && sh {sb.REMOTE_DIR}/driver.sh"


def test_ssh_check_probes_the_connection(fake_run):
    _ssh().check()
    assert any(c[-1] == "true" for c in fake_run.calls)


def test_ssh_check_failure_explains_itself(fake_run):
    fake_run.table["default"] = (255, "", "Permission denied (publickey).")
    with pytest.raises(sb.BackendError) as exc:
        _ssh().check()
    assert "can't reach devbox" in str(exc.value)
    assert "Permission denied" in str(exc.value)


def test_ssh_missing_binary_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(sb.shutil, "which", lambda name: None)
    with pytest.raises(sb.BackendError) as exc:
        _ssh().check()
    assert "isn't on PATH" in str(exc.value)


def test_ssh_materialize_pushes_the_script(fake_run, tmp_path):
    script = tmp_path / "cmd_abc.sh"
    script.write_text("echo hi", encoding="utf-8")
    remote = _ssh().materialize(str(script))
    assert remote == f"{sb.REMOTE_DIR}/cmd_abc.sh"
    assert any("cat > " in " ".join(c) for c in fake_run.calls)


def test_ssh_status_is_honest_about_the_sandbox(fake_run):
    """The Phase 1c caps bound the local ssh client, not the remote work.
    Saying otherwise would be a false security claim."""
    status = _ssh().status()
    assert status["isolation"] == "remote-host"
    assert "does NOT apply" in status["detail"]


# ── the no-silent-fallback contract ──────────────────────────────────────────

def test_a_broken_backend_fails_the_shell_instead_of_running_locally(monkeypatch, tmp_path):
    """The whole point of choosing a backend: if it can't start, the command
    must NOT quietly execute on the user's own machine."""
    from namma_agent.core.shell_session import PersistentShell

    monkeypatch.setattr(sb.shutil, "which", lambda name: None)
    sb.configure_backend({"shell": {"backend": "docker",
                                    "docker": {"container": "nope"}}})

    shell = PersistentShell("test-session", cwd=str(tmp_path))
    result = shell.run("echo this must not run", timeout=5)

    assert result.ok is False
    assert result.died is True
    assert "isn't on PATH" in result.output
    assert shell.alive is False


def test_status_never_raises(monkeypatch):
    sb.configure_backend({"shell": {"backend": "docker"}})

    def boom(*a, **k):
        raise OSError("docker exploded")

    monkeypatch.setattr(sb.subprocess, "run", boom)
    assert sb.status()["backend"] == "docker"      # reported, not raised
