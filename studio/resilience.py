"""Retry helpers with exponential backoff and jitter.

Every network- and model-facing call in the studio goes through
:func:`retry_call` so a single transient failure never destroys a 30-minute
render that is already half finished.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from studio.logs import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class RetryExhausted(RuntimeError):
    """Raised when all attempts fail; keeps the original error attached."""

    def __init__(self, label: str, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"{label} failed after {attempts} attempts: {last_error}")
        self.label = label
        self.attempts = attempts
        self.last_error = last_error


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    give_up_on: tuple[type[BaseException], ...] = (),
    label: str = "operation",
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call ``func`` until it succeeds, with exponential backoff.

    ``KeyboardInterrupt``/``SystemExit`` are never swallowed because the
    default ``exceptions`` only covers ``Exception``.

    ``give_up_on`` lists errors that must not be retried at all — a retired
    Gemini model (HTTP 404) or a rejected credential cannot succeed on a second
    attempt, so retrying only wastes the backoff budget.
    """
    attempts = max(1, int(attempts))
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except give_up_on:
            raise
        except exceptions as exc:  # noqa: PERF203 - retry loop by design
            last_error = exc
            if attempt >= attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 1 + random.uniform(-jitter, jitter)
            delay = max(0.0, delay)
            log.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                label, attempt, attempts, exc, delay,
            )
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            time.sleep(delay)
    assert last_error is not None
    raise RetryExhausted(label, attempts, last_error) from last_error


__all__ = ["retry_call", "RetryExhausted"]
