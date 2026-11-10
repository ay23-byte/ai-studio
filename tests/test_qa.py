"""Publish-readiness gate: catch silent, truncated or mis-shaped renders."""

from __future__ import annotations

from pathlib import Path

from studio.media import ffmpeg
from studio.qa import inspect_video
from tests.conftest import requires_ffmpeg

W, H = 1080, 1920


def _render(path: Path, *, audio: str = "tone", seconds: float = 4.0,
            size: str = f"{W}x{H}") -> Path:
    if audio == "tone":
        audio_args = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        codec = ["-c:a", "aac", "-b:a", "128k"]
    elif audio == "silence":
        audio_args = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={seconds}"]
        codec = ["-c:a", "aac", "-b:a", "128k"]
    else:
        audio_args = []
        codec = []
    ffmpeg.run([
        "-f", "lavfi", "-i", f"color=c=0x0a1a3a:s={size}:d={seconds}",
        *audio_args,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        *codec, "-shortest", path,
    ])
    return path


@requires_ffmpeg
def test_good_short_passes(tmp_path):
    path = _render(tmp_path / "good.mp4")
    report = inspect_video(path, expected_seconds=4.0, kind="shorts")
    assert report.ok, report.summary()
    assert report.width == W and report.height == H
    assert report.mean_volume_db is not None


@requires_ffmpeg
def test_silent_audio_is_blocked(tmp_path):
    path = _render(tmp_path / "silent.mp4", audio="silence")
    report = inspect_video(path)
    assert not report.ok
    assert any(check.name == "audio level" for check in report.failures)


@requires_ffmpeg
def test_wrong_orientation_is_blocked(tmp_path):
    path = _render(tmp_path / "landscape.mp4", size="1920x1080")
    report = inspect_video(path, kind="shorts")
    assert not report.ok
    assert any(check.name == "resolution" for check in report.failures)


@requires_ffmpeg
def test_duration_mismatch_is_blocked(tmp_path):
    path = _render(tmp_path / "short.mp4", seconds=3.0)
    report = inspect_video(path, expected_seconds=25.0)
    assert not report.ok
    assert any(check.name == "duration match" for check in report.failures)


def test_missing_file_fails(tmp_path):
    report = inspect_video(tmp_path / "nope.mp4")
    assert not report.ok
    assert report.failures[0].detail == "missing"


@requires_ffmpeg
def test_report_serialises(tmp_path):
    path = _render(tmp_path / "good.mp4")
    payload = inspect_video(path).to_dict()
    assert payload["ok"] is True
    assert payload["checks"]
    assert payload["path"].endswith("good.mp4")
