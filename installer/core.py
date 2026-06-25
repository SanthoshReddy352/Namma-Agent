"""UI-free installer logic (driven by installer/app.py).

Flow, in order: ensure Python/Git/Node -> get the source onto the chosen install
dir (copy the bundled source when frozen, else git-clone) -> create a .venv ->
install requirements -> build the UI if needed -> create shortcuts -> write the
chosen provider + the onboarding answers into the app's config/DB -> done.

Everything that touches the network / filesystem is a plain function so the GUI
can run it on a worker thread and stream progress; the pure helpers below are unit
tested.

Subprocess calls are all spawned *windowless* on Windows (see ``_NO_WINDOW`` /
``_startupinfo``) so the installer never flashes a console window for git, pip,
winget or npm — the whole install runs silently under the modern UI.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

REPO = "SanthoshReddy352/Namma-Agent"
REPO_URL = f"https://github.com/{REPO}.git"
APP_DIR_NAME = "Namma-Agent"

Log = Callable[[str], None]
_PY_CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python")


def _is_windows() -> bool:
    return os.name == "nt"


# ── windowless subprocess (no flashing consoles on Windows) ──────────────────

# CREATE_NO_WINDOW keeps console children (git/pip/winget/npm) from popping a
# window when the installer itself is a windowed (no-console) process.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if _is_windows() else 0


def _startupinfo():
    """A STARTUPINFO that hides any window, on Windows; None elsewhere."""
    if not _is_windows():
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    return si


# ── locations ────────────────────────────────────────────────────────────────

def _windows_desktop() -> Optional[Path]:
    """The current user's Desktop from the registry (``Shell Folders\\Desktop``).

    Authoritative and **OneDrive-redirect-aware**, and — crucially — it reads a string
    from the registry and expands env vars only: it never `stat`s the folder. A
    OneDrive Desktop can be "online-only", where `os.path.exists`/`os.access` block for
    several seconds while the file is hydrated; doing that inside the installer's
    ``get_defaults`` (which pywebview runs on the UI thread) is exactly what made the
    Welcome window freeze / show "not responding". Reading the registry is instant."""
    if not _is_windows():
        return None
    try:
        import winreg  # Windows-only; absent elsewhere.
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as key:
            raw, _ = winreg.QueryValueEx(key, "Desktop")
        path = os.path.expandvars(raw or "")
        return Path(path) if path else None
    except Exception:  # noqa: BLE001
        return None


def _onedrive_desktop() -> Optional[Path]:
    """A OneDrive-redirected Desktop derived from ``%OneDrive%`` (string only, no
    `stat`) — a fallback for the rare case the registry lookup fails."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base:
            return Path(base) / "Desktop"
    return None


def desktop_dir() -> Optional[Path]:
    """The user's Desktop, or ``None``. Resolved **without any filesystem probing** so
    the installer's Welcome screen fills the default path instantly (no freeze): Windows
    reads the registry (handles OneDrive redirection); elsewhere it uses ``~/Desktop``
    when that local folder exists (a `stat` on a local fs is cheap)."""
    if _is_windows():
        return _windows_desktop() or _onedrive_desktop()
    d = Path.home() / "Desktop"
    return d if d.is_dir() else None


def _fallback_install_root() -> Path:
    """A per-user, always-writable base to install under when there's no usable
    Desktop: ``%LOCALAPPDATA%`` on Windows (exists, writable, no admin, not
    redirected), the home directory elsewhere."""
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base)
    return Path.home()


def default_install_dir() -> Path:
    """Where the app lands by default: ``<Desktop>/Namma-Agent``, else a per-user
    writable location (``%LOCALAPPDATA%/Namma-Agent`` on Windows). Computed with **no**
    ``os.access``/``is_dir`` on the (possibly online-only OneDrive) Desktop, so it's
    instant and never freezes the UI; install-time writability is handled by
    :func:`_prepare_install_dir`. The user can override it in the UI."""
    return (desktop_dir() or _fallback_install_root()) / APP_DIR_NAME


