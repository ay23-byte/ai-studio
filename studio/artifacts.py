"""Collision-proof artefact names and atomic writes.

Rendering straight to ``output/shorts_3.mp4`` is risky: a timeout leaves a
truncated file that looks publishable, and job ids restart when the database is
recreated. Outputs are therefore written to a temporary sibling and renamed
atomically, and carry a timestamp as well as the job id.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from studio import config
from studio.logs import get_logger

log = get_logger(__name__)


def timestamp_slug(when: datetime | None = None) -> str:
    return (when or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")


def output_path(
    kind: str,
    job_id: int,
    *,
    suffix: str = ".mp4",
    when: datetime | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """``output/shorts_12_20261110-094501.mp4`` — unique across DB resets."""
    directory = Path(output_dir) if output_dir else Path(config.OUTPUT_DIR)
    return directory / f"{kind}_{job_id}_{timestamp_slug(when)}{suffix}"


@contextmanager
def atomic_path(final: str | Path) -> Iterator[Path]:
    """Yield a temporary path; rename to ``final`` only on success.

    On any exception the partial file is deleted, so ``output/`` never holds a
    half-written video that a watchdog could try to upload.
    """
    final = Path(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    temp = final.with_name(f".{final.stem}.{uuid.uuid4().hex[:8]}.part{final.suffix}")
    try:
        yield temp
        if not temp.exists() or temp.stat().st_size == 0:
            raise RuntimeError(f"renderer produced no bytes for {final.name}")
        os.replace(temp, final)
        log.debug("published %s (%s bytes)", final, final.stat().st_size)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


__all__ = ["timestamp_slug", "output_path", "atomic_path"]
