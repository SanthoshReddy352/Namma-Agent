"""`python -m namma_agent` → launch the app (or run a one-off subcommand).

Subcommands (used by the installers — do not rename):
  --version             print the version and exit
  --setup               interactive: configure the first provider, then onboarding
  --configure <file>    non-interactive: write provider config from a JSON file
                        (keys: type, model, api_key, base_url) — for the GUI installer
  --onboard <file>      non-interactive: save onboarding answers from a JSON file
  --server              run headless (no native window)
  --chat / --tui        the terminal UI (see :mod:`namma_agent.tui.cli`)

Anything else — ``gateway``, ``sessions``, ``config``, ``-z``, ``--resume``, … —
is handed to the full command surface in :mod:`namma_agent.tui.cli`.
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

# Everything below --server is the terminal front end. `--chat` is kept as an
# alias for the default action: it used to mean "the plain REPL", and it still
# gets a REPL whenever the terminal UI can't run (no TTY, missing deps), so the
# flag never breaks — it just gets nicer when it can.
_CLI_SUBCOMMANDS = {
    "chat", "gateway", "serve", "sessions", "model", "config", "skills",
    "tools", "mcp", "memory", "status", "doctor", "logs", "setup", "version",
}
_CLI_FLAGS = {
    "--tui", "--cli", "--chat", "-z", "--oneshot", "-c", "--continue",
    "-r", "--resume", "-m", "--model", "--mode", "--yolo", "--skin",
    "--no-color", "--ascii", "--gateway", "-h", "--help",
}


def _cli_argv(argv: list[str]):
    """The argv to hand the CLI, or None when this isn't a CLI invocation."""
    if not argv or "--server" in argv:
        return None
    if not (argv[0] in _CLI_SUBCOMMANDS or _CLI_FLAGS.intersection(argv)):
        return None
    # --chat predates the subcommand surface and carries no meaning of its own;
    # dropping it leaves the default action, which is exactly what it asked for.
    return [arg for arg in argv if arg != "--chat"]


_argv = _cli_argv(sys.argv[1:])
if _argv is not None:
    from namma_agent.tui.cli import main as cli_main

    raise SystemExit(cli_main(_argv))

from namma_agent.app import main  # noqa: E402

main(server_only="--server" in sys.argv)