def resolve_install_dir(chosen: Optional[str | os.PathLike]) -> Path:
    """Normalise a user-chosen install location.

    The folder picker returns the *parent* a user navigated to (e.g. they pick
    ``C:/Apps``); if they didn't already pick a folder literally named
    ``Namma-Agent`` we append it, so the app never spills its tree loose into a
    directory the user expected to keep tidy — and we never double-nest
    ``Namma-Agent/Namma-Agent``.
    """
    if not chosen:
        return default_install_dir()
    p = Path(chosen).expanduser()
    if p.name == APP_DIR_NAME:
        return p
    return p / APP_DIR_NAME


def venv_python(install_dir: Path) -> Path:
    if _is_windows():
        return install_dir / ".venv" / "Scripts" / "python.exe"
    return install_dir / ".venv" / "bin" / "python"


def venv_pythonw(install_dir: Path) -> Path:
    """Windows pythonw.exe (no console) for launching the app; falls back to python."""
    pyw = install_dir / ".venv" / "Scripts" / "pythonw.exe"
    return pyw if pyw.exists() else venv_python(install_dir)


def bundled_source() -> Optional[Path]:
    """When frozen by PyInstaller, the app source is bundled at <_MEIPASS>/app."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "app"
        if (p / "namma_agent").is_dir():
            return p
    return None


# ── dependency detection ─────────────────────────────────────────────────────

# Optional runtime tools Hermes also installs — they make some skills/tools richer
# (ripgrep = fast code search, ffmpeg = audio/video) but the app degrades gracefully
# without them, so a failed/absent install is never fatal.
OPTIONAL_TOOLS = ("ripgrep", "ffmpeg")

# A tool's name on disk differs from the package name for ripgrep (binary is ``rg``).
_TOOL_COMMAND = {"ripgrep": "rg"}


def _tool_command(tool: str) -> str:
    """The executable name to probe on PATH for ``tool`` (e.g. ripgrep → rg)."""
    return _TOOL_COMMAND.get(tool, tool)


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _is_py310(exe: str) -> bool:
    try:
        out = subprocess.run([exe, "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=_NO_WINDOW, startupinfo=_startupinfo())
        major, minor = out.stdout.split()[:2]
        return (int(major), int(minor)) >= (3, 10)
    except Exception:  # noqa: BLE001
        return False


def find_python() -> Optional[str]:
    """Path to a Python 3.10+ on PATH the app's venv can be built from."""
    for c in _PY_CANDIDATES:
        exe = shutil.which(c)
        if exe and _is_py310(exe):
            return exe
    return None


def dependency_status() -> dict:
    """{'python': bool, 'git': bool, 'node': bool} — what's already installed."""
    return {"python": find_python() is not None, "git": _has("git"), "node": _has("npm")}


