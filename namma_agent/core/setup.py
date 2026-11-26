"""Setup helpers (Phase 5): verify a provider for real, report integration
status, and keep secrets out of chat.

* :func:`verify_provider` makes one tiny model call and classifies a failure so
  the user hears *what* is wrong — a bad key, a bad model name, a wrong base
  URL, no network, or a quota/rate limit — instead of a raw stack trace.
* :func:`integrations_status` reports Google Workspace (`gws`), IMAP/SMTP mail,
  the messaging bridges and Home Assistant: configured? working? next step?
* :func:`find_secrets` / :func:`redact_secrets` spot API keys pasted into a chat
  message, so they are removed before the model or the transcript sees them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Optional

# ── secrets pasted into chat ────────────────────────────────────────────────

#: (pattern, label, conventional env name) — specific prefixes first.
_SECRET_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API key", "ANTHROPIC_API_KEY"),
    (re.compile(r"sk-or-[A-Za-z0-9_-]{20,}"), "OpenRouter API key", "OPENROUTER_API_KEY"),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "OpenAI API key", "OPENAI_API_KEY"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "API key (sk-…)", ""),
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "Groq API key", "GROQ_API_KEY"),
    (re.compile(r"xai-[A-Za-z0-9]{20,}"), "xAI API key", "XAI_API_KEY"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "Google API key", "GOOGLE_API_KEY"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "GitHub token", "GITHUB_PERSONAL_ACCESS_TOKEN"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "GitHub token", "GITHUB_PERSONAL_ACCESS_TOKEN"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"), "Slack token", ""),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"), "Telegram bot token", "NAMMA_TELEGRAM_TOKEN"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key", ""),
]


def find_secrets(text: str) -> list[dict]:
    """Credentials in ``text``: ``[{label, env, start, end}]`` (no values)."""
    found: list[dict] = []
    taken: list[tuple[int, int]] = []
    for pattern, label, env in _SECRET_PATTERNS:
        for m in pattern.finditer(text or ""):
            if any(a <= m.start() < b for a, b in taken):
                continue                      # already matched by a more specific pattern
            taken.append((m.start(), m.end()))
            found.append({"label": label, "env": env, "start": m.start(), "end": m.end()})
    return sorted(found, key=lambda f: f["start"])


def redact_secrets(text: str) -> tuple[str, list[dict]]:
    """Replace every credential in ``text`` with a placeholder. Returns
    ``(clean_text, found)`` — ``found`` carries labels/env names, never values."""
    found = find_secrets(text)
    if not found:
        return text, []
    out, last = [], 0
    for f in found:
        out.append(text[last:f["start"]])
        out.append(f"[{f['label']} removed — use the secure key field]")
        last = f["end"]
    out.append(text[last:])
    return "".join(out), [{"label": f["label"], "env": f["env"]} for f in found]


# ── provider verification ────────────────────────────────────────────────────

def _classify(message: str) -> tuple[str, str]:
    """(code, human advice) for a provider error message."""
    m = (message or "").lower()
    if any(s in m for s in ("401", "invalid api key", "invalid_api_key", "incorrect api key",
                            "authentication", "unauthorized", "api key not valid",
                            "permission_denied", "403")):
        return "bad_key", "The provider rejected the API key — re-enter it (check for a copy/paste slip)."
    if any(s in m for s in ("model_not_found", "does not exist", "not found", "404",
                            "unknown model", "no such model", "invalid model")):
        return "bad_model", "The key works but that model name isn't available — pick one from the list."
    if any(s in m for s in ("429", "rate limit", "quota", "insufficient_quota", "billing",
                            "exceeded")):
        return "quota", "The key is valid but out of quota / rate-limited — check billing or try later."
    if any(s in m for s in ("connection", "timed out", "timeout", "name or service",
                            "getaddrinfo", "unreachable", "refused", "ssl")):
        return "unreachable", "Couldn't reach the provider — check the base URL and your connection."
    return "error", (message or "unknown error")[:200]


def verify_provider(ptype: str, model: str = "", base_url: str = "",
                    api_key_env: str = "", timeout_s: float = 30.0) -> dict:
    """Check a provider end to end. Returns ``{ok, code, message, models?,
    latency_ms?}`` with ``code`` one of ok | missing_key | bad_key | bad_model |
    bad_base_url | unreachable | quota | error."""
    from namma_agent.core.providers.catalog import _BY_TYPE, list_models_result
    from namma_agent.core.providers.registry import build_provider

    ptype = (ptype or "").lower()
    spec = _BY_TYPE.get(ptype, {})
    key_env = api_key_env or spec.get("key_env") or ""
    base = base_url or spec.get("base_url") or ""
    key = os.environ.get(key_env, "") if key_env else ""
    local = bool(re.match(r"^https?://(localhost|127\.0\.0\.1)", base or ""))
    if spec.get("needs_key", True) and not key and not local and ptype not in ("openai_compat",):
        return {"ok": False, "code": "missing_key",
                "message": f"No API key saved yet — add {key_env or 'the key'} first."}
    listing = list_models_result(ptype, base, key, timeout=10)
    models = listing["models"] if listing["source"] == "live" else []
    err = listing.get("error") or ""
    if err and not models:
        if "check the API key" in err:
            return {"ok": False, "code": "bad_key", "message": err}
        if "Couldn't reach" in err:
            return {"ok": False, "code": "unreachable", "message": err}
        if "no /models endpoint" in err or "Base URL" in err:
            return {"ok": False, "code": "bad_base_url", "message": err}
    if not model:
        ok = bool(models)
        return {"ok": ok, "code": "ok" if ok else "error", "models": models[:200],
                "message": f"Connected — {len(models)} models available." if ok
                else (err or "Couldn't list models.")}
    try:
        prov = build_provider({"type": ptype, "model": model, "base_url": base,
                               "api_key_env": key_env, "max_tokens": 16,
                               "timeout_s": timeout_s, "max_retries": 1})
        started = time.time()
        resp = prov.generate([{"role": "user", "content": "Reply with the word OK."}])
        latency = int((time.time() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        code, advice = _classify(str(exc))
        if code == "bad_model" and models:
            advice += f" ({len(models)} available.)"
        return {"ok": False, "code": code, "message": advice, "models": models[:200]}
    return {"ok": True, "code": "ok", "latency_ms": latency, "models": models[:200],
            "message": f"{model} answered in {latency} ms.",
            "reply": (getattr(resp, "content", "") or "")[:40]}


# ── integrations ─────────────────────────────────────────────────────────────

def gws_status(timeout: float = 20.0) -> dict:
    """Google Workspace CLI: installed → client configured → signed in."""
    exe = shutil.which("gws") or shutil.which("gws.exe")
    base = {"id": "google", "label": "Google Workspace (Gmail, Calendar, Drive)",
            "docs": "https://github.com/googleworkspace/cli"}
    if not exe:
        return {**base, "state": "not_installed",
                "next": "Install the gws CLI: npm install -g @googleworkspace/cli"}
    try:
        proc = subprocess.run([exe, "auth", "status"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        out = proc.stdout or ""
        data = json.loads(out[out.index("{"):]) if "{" in out else {}
    except Exception as exc:  # noqa: BLE001
        return {**base, "state": "error", "next": f"`gws auth status` failed: {exc}"}
    apis = set(data.get("enabled_apis") or [])
    services = {"gmail": "gmail.googleapis.com" in apis,
                "calendar": bool({"calendar-json.googleapis.com", "calendar.googleapis.com"} & apis),
                "drive": "drive.googleapis.com" in apis}
    if not data.get("client_config_exists"):
        return {**base, "state": "needs_setup", "services": services,
                "next": "Run `gws auth setup` once (creates the Google OAuth client)."}
    if not data.get("has_refresh_token"):
        return {**base, "state": "needs_login", "services": services,
                "next": "Run `gws auth login` and finish signing in in the browser."}
    if data.get("token_valid") is False:
        return {**base, "state": "needs_login", "services": services,
                "detail": f"saved sign-in is no longer valid ({data.get('token_error') or 'expired'})",
                "next": "Run `gws auth login` again to refresh the sign-in."}
    missing = [k for k, v in services.items() if not v]
    return {**base, "state": "ok", "services": services,
            "next": (f"Enable the {', '.join(missing)} API in Google Cloud for full access."
                     if missing else "")}


def _env_state(*names: str) -> bool:
    return all(bool(os.environ.get(n)) for n in names)


def integrations_status(config: Optional[dict] = None, check_gws: bool = True) -> list[dict]:
    """Every productivity integration with a state and the next step."""
    config = config or {}
    out = []
    out.append(gws_status() if check_gws else {"id": "google", "state": "unchecked"})
    accounts = ((config.get("mail") or {}).get("accounts") or [])
    mail_ok = [a for a in accounts if isinstance(a, dict)
               and os.environ.get(a.get("password_env") or "")]
    out.append({"id": "mail", "label": "Email (IMAP/SMTP: Outlook, Yahoo, iCloud, Zoho, …)",
                "state": "ok" if mail_ok else ("needs_secret" if accounts else "not_configured"),
                "accounts": [a.get("address") for a in accounts if isinstance(a, dict)],
                "next": "" if mail_ok else (
                    "Save the app password for the configured account." if accounts else
                    "Add an account with the mail setup (address + app password).")})
    bridges = [
        ("telegram", "Telegram", ("NAMMA_TELEGRAM_TOKEN",), "Create a bot with @BotFather"),
        ("discord", "Discord", ("NAMMA_DISCORD_BOT_TOKEN",), "Create a bot at discord.com/developers"),
        ("slack", "Slack", ("NAMMA_SLACK_BOT_TOKEN", "NAMMA_SLACK_APP_TOKEN"),
         "Create a Slack app with Socket Mode"),
        ("signal", "Signal", ("NAMMA_SIGNAL_API_URL", "NAMMA_SIGNAL_NUMBER"),
         "Run signal-cli-rest-api and link a number"),
    ]
    for bid, label, envs, hint in bridges:
        out.append({"id": bid, "label": f"{label} messaging", "kind": "messaging",
                    "state": "ok" if _env_state(*envs) else "not_configured",
                    "needs": list(envs), "next": "" if _env_state(*envs) else hint})
    wa_mode = os.environ.get("NAMMA_WHATSAPP_MODE", "")
    out.append({"id": "whatsapp", "label": "WhatsApp messaging", "kind": "messaging",
                "state": "ok" if wa_mode else "not_configured",
                "next": "" if wa_mode else "Settings → Messaging → WhatsApp (QR link or Cloud API)"})
    ha = config.get("smart_home") or {}
    ha_ok = bool(ha.get("url")) and bool(os.environ.get(ha.get("token_env") or "HASS_TOKEN"))
    out.append({"id": "home_assistant", "label": "Home Assistant", "state":
                "ok" if ha_ok else "not_configured",
                "next": "" if ha_ok else "Add the Home Assistant URL and a long-lived token"})
    return out
