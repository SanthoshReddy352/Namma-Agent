"""First-run setup — configure the first API provider.

Run by the installers (``python -m namma_agent --setup``) right after the
environment + dependencies are in place, so the desktop app opens already
talking to a brain. Everything written here is the same config the in-app
Settings panel edits, so the user can change provider/model/keys later.

- ``configure_provider(...)`` is the pure, testable core: it writes the chosen
  provider to ``user_config.yaml`` and the API key to ``.env``.
- ``run_wizard(...)`` is the interactive terminal front-end.

The assistant's display name is intentionally left untouched: it defaults to
"Namma Agent" (``config.assistant_name``) and the user renames it in Settings.
"""
from __future__ import annotations

from typing import Callable, Optional

from namma_agent.config import set_env_values, update_config

#: Curated default model per provider for the terminal wizard (else the
#: catalogue's first fallback model).
_DEFAULT_MODELS = {"anthropic": "claude-opus-4-8", "openai": "gpt-4o",
                   "google": "gemini-2.0-flash", "ollama": "llama3.1",
                   "lmstudio": "local-model", "openai_compat": ""}


def _derive_presets() -> dict[str, dict]:
    """``PROVIDER_PRESETS`` DERIVED from the provider catalogue
    (core/providers/catalog.py) — one entry per catalogue provider."""
    from namma_agent.core.providers.catalog import CATALOG

    out: dict[str, dict] = {}
    for p in CATALOG:
        fallback = p.get("fallback_models") or []
        out[p["id"]] = {
            "label": p["label"] + (" (local, no key)" if p["auth"] == "none" else ""),
            "api_key_env": p["key_env"],
            "default_model": _DEFAULT_MODELS.get(p["id"], fallback[0] if fallback else ""),
            "base_url": p["base_url"] or None,
            "needs_key": bool(p["needs_key"]),
            "group": p["group"],
            "needs_base_url": bool(p["needs_base_url"]),
        }
    return out


#: provider id → {label, api_key_env, default_model, base_url, needs_key, group,
#: needs_base_url}. Derived from the catalogue; covers every catalogue provider.
PROVIDER_PRESETS: dict[str, dict] = _derive_presets()

#: The short list the terminal wizard shows by number (everything else is
#: reachable in the app's Settings → Model → Add a model).
_ORDER = ["anthropic", "openai", "google", "openrouter", "ollama", "lmstudio", "openai_compat"]


def configure_provider(provider_type: str, model: Optional[str] = None,
                       api_key: Optional[str] = None, base_url: Optional[str] = None,
                       *, config_path: Optional[str] = None,
                       env_path: Optional[str] = None) -> dict:
    """Persist the first provider. Returns the provider dict written to config.

    Writes ``provider:`` into ``user_config.yaml`` (never the documented base
    file) and, when the provider needs one, the API key into ``.env`` under the
    provider's ``api_key_env``. ``config_path`` / ``env_path`` are for tests.
    """
    preset = PROVIDER_PRESETS.get(provider_type)
    if preset is None:
        raise ValueError(f"unknown provider '{provider_type}'. "
                         f"choose one of: {', '.join(_ORDER)}")

    provider: dict = {"type": provider_type}
    provider["model"] = (model or preset["default_model"] or "").strip()
    api_key_env = preset["api_key_env"]
    if api_key_env:
        provider["api_key_env"] = api_key_env
    url = base_url if base_url is not None else preset["base_url"]
    # Always pin base_url (even to "") so a provider with no base URL doesn't inherit
    # a stale one from the shipped default `provider:` via deep-merge.
    provider["base_url"] = url or ""

    update_config({"provider": provider}, path=config_path)

    # Also register this as a switchable connection + model, so the freshly
    # configured brain shows up in the UI picker (Settings → Providers / Models and
    # the chat model dropdown) — not just as the silent default `provider:`. Without
    # this, a fresh install has empty `providers:`/`models:` lists and the app reads
    # as "no provider / no model set" even though the default brain is configured.
    # Appends without clobbering any list the user has already curated.
    from namma_agent.config import configured_models, configured_providers, load_config

    cfg = load_config(config_path)
    pid = provider_type
    connection = {"id": pid, "label": preset["label"], "type": provider_type,
                  "base_url": url or "", "api_key_env": api_key_env or ""}
    provs = configured_providers(cfg)
    if not any(p["id"] == pid for p in provs):
        provs.append(connection)
    model_id = provider["model"] or provider_type
    model_entry = {"id": model_id, "label": model_id, "provider": pid,
                   "model": provider["model"], "type": "", "base_url": "", "api_key_env": ""}
    models = configured_models(cfg)
    if not any(m["id"] == model_id for m in models):
        models.append(model_entry)
    update_config({"providers": provs, "models": models}, path=config_path)

    if api_key and api_key_env:
        set_env_values({api_key_env: api_key}, path=env_path)
    return provider


