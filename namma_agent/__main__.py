"""`python -m namma_agent` → launch the app (or run a one-off subcommand).

Subcommands (used by the installers):
  --version             print the version and exit
  --setup               interactive: configure the first provider, then onboarding
  --configure <file>    non-interactive: write provider config from a JSON file
                        (keys: type, model, api_key, base_url) — for the GUI installer
  --onboard <file>      non-interactive: save onboarding answers from a JSON file
  --server              run headless (no native window)
  --chat                local CLI chat gateway (REPL in the terminal)
"""
import sys

# Re-exec into the project venv if started with an interpreter missing the deps
# (e.g. system python). Must run before importing the app / provider stack.
from namma_agent._bootstrap import ensure_venv

ensure_venv()


def _arg_after(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else None


if "--version" in sys.argv:
    from namma_agent.version import __version__
    print(f"Namma Agent v{__version__}")
    raise SystemExit(0)

if "--configure" in sys.argv:
    # Non-interactive provider config from a JSON file (the GUI installer writes one).
    import json
    from namma_agent.core.setup_wizard import configure_provider
    data = json.load(open(_arg_after("--configure"), encoding="utf-8"))
    configure_provider(data["type"], model=data.get("model"),
                       api_key=data.get("api_key"), base_url=data.get("base_url"))
    print("provider configured")
    raise SystemExit(0)

if "--onboard" in sys.argv:
    # Non-interactive onboarding from a JSON file ({name, date_of_birth, ...}).
    import json
    from namma_agent.core.setup_wizard import save_onboarding
    data = json.load(open(_arg_after("--onboard"), encoding="utf-8"))
    saved = save_onboarding(data)
    print(f"onboarding saved: {len(saved)} fact(s)")
    raise SystemExit(0)

if "--setup" in sys.argv:
    # First-run: pick the provider, then ask the basic onboarding questions.
    from namma_agent.core.setup_wizard import run_onboarding, run_wizard
    run_wizard()
    run_onboarding()
    raise SystemExit(0)

if "--chat" in sys.argv:
    # Local CLI chat gateway: talk to the same agent (memory, tools, model picker,
    # /commands, !shell) right in the terminal — no server, no window.
    from namma_agent.comms.console import ConsoleInbound
    from namma_agent.config import assistant_name, load_config
    from namma_agent.service import NammaAgentService

    _svc = NammaAgentService(config=load_config())

    def _chat_turn(text, session_id, mode, askpass=None, model=None):
        res = _svc.run_turn(text, session_id=session_id, mode=mode,
                            askpass=askpass, model_id=model)
        return res.content, res.session_id

    ConsoleInbound(_chat_turn, get_models=_svc.configured_models,
                   name=assistant_name(_svc.config)).run_blocking()
    raise SystemExit(0)

from namma_agent.app import main  # noqa: E402

main(server_only="--server" in sys.argv)