def install_dep_command(tool: str, system: Optional[str] = None) -> Optional[list[str]]:
    """The OS-appropriate command to install a missing tool, or None if unknown.
    Pure (no execution) so it's testable. ``tool`` in {python, git, node}."""
    system = system or platform.system()
    if system == "Windows":
        ids = {"python": "Python.Python.3.12", "git": "Git.Git", "node": "OpenJS.NodeJS.LTS",
               "ripgrep": "BurntSushi.ripgrep.MSVC", "ffmpeg": "Gyan.FFmpeg"}
        if tool not in ids:
            return None
        return ["winget", "install", "-e", "--id", ids[tool], "--silent",
                "--accept-source-agreements", "--accept-package-agreements"]
    if system == "Darwin":
        pkg = {"python": "python", "git": "git", "node": "node",
               "ripgrep": "ripgrep", "ffmpeg": "ffmpeg"}.get(tool)
        return ["brew", "install", pkg] if pkg else None
    # Linux: choose by available package manager.
    matrix = {
        "apt-get": (["sudo", "apt-get", "install", "-y"],
                    {"python": ["python3", "python3-venv", "python3-pip"], "git": ["git"], "node": ["nodejs", "npm"],
                     "ripgrep": ["ripgrep"], "ffmpeg": ["ffmpeg"]}),
        "dnf": (["sudo", "dnf", "install", "-y"],
                {"python": ["python3", "python3-pip"], "git": ["git"], "node": ["nodejs", "npm"],
                 "ripgrep": ["ripgrep"], "ffmpeg": ["ffmpeg"]}),
        "pacman": (["sudo", "pacman", "-Sy", "--noconfirm"],
                   {"python": ["python"], "git": ["git"], "node": ["nodejs", "npm"],
                    "ripgrep": ["ripgrep"], "ffmpeg": ["ffmpeg"]}),
        "zypper": (["sudo", "zypper", "install", "-y"],
                   {"python": ["python3", "python3-venv"], "git": ["git"], "node": ["nodejs", "npm"],
                    "ripgrep": ["ripgrep"], "ffmpeg": ["ffmpeg"]}),
    }
    for pm, (prefix, names) in matrix.items():
        if _has(pm) and tool in names:
            return prefix + names[tool]
    return None


# ── progress reporting ───────────────────────────────────────────────────────

# The named, ordered steps the install runs through. The UI renders this list up
# front (all "pending") and lights each one up as bootstrap drives it — exactly
# the stepper look the design calls for.
INSTALL_STEPS: list[tuple[str, str]] = [
    ("python", "Verifying Python 3.10+"),
    ("tools", "Checking Git, Node.js & tools"),
    ("source", "Getting the app files"),
    ("venv", "Creating the Python environment"),
    ("deps", "Installing Python dependencies"),
    ("ui", "Building the interface"),
    ("shortcuts", "Creating shortcuts"),
    ("path", "Adding the namma command to PATH"),
]


@dataclass
class _Step:
    key: str
    label: str
    status: str = "pending"  # pending | active | done | error


class StepReporter:
    """Drives the ordered install steps + free-text log lines for the GUI.

    ``on_update(steps)`` gets the full step list (list of dicts) on every state
    change so the UI can re-render the stepper; ``on_log(line)`` gets each command
    output line for the collapsible "Show details" drawer.
    """

    def __init__(self, steps: list[tuple[str, str]],
                 on_update: Optional[Callable[[list[dict]], None]] = None,
                 on_log: Optional[Log] = None):
        self.steps = [_Step(k, l) for k, l in steps]
        self._by_key = {s.key: s for s in self.steps}
        self._on_update = on_update or (lambda _steps: None)
        self._on_log = on_log or (lambda _line: None)
        self.emit()

    def snapshot(self) -> list[dict]:
        return [{"key": s.key, "label": s.label, "status": s.status} for s in self.steps]

    def emit(self) -> None:
        with suppress(Exception):
            self._on_update(self.snapshot())

    def log(self, line: str) -> None:
        with suppress(Exception):
            self._on_log(line)

    @contextmanager
    def step(self, key: str) -> Iterator[Log]:
        s = self._by_key[key]
        s.status = "active"
        self.emit()
        try:
            yield self.log
        except BaseException:
            s.status = "error"
            self.emit()
            raise
        else:
            s.status = "done"
            self.emit()

    def skip(self, key: str) -> None:
        """Mark a step done without running it (e.g. the UI is already built)."""
        self._by_key[key].status = "done"
        self.emit()


def _as_reporter(x: "StepReporter | Log") -> StepReporter:
    """Accept either a StepReporter (GUI) or a plain log callable (``--cli`` / tests)."""
    if isinstance(x, StepReporter):
        return x
    return StepReporter(INSTALL_STEPS, on_log=x)


# ── steps ────────────────────────────────────────────────────────────────────

