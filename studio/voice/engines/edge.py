"""Microsoft edge-tts engine — free fallback when no Chatterbox runtime exists.

It is not as human as Chatterbox, but it keeps the pipeline usable on a laptop
or a CI runner with no GPU. The same pacing layer applies, so the timing,
pauses and emphasis behave identically.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from studio import config
from studio.logs import get_logger
from studio.voice.engines.base import EngineUnavailable, TTSEngine
from studio.voice.types import PacingProfile, language_code

log = get_logger(__name__)


class EdgeEngine(TTSEngine):
    name = "edge"
    output_suffix = ".mp3"

    def __init__(
        self,
        voice_hindi: str | None = None,
        voice_english: str | None = None,
        voice_female: str | None = None,
        gender: str = "male",
    ) -> None:
        self.voice_hindi = voice_hindi or config.VOICE_HINDI
        self.voice_english = voice_english or config.VOICE_ENGLISH
        self.voice_female = voice_female or config.VOICE_FEMALE
        self.gender = gender

    @property
    def languages(self) -> tuple[str, ...]:  # type: ignore[override]
        return ("hi", "en")

    def pick_voice(self, language: str) -> str:
        if language_code(language) == "en":
            return self.voice_english
        if self.gender == "female":
            return self.voice_female
        return self.voice_hindi

    async def _synth_async(self, text: str, voice: str, rate: str, pitch: str, path: Path) -> None:
        import edge_tts

        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))

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
        voice = self.pick_voice(language)
        try:
            asyncio.run(
                self._synth_async(text, voice, profile.edge_rate, profile.edge_pitch, out_path)
            )
        except ImportError as exc:  # pragma: no cover
            raise EngineUnavailable("edge-tts is not installed (pip install edge-tts)") from exc
        except Exception as exc:  # network / service errors
            raise EngineUnavailable(f"edge-tts failed for voice {voice}: {exc}") from exc
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise EngineUnavailable("edge-tts produced no audio")
        return out_path

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "hindi": self.voice_hindi,
            "english": self.voice_english,
            "female": self.voice_female,
        }


__all__ = ["EdgeEngine"]
