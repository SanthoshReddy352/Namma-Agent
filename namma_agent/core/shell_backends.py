"""Shell execution backends (Phase 7d) — where ``run_shell`` actually runs.

Phase 1c bounded the blast radius of shell commands with OS resource caps (a
Windows Job Object / POSIX rlimits). Caps are not isolation: an approved command
still runs as your user, on your filesystem. These backends move the *execution*
somewhere else:

``local``   (default, unchanged) — the persistent shell on this machine, with
            the Phase 1c sandbox around it. Nothing about this path changes.
``docker``  — a persistent Linux container. Real isolation: dropped
            capabilities, ``no-new-privileges``, a pids limit, memory/CPU caps,
            and only the workspace you name is visible. This is what completes
            the Phase 1c story for anything an untrusted channel can trigger.
``ssh``     — a remote host over an existing key/agent. Pairs with Phase 6: the
            agent lives on the always-on box, the work happens on your dev
            machine (or the other way round).

**The protocol is unchanged.** ``PersistentShell`` writes each command to a
script file and hands the driver loop its path; a remote backend just has to
make that file visible on the far side, which is what :meth:`materialize` does
(``docker cp`` / ``ssh cat``). Keeping the local path byte-identical was the
point: the well-tested path must not regress to gain the new ones.

**Two honest limits.**

* The Phase 1c sandbox on a remote backend wraps the ``docker``/``ssh`` CLIENT
  process, not the workload. Docker's own flags do the real bounding; over SSH
  the remote host's limits apply and Namma's do not. :func:`status` says so
  rather than implying coverage it doesn't have.
* Remote backends pay a subprocess round trip per command to ship the script.
  That is the cost of not rewriting the driver protocol.

An explicitly chosen backend that cannot start **fails loudly** — it never
silently falls back to running on your machine, which would be the worst
possible outcome of a misconfiguration.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import uuid
from typing import Optional

from namma_agent.core.logger import logger

IS_WINDOWS = platform.system() == "Windows"

#: Where a remote backend keeps the driver + per-command scripts.
REMOTE_DIR = "/tmp/namma-shell"


class BackendError(RuntimeError):
    """The configured backend cannot be used. The message is user-facing."""


class ShellBackend:
    """Local execution — the default, and the shape the others implement."""

    name = "local"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    # -- what the driver looks like -----------------------------------------

    @property
    def windows_shell(self) -> bool:
        """True when the far side is PowerShell (only ever the local Windows
        case — containers and SSH targets are POSIX)."""
        return IS_WINDOWS

    def driver_text(self) -> str:
        from namma_agent.core.shell_session import _POSIX_DRIVER, _PS_DRIVER
        return _PS_DRIVER if self.windows_shell else _POSIX_DRIVER

    def script_ext(self) -> str:
        return ".ps1" if self.windows_shell else ".sh"

    def script_encoding(self) -> str:
        # Windows PowerShell 5.1 needs the BOM to parse UTF-8 scripts.
        return "utf-8-sig" if self.windows_shell else "utf-8"

    # -- lifecycle -----------------------------------------------------------

    def check(self) -> None:
        """Raise :class:`BackendError` if this backend can't run right now."""
        return None

    def prepare(self, driver_path: str) -> None:
        """Put the driver where :meth:`argv` expects it (a no-op locally)."""
        return None

    def argv(self, driver_path: str) -> list[str]:
        from namma_agent.core.shell_session import _find_shell
        return _find_shell() + [driver_path]

    def popen_kwargs(self, cwd: str) -> dict:
        """Spawn kwargs specific to this backend (cwd/env handling)."""
        from namma_agent.core.shell_session import _shell_env
        return {"cwd": cwd, "env": _shell_env()}

    def materialize(self, local_script: str) -> str:
        """The path the DRIVER should be given for a per-command script.
        Locally that's the local path; remotely, ship it and return the far
        side's path."""
        return local_script

    def status(self) -> dict:
        return {"backend": self.name, "isolation": "os-sandbox",
                "detail": "this machine, with the Phase 1c resource caps"}