def _run(cmd, cwd=None, log: Optional[Log] = None, check: bool = True) -> int:
    """Run a command, capturing its output and streaming a trimmed tail to the
    installer log. On failure (when ``check``) raise with the real error tail — so
    the GUI shows WHY it failed instead of an opaque exit code. Windowless on
    Windows so no console flashes."""
    shown = " ".join(str(c) for c in cmd[:4])
    if log:
        log(f"  $ {shown} …")
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd and str(cwd),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=_NO_WINDOW, startupinfo=_startupinfo())
    combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if log and combined:
        for line in combined.splitlines()[-12:]:
            log(f"    {line}")
    if check and proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-12:])
        raise RuntimeError(f"`{shown}` failed (exit {proc.returncode}):\n{tail}")
    return proc.returncode


def ensure_dependencies(log: Log) -> None:
    status = dependency_status()
    for tool in ("git", "node", "python"):
        if status.get(tool):
            continue
        cmd = install_dep_command(tool)
        if not cmd:
            log(f"  ! {tool} missing and no installer available — please install it manually.")
            continue
        log(f"  Installing {tool} ({' '.join(cmd[:3])} …)")
        _run(cmd, log=log, check=False)
    if find_python() is None:
        raise RuntimeError("Python 3.10+ is required but could not be installed automatically.")


def ensure_optional_tools(log: Log) -> None:
    """Best-effort install of ripgrep + ffmpeg (Hermes parity). These enrich some
    skills/tools but the app degrades gracefully without them, so nothing here is
    fatal — a missing package manager or a failed install is just logged."""
    for tool in OPTIONAL_TOOLS:
        if _has(_tool_command(tool)):
            continue
        cmd = install_dep_command(tool)
        if not cmd:
            log(f"  ! {tool} not found and no installer available — skipping (optional).")
            continue
        log(f"  Installing {tool} ({' '.join(cmd[:3])} …)")
        with suppress(Exception):
            _run(cmd, log=log, check=False)


def _prepare_install_dir(install_dir: Path) -> None:
    """Create the install folder (and parents), turning a raw OS 'Access is denied'
    (WinError 5 — e.g. the chosen path is under a protected/non-existent profile root)
    into a clear, actionable message instead of an opaque traceback."""
    try:
        install_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as exc:
        raise RuntimeError(
            f"Can't write to {install_dir} (access denied). Pick a different install "
            f"folder you own — for example your Documents folder — using “Browse…”, "
            f"then try again."
        ) from exc


def fetch_source(install_dir: Path, log: Log) -> None:
    src = bundled_source()
    if src:
        log(f"  Copying app files to {install_dir} …")
        _prepare_install_dir(install_dir)
        # Copy the *contents* of the bundle into install_dir (not a nested child) —
        # guards against the Namma-Agent/Namma-Agent double-nesting.
        shutil.copytree(src, install_dir, dirs_exist_ok=True)
    elif (install_dir / ".git").is_dir():
        log("  Updating existing copy (git pull) …")
        _run(["git", "pull", "--ff-only"], cwd=install_dir, log=log, check=False)
    else:
        log(f"  Cloning {REPO_URL} to {install_dir} …")
        _prepare_install_dir(install_dir.parent)
        _run(["git", "clone", "--depth", "1", REPO_URL, str(install_dir)], log=log)


def create_venv(install_dir: Path, log: Log) -> None:
    py = find_python()
    if not py:
        raise RuntimeError("No suitable Python found for the virtual environment.")
    if not venv_python(install_dir).exists():
        log("  Creating the Python environment (.venv) …")
        _run([py, "-m", "venv", str(install_dir / ".venv")], log=log)


