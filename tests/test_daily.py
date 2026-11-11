"""Scheduled runner guards: QA gate before upload, freshness watchdog."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from studio import config, daily, db, qa
from studio.db import init_db, save_video, update_video


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp DB + output dir, and no Telegram traffic."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db" / "studio.sqlite")
    monkeypatch.setattr(db, "_SCHEMA_READY", False)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(daily, "send", lambda *a, **k: None)
    (tmp_path / "db").mkdir(parents=True, exist_ok=True)
    init_db()


def _built_video(tmp_path: Path, title: str = "Test video") -> tuple[int, Path]:
    path = tmp_path / "out" / "video.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 64)
    job = save_video(title, "shorts", "hindi", "finance", {"title": title})
    update_video(job, video_path=str(path), status="built")
    return job, path


def _set_created_at(job: int, hours_ago: int) -> None:
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "UPDATE videos SET created_at = datetime('now', ?) WHERE id = ?",
            (f"-{hours_ago} hours", job),
        )


# --------------------------------------------------------------------------- #
# QA gate
# --------------------------------------------------------------------------- #
def test_upload_blocked_when_qa_fails(tmp_path, monkeypatch):
    job, _ = _built_video(tmp_path)
    report = qa.QAReport(
        path=tmp_path / "out" / "video.mp4",
        checks=[qa.Check("audio level", False, "silent: -91.0 dBFS")],
    )
    monkeypatch.setattr(qa, "inspect_video", lambda *a, **k: report)

    assert daily.upload_latest() is False
    from studio.db import get_video

    assert "FAIL" in (get_video(job)["notes"] or "")


def test_upload_blocked_skips_google_import(tmp_path, monkeypatch):
    """The gate runs before any YouTube client is constructed."""
    _built_video(tmp_path)
    report = qa.QAReport(path=tmp_path / "x.mp4", checks=[qa.Check("duration", False, "0s")])
    monkeypatch.setattr(qa, "inspect_video", lambda *a, **k: report)
    import studio.publishing as publishing

    def explode(*args, **kwargs):
        raise AssertionError("upload must not be reached")

    monkeypatch.setattr(publishing, "upload", explode)
    assert daily.upload_latest() is False


def test_invalid_youtube_oauth_fails_cleanly_without_marking_video_uploaded(
    tmp_path, monkeypatch
):
    import studio.publishing as publishing
    from studio.db import get_video
    from studio.publishing import YouTubeAuthError

    job, video = _built_video(tmp_path)
    monkeypatch.setattr(
        qa,
        "inspect_video",
        lambda *a, **k: qa.QAReport(
            path=video,
            checks=[qa.Check("audio/video", True, "ok")],
            duration=12.0,
            mean_volume_db=-18.0,
        ),
    )
    monkeypatch.setattr(
        publishing,
        "upload",
        lambda *a, **k: (_ for _ in ()).throw(
            YouTubeAuthError("replace YT_REFRESH_TOKEN; no video was uploaded")
        ),
    )
    notifications = []
    monkeypatch.setattr(daily, "send", lambda message: notifications.append(message))

    assert daily.upload_latest() is False
    assert get_video(job)["youtube_id"] is None
    assert any("replace YT_REFRESH_TOKEN" in message for message in notifications)


def test_post_upload_scope_error_keeps_id_and_never_retries_upload(tmp_path, monkeypatch):
    import studio.publishing as publishing
    from studio.db import get_video
    from studio.publishing import YouTubeAuthError

    job, video = _built_video(tmp_path)
    monkeypatch.setattr(
        qa,
        "inspect_video",
        lambda *a, **k: qa.QAReport(
            path=video,
            checks=[qa.Check("audio/video", True, "ok")],
            duration=12.0,
            mean_volume_db=-18.0,
        ),
    )
    uploads = []

    def fake_upload(*args, **kwargs):
        uploads.append(True)
        return "already-uploaded-id"

    monkeypatch.setattr(publishing, "upload", fake_upload)
    monkeypatch.setattr(
        publishing,
        "wait_processed",
        lambda video_id: (_ for _ in ()).throw(
            YouTubeAuthError(
                f"video id {video_id} is already saved; do not upload it again"
            )
        ),
    )
    monkeypatch.setattr(daily, "send", lambda *a, **k: None)

    assert daily.upload_latest() is False
    assert get_video(job)["youtube_id"] == "already-uploaded-id"
    assert daily.upload_latest() is False
    assert len(uploads) == 1


def test_missing_file_is_recorded(tmp_path):
    job = save_video("gone", "shorts", "hindi", "finance", {})
    update_video(job, video_path=str(tmp_path / "missing.mp4"))
    assert daily.upload_latest() is False
    from studio.db import get_video

    assert "missing" in (get_video(job)["notes"] or "")


# --------------------------------------------------------------------------- #
# freshness watchdog
# --------------------------------------------------------------------------- #
def test_freshness_fails_without_uploads():
    assert daily.check_freshness(26) is False


def test_freshness_passes_for_recent_upload(tmp_path):
    job, _ = _built_video(tmp_path)
    update_video(job, youtube_id="abc123")
    assert daily.check_freshness(26) is True


def test_freshness_fails_for_stale_upload(tmp_path):
    job, _ = _built_video(tmp_path)
    update_video(job, youtube_id="abc123")
    _set_created_at(job, 40)
    assert daily.check_freshness(26) is False


def test_freshness_tolerates_rows_without_ids(tmp_path):
    _built_video(tmp_path)
    assert daily.check_freshness(26) is False
