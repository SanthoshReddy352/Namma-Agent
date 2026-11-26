"""Setup-mode tools (Phase 5): the agent guides configuration of models and
providers, MCP servers, Google Workspace, email and messaging — and NEVER sees
a secret value.

Secrets flow through :func:`request_secret`: it places a secure input card in
the chat (a ```secret fence the UI renders as a password field). The user's
value posts straight to ``/api/setup/secret`` → the vault; the agent only ever
learns the variable NAME and whether it is set.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from namma_agent.core.tools import ToolRegistry, ToolResult

#: Exactly the tools setup mode exposes (plus web lookups for provider docs).
SETUP_TOOLS = (
    "setup_status", "setup_catalog", "request_secret",
    "save_provider", "save_model", "verify_provider",
    "mcp_detect", "mcp_add_server", "mcp_remove_server", "mcp_list_servers",
    "integration_status", "gws_auth_login", "mail_add_account", "mail_test_account",
    "web_search", "web_extract",
)

_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def setup_context(service) -> str:
    """A compact, live snapshot for setup mode's system prompt: what is already
    configured, and every preset that can be set up (with the secret each one
    needs). Without it the model must remember to call ``setup_status`` /
    ``setup_catalog`` first, and in a live session gpt-4o didn't: asked to
    "configure GitHub" it answered with generic advice and config snippets
    instead of using the GitHub preset and a secure secret field. Never raises.
    """
    lines: list[str] = []
    try:
        st = service.setup_status(check_gws=False) or {}
    except Exception:  # noqa: BLE001
        st = {}
    try:
        presets = (service.mcp_catalog() or {}).get("presets") or []
    except Exception:  # noqa: BLE001
        presets = []
    lines.append("CURRENT SETUP (live, refreshed every turn):")
    lines.append(f"- AI: default model {st.get('default_model') or 'none'}; "
                 f"ready: {'yes' if st.get('provider_ready') else 'NO'}; providers: "
                 + (", ".join(f"{p.get('label') or p.get('id')} (key {'set' if p.get('key_set') or not p.get('needs_key') else 'MISSING'})"
                              for p in st.get("providers") or []) or "none"))
    servers = st.get("mcp_servers") or []
    lines.append("- MCP servers: " + (", ".join(
        f"{s.get('name') or s.get('id')} ({s.get('status') or s.get('state') or 'configured'})" for s in servers)
        if servers else "none"))
    for it in st.get("integrations") or []:
        state = it.get("state") or "?"
        extra = f"; needs {', '.join(it['needs'])}" if it.get("needs") and state != "ok" else ""
        lines.append(f"- {it.get('label') or it.get('id')}: {state}{extra}")
    if presets:
        lines.append("")
        lines.append("WHAT YOU CAN SET UP. Match what the user names to one of these and follow it:")
        for p in presets:
            secrets = [x.get("env") for x in p.get("secrets") or [] if x.get("env")]
            params = [q.get("key") for q in p.get("params") or []]
            lines.append(
                f"- MCP preset id \"{p.get('id')}\": {p.get('title')} ({p.get('runtime')})"
                + (f"; secret: {', '.join(secrets)}" if secrets else "; no secret")
                + (f"; params: {', '.join(params)}" if params else ""))
    try:
        from namma_agent.tools.mail import MAIL_PRESETS
        lines.append("- Email (IMAP/SMTP) presets: " + ", ".join(MAIL_PRESETS) + " (mail_add_account; app password via request_secret)")
    except Exception:  # noqa: BLE001
        pass
    lines.append("- AI providers: setup_catalog kind \"providers\" lists them all.")
    return "\n".join(lines)


def register_setup_tools(registry: ToolRegistry, service) -> None:
    # The live snapshot the agent adds to setup-mode prompts (not a model tool).
    registry.setup_context = lambda: setup_context(service)
    # Setup mode's safety net for a skipped request_secret (see the agent).
    registry.setup_missing_secret = lambda text: missing_secret_for(service, text)

    def status(_args: dict) -> ToolResult:
        st = service.setup_status(check_gws=bool(_args.get("check_google", True)))
        return ToolResult(ok=True, content=_j(st))

    def catalog(args: dict) -> ToolResult:
        kind = (args.get("kind") or "providers").lower()
        if kind == "providers":
            from namma_agent.core.providers.catalog import provider_catalog
            rows = [{k: p[k] for k in ("type", "label", "key_env", "needs_key", "base_url",
                                       "key_url", "key_set")} for p in provider_catalog()]
            return ToolResult(ok=True, content=_j(rows))
        if kind == "mcp":
            rows = [{"id": p["id"], "title": p["title"], "runtime": p["runtime"],
                     "description": p["description"],
                     "params": [{"key": q["key"], "label": q["label"], "type": q["type"],
                                 "required": q.get("required", False),
                                 **({"options": q["options"]} if q.get("options") else {})}
                                for q in p["params"]],
                     "secrets": p["secrets"]} for p in service.mcp_catalog()["presets"]]
            return ToolResult(ok=True, content=_j(rows))
        if kind == "mail":
            from namma_agent.tools.mail import MAIL_PRESETS
            return ToolResult(ok=True, content=_j(MAIL_PRESETS))
        return ToolResult(ok=False, content="", error="kind must be providers, mcp or mail")

    def request_secret(args: dict) -> ToolResult:
        name = str(args.get("name") or "").strip()
        from namma_agent.core.secrets import is_secret_name
        if not _ENV_RE.match(name) or not is_secret_name(name):
            return ToolResult(ok=False, content="", error=(
                "name must be an env-var credential name like OPENAI_API_KEY, "
                "GITHUB_PERSONAL_ACCESS_TOKEN or NAMMA_MAIL_WORK_PASSWORD"))
        card = {"name": name,
                "label": str(args.get("label") or name)[:80],
                "why": str(args.get("why") or "")[:240],
                "url": str(args.get("url") or "")[:300],
                "set": bool(os.environ.get(name))}
        if card["url"] and not re.match(r"^https://", card["url"]):
            card["url"] = ""
        fence = "```secret\n" + json.dumps(card, ensure_ascii=False) + "\n```"
        return ToolResult(
            ok=True,
            content=(f"A secure field for {name} is now shown to the user. They paste the "
                     "value there; it goes straight to the vault and you will NEVER see it. "
                     "Wait for their '[setup] saved' message, then continue (e.g. verify)."),
            data={"inline": fence, "secret_request": name})

    def save_provider(args: dict) -> ToolResult:
        r = service.setup_save_provider(args.get("type", ""), args.get("id", ""),
                                        args.get("label", ""), args.get("base_url", ""),
                                        args.get("api_key_env", ""))
        if not r.get("ok"):
            return ToolResult(ok=False, content="", error=r.get("error", "failed"))
        p = r["provider"]
        return ToolResult(ok=True, content=(
            f"Saved provider '{p['id']}' ({p['type']}). Key {p['api_key_env'] or '(none needed)'}: "
            f"{'set' if r['key_set'] else 'NOT set — call request_secret'}."))

    def save_model(args: dict) -> ToolResult:
        r = service.setup_save_model(args.get("provider", ""), args.get("model", ""),
                                     args.get("label", ""), bool(args.get("make_default")))
        if not r.get("ok"):
            return ToolResult(ok=False, content="", error=r.get("error", "failed"))
        return ToolResult(ok=True, content=f"Saved model {r['model']['id']}. Default: {r['default']}.")

    def verify(args: dict) -> ToolResult:
        r = service.setup_verify_provider(args.get("provider", ""), args.get("model", ""))
        models = r.pop("models", []) or []
        if models:
            r["models_sample"] = models[:25]
            r["models_total"] = len(models)
        return ToolResult(ok=True, content=_j(r))

    def detect(_args: dict) -> ToolResult:
        d = service.mcp_detect()
        slim = {"runtimes": {k: {"found": v["found"], **({"daemon": v["daemon"]} if "daemon" in v else {}),
                                 **({"hint": v["hint"]} if v.get("hint") else {})}
                             for k, v in d["runtimes"].items()},
                "disk": [{"path": x["path"], "free_gb": round(x["free_bytes"] / 1e9, 1),
                          "low": x["low"]} for x in d["disk"]],
                "importable": [{"source": i["source"], "name": i["server"].get("name")}
                               for i in d["importable"]],
                "docker_images": [i["image"] for i in d["docker_images"]],
                "launchers": d["launchers"]}
        return ToolResult(ok=True, content=_j(slim))

    def add_server(args: dict) -> ToolResult:
        if args.get("preset"):
            built = service.mcp_build_preset(args["preset"], args.get("params") or {},
                                             args.get("name", ""))
            if not built["ok"]:
                return ToolResult(ok=False, content="", error=_j(built["errors"]))
            entry = built["servers"][0]
        elif isinstance(args.get("server"), dict):
            entry = args["server"]
        else:
            return ToolResult(ok=False, content="", error="give a preset (+ params) or a server object")
        r = service.mcp_add_server(entry, replace=bool(args.get("replace")))
        if not r.get("ok"):
            return ToolResult(ok=False, content="", error=_j(r.get("errors")))
        missing = sorted({w["field"].strip("${}") for w in r.get("warnings", [])
                          if w["field"].startswith("${")})
        msg = (f"Added MCP server '{r['server']}'; it is connecting in the background — "
               "check with mcp_list_servers in a moment.")
        if missing:
            msg += f" Missing secrets: {', '.join(missing)} — call request_secret for each."
        return ToolResult(ok=True, content=msg)

    def remove_server(args: dict) -> ToolResult:
        r = service.mcp_remove_server(args.get("name", ""))
        if not r.get("ok"):
            return ToolResult(ok=False, content="", error=r.get("error", "failed"))
        return ToolResult(ok=True, content=f"Removed MCP server '{r['removed']}'.")

    def integration(args: dict) -> ToolResult:
        want = (args.get("id") or "").lower()
        rows = service.setup_integrations(check_gws=(not want or want == "google"))
        if want:
            rows = [r for r in rows if r.get("id") == want] or rows
        return ToolResult(ok=True, content=_j(rows))

    def gws_login(_args: dict) -> ToolResult:
        exe = shutil.which("gws") or shutil.which("gws.exe")
        if not exe:
            return ToolResult(ok=False, content="", error=(
                "gws isn't installed. Install it with `npm install -g @googleworkspace/cli` "
                "(needs Node.js), then try again."))
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                  "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008       # DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen([exe, "auth", "login"], **kwargs)  # noqa: S603
        except OSError as exc:
            return ToolResult(ok=False, content="", error=f"couldn't start gws: {exc}")
        return ToolResult(ok=True, content=(
            "Started `gws auth login` — a browser window opens for Google sign-in. Ask the "
            "user to finish it, then call integration_status with id 'google' to confirm."))

    def mail_add(args: dict) -> ToolResult:
        r = service.setup_mail_add(args.get("address", ""), args.get("provider", "custom"),
                                   args.get("id", ""), args.get("imap_host", ""),
                                   args.get("smtp_host", ""), int(args.get("imap_port") or 0),
                                   int(args.get("smtp_port") or 0), args.get("username", ""))
        if not r.get("ok"):
            return ToolResult(ok=False, content="", error="; ".join(r.get("errors") or []))
        msg = (f"Saved account {r['account']['address']} (id {r['account']['id']}). App password "
               f"variable: {r['password_env']} — {'set' if r['password_set'] else 'NOT set'}.")
        if not r["password_set"]:
            msg += " Call request_secret for it"
            msg += f" (create one at {r['app_password_url']})." if r["app_password_url"] else "."
        if r.get("note"):
            msg += f" Note: {r['note']}"
        return ToolResult(ok=True, content=msg)

    def mail_test(args: dict) -> ToolResult:
        r = service.setup_mail_test(args.get("account", ""))
        return ToolResult(ok=True, content=_j(r))

    obj = {"type": "object", "properties": {}}
    reg = registry.register
    reg("setup_status", "Overview of what is configured: providers (key set?), models and "
        "the default, MCP servers with live status, Google/email/messaging integrations.",
        {"type": "object", "properties": {"check_google": {"type": "boolean"}}}, status,
        category="setup")
    reg("setup_catalog", "Options to offer: 'providers' (AI model providers + where to get a "
        "key), 'mcp' (curated MCP server presets and their fields), 'mail' (email provider "
        "presets).", {"type": "object", "properties": {"kind": {
            "type": "string", "enum": ["providers", "mcp", "mail"]}}, "required": ["kind"]},
        catalog, category="setup")
    reg("request_secret", "Show the user a SECURE input for one credential (API key, token, "
        "app password). The value goes straight to the vault; you never see it. Never ask "
        "the user to paste a secret into the chat.",
        {"type": "object", "properties": {
            "name": {"type": "string", "description": "env-var name, e.g. OPENAI_API_KEY"},
            "label": {"type": "string", "description": "what it is, in plain words"},
            "why": {"type": "string", "description": "one line: what it unlocks"},
            "url": {"type": "string", "description": "https page where the user creates it"}},
         "required": ["name"]}, request_secret, category="setup")
    reg("save_provider", "Add/update an AI provider connection. type: anthropic, openai, google, "
        "openrouter, groq, deepseek, mistral, xai, together, ollama, lmstudio, openai_compat. "
        "Catalogue defaults fill base_url and the key variable.",
        {"type": "object", "properties": {
            "type": {"type": "string"}, "id": {"type": "string"}, "label": {"type": "string"},
            "base_url": {"type": "string"}, "api_key_env": {"type": "string"}},
         "required": ["type"]}, save_provider, category="setup")
    reg("save_model", "Add a model to the chat's model switcher (optionally as the default).",
        {"type": "object", "properties": {
            "provider": {"type": "string", "description": "a saved provider id"},
            "model": {"type": "string"}, "label": {"type": "string"},
            "make_default": {"type": "boolean"}}, "required": ["provider", "model"]},
        save_model, category="setup")
    reg("verify_provider", "Test a provider for real (lists models; with 'model', one tiny "
        "call). Result code tells a bad key from a bad model, base URL, network or quota.",
        {"type": "object", "properties": {
            "provider": {"type": "string", "description": "saved provider id or a type"},
            "model": {"type": "string"}}, "required": ["provider"]},
        verify, category="setup")
    reg("mcp_detect", "What this machine can run for MCP: node/npx, uvx, Docker (and whether "
        "its engine runs), free disk, servers already set up in Claude Desktop/Cursor/VS Code, "
        "Docker MCP images.", obj, detect, category="setup")
    reg("mcp_add_server", "Add an MCP server from a catalogue preset (+ params) or a full server "
        "object, then start it in the background. Launches third-party code, so it needs the "
        "user's approval.",
        {"type": "object", "properties": {
            "preset": {"type": "string"}, "params": {"type": "object"},
            "name": {"type": "string"}, "server": {"type": "object"},
            "replace": {"type": "boolean"}}}, add_server, destructive=True, category="setup")
    reg("mcp_remove_server", "Remove an MCP server (stops it and drops its tools).",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        remove_server, destructive=True, category="setup")
    reg("integration_status", "Status + next step for productivity integrations: google (gws: "
        "Gmail/Calendar/Drive), mail (IMAP/SMTP), telegram, discord, slack, signal, whatsapp, "
        "home_assistant.", {"type": "object", "properties": {"id": {"type": "string"}}},
        integration, category="setup")
    reg("gws_auth_login", "Start Google sign-in for the gws CLI (opens the user's browser).",
        obj, gws_login, category="setup")
    reg("mail_add_account", "Save an IMAP/SMTP email account (Gmail with an app password, "
        "Outlook, Yahoo, iCloud, Zoho, Fastmail or custom hosts). The app password is "
        "requested separately with request_secret.",
        {"type": "object", "properties": {
            "address": {"type": "string"}, "provider": {"type": "string"},
            "id": {"type": "string"}, "imap_host": {"type": "string"},
            "smtp_host": {"type": "string"}, "imap_port": {"type": "integer"},
            "smtp_port": {"type": "integer"}, "username": {"type": "string"}},
         "required": ["address"]}, mail_add, category="setup")
    reg("mail_test_account", "Sign in to an email account's IMAP and SMTP (reads and sends "
        "nothing).", {"type": "object", "properties": {"account": {"type": "string"}}},
        mail_test, category="setup")


def missing_secret_for(service, text: str) -> dict | None:
    """The first required, not-yet-stored secret of the MCP preset that ``text``
    (the user's setup request) names, as ``request_secret`` arguments, or None.

    Matching is by the preset's id words ("github", "context7", ...); when both
    a hosted and a Docker variant match, the hosted one wins unless the text
    says "docker". Used as setup mode's safety net: models often say "once you
    have the token, let me know" instead of calling ``request_secret``, which
    leaves the user with nowhere safe to put it.
    """
    low = (text or "").lower()
    if not low.strip():
        return None
    try:
        presets = (service.mcp_catalog() or {}).get("presets") or []
    except Exception:  # noqa: BLE001
        return None
    hits = []
    for p in presets:
        pid = str(p.get("id") or "").lower()
        words = [w for w in re.split(r"[^a-z0-9]+", pid) if w and w != "docker"]
        if words and all(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            hits.append(p)
    if not hits:
        return None
    wants_docker = "docker" in low
    hits.sort(key=lambda p: (("docker" in str(p.get("id"))) != wants_docker, len(str(p.get("id")))))
    for sec in hits[0].get("secrets") or []:
        env = sec.get("env")
        if env and sec.get("required", True) and not sec.get("set") and not os.environ.get(env):
            return {"name": env, "label": sec.get("label") or env,
                    "why": f"Connects {hits[0].get('title') or hits[0].get('id')}. "
                           + (sec.get("help") or ""),
                    "url": sec.get("url") or ""}
    return None
