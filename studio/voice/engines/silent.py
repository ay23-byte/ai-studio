"""Silent engine: timed silence instead of speech.

Used for dry runs and tests so the render pipeline can be exercised with no
model, no network and no GPU. Duration follows the same word-rate estimate as a
real narrator, which keeps captions and cuts in the right ballpark.
"""

from __future__ import annotations

import wave
from pathlib import Path

from studio.voice.engines.base import TTSEngine
from studio.voice.humanize import estimate_speech_seconds
from studio.voice.types import PacingProfile

SAMPLE_RATE = 44100


class SilentEngine(TTSEngine):
    name = "silent"
    native_wav = True

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate

    def synth(
        self,
        text: str,
        out_path: Path,
        *,
        language: str = "hi",
        profile: PacingProfile,
        reference: Path | None = None,
    ) -> Path:
        out_path = Path(out_path)
        seconds = estimate_speech_seconds(text, language, profile.speed)
        frames = int(seconds * self.sample_rate)
        with wave.open(str(out_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.sample_rate)
            handle.writeframes(b"\x00\x00" * frames)
        return out_path

    def supports(self, language: str) -> bool:  # noqa: ARG002 - speaks anything
        return True

    def describe(self) -> dict[str, object]:
        return {"name": self.name, "language_agnostic": True}
