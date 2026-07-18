"""Secrets vault + redaction (Phase 1d) — stdlib + ctypes only.

**The vault** keeps channel tokens and API keys out of plaintext ``.env``:

  * Windows → **Credential Manager** (``advapi32 CredRead/Write/DeleteW``,
    generic credentials under the ``NammaAgent/`` prefix) — encrypted by the OS,
    per-user, zero dependencies.
  * POSIX  → the ``keyring`` package when installed (libsecret / Keychain —
    a tiny optional dep), else the fallback file.
  * Fallback file (``data/secrets.vault.json``) → values encrypted with
    **DPAPI** on Windows (real, user-bound encryption via ``crypt32``); on
    POSIX the file is ``chmod 600`` and values are obfuscated with a
    machine/user-derived XOR stream — honest caveat: that is *obfuscation*;
    the file permission is the real protection there.

A names-only index (``data/secrets.index.json``) records what the vault holds
(every backend), powering the Security tab's inventory without touching values.

**Redaction**: every known secret VALUE (vault entries + secret-looking env
vars) is masked as ``***NAME***`` in model-visible tool output (hooked in
``ToolRegistry.execute``) and in the application log (a logging filter) — so a
``cat .env`` or an echoed webhook URL never hands the model, the Activity
strip, or the log file a live credential.

**Boot bridge**: :func:`bridge_env` loads vault values into ``os.environ`` (only
where unset), so providers/channels keep reading env vars unchanged and ``.env``
can be emptied after an opt-in migration (:func:`migrate_env_file`).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from namma_agent.core.logger import logger

IS_WINDOWS = platform.system() == "Windows"

_PREFIX = "NammaAgent/"  # Credential Manager target-name namespace


# ── Windows Credential Manager (ctypes, zero deps) ───────────────────────────

def _credman():
    """The advapi32 functions + CREDENTIALW structure, or None off-Windows."""
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    adv = ctypes.windll.advapi32
    return ctypes, CREDENTIALW, adv


class CredManBackend:
    """Generic credentials named ``NammaAgent/<NAME>`` (type=1, per-user)."""

    name = "credential-manager"

    @staticmethod
    def available() -> bool:
        return IS_WINDOWS and _credman() is not None

    def set(self, key: str, value: str) -> bool:
        ctypes, CREDENTIALW, adv = _credman()
        blob = value.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIALW()
        cred.Flags = 0
        cred.Type = 1  # CRED_TYPE_GENERIC
        cred.TargetName = _PREFIX + key
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE (this user, this machine)
        cred.UserName = "namma-agent"
        return bool(adv.CredWriteW(ctypes.byref(cred), 0))

    def get(self, key: str) -> Optional[str]:
        ctypes, CREDENTIALW, adv = _credman()
        pcred = ctypes.POINTER(CREDENTIALW)()
        if not adv.CredReadW(_PREFIX + key, 1, 0, ctypes.byref(pcred)):
            return None
        try:
            cred = pcred.contents
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return raw.decode("utf-16-le", errors="replace")
        finally:
            adv.CredFree(pcred)

    def delete(self, key: str) -> bool:
        ctypes, _CREDENTIALW, adv = _credman()
        return bool(adv.CredDeleteW(_PREFIX + key, 1, 0))


# ── keyring (POSIX optional tiny dep) ────────────────────────────────────────

class KeyringBackend:
    name = "keyring"

    def __init__(self):
        import keyring  # noqa: PLC0415 — optional
        self._kr = keyring

    @staticmethod
    def available() -> bool:
        try:
            import keyring  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    def set(self, key: str, value: str) -> bool:
        self._kr.set_password(_PREFIX.rstrip("/"), key, value)
        return True

    def get(self, key: str) -> Optional[str]:
        return self._kr.get_password(_PREFIX.rstrip("/"), key)

    def delete(self, key: str) -> bool:
        try:
            self._kr.delete_password(_PREFIX.rstrip("/"), key)
            return True
        except Exception:  # noqa: BLE001
            return False


# ── fallback file (DPAPI on Windows; 0600 + obfuscation on POSIX) ────────────

def _dpapi(protect: bool, data: bytes) -> Optional[bytes]:
    """Windows DPAPI encrypt/decrypt bound to the current user account."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def to_blob(b: bytes) -> DATA_BLOB:
        buf = (ctypes.c_ubyte * len(b)).from_buffer_copy(b) if b else (ctypes.c_ubyte * 1)()
        return DATA_BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))

    blob_in, blob_out = to_blob(data), DATA_BLOB()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _xor_stream(data: bytes) -> bytes:
    """Symmetric XOR keystream derived from user+machine (POSIX fallback).
    Obfuscation, not encryption — the 0600 file mode is the actual barrier."""
    seed = hashlib.sha256(
        f"{os.environ.get('USER') or os.environ.get('USERNAME') or ''}"
        f"|{uuid.getnode()}|namma-vault".encode()).digest()
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        out.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(b ^ k for b, k in zip(data, out))


