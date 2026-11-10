"""Post-render quality gate.

A render can "succeed" and still be unpublishable: silent audio, a truncated
file, wrong orientation, or a duration that does not match the narration.
:func:`inspect_video` checks all of that before an upload is attempted.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.logs import get_logger
from studio.media import ffmpeg

log = get_logger(__name__)

MIN_BYTES = 20_000
MIN_MEAN_VOLUME_DB = -45.0
EXPECTED_KIND = {
    "shorts": (1080, 1920),
    "longform": (1920, 1080),
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class QAReport:
    path: Path
    checks: list[Check] = field(default_factory=list)
    duration: float = 0.0
    expected: float | None = None
    width: int | None = None
    height: int | None = None
    mean_volume_db: float | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.ok]

    def summary(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        lines = [f"{head} {self.path.name} ({self.duration:.2f}s)"]
        lines += [f"  {'✓' if c.ok else '✗'} {c.name}: {c.detail}" for c in self.checks]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "ok": self.ok,
            "duration": round(self.duration, 3),
            "expected": self.expected,
            "width": self.width,
            "height": self.height,
            "mean_volume_db": self.mean_volume_db,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
        }


def _ffmpeg_banner(path: Path) -> str:
    binary = ffmpeg.ffmpeg_bin()
    if not binary:
        return ""
    proc = subprocess.run([binary, "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, check=False)
    return proc.stderr


def _streams(path: Path) -> tuple[bool, bool, int | None, int | None]:
    """(has_video, has_audio, width, height) best effort."""
    banner = _ffmpeg_banner(path)
    has_video = "Video:" in banner
    has_audio = "Audio:" in banner
    width = height = None
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", banner)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
    return has_video, has_audio, width, height


def mean_volume_db(path: Path) -> float | None:
    """Mean loudness in dBFS, or ``None`` when ffmpeg cannot report it."""
    binary = ffmpeg.ffmpeg_bin()
    if not binary:
        return None
    proc = subprocess.run(
        [binary, "-hide_banner", "-i", str(path), "-map", "0:a:0",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", proc.stderr)
    return float(match.group(1)) if match else None


def inspect_video(
    path: str | Path,
    *,
    expected_seconds: float | None = None,
    kind: str | None = None,
    require_audio: bool = True,
    require_sound: bool = True,
    min_mean_volume_db: float = MIN_MEAN_VOLUME_DB,
) -> QAReport:
    """Run all publish-readiness checks on one rendered file."""
    path = Path(path)
    report = QAReport(path=path, expected=expected_seconds)

    if not path.is_file():
        report.checks.append(Check("file", False, "missing"))
        return report
    size = path.stat().st_size
    report.checks.append(
        Check("file", size >= MIN_BYTES, f"{size / 1024:.0f} KiB")
    )

    report.duration = ffmpeg.duration(path)
    report.checks.append(
        Check("duration", report.duration > 0.5, f"{report.duration:.2f}s")
    )

    has_video, has_audio, width, height = _streams(path)
    report.width, report.height = width, height
    report.checks.append(Check("video stream", has_video, f"{width}x{height}" if width else ""))
    if require_audio:
        report.checks.append(Check("audio stream", has_audio, "present" if has_audio else "missing"))

    if has_video and kind in EXPECTED_KIND and width and height:
        expected_w, expected_h = EXPECTED_KIND[kind]
        orientation_ok = (width, height) == (expected_w, expected_h)
        report.checks.append(
            Check("resolution", orientation_ok, f"{width}x{height} (want {expected_w}x{expected_h})")
        )

    if expected_seconds and report.duration > 0:
        tolerance = max(3.0, expected_seconds * 0.20)
        delta = abs(report.duration - expected_seconds)
        report.checks.append(
            Check("duration match", delta <= tolerance,
                  f"{report.duration:.1f}s vs expected {expected_seconds:.1f}s (±{tolerance:.1f})")
        )

    if require_audio and has_audio and require_sound:
        report.mean_volume_db = mean_volume_db(path)
        if report.mean_volume_db is None:
            report.checks.append(Check("audio level", True, "unavailable (not verified)"))
        else:
            report.checks.append(
                Check("audio level", report.mean_volume_db > min_mean_volume_db,
                      f"mean {report.mean_volume_db:.1f} dBFS")
            )
    return report


__all__ = [
    "Check", "QAReport", "inspect_video", "mean_volume_db",
    "MIN_MEAN_VOLUME_DB", "MIN_BYTES",
]
