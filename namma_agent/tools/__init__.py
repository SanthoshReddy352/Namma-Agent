"""v2 capability tools with auto-discovery.

Each tool module exposes ``register(registry)``. :func:`load_tools` imports every
non-private submodule and calls it, so adding a tool file is all it takes to ship
a new capability — no intent regex, no catalog (the model routes from the schema).
"""
from __future__ import annotations

import importlib
import pkgutil

from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry


def load_tools(registry: ToolRegistry) -> ToolRegistry:
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
            if hasattr(module, "register"):
                # Each tool module is a toolset; its name groups the tools it
                # registers (file_ops, shell, web, browser, vision, …) in the
                # Toolsets tab. A module may still set its own category per tool.
                with registry.categorize(info.name):
                    module.register(registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[tools] failed to load %s: %s", info.name, exc)
    # Load any tools the agent authored itself (~/.namma_agent/tools).
    try:
        from namma_agent.tools.authoring import load_user_tools

        with registry.categorize("custom"):
            load_user_tools(registry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tools] user-tool load failed: %s", exc)
    return registry