def install_requirements(install_dir: Path, log: Log) -> None:
    vpy = str(venv_python(install_dir))
    log("  Installing dependencies (a few minutes) …")
    # --no-cache-dir: a fresh install never benefits from the cache, and it sidesteps
    # "Cache entry deserialization failed" errors from a corrupted pip cache.
    _run([vpy, "-m", "pip", "install", "--upgrade", "pip", "--no-cache-dir"], log=log, check=False)
    _run([vpy, "-m", "pip", "install", "--no-cache-dir", "-r",
          str(install_dir / "namma_agent" / "requirements.txt")], log=log)


def _npm(args: list[str], cwd: str, log: Optional[Log] = None) -> None:
    # npm is npm.cmd on Windows — launch via cmd.exe so subprocess can find it.
    cmd = (["cmd", "/c", "npm", *args] if os.name == "nt" else ["npm", *args])
    _run(cmd, cwd=cwd, log=log, check=False)


def build_ui(install_dir: Path, log: Log) -> bool:
    """Build the app's web UI if it isn't already bundled. Returns True if a build
    ran, False if it was already present / npm is missing (so the caller can mark
    the step skipped)."""
    if (install_dir / "namma_agent" / "webui" / "dist" / "index.html").exists():
        return False
    if _has("npm"):
        log("  Building the web UI …")
        webui = str(install_dir / "namma_agent" / "webui")
        _npm(["install"], webui, log)
        _npm(["run", "build"], webui, log)
        return True
    log("  ! npm not found — the app will build its UI on first run.")
    return False


def _clean_env() -> dict:
    """Environment for spawning the app's venv Python from the (PyInstaller-frozen)
    installer. PyInstaller prepends its onefile temp dir (``sys._MEIPASS``) to PATH
    and may export PYTHON*/_PYI* vars — a spawned interpreter could then load the
    WRONG DLLs/modules and misbehave. Strip those so the venv Python is pristine."""
    env = dict(os.environ)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        norm = os.path.normcase(os.path.abspath(meipass))
        parts = env.get("PATH", "").split(os.pathsep)
        env["PATH"] = os.pathsep.join(
            p for p in parts if p and os.path.normcase(os.path.abspath(p)) != norm)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
              "_PYI_ARCHIVE_FILE", "_PYI_APPLICATION_HOME_DIR", "_MEIPASS2"):
        env.pop(k, None)
    return env


def _run_app_cli(install_dir: Path, args: list[str]) -> None:
    """Run the installed app's CLI (``--configure`` / ``--onboard``) and FAIL LOUDLY
    if it errors — the result is logged to <install>/logs/installer-actions.log and a
    non-zero exit raises, so a bad provider/onboarding write can't pass silently."""
    install_dir = Path(install_dir)
    proc = subprocess.run(
        [str(venv_python(install_dir)), "-m", "namma_agent", *args],
        cwd=str(install_dir), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=_clean_env(),
        creationflags=_NO_WINDOW, startupinfo=_startupinfo(),
    )
    with suppress(Exception):
        logs = install_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "installer-actions.log").open("a", encoding="utf-8") as f:
            f.write(f"$ namma_agent {' '.join(args[:1])} (exit {proc.returncode})\n")
            if proc.stdout:
                f.write(proc.stdout.strip() + "\n")
            if proc.stderr:
                f.write(proc.stderr.strip() + "\n")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-8:])
        raise RuntimeError(f"`namma_agent {args[0]}` failed (exit {proc.returncode}):\n{tail}")


def write_provider(install_dir: Path, provider: dict) -> None:
    """provider = {type, model?, api_key?, base_url?} -> config.local.yaml + .env."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(provider, f)
        path = f.name
    try:
        _run_app_cli(install_dir, ["--configure", path])
    finally:
        os.unlink(path)


def write_onboarding(install_dir: Path, answers: dict) -> None:
    """answers = {name, date_of_birth, occupation, ...} -> saved into the app DB."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(answers, f)
        path = f.name
    try:
        _run_app_cli(install_dir, ["--onboard", path])
    finally:
        os.unlink(path)


# ── shortcuts (Desktop + app menu) ───────────────────────────────────────────

