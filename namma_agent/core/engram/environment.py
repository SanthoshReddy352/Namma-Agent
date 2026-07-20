"""L5 environment memory — a persistent model of the machine Namma runs on.

The agent used to *guess* host paths (POSIX paths on Windows, invented drive
letters, wrong home directories). This module probes the real host — OS, user,
home, temp, drives, key folders, shell, working directory — caches it as JSON
(``data/memory/ENVIRONMENT.json``), and renders a compact HOST block injected
into every system prompt so paths are never invented.

``resolve_path`` is the tool-side assist: it expands ``~``/env vars, maps spoken
folder names ("desktop", "downloads"), normalizes separators for this OS, and
rejects paths on drives that don't exist — with the real layout quoted in the
error so a wrong guess *teaches* the model the actual filesystem.

``find_binary`` is the tool-discovery assist: the agent used to declare a program
"not installed" after one PATH miss, even when it sat in an obvious install
directory (``C:\\Program Files\\Tesseract-OCR\\tesseract.exe``). The probe scans
PATH **and** the well-known install roots for a curated set of CLI tools, the
results ride in the HOST prompt block, and any tool can call ``find_binary`` to
get the real executable path instead of assuming absence.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import string
import subprocess
import time
from pathlib import Path
from typing import Optional

from namma_agent.core.logger import logger

_CACHE_MAX_AGE_S = 24 * 3600
#: Folder names users say out loud, resolved against home if they exist.
_KEY_FOLDERS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")

#: CLI programs Namma's tools (or the user's tasks) commonly need. Each is looked
#: up on PATH first, then in the well-known install roots below — so a tool that
#: is installed but not on PATH is still FOUND, not declared missing.
_KNOWN_TOOLS = (
    "tesseract", "ffmpeg", "ffprobe", "pandoc", "magick", "git", "docker",
    "node", "npm", "python", "java", "7z", "rg", "curl", "wget", "ollama",
    "adb", "mmdc", "code", "gs",
)


def _install_roots() -> list[Path]:
    """Directories where Windows/POSIX software commonly lands without touching
    PATH. Only existing roots are returned."""
    roots: list[Path] = []
    home = Path.home()
    if platform.system() == "Windows":
        for env_var, sub in (("ProgramFiles", ""), ("ProgramFiles(x86)", ""),
                             ("LOCALAPPDATA", "Programs"), ("ProgramData", "chocolatey\\bin")):
            base = os.environ.get(env_var)
            if base:
                roots.append(Path(base) / sub if sub else Path(base))
        roots += [home / "scoop" / "shims", Path("C:\\Tools")]
    else:
        roots += [Path("/usr/local/bin"), Path("/opt"), home / ".local" / "bin",
                  home / "bin"]
    return [r for r in roots if r.is_dir()]


def _scan_root(root: Path, exe: str) -> Optional[str]:
    """Look for ``exe`` directly in ``root``, one level of subdirectories, and
    their ``bin/`` folders (covers ``Tesseract-OCR\\tesseract.exe``,
    ``ffmpeg-7.0\\bin\\ffmpeg.exe``, JDK layouts…). Shallow on purpose — never a
    full recursive walk."""
    direct = root / exe
    if direct.is_file():
        return str(direct)
    try:
        subdirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return None
    for sub in subdirs:
        for candidate in (sub / exe, sub / "bin" / exe):
            if candidate.is_file():
                return str(candidate)
    return None


def discover_tools(names: tuple = _KNOWN_TOOLS) -> dict:
    """``{tool: path}`` for every curated tool found on this machine. PATH wins;
    otherwise the install roots are scanned shallowly."""
    exts = (".exe", ".cmd", ".bat") if platform.system() == "Windows" else ("",)
    roots = _install_roots()
    found: dict[str, str] = {}
    for name in names:
        hit = shutil.which(name)
        if hit:
            found[name] = hit
            continue
        for root in roots:
            for ext in exts:
                hit = _scan_root(root, name + ext) if ext else _scan_root(root, name)
                if hit:
                    break
            if hit:
                found[name] = hit
                break
    return found


def find_binary(name: str, env: Optional[dict] = None) -> Optional[str]:
    """The executable path for ``name`` on THIS machine, or None.

    Tools should call this instead of a bare ``shutil.which`` so a program that
    is installed but not on PATH (the classic Tesseract case) is still used.
    ``env`` may be a cached environment dict (its ``tools`` map is checked first).
    """
    name = (name or "").strip()
    if not name:
        return None
    cached = ((env or {}).get("tools") or {}).get(name)
    if cached and Path(cached).is_file():
        return cached
    hit = shutil.which(name)
    if hit:
        return hit
    return discover_tools((name,)).get(name)


def detect_wsl(_run=None) -> Optional[dict]:
    """WSL distros on this Windows host: ``{"distros": [...], "default": name}``.

    Phase 5 (Engram G8): the agent should know WSL exists so it can translate
    ``/mnt/c/...`` ↔ ``C:\\...`` instead of treating a WSL path as an invented
    POSIX guess. Returns None off Windows, when ``wsl.exe`` is absent, or when
    no distro is registered. ``wsl.exe`` prints UTF-16-LE — decoded with a
    UTF-8 fallback for builds that don't.
    """
    if platform.system() != "Windows" or not shutil.which("wsl"):
        return None
    run = _run or (lambda: subprocess.run(
        ["wsl.exe", "-l", "-v"], capture_output=True, timeout=8,
        creationflags=0x08000000))  # CREATE_NO_WINDOW
    try:
        out = run()
        raw = out.stdout or b""
    except Exception:  # noqa: BLE001 — WSL present but broken: no model, no crash
        return None
    text = raw.decode("utf-16-le", errors="ignore")
    if sum(c.isalpha() for c in text) < 4:  # wasn't UTF-16 after all
        text = raw.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "").replace("\ufeff", "")
    distros: list[str] = []
    default: Optional[str] = None
    for line in text.splitlines()[1:]:  # first line is the NAME/STATE header
        line = line.strip()
        if not line:
            continue
        is_default = line.startswith("*")
        fields = line.lstrip("*").split()
        if not fields:
            continue
        name = fields[0]
        distros.append(name)
        if is_default:
            default = name
    if not distros:
        return None
    return {"distros": distros, "default": default or distros[0]}


def probe(apps_count: Optional[int] = None) -> dict:
    """Collect the host model. Cheap and cross-platform (the only subprocess is
    a short ``wsl.exe -l`` probe on Windows hosts that have WSL installed)."""
    home = Path.home()
    system = platform.system()
    env: dict = {
        "generated_at": time.time(),
        "os": f"{system} {platform.release()}",
        "platform": os.name,
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "home": str(home),
        "cwd": os.getcwd(),
        "temp": os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp",
        "sep": os.sep,
        "shell": ("PowerShell" if system == "Windows"
                  else os.path.basename(os.environ.get("SHELL", "sh"))),
        "path_style": ("backslash with drive letters (C:\\...)"
                       if system == "Windows" else "forward-slash POSIX"),
    }
    drives = []
    if system == "Windows":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if not os.path.exists(root):
                continue
            try:
                usage = shutil.disk_usage(root)
                drives.append({"root": root, "free_gb": round(usage.free / 1e9)})
            except OSError:
                drives.append({"root": root, "free_gb": None})
    else:
        try:
            usage = shutil.disk_usage("/")
            drives.append({"root": "/", "free_gb": round(usage.free / 1e9)})
        except OSError:
            pass
    env["drives"] = drives
    if system == "Windows":
        wsl = detect_wsl()
        if wsl:
            env["wsl"] = wsl
    env["folders"] = {name: str(home / name) for name in _KEY_FOLDERS
                      if (home / name).is_dir()}
    env["tools"] = discover_tools()
    if apps_count:
        env["apps_indexed"] = int(apps_count)
    return env


#: Process-wide default instance so stateless tool modules (tools/*.py register
#: with no service handle) can reach the SAME host model the prompt block uses.
#: The Engram facade registers its instance at construction; bare test setups
#: fall back to a lazily-created probe.
_default: Optional["EnvironmentMemory"] = None


def set_default(env: "EnvironmentMemory") -> None:
    global _default
    _default = env


def default() -> "EnvironmentMemory":
    global _default
    if _default is None:
        _default = EnvironmentMemory()
    return _default


def resolve_path(text: str) -> tuple[str, Optional[str]]:
    """Module-level path assist for tools (design §5 L5): every file-handling
    tool runs the model-written path through this BEFORE touching the disk, so a
    wrong guess (POSIX path on Windows, invented drive) is corrected — or comes
    back as an error that quotes the real layout. Never raises: an assist that
    breaks a tool would be worse than no assist."""
    try:
        return default().resolve_path(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[engram] resolve_path assist failed: %s", exc)
        return text, None


class EnvironmentMemory:
    def __init__(self, data_dir: Optional[Path] = None,
                 apps_count_getter=None):
        self._path = (Path(data_dir) / "ENVIRONMENT.json") if data_dir else None
        self._apps_count_getter = apps_count_getter
        self._env: Optional[dict] = None

    def get(self, refresh: bool = False) -> dict:
        """The cached host model, re-probed when stale/missing/forced."""
        if self._env is not None and not refresh:
            return self._env
        env = None
        if not refresh and self._path is not None and self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if time.time() - float(data.get("generated_at", 0)) < _CACHE_MAX_AGE_S:
                    env = data
            except (OSError, ValueError):
                env = None
        if env is None:
            apps = None
            try:
                apps = self._apps_count_getter() if self._apps_count_getter else None
            except Exception:  # noqa: BLE001
                apps = None
            env = probe(apps_count=apps)
            if self._path is not None:
                try:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    self._path.write_text(json.dumps(env, indent=2), encoding="utf-8")
                except OSError as exc:
                    logger.warning("[engram] environment cache write failed: %s", exc)
        self._env = env
        return env

    def render(self) -> str:
        """Compact HOST block for the system prompt."""
        e = self.get()
        drives = " · ".join(
            d["root"] + (f" ({d['free_gb']} GB free)" if d.get("free_gb") is not None else "")
            for d in e.get("drives", [])) or "?"
        folders = " · ".join(f"{k}={v}" for k, v in (e.get("folders") or {}).items())
        lines = [
            "HOST — the real machine you are running on. Use ONLY these paths; "
            "never invent paths for another operating system.",
            f"OS: {e['os']} · user: {e['user']} · home: {e['home']}",
            f"Path style: {e['path_style']}. Shell: {e['shell']}. Temp: {e['temp']}",
            f"Drives: {drives}",
        ]
        wsl = e.get("wsl")
        if wsl:
            names = " · ".join(
                n + (" (default)" if n == wsl.get("default") else "")
                for n in wsl.get("distros", []))
            lines.append(
                f"WSL distros: {names}. Inside WSL, Windows drives are mounted at "
                "/mnt/<drive> (C:\\Users ↔ /mnt/c/Users); from Windows, WSL files "
                "live at \\\\wsl$\\<distro>\\. Use `wsl -d <distro> <cmd>` to run "
                "Linux commands.")
        if folders:
            lines.append(f"Key folders: {folders}")
        tools = e.get("tools") or {}
        if tools:
            # Off-PATH tools show their full path so the model invokes them right.
            path_dirs = {p.rstrip("\\/").lower()
                         for p in os.environ.get("PATH", "").split(os.pathsep) if p}
            rendered = [
                name if str(Path(path).parent).rstrip("\\/").lower() in path_dirs
                else f"{name}={path}"
                for name, path in sorted(tools.items())]
            lines.append("Installed tools: " + " · ".join(rendered))
            lines.append("Before saying a program is missing, check this list and "
                         "search the machine (PATH + common install dirs) — prefer "
                         "tools already installed on this host.")
        if e.get("apps_indexed"):
            lines.append(f"Apps indexed: {e['apps_indexed']} (use open_app)")
        lines.append(f"Working directory: {e['cwd']}")
        return "\n".join(lines)

    # -- path assist -------------------------------------------------------------

    def resolve_path(self, text: str) -> tuple[str, Optional[str]]:
        """Best-effort normalization of a model-written path for THIS host.

        Returns ``(resolved_path, error)`` — ``error`` is None when the path is
        plausible here; otherwise it explains the problem *and quotes the real
        layout* so the failed attempt teaches the model the actual filesystem.
        """
        e = self.get()
        raw = (text or "").strip().strip('"').strip("'")
        if not raw:
            return "", "empty path"
        p = os.path.expandvars(os.path.expanduser(raw))
        # Spoken folder names → real key folders ("Desktop/notes.txt").
        parts = p.replace("\\", "/").split("/")
        head = parts[0].strip().lower()
        for name, full in (e.get("folders") or {}).items():
            if head == name.lower():
                p = os.path.join(full, *parts[1:])
                break
        if platform.system() == "Windows":
            # POSIX-style guesses on a Windows host: /tmp, /home/<u>, /c/...
            low = p.replace("\\", "/").lower()
            # WSL paths are REAL locations on a Windows host, not guesses:
            # \\wsl$\<distro>\... passes through untouched (UNC — no drive
            # check), and /mnt/<drive>/... translates to the Windows drive
            # so file tools operate on the same bytes WSL sees.
            if low.startswith(("//wsl$", "//wsl.localhost")) or \
                    p.replace("/", "\\").lower().startswith(("\\\\wsl$", "\\\\wsl.localhost")):
                return os.path.normpath(p.replace("/", "\\")), None
            if len(low) >= 6 and low.startswith("/mnt/") and low[5].isalpha() \
                    and (len(low) == 6 or low[6] == "/"):
                drive_letter = low[5].upper()
                rest = p.replace("\\", "/").split("/")[3:]
                p = os.path.join(f"{drive_letter}:\\", *rest)
            if low.startswith("/tmp"):
                p = os.path.join(e["temp"], *p.replace("\\", "/").split("/")[2:])
            elif low.startswith(("/home/", "/root")):
                p = os.path.join(e["home"], *p.replace("\\", "/").split("/")[3:])
            p = os.path.normpath(p)
            drive = os.path.splitdrive(p)[0]
            if drive:
                roots = [d["root"].rstrip("\\").lower() for d in e.get("drives", [])]
                if drive.lower() not in roots:
                    return p, (f"drive {drive} does not exist on this machine. "
                               f"Real drives: {', '.join(r.upper() for r in roots)}. "
                               f"Home is {e['home']}.")
        else:
            p = os.path.normpath(p)
        return p, None
