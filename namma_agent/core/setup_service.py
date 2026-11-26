"""Setup operations shared by the first-run onboarding, the Settings UI and the
setup-mode tools (Phase 5). Mixed into :class:`NammaAgentService`.

Every write goes through the same paths as the Settings tabs (user_config.yaml
+ the vault) and applies live. Secret VALUES only ever arrive through
:meth:`setup_save_secret` (a dedicated HTTP endpoint the secure input posts to);
nothing here returns one.
"""
from __future__ import annotations

import os
import re

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class SetupMixin:
    # -- secrets -----------------------------------------------------------

    def setup_save_secret(self, name: str, value: str) -> dict:
        """Store one credential in the vault and apply it live. Returns names
        only. The name must look like a credential (KEY/TOKEN/SECRET/PASSWORD)
        so this endpoint can't be used to rewrite arbitrary environment."""
        from namma_agent.core.secrets import is_secret_name, save_settings_env

        name = (name or "").strip()
        if not _ENV_NAME_RE.match(name) or not is_secret_name(name):
            return {"ok": False, "error": "not a credential name (expected …_API_KEY, "
                                          "…_TOKEN, …_SECRET or …_PASSWORD)"}
        value = (value or "").strip()
        if not value:
            return {"ok": False, "error": "empty value"}
        try:
            saved = save_settings_env({name: value})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            self.apply_config(None)          # rebuild providers on the new key
        except Exception:  # noqa: BLE001 — the key is saved either way
            pass
        self._model_providers = {}
        return {"ok": True, "name": name, "vault": name in saved["vault"]}

    def secret_names(self) -> dict:
        """Which credential names are set (booleans only)."""
        from namma_agent.core.secrets import get_store, is_secret_name
        names = set(get_store().names()) | {k for k in os.environ if is_secret_name(k)}
        return {n: True for n in sorted(names) if _ENV_NAME_RE.match(n)}

    # -- providers & models -----------------------------------------------

    def _persist_providers(self, providers: list[dict]) -> list[dict]:
        from namma_agent.config import configured_providers as _norm
        from namma_agent.config import update_config
        normalised = _norm({"providers": providers})
        update_config({"providers": normalised})
        return self.reload_providers(normalised)

    def _persist_models(self, models: list[dict]) -> list[dict]:
        from namma_agent.config import configured_models as _norm
        from namma_agent.config import update_config
        normalised = _norm({"models": models})
        update_config({"models": normalised})
        return self.reload_models(normalised)

    def setup_save_provider(self, ptype: str, pid: str = "", label: str = "",
                            base_url: str = "", api_key_env: str = "") -> dict:
        """Add or update a named provider connection (catalogue defaults fill
        base_url / key name)."""
        from namma_agent.core.providers.catalog import _BY_TYPE
        from namma_agent.core.providers.registry import PROVIDER_TYPES

        ptype = (ptype or "").strip().lower()
        if ptype not in PROVIDER_TYPES:
            return {"ok": False, "error": f"unknown provider type {ptype!r}; known: "
                                          + ", ".join(sorted(_BY_TYPE))}
        spec = _BY_TYPE.get(ptype, {})
        pid = (pid or spec.get("label", ptype).split(" (")[0] or ptype).strip()
        if base_url and not re.match(r"^https?://", base_url):
            return {"ok": False, "error": "base_url must start with http:// or https://"}
        if api_key_env and not _ENV_NAME_RE.match(api_key_env):
            return {"ok": False, "error": "api_key_env must be an env-var name like OPENAI_API_KEY"}
        entry = {"id": pid, "label": label or pid, "type": ptype,
                 "base_url": base_url or spec.get("base_url", ""),
                 "api_key_env": api_key_env or spec.get("key_env", "")}
        providers = [p for p in self.configured_providers() if p["id"] != pid]
        providers.append(entry)
        applied = self._persist_providers(providers)
        return {"ok": True, "provider": entry, "providers": applied,
                "key_set": bool(entry["api_key_env"] and os.environ.get(entry["api_key_env"]))}

    def setup_save_model(self, provider_id: str, model: str, label: str = "",
                         make_default: bool = False) -> dict:
        model = (model or "").strip()
        conn = next((p for p in self.configured_providers() if p["id"] == provider_id), None)
        if conn is None:
            return {"ok": False, "error": f"no provider {provider_id!r} — save the provider first"}
        if not model:
            return {"ok": False, "error": "model is required"}
        mid = model
        models = [m for m in self.configured_models() if m["id"] != mid]
        entry = {"id": mid, "label": label or model, "provider": provider_id, "model": model}
        models = [entry, *models] if make_default else [*models, entry]
        applied = self._persist_models(models)
        return {"ok": True, "model": entry, "default": applied[0]["id"] if applied else "",
                "models": applied}

    def setup_verify_provider(self, provider: str, model: str = "") -> dict:
        """Verify a configured provider id (or a bare catalogue type)."""
        from namma_agent.core.setup import verify_provider
        conn = next((p for p in self.configured_providers() if p["id"] == provider), None)
        if conn is None:
            return verify_provider(provider, model)
        return verify_provider(conn["type"], model, conn.get("base_url", ""),
                               conn.get("api_key_env", ""))

    def provider_ready(self) -> bool:
        """At least one model the app can actually call (a key is set, or the
        provider needs none)."""
        for m in self.configured_models():
            conn = next((p for p in self.configured_providers() if p["id"] == m.get("provider")), {})
            ptype = conn.get("type") or m.get("type") or ""
            base = conn.get("base_url") or m.get("base_url") or ""
            env = conn.get("api_key_env") or m.get("api_key_env") or ""
            if env and os.environ.get(env):
                return True
            if ptype in ("ollama", "lmstudio") or re.match(r"^https?://(localhost|127\.)", base):
                return True
        # No model profiles: the legacy `provider:` block counts only when the USER
        # set it — the shipped default (opencode/big-pickle on OPENAI_API_KEY) would
        # otherwise look "ready" to anyone holding an unrelated OpenAI key.
        if not self._user_set_provider():
            return False
        try:
            return bool(self.provider.is_available())
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _user_set_provider() -> bool:
        import yaml

        from namma_agent.config import user_config_file
        try:
            path = user_config_file()
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:  # noqa: BLE001
            return False
        prov = (data or {}).get("provider") or {}
        return isinstance(prov, dict) and bool(prov.get("type"))

    def setup_onboard_provider(self, ptype: str, model: str, key: str = "",
                               base_url: str = "") -> dict:
        """First-run: save the key (vault) → the provider → verify with a tiny
        call → only then make the model the default."""
        from namma_agent.core.providers.catalog import _BY_TYPE

        spec = _BY_TYPE.get((ptype or "").lower())
        if spec is None:
            return {"ok": False, "code": "error", "message": f"unknown provider {ptype!r}"}
        if key:
            env = spec.get("key_env") or f"{ptype.upper()}_API_KEY"
            saved = self.setup_save_secret(env, key)
            if not saved.get("ok"):
                return {"ok": False, "code": "error", "message": saved.get("error", "")}
        prov = self.setup_save_provider(ptype, base_url=base_url)
        if not prov.get("ok"):
            return {"ok": False, "code": "error", "message": prov.get("error", "")}
        pid = prov["provider"]["id"]
        result = self.setup_verify_provider(pid, model)
        if result.get("ok"):
            self.setup_save_model(pid, model, make_default=True)
        return {**result, "provider": pid, "ready": self.provider_ready()}

    # -- integrations ------------------------------------------------------

    def setup_integrations(self, check_gws: bool = True) -> list[dict]:
        from namma_agent.core.setup import integrations_status
        return integrations_status(self.config, check_gws=check_gws)

    def setup_mail_add(self, address: str, provider: str = "custom", account_id: str = "",
                       imap_host: str = "", smtp_host: str = "", imap_port: int = 0,
                       smtp_port: int = 0, username: str = "") -> dict:
        from namma_agent.config import update_config
        from namma_agent.tools.mail import MAIL_PRESETS, normalize_account, validate_account

        raw = {"address": address, "provider": provider, "id": account_id or "",
               "username": username or address}
        for k, v in (("imap_host", imap_host), ("smtp_host", smtp_host),
                     ("imap_port", imap_port), ("smtp_port", smtp_port)):
            if v:
                raw[k] = v
        errs = validate_account(raw)
        if errs:
            return {"ok": False, "errors": errs}
        acc = normalize_account(raw)
        mail = dict(self.config.get("mail") or {})
        accounts = [a for a in (mail.get("accounts") or [])
                    if isinstance(a, dict) and a.get("id") != acc["id"]]
        accounts.append(acc)
        mail["accounts"] = accounts
        self._replace_config(update_config({"mail": mail}))
        preset = MAIL_PRESETS.get(acc["provider"], {})
        return {"ok": True, "account": acc, "password_env": acc["password_env"],
                "password_set": bool(os.environ.get(acc["password_env"])),
                "app_password_url": preset.get("app_password_url", ""),
                "note": preset.get("note", "")}

    def setup_mail_test(self, account: str = "") -> dict:
        from namma_agent.tools.mail import _pick, check_account
        acc, err = _pick(account)
        if err:
            return {"ok": False, "errors": [err]}
        return {**check_account(acc), "account": acc["id"]}

    # -- overview ----------------------------------------------------------

    def setup_status(self, check_gws: bool = True) -> dict:
        models = self.configured_models()
        providers = []
        for p in self.configured_providers():
            env = p.get("api_key_env") or ""
            providers.append({**p, "key_set": bool(env and os.environ.get(env)),
                              "needs_key": bool(env)})
        mcp = self.mcp_detail() if hasattr(self, "mcp_detail") else {"servers": []}
        return {
            "provider_ready": self.provider_ready(),
            "providers": providers,
            "models": [{"id": m["id"], "provider": m.get("provider"), "model": m.get("model")}
                       for m in models],
            "default_model": models[0]["id"] if models else "",
            "mcp_servers": [{"name": s["name"], "state": s.get("state"),
                             "error": s.get("error", ""), "tools": len(s.get("tools") or [])}
                            for s in mcp.get("servers", [])],
            "integrations": self.setup_integrations(check_gws=check_gws),
            "secrets_set": sorted(self.secret_names()),
        }
