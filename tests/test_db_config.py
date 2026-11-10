"""Database and configuration contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from studio import config, db


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_root_points_at_repository():
    assert (config.ROOT / "studio" / "config.py").is_file()
    assert config.ROOT.name == "ai-studio"


def test_project_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_STUDIO_HOME", str(tmp_path))
    assert config.project_root() == tmp_path.resolve()


def test_ensure_directories_creates_tree(temp_config):
    config.ensure_directories()
    for path in (config.OUTPUT_DIR, config.BUILD_DIR, config.DB_PATH.parent,
                 config.MUSIC_DIR, config.CLIPS_DIR, config.VOICES_DIR):
        assert Path(path).is_dir()


# --------------------------------------------------------------------------- #
# database
# --------------------------------------------------------------------------- #
def test_save_update_and_fetch(temp_config):
    vid = db.save_video("Test title", "shorts", "hindi", "finance", {"title": "T"})
    assert vid > 0

    row = db.get_video(vid)
    assert row["title"] == "Test title"
    assert row["status"] == "pending"
    assert row["script_json"] == '{"title": "T"}'

    db.update_video(vid, status="done", video_path="/tmp/x.mp4")
    row = db.get_video(vid)
    assert row["status"] == "done"
    assert row["video_path"] == "/tmp/x.mp4"

    assert [r["id"] for r in db.list_videos()] == [vid]


def test_pending_upload_filters_built_videos(temp_config):
    built = db.save_video("Built", "shorts", "hindi", "finance", {})
    db.update_video(built, video_path="/tmp/built.mp4", status="done")
    uploaded = db.save_video("Uploaded", "shorts", "hindi", "finance", {})
    db.update_video(uploaded, video_path="/tmp/up.mp4", youtube_id="abc", status="uploaded")
    db.save_video("Not built", "shorts", "hindi", "finance", {})

    pending = db.pending_upload()
    assert [row["id"] for row in pending] == [built]


def test_update_rejects_unknown_columns(temp_config):
    vid = db.save_video("T", "shorts", "hindi", "finance", {})
    with pytest.raises(ValueError):
        db.update_video(vid, totes_not_a_column="x")


def test_get_missing_video_returns_none(temp_config):
    assert db.get_video(9999) is None
