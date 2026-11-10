"""Tiny logging facade so library code never has to print.

``configure()`` is called once by the CLI; modules simply do::

    from studio.logs import get_logger
    log = get_logger(__name__)
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-7s %(name)-24s %(message)s"


class _Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 - stdlib API
        return super().formatTime(record, "%H:%M:%S")


def configure(verbose: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter(_FORMAT))
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
