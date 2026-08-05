"""Namma Agent's terminal UI — a prompt_toolkit + rich front end for the agent.

``python -m namma_agent --tui`` gives the same agent (memory, tools, skills, model
picker, /commands, !shell) as every other channel, with live token streaming, a
status bar, an animated spinner and inline tool previews.

Layout and interaction model follow Hermes Agent's CLI (MIT — see
``namma_agent/skills/HERMES-LICENSE``); the artwork, palette wiring and every
integration point are Namma's own.

Modules:
  * :mod:`~namma_agent.tui.theme`   — palette, skins, color-depth degradation
  * :mod:`~namma_agent.tui.art`     — hero emblem + the name-driven wordmark
  * :mod:`~namma_agent.tui.banner`  — the welcome banner
  * :mod:`~namma_agent.tui.render`  — tool previews, spinner frames and faces
  * :mod:`~namma_agent.tui.app`     — the prompt_toolkit application
  * :mod:`~namma_agent.tui.cli`     — the argparse command surface
"""