def windows_shortcut_ps1(install_dir: Path) -> str:
    """PowerShell that creates 'Namma Agent.lnk' on the Desktop and in the Start
    Menu, launching the app with pythonw (no console). Pure → unit tested."""
    pyw = venv_pythonw(install_dir)
    icon = install_dir / "namma_agent" / "assets" / "sparkle.ico"
    root = str(install_dir)
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        "$W=New-Object -ComObject WScript.Shell;"
        "$dirs=@([Environment]::GetFolderPath('Desktop'),"
        "(Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'));"
        "foreach($d in $dirs){"
        "$l=$W.CreateShortcut((Join-Path $d 'Namma Agent.lnk'));"
        f"$l.TargetPath='{pyw}';"
        "$l.Arguments='-m namma_agent';"
        f"$l.WorkingDirectory='{root}';"
        f"if(Test-Path '{icon}'){{$l.IconLocation='{icon}'}};"
        "$l.Description='Namma Agent - Intelligence for Everyone';"
        "$l.Save()}"
    )


def macos_launcher_body(install_dir: Path) -> str:
    """Contents of the 'Namma Agent.command' double-click launcher. Pure."""
    vpy = venv_python(install_dir)
    return f'#!/usr/bin/env bash\ncd "{install_dir}"\nexec "{vpy}" -m namma_agent\n'


def linux_desktop_entry(install_dir: Path) -> str:
    """A .desktop launcher body for the app menu. Pure."""
    vpy = venv_python(install_dir)
    icon = install_dir / "namma_agent" / "assets" / "sparkle.png"
    return (
        "[Desktop Entry]\nType=Application\nName=Namma Agent\n"
        "Comment=Intelligence for Everyone\n"
        f"Exec={vpy} -m namma_agent\nIcon={icon}\n"
        "Terminal=false\nCategories=Utility;Development;\n"
    )


def _installed_version(install_dir: Path) -> str:
    """Read __version__ from the installed app, or '' if unavailable."""
    import re
    vf = Path(install_dir) / "namma_agent" / "version.py"
    if vf.exists():
        m = re.search(r'__version__\s*=\s*"([^"]+)"', vf.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return ""


def windows_uninstall_registry_ps1(install_dir: Path, version: str = "") -> str:
    """PowerShell that registers Namma Agent in Add/Remove Programs (HKCU Uninstall),
    so it shows up in Settings → Apps with a working Uninstall button. Pure → tested."""
    root = str(install_dir).replace("'", "''")
    icon = str(Path(install_dir) / "namma_agent" / "assets" / "sparkle.ico").replace("'", "''")
    script = str(Path(install_dir) / "installers" / "uninstall.ps1").replace("'", "''")
    uninstall_cmd = (f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                     f'-File "{script}" -InstallDir "{root}" -Scope all')
    return (
        "$k='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\NammaAgent';"
        "New-Item -Path $k -Force | Out-Null;"
        "Set-ItemProperty -Path $k -Name DisplayName -Value 'Namma Agent';"
        f"Set-ItemProperty -Path $k -Name DisplayIcon -Value '{icon}';"
        f"Set-ItemProperty -Path $k -Name DisplayVersion -Value '{version}';"
        "Set-ItemProperty -Path $k -Name Publisher -Value 'Namma Agent';"
        f"Set-ItemProperty -Path $k -Name InstallLocation -Value '{root}';"
        f"Set-ItemProperty -Path $k -Name UninstallString -Value '{uninstall_cmd}';"
        f"Set-ItemProperty -Path $k -Name QuietUninstallString -Value '{uninstall_cmd}';"
        "Set-ItemProperty -Path $k -Name NoModify -Type DWord -Value 1;"
        "Set-ItemProperty -Path $k -Name NoRepair -Type DWord -Value 1;"
    )


def register_windows_app(install_dir: Path, log: Optional[Log] = None) -> None:
    """Register the app in Windows Add/Remove Programs (best-effort, Windows only)."""
    if os.name != "nt":
        return
    log = log or (lambda _m: None)
    with suppress(Exception):
        _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
              "-Command", windows_uninstall_registry_ps1(install_dir, _installed_version(install_dir))],
             log=log, check=False)
        log("  Registered 'Namma Agent' in Add/Remove Programs.")


