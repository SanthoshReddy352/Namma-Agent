"""Engram embeddings — the optional vector channel in fused recall.

BM25 alone misses paraphrases ("my college" never matches "KARE university");
an embedding index catches meaning. Design constraints (G6): zero heavy
infrastructure — one OpenAI-compatible ``/embeddings`` endpoint called with
stdlib urllib (works with OpenAI, Groq, LM Studio, Ollama, any compat server),
float32 BLOBs in SQLite, brute-force cosine in-process (fine to ~100k rows at
personal-agent scale). No key + no local endpoint = the channel simply stays
off and recall is BM25-only, exactly as before.

Configured under ``memory.embeddings`` (base_url / model / api_key_env), and
shipped ON by default pointing at a local Ollama + ``all-minilm`` (the
installers provision it). That default is only safe because of the circuit
breaker below: on a host where Ollama is absent or restarting, the channel
backs off instead of retrying a dead endpoint on every single recall.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from array import array
from typing import Optional

from namma_agent.core.logger import logger

_LOCAL_HINTS = ("localhost", "127.0.0.1", "0.0.0.0")


def _prefer_ipv4(url: str) -> str:
    """Rewrite a ``localhost`` host to ``127.0.0.1``.

    On Windows ``localhost`` resolves to ``::1`` first. Ollama and LM Studio
    bind IPv4 only, so every request paid a ~2 s failed-IPv6-connect penalty
    before falling back — measured 2154 ms via ``localhost`` vs 75 ms via
    ``127.0.0.1`` against the same server. Since the documented config example
    uses ``localhost``, that tax hit every recall by default. Anyone who
    genuinely wants IPv6 can write ``[::1]``, which is left untouched.
    """
    for scheme in ("http://", "https://"):
        if url.startswith(scheme + "localhost"):
            return scheme + "127.0.0.1" + url[len(scheme) + len("localhost"):]
    return url


def to_blob(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def from_blob(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class Embedder:
    """Thin client for an OpenAI-compatible ``/embeddings`` endpoint."""

    #: Back-off after a failed call, doubling up to :data:`MAX_COOLDOWN_S`.
    COOLDOWN_S = 60.0
    MAX_COOLDOWN_S = 300.0

    def __init__(self, base_url: str = "", model: str = "",
                 api_key_env: str = "", timeout_s: float = 15.0):
        self.base_url = _prefer_ipv4((base_url or "").rstrip("/"))
        self.model = model or ""
        self.api_key_env = api_key_env or ""
        self.timeout_s = float(timeout_s)
        # Circuit breaker. Embeddings are configured by default, so on a host
        # without Ollama every recall would otherwise retry a dead endpoint —
        # and an unreachable port is not always cheap (a closed loopback port
        # measured 2.05 s at the OS level on Windows). After a failure the
        # channel goes quiet for a growing window instead of taxing every turn.
        self._blocked_until = 0.0
        self._failures = 0
        self.last_error = ""

    @classmethod
    def from_config(cls, config: Optional[dict]) -> Optional["Embedder"]:
        cfg = ((config or {}).get("memory") or {}).get("embeddings") or {}
        if not cfg.get("base_url") or not cfg.get("model"):
            return None
        return cls(base_url=str(cfg["base_url"]), model=str(cfg["model"]),
                   api_key_env=str(cfg.get("api_key_env") or ""),
                   timeout_s=float(cfg.get("timeout_s", 15)))

    def _api_key(self) -> str:
        return os.environ.get(self.api_key_env, "") if self.api_key_env else ""

    def configured(self) -> bool:
        """Has an endpoint + model and, unless local, a key. Says nothing about
        whether the server is actually up."""
        if not (self.base_url and self.model):
            return False
        return bool(self._api_key()) or any(h in self.base_url for h in _LOCAL_HINTS)

    def available(self) -> bool:
        """Configured AND not currently circuit-broken. Callers check this
        before embedding, so a cooling-off channel costs zero network calls."""
        return self.configured() and time.monotonic() >= self._blocked_until

    def _note_failure(self, exc: object) -> None:
        self._failures += 1
        self.last_error = str(exc)[:200]
        wait = min(self.COOLDOWN_S * (2 ** (self._failures - 1)), self.MAX_COOLDOWN_S)
        self._blocked_until = time.monotonic() + wait
        logger.debug("[engram] embeddings unavailable, pausing %.0fs: %s", wait, exc)

    def _note_success(self) -> None:
        self._failures = 0
        self._blocked_until = 0.0
        self.last_error = ""

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Embed a batch; None on any failure (the caller degrades to BM25)."""
        texts = [t for t in (texts or []) if (t or "").strip()]
        if not texts or not self.available():
            return None
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embeddings", data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        key = self._api_key()
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — recall must never break on this
            self._note_failure(exc)
            return None
        rows = data.get("data") or []
        vecs = [r.get("embedding") for r in sorted(rows, key=lambda r: r.get("index", 0))]
        if len(vecs) != len(texts) or not all(isinstance(v, list) for v in vecs):
            # Reachable but wrong shape — e.g. the model isn't pulled yet. Still
            # a failure worth backing off from, not a transparent no-op.
            self._note_failure("unexpected /embeddings response shape")
            return None
        self._note_success()
        return vecs