class DockerBackend(ShellBackend):
    """A persistent, hardened Linux container."""

    name = "docker"

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        cfg = self.config or {}
        self.container = str(cfg.get("container") or "namma-shell").strip()
        self.image = str(cfg.get("image") or "").strip()
        self.workspace = str(cfg.get("workspace") or "").strip()
        self.memory = str(cfg.get("memory") or "2g").strip()
        self.cpus = str(cfg.get("cpus") or "").strip()
        self.pids_limit = int(cfg.get("pids_limit") or 256)
        self.network = str(cfg.get("network") or "").strip()
        self._prepared = False

    @property
    def windows_shell(self) -> bool:
        return False  # the container is Linux even when the host is Windows

    def _docker(self, *args: str, stdin_file: Optional[str] = None,
                timeout: int = 60) -> subprocess.CompletedProcess:
        binary = shutil.which("docker")
        if not binary:
            raise BackendError(
                "the docker backend is selected but the `docker` command isn't on "
                "PATH — install Docker, or set security.shell.backend back to 'local'.")
        stdin = open(stdin_file, "rb") if stdin_file else None
        try:
            return subprocess.run([binary, *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  stdin=stdin, timeout=timeout)
        finally:
            if stdin:
                stdin.close()

    def _container_state(self) -> str:
        """'running' | 'exists' | 'missing'."""
        proc = self._docker("inspect", "-f", "{{.State.Running}}", self.container)
        if proc.returncode != 0:
            return "missing"
        return "running" if "true" in (proc.stdout or "").lower() else "exists"

    def check(self) -> None:
        state = self._container_state()
        if state == "running":
            return
        if state == "exists":
            proc = self._docker("start", self.container)
            if proc.returncode != 0:
                raise BackendError(
                    f"couldn't start the container {self.container!r}: "
                    f"{(proc.stderr or '').strip()[:200]}")
            return
        if not self.image:
            raise BackendError(
                f"no container named {self.container!r} and no "
                f"security.shell.docker.image configured to create one from. "
                f"Either start that container yourself or set an image.")
        self._create()

    def _create(self) -> None:
        """Create the container with the hardening that makes this worth doing."""
        args = ["run", "-d", "--name", self.container,
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--pids-limit", str(self.pids_limit)]
        if self.memory:
            args += ["--memory", self.memory]
        if self.cpus:
            args += ["--cpus", self.cpus]
        if self.network:
            args += ["--network", self.network]
        if self.workspace:
            host = os.path.abspath(os.path.expanduser(self.workspace))
            args += ["-v", f"{host}:/workspace", "-w", "/workspace"]
        # Keep it alive without a service: sleep forever, exec into it per shell.
        args += [self.image, "sleep", "infinity"]
        proc = self._docker(*args, timeout=180)
        if proc.returncode != 0:
            raise BackendError(
                f"couldn't create the container from {self.image!r}: "
                f"{(proc.stderr or '').strip()[:200]}")
        logger.info("[shell] created hardened container %s from %s",
                    self.container, self.image)

    def prepare(self, driver_path: str) -> None:
        self._docker("exec", self.container, "mkdir", "-p", REMOTE_DIR)
        proc = self._docker("cp", driver_path, f"{self.container}:{REMOTE_DIR}/driver.sh")
        if proc.returncode != 0:
            raise BackendError(
                f"couldn't copy the shell driver into {self.container!r}: "
                f"{(proc.stderr or '').strip()[:200]}")
        self._prepared = True

    def argv(self, driver_path: str) -> list[str]:
        binary = shutil.which("docker") or "docker"
        workdir = "/workspace" if self.workspace else "/"
        return [binary, "exec", "-i", "-w", workdir, self.container,
                "/bin/sh", f"{REMOTE_DIR}/driver.sh"]

    def popen_kwargs(self, cwd: str) -> dict:
        # `docker exec -w` sets the working directory INSIDE the container; the
        # local cwd is irrelevant and a stale one would break the spawn.
        return {}

    def materialize(self, local_script: str) -> str:
        remote = f"{REMOTE_DIR}/{os.path.basename(local_script)}"
        proc = self._docker("cp", local_script, f"{self.container}:{remote}")
        if proc.returncode != 0:
            raise BackendError(
                f"couldn't copy the command into the container: "
                f"{(proc.stderr or '').strip()[:200]}")
        return remote

    def status(self) -> dict:
        try:
            state = self._container_state()
        except BackendError as exc:
            state = "unavailable"
            logger.debug("[shell] docker status: %s", exc)
        return {
            "backend": self.name,
            "isolation": "container",
            "container": self.container,
            "state": state,
            "image": self.image,
            "workspace": self.workspace or "(none — container filesystem only)",
            "caps": f"cap-drop ALL · no-new-privileges · pids {self.pids_limit}"
                    + (f" · mem {self.memory}" if self.memory else "")
                    + (f" · cpus {self.cpus}" if self.cpus else ""),
            "detail": "commands run inside the container; the host filesystem is "
                      "not visible except the workspace mount",
        }


class SshBackend(ShellBackend):
    """A remote host over an existing key/agent. Namma never handles passwords."""

    name = "ssh"

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        cfg = self.config or {}
        self.host = str(cfg.get("host") or "").strip()
        self.user = str(cfg.get("user") or "").strip()
        self.port = str(cfg.get("port") or "").strip()
        self.key = str(cfg.get("key") or "").strip()
        self.remote_cwd = str(cfg.get("cwd") or "").strip()

    @property
    def windows_shell(self) -> bool:
        return False

    def _target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def _ssh_args(self) -> list[str]:
        binary = shutil.which("ssh")
        if not binary:
            raise BackendError(
                "the ssh backend is selected but the `ssh` command isn't on PATH "
                "— install an OpenSSH client, or set security.shell.backend back "
                "to 'local'.")
        # BatchMode: never prompt. Namma does not handle SSH passwords — set up
        # a key or an agent, which is the only safe way to do this unattended.
        args = [binary, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
        if self.port:
            args += ["-p", self.port]
        if self.key:
            args += ["-i", os.path.expanduser(self.key)]
        return args

    def check(self) -> None:
        if not self.host:
            raise BackendError(
                "the ssh backend needs security.shell.ssh.host — nothing to connect to.")
        proc = subprocess.run(self._ssh_args() + [self._target(), "true"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
        if proc.returncode != 0:
            raise BackendError(
                f"can't reach {self._target()} over SSH: "
                f"{(proc.stderr or '').strip()[:200]} — check the host, the key, "
                f"and that key-based login works from a terminal first.")

    def _push(self, local_path: str, remote_path: str) -> None:
        with open(local_path, "rb") as fh:
            proc = subprocess.run(
                self._ssh_args() + [self._target(),
                                    f"mkdir -p {REMOTE_DIR} && cat > {remote_path}"],
                stdin=fh, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60)
        if proc.returncode != 0:
            raise BackendError(
                f"couldn't copy a script to {self._target()}: "
                f"{(proc.stderr or '').strip()[:200]}")

    def prepare(self, driver_path: str) -> None:
        self._push(driver_path, f"{REMOTE_DIR}/driver.sh")

    def argv(self, driver_path: str) -> list[str]:
        cd = f"cd {self.remote_cwd} && " if self.remote_cwd else ""
        return self._ssh_args() + ["-T", self._target(),
                                   f"{cd}sh {REMOTE_DIR}/driver.sh"]

    def popen_kwargs(self, cwd: str) -> dict:
        return {}

    def materialize(self, local_script: str) -> str:
        remote = f"{REMOTE_DIR}/{os.path.basename(local_script)}"
        self._push(local_script, remote)
        return remote

    def status(self) -> dict:
        return {
            "backend": self.name,
            "isolation": "remote-host",
            "host": self._target(),
            "cwd": self.remote_cwd or "(login directory)",
            "detail": "commands run on the remote host under its own limits — "
                      "Namma's local sandbox does NOT apply there",
        }


BACKENDS = {"local": ShellBackend, "docker": DockerBackend, "ssh": SshBackend}


def build_backend(security_cfg: Optional[dict] = None) -> ShellBackend:
    """Construct the configured backend from ``security.shell``.

    An unknown name degrades to ``local`` with a warning — a typo must not
    silently disable the shell, and it must not silently pick something
    surprising either.
    """
    shell_cfg = (security_cfg or {}).get("shell") or {}
    name = str(shell_cfg.get("backend") or "local").strip().lower()
    cls = BACKENDS.get(name)
    if cls is None:
        logger.warning("[shell] unknown backend %r — falling back to 'local'", name)
        return ShellBackend()
    return cls(shell_cfg.get(name) or {})


# -- module state (service-configured at boot, like core.sandbox) -------------

_BACKEND: ShellBackend = ShellBackend()


def configure_backend(security_cfg: Optional[dict] = None) -> ShellBackend:
    global _BACKEND
    _BACKEND = build_backend(security_cfg)
    if _BACKEND.name != "local":
        logger.info("[shell] execution backend: %s", _BACKEND.name)
    return _BACKEND


def current_backend() -> ShellBackend:
    return _BACKEND


def status() -> dict:
    """Row for the Status/Security tabs."""
    try:
        return _BACKEND.status()
    except Exception as exc:  # noqa: BLE001 — status must never raise
        return {"backend": _BACKEND.name, "isolation": "unknown", "error": str(exc)}


def new_script_name(ext: str) -> str:
    return f"cmd_{uuid.uuid4().hex[:12]}{ext}"
