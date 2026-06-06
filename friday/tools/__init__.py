"""v2 capability tools with auto-discovery.

Each tool module exposes ``register(registry)``. :func:`load_tools` imports every
non-private submodule and calls it, so adding a tool file is all it takes to ship
a new capability — no intent regex, no catalog (the model routes from the schema).
"""
from __future__ import annotations

import importlib
import pkgutil

from friday.core.logger import logger
from friday.core.tools import ToolRegistry


def load_tools(registry: ToolRegistry) -> ToolRegistry:
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
            if hasattr(module, "register"):
                module.register(registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[tools] failed to load %s: %s", info.name, exc)
    return registry
