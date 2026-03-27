"""Structured JSON logging helper for the Pantry-to-Plate backend.

Usage::

    from backend.utils.log_config import get_logger

    logger = get_logger(__name__)
    logger.info("search complete", extra={"session_id": sid, "duration_ms": 120.4})

Each call to ``get_logger`` returns a standard ``logging.Logger`` whose handler
emits a single JSON line to *stderr* per record.  Loggers do **not** propagate
to the root logger, so multiple ``get_logger`` calls for the same name are safe
and idempotent (the handler is only attached once).

Log level is read from the ``LOG_LEVEL`` environment variable (default
``"INFO"``).  Any unrecognised value falls back to ``INFO``.

JSON fields emitted per record:

* ``timestamp`` — ISO-8601 UTC, millisecond precision (``2026-03-27T14:05:01.123Z``)
* ``level``     — ``"INFO"``, ``"WARNING"``, ``"ERROR"``, etc.
* ``name``      — logger name (typically ``__name__`` of the calling module)
* ``message``   — formatted log message
* ``session_id``    — included when passed as ``extra={"session_id": ...}``
* ``current_step``  — included when passed as ``extra={"current_step": ...}``
* ``duration_ms``   — included when passed as ``extra={"duration_ms": ...}``
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

_EXTRA_KEYS: tuple[str, ...] = ("session_id", "current_step", "duration_ms")


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Standard fields (timestamp, level, name, message) are always present.
    Optional extra fields (session_id, current_step, duration_ms) are
    included only when the caller passes them via ``extra={...}``.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{record.msecs:03.0f}Z"
        )
        payload: dict = {
            "timestamp": ts,
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        for key in _EXTRA_KEYS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a JSON-structured logger for *name*.

    The logger is configured on first call and returned as-is on subsequent
    calls with the same name (idempotent — handlers are never duplicated).

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A ``logging.Logger`` writing JSON lines to *stderr*.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    return logger