class FileBackend:
    name = "encrypted-file"

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self._path)
        if not IS_WINDOWS:
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass

    def _seal(self, value: str) -> Optional[str]:
        raw = value.encode("utf-8")
        if IS_WINDOWS:
            sealed = _dpapi(True, raw)
            if sealed is None:
                return None
            return "dpapi:" + base64.b64encode(sealed).decode()
        return "xor:" + base64.b64encode(_xor_stream(raw)).decode()

    def _unseal(self, sealed: str) -> Optional[str]:
        try:
            kind, b64 = sealed.split(":", 1)
            raw = base64.b64decode(b64)
        except ValueError:
            return None
        if kind == "dpapi":
            plain = _dpapi(False, raw) if IS_WINDOWS else None
            return plain.decode("utf-8", errors="replace") if plain is not None else None
        if kind == "xor":
            return _xor_stream(raw).decode("utf-8", errors="replace")
        return None

    def set(self, key: str, value: str) -> bool:
        sealed = self._seal(value)
        if sealed is None:
            return False
        with self._lock:
            data = self._load()
            data[key] = sealed
            self._save(data)
        return True

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            sealed = self._load().get(key)
        return self._unseal(sealed) if sealed else None

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._load()
            if key not in data:
                return False
            del data[key]
            self._save(data)
        return True


