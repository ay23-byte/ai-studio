"""SQLite persistence for jobs and videos.

The schema is created lazily on first connection, so importing this module has
no side effects and the database lives wherever ``DB_PATH`` points.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from studio import config
from studio.logs import get_logger

log = get_logger(__name__)
_SCHEMA_READY = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now')),
    title       TEXT,
    format      TEXT,
    language    TEXT,
    category    TEXT,
    status      TEXT DEFAULT 'pending',
    script_json TEXT,
    video_path  TEXT,
    thumb_path  TEXT,
    youtube_id  TEXT,
    notes       TEXT
);
CREATE TABLE IF NOT EXISTS topics (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    title    TEXT UNIQUE,
    category TEXT,
    used     INTEGER DEFAULT 0,
    approved INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
"""


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Yield a committed connection, closing it afterwards."""
    global _SCHEMA_READY
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if not _SCHEMA_READY:
            conn.executescript(_SCHEMA)
            conn.commit()
            _SCHEMA_READY = True
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_conn() -> sqlite3.Connection:
    """Legacy accessor: a plain connection with the schema in place.

    Prefer :func:`connection` in new code.
    """
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def init_db() -> None:
    with connection():
        pass


def save_video(
    title: str,
    fmt: str,
    lang: str,
    category: str,
    script: dict[str, Any],
    status: str = "pending",
) -> int:
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO videos (title,format,language,category,status,script_json)"
            " VALUES (?,?,?,?,?,?)",
            (title, fmt, lang, category, status, json.dumps(script, ensure_ascii=False)),
        )
        vid = int(cur.lastrowid or 0)
    log.info("job #%s queued (%s / %s)", vid, fmt, category)
    return vid


def update_video(vid_id: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "title", "format", "language", "category", "status",
        "script_json", "video_path", "thumb_path", "youtube_id", "notes",
    }
    cols = {k: v for k, v in fields.items() if k in allowed}
    if not cols:
        raise ValueError(f"No updatable columns in {sorted(fields)}")
    assignments = ", ".join(f"{k}=?" for k in cols)
    with connection() as conn:
        conn.execute(f"UPDATE videos SET {assignments} WHERE id=?", (*cols.values(), vid_id))


def list_videos(limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_video(vid_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id=?", (vid_id,)).fetchone()
    return dict(row) if row else None


def pending_upload() -> list[dict[str, Any]]:
    """Built videos that have not been published yet, newest first."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE video_path IS NOT NULL AND video_path != ''"
            " AND (youtube_id IS NULL OR youtube_id = '') ORDER BY id DESC LIMIT 10"
        ).fetchall()
    return [dict(r) for r in rows]


__all__ = [
    "connection", "get_conn", "init_db", "save_video", "update_video",
    "list_videos", "get_video", "pending_upload",
]
