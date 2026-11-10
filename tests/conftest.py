"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio import config, db  # noqa: E402
from studio.media.ffmpeg import has_ffmpeg  # noqa: E402

requires_ffmpeg = pytest.mark.skipif(not has_ffmpeg(), reason="ffmpeg not installed")


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Point every writable path at a tmp dir so tests never touch the repo."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(config, "DB_DIR", tmp_path / "db")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db" / "studio.sqlite")
    monkeypatch.setattr(config, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "assets" / "music")
    monkeypatch.setattr(config, "CLIPS_DIR", tmp_path / "assets" / "clips")
    monkeypatch.setattr(config, "VOICES_DIR", tmp_path / "assets" / "voices")
    monkeypatch.setattr(config, "TOPICS_PATH", tmp_path / "topics.json")
    monkeypatch.setattr(db, "_SCHEMA_READY", False)
    config.ensure_directories()
    return tmp_path