def create_shortcuts(install_dir: Path, log: Optional[Log] = None) -> None:
    """Create Desktop + app-menu shortcuts for the installed app (best-effort), and on
    Windows register an Add/Remove-Programs entry with a working uninstaller."""
    log = log or (lambda _m: None)
    install_dir = Path(install_dir)
    system = platform.system()
    try:
        if system == "Windows":
            _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                  "-WindowStyle", "Hidden", "-Command", windows_shortcut_ps1(install_dir)],
                 log=log, check=False)
            log("  Shortcut 'Namma Agent' added to Desktop + Start Menu.")
            register_windows_app(install_dir, log)
        elif system == "Darwin":
            launcher = install_dir / "Namma Agent.command"
            launcher.write_text(macos_launcher_body(install_dir), encoding="utf-8")
            os.chmod(launcher, 0o755)
            log(f"  Launcher created: {launcher}")
        else:  # Linux
            apps = Path.home() / ".local" / "share" / "applications"
            apps.mkdir(parents=True, exist_ok=True)
            entry = apps / "namma-agent.desktop"
            entry.write_text(linux_desktop_entry(install_dir), encoding="utf-8")
            with suppress(Exception):
                os.chmod(entry, 0o755)
            log("  Added 'Namma Agent' to your applications menu.")
    except Exception as exc:  # noqa: BLE001 — shortcuts are best-effort
        log(f"  (could not create shortcuts: {exc})")


# ── add the `namma` command to PATH ──────────────────────────────────────────

def windows_namma_cmd(install_dir: Path) -> str:
    """Body of ``<install>/bin/namma.cmd`` — the on-PATH launcher. Bare ``namma``
    opens the GUI detached (pythonw, no lingering console); ``namma --chat`` /
    ``--server`` / any args run in the console so their output is visible. Pure → tested."""
    pyw = venv_pythonw(install_dir)
    py = venv_python(install_dir)
    return (
        "@echo off\r\n"
        'if "%~1"=="" (\r\n'
        f'  start "" "{pyw}" -m namma_agent\r\n'
        ") else (\r\n"
        f'  "{py}" -m namma_agent %*\r\n'
        ")\r\n"
    )


def windows_path_append_ps1(bin_dir: Path) -> str:
    """PowerShell that idempotently appends ``bin_dir`` to the *user* PATH (persists
    across sessions, no admin needed) and to this process's PATH. Pure → tested."""
    b = str(bin_dir).replace("'", "''")
    return (
        f"$b='{b}';"
        "$p=[Environment]::GetEnvironmentVariable('Path','User');"
        "if(-not $p){$p=''};"
        "if(($p -split ';') -notcontains $b){"
        "[Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $b).TrimStart(';'), 'User')};"
    )


def posix_namma_script(install_dir: Path) -> str:
    """Body of the ``namma`` launcher dropped into ``~/.local/bin``. Pure → tested."""
    vpy = venv_python(install_dir)
    return f'#!/usr/bin/env bash\nexec "{vpy}" -m namma_agent "$@"\n'


