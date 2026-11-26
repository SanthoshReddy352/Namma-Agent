"""Official third-party OAuth for providers — OpenRouter PKCE (stdlib only).

OpenRouter's contract (https://openrouter.ai/docs/guides/overview/auth/oauth):

1. send the browser to ``https://openrouter.ai/auth?callback_url=…&code_challenge=…
   &code_challenge_method=S256``;
2. OpenRouter redirects back to ``callback_url`` with ``?code=…``;
3. ``POST https://openrouter.ai/api/v1/auth/keys`` with
   ``{code, code_verifier, code_challenge_method}`` returns ``{"key": "sk-or-…"}`` —
   a plain, user-owned API key (no refresh token).

OpenRouter echoes no ``state``, so the CSRF nonce rides in the callback PATH
(``/api/oauth/openrouter/callback/<nonce>``), the same trick Hermes Agent uses;
a ``?state=`` query on the bare callback path is accepted too. A nonce is
single-use and expires after 10 minutes (OpenRouter's code lifetime).

The key is stored by the caller through ``SetupMixin.setup_save_secret`` — the
vault when it is on — and never logged or returned.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
FLOW_TTL_S = 600.0


@dataclass(frozen=True)
class OAuthSpec:
    provider_id: str
    authorize_url: str
    exchange_url: str
    key_env: str


#: provider id → its OAuth spec. Only official, documented third-party flows.
OAUTH_PROVIDERS: dict[str, OAuthSpec] = {
    "openrouter": OAuthSpec("openrouter", OPENROUTER_AUTH_URL, OPENROUTER_KEYS_URL,
                            "OPENROUTER_API_KEY"),
}


class OAuthError(RuntimeError):
    """A user-presentable OAuth failure (never contains the key or code)."""


def pkce_verifier() -> str:
    """A 43-128 char URL-safe code verifier (RFC 7636 §4.1)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")[:128]


def pkce_challenge(verifier: str) -> str:
    """S256 challenge: BASE64URL(SHA256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@dataclass
class _Flow:
    provider_id: str
    verifier: str
    callback_url: str
    created: float = field(default_factory=time.time)


#: A JSON POST: (url, payload, timeout) -> (status, parsed body or None).
Poster = Callable[[str, dict, float], tuple]


def _post_json(url: str, payload: dict, timeout: float = 20.0) -> tuple:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "Namma Agent (oauth)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except urllib.error.URLError as exc:
        raise OAuthError(f"Couldn't reach the provider to finish sign-in ({exc.reason}).") from exc
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


class OAuthManager:
    """Pending PKCE flows (in memory, per server process)."""

    def __init__(self, poster: Optional[Poster] = None, clock: Callable[[], float] = time.time):
        self._poster = poster or _post_json
        self._clock = clock
        self._flows: dict[str, _Flow] = {}
        self._lock = threading.Lock()

    @staticmethod
    def supports(provider_id: str) -> bool:
        return provider_id in OAUTH_PROVIDERS

    def _prune(self) -> None:
        now = self._clock()
        for nonce in [n for n, f in self._flows.items() if now - f.created > FLOW_TTL_S]:
            self._flows.pop(nonce, None)

    def start(self, provider_id: str, server_base: str) -> dict:
        """Begin a flow. ``server_base`` is this server's public origin
        (e.g. ``http://127.0.0.1:8000``). Returns ``{authorize_url, state}``."""
        spec = OAUTH_PROVIDERS.get(provider_id)
        if spec is None:
            raise OAuthError(f"{provider_id!r} has no sign-in flow; paste an API key instead.")
        verifier = pkce_verifier()
        nonce = secrets.token_urlsafe(24)
        callback = f"{server_base.rstrip('/')}/api/oauth/{provider_id}/callback/{nonce}"
        with self._lock:
            self._prune()
            self._flows[nonce] = _Flow(provider_id, verifier, callback, created=self._clock())
        query = urllib.parse.urlencode({
            "callback_url": callback,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        })
        return {"authorize_url": f"{spec.authorize_url}?{query}", "state": nonce}

    def finish(self, provider_id: str, state: str, code: str) -> tuple[str, str]:
        """Exchange ``code`` for a key. Returns ``(key_env, key)``. The flow is
        consumed whether or not the exchange succeeds (codes are single-use)."""
        with self._lock:
            self._prune()
            flow = self._flows.pop(state or "", None)
        if flow is None or flow.provider_id != provider_id:
            raise OAuthError("This sign-in link expired or was already used. Start again.")
        if not code:
            raise OAuthError("The provider didn't return an authorization code.")
        spec = OAUTH_PROVIDERS[provider_id]
        status, body = self._poster(spec.exchange_url, {
            "code": code, "code_verifier": flow.verifier, "code_challenge_method": "S256",
        }, 20.0)
        if status == 403:
            raise OAuthError("OpenRouter rejected the sign-in code (expired or already used). "
                             "Start again.")
        if status >= 400:
            raise OAuthError(f"OpenRouter sign-in failed (HTTP {status}).")
        key = str((body or {}).get("key") or "").strip() if isinstance(body, dict) else ""
        if not key:
            raise OAuthError("OpenRouter's reply didn't include a key.")
        return spec.key_env, key

    def pending(self) -> int:
        with self._lock:
            self._prune()
            return len(self._flows)
