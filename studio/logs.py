"""Tiny logging facade so library code never has to print.

``configure()`` is called once by the CLI; modules simply do::

    from studio.logs import get_logger
    log = get_logger(__name__)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-7s %(name)-24s %(message)s"


class _Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 - stdlib API
        return super().formatTime(record, "%H:%M:%S")


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, for log shippers and CI forensics."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": os.getenv("STUDIO_RUN_ID", ""),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(verbose: bool = False, json_logs: bool | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    if json_logs is None:
        json_logs = os.getenv("STUDIO_LOG_FORMAT", "").strip().lower() == "json"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if json_logs else _Formatter(_FORMAT))
    root = logging.getLogger("studio")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    root.propagate = False
    # Third-party libraries are chatty at INFO level.
    for noisy in ("urllib3", "requests", "httpx", "googleapiclient"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, auto-configuring on first use."""
    if not _CONFIGURED:
        configure(verbose=os.getenv("STUDIO_DEBUG", "").lower() in {"1", "true", "yes"})
    if not name.startswith("studio"):
        name = f"studio.{name.rsplit('.', 1)[-1]}"
    return logging.getLogger(name)