def add_to_path(install_dir: Path, log: Optional[Log] = None) -> None:
    """Install a ``namma`` command on PATH so the app can be launched/scripted from a
    terminal (``namma``, ``namma --chat``, ``namma --server``). Best-effort: a failure
    here never breaks the install — shortcuts already cover the GUI launch."""
    log = log or (lambda _m: None)
    install_dir = Path(install_dir)
    try:
        if os.name == "nt":
            bin_dir = install_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "namma.cmd").write_text(windows_namma_cmd(install_dir), encoding="utf-8")
            _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                  "-Command", windows_path_append_ps1(bin_dir)], log=log, check=False)
            log("  Added the `namma` command to your PATH (open a new terminal to use it).")
        else:
            bin_dir = Path.home() / ".local" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            launcher = bin_dir / "namma"
            launcher.write_text(posix_namma_script(install_dir), encoding="utf-8")
            os.chmod(launcher, 0o755)
            on_path = bin_dir.is_dir() and str(bin_dir) in os.environ.get("PATH", "").split(os.pathsep)
            log(f"  Installed the `namma` command at {launcher}."
                + ("" if on_path else f"  (add {bin_dir} to your PATH to use it.)"))
    except Exception as exc:  # noqa: BLE001 — PATH wiring is best-effort
        log(f"  (could not add the `namma` command to PATH: {exc})")


# ── launch / verify ──────────────────────────────────────────────────────────

def launch(install_dir: Path) -> None:
    """Open the installed app, detached and windowless, then return."""
    install_dir = Path(install_dir)
    if _is_windows():
        exe = str(venv_pythonw(install_dir))
        subprocess.Popen([exe, "-m", "namma_agent"], cwd=str(install_dir), close_fds=True,
                         env=_clean_env(), creationflags=_NO_WINDOW, startupinfo=_startupinfo())
    else:
        subprocess.Popen([str(venv_python(install_dir)), "-m", "namma_agent"],
                         cwd=str(install_dir), start_new_session=True, close_fds=True,
                         env=_clean_env())


def verify_launch(install_dir: Path, timeout: float = 60.0, port: int = 8000) -> bool:
    """Boot the app headless (``--server``) and poll ``/api/health`` so the Done
    screen can confirm the backend really starts (catching the '127.0.0.1 refused'
    failure *before* the user hits Launch). Returns True if it became reachable."""
    install_dir = Path(install_dir)
    proc = subprocess.Popen(
        [str(venv_python(install_dir)), "-m", "namma_agent", "--server"],
        cwd=str(install_dir), creationflags=_NO_WINDOW, startupinfo=_startupinfo(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**_clean_env(), "PORT": str(port)},
    )
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:  # server process exited → it crashed
                return False
            with suppress(Exception):
                urllib.request.urlopen(url, timeout=1)
                return True
            time.sleep(0.4)
        return False
    finally:
        with suppress(Exception):
            proc.terminate()


# ── orchestration ────────────────────────────────────────────────────────────

def bootstrap(install_dir: Path, reporter: "StepReporter | Log") -> Path:
    """The heavy half (deps -> source -> venv -> requirements -> UI -> shortcuts).
    Provider + onboarding are written afterwards from the GUI forms.

    ``reporter`` may be a :class:`StepReporter` (modern GUI) or a plain log
    callable (``--cli`` / tests)."""
    install_dir = Path(install_dir)
    rep = _as_reporter(reporter)

    with rep.step("python") as log:
        log("Checking Python …")
        if find_python() is None:
            ensure_dependencies(log)
        if find_python() is None:
            raise RuntimeError("Python 3.10+ is required but could not be installed automatically.")

    with rep.step("tools") as log:
        log("Checking Git and Node.js …")
        ensure_dependencies(log)
        log("Checking optional tools (ripgrep, ffmpeg) …")
        ensure_optional_tools(log)

    with rep.step("source") as log:
        fetch_source(install_dir, log)

    with rep.step("venv") as log:
        create_venv(install_dir, log)

    with rep.step("deps") as log:
        install_requirements(install_dir, log)

    built = False
    with rep.step("ui") as log:
        built = build_ui(install_dir, log)
    if not built:
        rep.skip("ui")

    with rep.step("shortcuts") as log:
        create_shortcuts(install_dir, log)

    with rep.step("path") as log:
        add_to_path(install_dir, log)

    rep.log("Base install complete.")
    return install_dir
