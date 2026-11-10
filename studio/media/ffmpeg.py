"""Thin, dependency-light wrapper around the ffmpeg / ffprobe binaries.

Resolution order for the binaries:

1. ``FFMPEG_BIN`` / ``FFPROBE_BIN`` environment variables
2. ``ffmpeg`` / ``ffprobe`` on ``PATH``
3. the static build shipped by ``imageio-ffmpeg``, when installed

Media duration falls back to the standard-library ``wave`` module or to parsing
``ffmpeg -i`` output, which keeps the project usable on machines without
ffprobe.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

from studio.logs import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def ffmpeg_bin() -> str | None:
    explicit = os.getenv("FFMPEG_BIN")
    if explicit:
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # optional convenience dependency
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - depends on the host
        return None


@lru_cache(maxsize=1)
def ffprobe_bin() -> str | None:
    explicit = os.getenv("FFPROBE_BIN")
    if explicit:
        return explicit
    return shutil.which("ffprobe")


def has_ffmpeg() -> bool:
    return ffmpeg_bin() is not None


def require_ffmpeg() -> str:
    binary = ffmpeg_bin()
    if not binary:
        raise RuntimeError(
            "ffmpeg was not found. Install it (apt install ffmpeg / brew install ffmpeg) "
            "or `pip install imageio-ffmpeg`."
        )
    return binary


def run(args: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    """Run ffmpeg with ``-y -loglevel error`` prepended."""
    binary = require_ffmpeg()
    cmd = [binary, "-y", "-loglevel", "error", *[str(a) for a in args]]
    log.debug("ffmpeg %s", " ".join(str(a) for a in args)[:400])
    return subprocess.run(cmd, check=check, timeout=timeout, capture_output=True, text=True)


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Run a fully formed command, swapping in the resolved ffmpeg binary."""
    resolved = require_ffmpeg()
    argv = [resolved, *[str(a) for a in cmd[1:]]] if cmd else cmd
    log.debug("cmd %s", " ".join(str(a) for a in argv)[:400])
    return subprocess.run(argv, check=check, capture_output=True, text=True)


def _wav_duration(path: Path) -> float | None:
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as handle:
            rate = handle.getframerate() or 1
            return handle.getnframes() / float(rate)
    except Exception:
        return None


def duration(path: str | Path) -> float:
    """Duration of a media file in seconds (0.0 when it cannot be determined)."""
    path = Path(path)
    if not path.exists():
        return 0.0
    probe = ffprobe_bin()
    if probe:
        try:
            out = subprocess.check_output(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            value = float(out)
            if value > 0:
                return value
        except Exception:
            pass
    if path.suffix.lower() == ".wav":
        value = _wav_duration(path)
        if value:
            return value
    binary = ffmpeg_bin()
    if binary:
        proc = subprocess.run([binary, "-i", str(path)], capture_output=True,
                              text=True, check=False)
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0.0


def has_audio_stream(path: str | Path) -> bool:
    probe = ffprobe_bin()
    if probe:
        try:
            out = subprocess.check_output(
                [probe, "-v", "error", "-select_streams", "a", "-show_entries",
                 "stream=index", "-of", "csv=p=0", str(path)],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            return bool(out)
        except Exception:
            return False
    return True  # assume yes; callers use this only for diagnostics


def image_size(path: str | Path) -> tuple[int, int]:
    """(width, height) of the first video/image stream."""
    probe = ffprobe_bin()
    if probe:
        try:
            out = subprocess.check_output(
                [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", str(path)],
                text=True, stderr=subprocess.DEVNULL,
            ).strip().split(",")
            return int(out[0]), int(out[1])
        except Exception:
            pass  # fall back to parsing ffmpeg's banner

    binary = ffmpeg_bin()
    if binary:
        proc = subprocess.run([binary, "-i", str(path)], capture_output=True,
                              text=True, check=False)
        match = re.search(r"(\d{2,5})x(\d{2,5})[\s,\[]", proc.stderr)
        if match:
            return int(match.group(1)), int(match.group(2))
    raise RuntimeError(f"Cannot determine dimensions of {path}")


def to_wav(src: str | Path, dst: str | Path, *, sample_rate: int = 44100, channels: int = 1) -> Path:
    """Decode any media file to 16-bit PCM wav."""
    dst = Path(dst)
    run(["-i", src, "-ar", sample_rate, "-ac", channels, "-c:a", "pcm_s16le", dst])
    return dst


__all__ = [
    "ffmpeg_bin", "ffprobe_bin", "has_ffmpeg", "require_ffmpeg", "run",
    "run_cmd", "duration", "has_audio_stream", "image_size", "to_wav",
]
