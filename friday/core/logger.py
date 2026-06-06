"""Package-local logger for FRIDAY v2.

Self-contained so the new ``friday/`` package has no dependency on the legacy
``core/`` tree (which is removed in the Phase 8 purge). Honors the
``FRIDAY_LOG_LEVEL`` env var (default ``INFO``).
"""
from __future__ import annotations

import logging
import os
import sys

_LEVEL = os.environ.get("FRIDAY_LOG_LEVEL", "INFO").upper()

logger = logging.getLogger("friday")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
    logger.propagate = False