# ── the store facade (backend + names-only index) ────────────────────────────

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SecretStore:
    def __init__(self, data_dir: str = "data", backend=None):
        self._dir = Path(data_dir)
        self._index_path = self._dir / "secrets.index.json"
        self._index_lock = threading.Lock()
        if backend is not None:
            self._backend = backend
        elif CredManBackend.available():
            self._backend = CredManBackend()
        elif KeyringBackend.available():
            try:
                self._backend = KeyringBackend()
            except Exception:  # noqa: BLE001 — keyring import quirks → file
                self._backend = FileBackend(self._dir / "secrets.vault.json")
        else:
            self._backend = FileBackend(self._dir / "secrets.vault.json")

    @property
    def backend(self) -> str:
        return self._backend.name

    # -- index (names only — never values) ---------------------------------

    def names(self) -> list[str]:
        try:
            return sorted(json.loads(self._index_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _index_update(self, key: str, present: bool) -> None:
        with self._index_lock:
            names = set(self.names())
            (names.add if present else names.discard)(key)
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            self._index_path.write_text(json.dumps(sorted(names)), encoding="utf-8")

    # -- operations ---------------------------------------------------------

    def set(self, key: str, value: str) -> bool:
        key, value = (key or "").strip(), (value or "").strip()
        if not _NAME_RE.match(key) or not value:
            return False
        ok = False
        try:
            ok = self._backend.set(key, value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[secrets] set %s failed on %s: %s", key, self.backend, exc)
        if ok:
            self._index_update(key, True)
            refresh_redaction()
        return ok

    def get(self, key: str) -> Optional[str]:
        try:
            return self._backend.get((key or "").strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[secrets] get %s failed on %s: %s", key, self.backend, exc)
            return None

    def delete(self, key: str) -> bool:
        try:
            ok = self._backend.delete((key or "").strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[secrets] delete %s failed on %s: %s", key, self.backend, exc)
            ok = False
        self._index_update(key, False)  # index drops it even if the backend already had
        refresh_redaction()
        return ok


_STORE: Optional[SecretStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> SecretStore:
    """The process-wide vault (created on first use)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = SecretStore()
        return _STORE


def set_store(store: Optional[SecretStore]) -> None:
    """Inject/replace the singleton (tests; service boot with a data dir)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = store
    refresh_redaction()


# ── boot bridge + opt-in migration ───────────────────────────────────────────

def bridge_env() -> list[str]:
    """Load vault values into ``os.environ`` (only where unset/blank), so
    providers and channels keep reading env vars unchanged. Returns the names
    bridged. Called once at service boot."""
    store = get_store()
    bridged = []
    for name in store.names():
        if os.environ.get(name, "").strip():
            continue  # a live env var wins — never silently overridden
        value = store.get(name)
        if value:
            os.environ[name] = value
            bridged.append(name)
    if bridged:
        logger.info("[secrets] bridged %d vault secret(s) into the environment",
                    len(bridged))
    refresh_redaction()
    return bridged


def migrate_env_file(env_path: Optional[str] = None, scrub: bool = False) -> dict:
    """Opt-in: copy secret-looking ``KEY=value`` entries from ``.env`` into the
    vault. With ``scrub=True`` the migrated values are BLANKED in ``.env``
    (the file keeps its keys as documentation; the vault + boot bridge serve
    the values from then on). Returns {migrated, skipped, backend, scrubbed}."""
    from namma_agent.config import _REPO_ROOT  # noqa: PLC0415 — avoid cycle at import time

    path = Path(env_path) if env_path else _REPO_ROOT / ".env"
    store = get_store()
    migrated, skipped = [], []
    if not path.exists():
        return {"migrated": [], "skipped": [], "backend": store.backend,
                "scrubbed": False, "error": f"{path} does not exist"}
    lines = path.read_text(encoding="utf-8").splitlines()
    out_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, value = stripped.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if value and _SECRET_NAME_RE.search(key):
                if store.set(key, value):
                    migrated.append(key)
                    os.environ.setdefault(key, value)
                    if scrub:
                        out_lines.append(f"{key}=")  # key stays as documentation
                        continue
                else:
                    skipped.append(key)
        out_lines.append(line)
    if scrub and migrated:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    refresh_redaction()
    return {"migrated": migrated, "skipped": skipped, "backend": store.backend,
            "scrubbed": bool(scrub and migrated)}


# ── redaction ────────────────────────────────────────────────────────────────

#: Env-var names that look like credentials. WEBHOOK covers Slack/Discord URLs
#: (the path IS the secret); the 8-char floor stops "true"/"8000" masking.
_SECRET_NAME_RE = re.compile(r"(TOKEN|SECRET|API_?KEY|PASSWORD|PASSWD|WEBHOOK)",
                             re.IGNORECASE)
_MIN_SECRET_LEN = 8

_red_lock = threading.Lock()
_red_cache: list[tuple[str, str]] = []  # (value, name), longest value first
_red_built_at = 0.0
_RED_TTL = 60.0


def refresh_redaction() -> None:
    """Drop the cached value→name map (vault/env changed); rebuilt lazily."""
    global _red_built_at
    with _red_lock:
        _red_built_at = 0.0


def _redaction_map() -> list[tuple[str, str]]:
    global _red_built_at, _red_cache
    with _red_lock:
        now = time.time()
        if now - _red_built_at < _RED_TTL:
            return _red_cache
        found: dict[str, str] = {}
        for name, value in os.environ.items():
            value = (value or "").strip()
            if _SECRET_NAME_RE.search(name) and len(value) >= _MIN_SECRET_LEN:
                found.setdefault(value, name)
        store = _STORE  # only consult an already-built vault — no I/O storms
        if store is not None:
            for name in store.names():
                value = store.get(name) or ""
                if len(value) >= _MIN_SECRET_LEN:
                    found.setdefault(value, name)
        # Longest values first, so a secret containing another masks cleanly.
        _red_cache = sorted(found.items(), key=lambda kv: -len(kv[0]))
        _red_built_at = now
        return _red_cache


def redact(text: str) -> str:
    """Mask every known secret value in ``text`` as ``***NAME***``. Cheap when
    nothing matches; safe on empty/None."""
    if not text:
        return text
    for value, name in _redaction_map():
        if value in text:
            text = text.replace(value, f"***{name}***")
    return text


class RedactingFilter:
    """A logging filter masking secrets in every record that passes through."""

    def filter(self, record) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never break logging
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


# Arm the log-redaction filter the moment the secrets machinery loads (the
# service imports this module at boot). Idempotent across re-imports.
if not any(isinstance(f, RedactingFilter) for f in logger.filters):
    logger.addFilter(RedactingFilter())
