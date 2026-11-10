"""Atomic output handling and collision-proof names."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from studio.artifacts import atomic_path, output_path, timestamp_slug


def test_output_path_is_timestamped_and_unique():
    moment = datetime(2026, 11, 10, 9, 45, 1, tzinfo=timezone.utc)
    first = output_path("shorts", 12, when=moment, output_dir="/tmp/out")
    second = output_path("shorts", 12, when=datetime(2026, 11, 10, 9, 45, 2),
                         output_dir="/tmp/out")
    assert first.name == "shorts_12_20261110-094501.mp4"
    assert first != second


def test_timestamp_slug_format():
    slug = timestamp_slug(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    assert slug == "20260102-030405"


def test_atomic_path_publishes_on_success(tmp_path):
    final = tmp_path / "video.mp4"
    with atomic_path(final) as temp:
        assert temp != final
        temp.write_bytes(b"rendered")
        assert not final.exists()
    assert final.read_bytes() == b"rendered"
    assert not temp.exists()


def test_atomic_path_removes_partial_on_failure(tmp_path):
    final = tmp_path / "video.mp4"
    with pytest.raises(RuntimeError, match="boom"):
        with atomic_path(final) as temp:
            temp.write_bytes(b"half")
            raise RuntimeError("boom")
    assert not final.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_path_rejects_empty_output(tmp_path):
    final = tmp_path / "video.mp4"
    with pytest.raises(RuntimeError, match="no bytes"):
        with atomic_path(final):
            pass
    assert not final.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_path_creates_parent(tmp_path):
    final = tmp_path / "nested" / "deeper" / "video.mp4"
    with atomic_path(final) as temp:
        temp.write_bytes(b"x")
    assert final.exists()
