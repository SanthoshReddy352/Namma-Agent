"""Engram embeddings — the optional vector channel in fused recall.

BM25 alone misses paraphrases ("my college" never matches "KARE university");
an embedding index catches meaning. Design constraints (G6): zero heavy
infrastructure — one OpenAI-compatible ``/embeddings`` endpoint called with
stdlib urllib (works with OpenAI, Groq, LM Studio, Ollama, any compat server),
float32 BLOBs in SQLite, brute-force cosine in-process (fine to ~100k rows at
personal-agent scale). No key + no local endpoint = the channel simply stays
off and recall is BM25-only, exactly as before.

Configured under ``memory.embeddings`` (base_url / model / api_key_env).
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from array import array
from typing import Optional

from namma_agent.core.logger import logger

_LOCAL_HINTS = ("localhost", "127.0.0.1", "0.0.0.0")


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

    def __init__(self, base_url: str = "", model: str = "",
                 api_key_env: str = "", timeout_s: float = 15.0):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.api_key_env = api_key_env or ""
        self.timeout_s = float(timeout_s)

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

    def available(self) -> bool:
        """Configured and plausibly reachable: a key is set, or the endpoint is
        local (LM Studio / Ollama need no key)."""
        if not (self.base_url and self.model):
            return False
        return bool(self._api_key()) or any(h in self.base_url for h in _LOCAL_HINTS)

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
            logger.debug("[engram] embeddings call failed: %s", exc)
            return None
        rows = data.get("data") or []
        vecs = [r.get("embedding") for r in sorted(rows, key=lambda r: r.get("index", 0))]
        if len(vecs) != len(texts) or not all(isinstance(v, list) for v in vecs):
            return None
        return vecs