# ── First-run onboarding (asked once, at install time) ───────────────────────
# (key, prompt, category). Stored in the SAME place the in-chat onboarding writes:
# `name` as an identity fact, the rest as onboarding facts — so the agent recalls
# them from turn one and they survive normal use. (A "wipe data" in Settings clears
# them, and the in-chat onboarding card then re-collects the name.)
ONBOARDING_QUESTIONS = [
    ("name", "Your name", "identity"),
    ("date_of_birth", "Date of birth (YYYY-MM-DD, optional)", "onboarding"),
    ("occupation", "What do you do (work or study)", "onboarding"),
    ("location", "Where are you based (city / country)", "onboarding"),
    ("interests", "A few interests or hobbies", "onboarding"),
]


def save_onboarding(answers: dict, *, db_path: Optional[str] = None) -> dict:
    """Persist onboarding answers into the agent's SQLite DB exactly as the in-chat
    onboarding does: ``name`` → an *identity* fact, everything else → *onboarding*
    facts. Returns the facts actually saved. ``db_path`` is for tests."""
    from namma_agent.config import data_dir, load_config
    from namma_agent.core.memory import Database

    if db_path is None:
        db_path = ((load_config().get("database") or {}).get("path")) or str(data_dir() / "namma_agent.db")
    db = Database(db_path)
    saved: dict = {}
    name = str(answers.get("name") or "").strip()
    if name:
        db.save_fact("name", name, category="identity")
        saved["name"] = name
    for key, value in answers.items():
        if key == "name":
            continue
        value = str(value or "").strip()
        if key and value:
            db.save_fact(str(key).strip(), value, category="onboarding")
            saved[str(key).strip()] = value
    return saved


def run_onboarding(input_fn: Callable[[str], str] = input,
                   print_fn: Callable[..., None] = print) -> dict:
    """Interactive first-run Q&A (Name, DOB, occupation, ...). Press Enter to skip
    any. Saves to the DB so the chat doesn't have to ask again."""
    p = print_fn
    p("\n  A few quick questions so Namma Agent knows you (press Enter to skip any):")
    answers: dict = {}
    for key, prompt, _cat in ONBOARDING_QUESTIONS:
        ans = (input_fn(f"  {prompt}: ") or "").strip()
        if ans:
            answers[key] = ans
    if not answers:
        p("  Skipped - tell me about yourself anytime in chat.\n")
        return {}
    saved = save_onboarding(answers)
    p(f"\n  [ok] Saved {len(saved)} detail(s) - change them anytime in chat.\n")
    return saved


def run_wizard(input_fn: Callable[[str], str] = input,
               print_fn: Callable[..., None] = print) -> Optional[dict]:
    """Interactive first-run provider setup. Returns the provider dict, or None
    if the user skipped (e.g. they'll configure it in-app)."""
    p = print_fn
    p("\n  Namma Agent - first-run setup")
    p("  Pick the AI provider (the 'brain'). You can change this later in Settings.\n")
    for i, pid in enumerate(_ORDER, 1):
        p(f"    {i}. {PROVIDER_PRESETS[pid]['label']}")
    p("    0. Skip - I'll set it up in the app")

    raw = (input_fn("\n  Choice [1]: ") or "1").strip()
    if raw == "0":
        p("  Skipped. Open the app and add a provider in Settings -> Providers.\n")
        return None
    try:
        pid = _ORDER[int(raw) - 1]
    except (ValueError, IndexError):
        p("  Not a valid choice - skipping. Configure it in the app's Settings.\n")
        return None

    preset = PROVIDER_PRESETS[pid]
    default_model = preset["default_model"]
    model = (input_fn(f"  Model [{default_model or 'required'}]: ") or default_model).strip()

    base_url = None
    if pid == "openai_compat":
        base_url = (input_fn("  Base URL (e.g. https://api.groq.com/openai/v1): ") or "").strip()
    elif preset["needs_base_url"] and preset["base_url"]:
        base_url = (input_fn(f"  Base URL [{preset['base_url']}]: ") or preset["base_url"]).strip()

    api_key = None
    if preset["needs_key"] or pid == "openai_compat":   # custom: key optional
        api_key = (input_fn(f"  API key for {preset['label']} "
                            f"(stored in .env as {preset['api_key_env']}): ") or "").strip()
        if not api_key:
            p("  No key entered - saving the provider; add the key later in Settings.")

    provider = configure_provider(pid, model=model, api_key=api_key, base_url=base_url)
    p(f"\n  [ok] Configured {preset['label']} (model: {provider.get('model') or 'unset'}).")
    p("  Launching Namma Agent...\n")
    return provider
