"""Engine contract shared by Chatterbox, edge-tts and the silent engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from studio.voice.types import PacingProfile, language_code


class EngineUnavailable(RuntimeError):
    """Raised when an engine is requested but cannot run on this machine."""


class VoiceUnavailable(EngineUnavailable):
    """No voice could speak this language.

    Distinct from :class:`EngineUnavailable` because retrying the same sentence
    against the same dead voice can never succeed — the retry layer gives up
    immediately and the build fails with a clear, actionable message.
    """


class TTSEngine(ABC):
    """Minimal interface: say one sentence, write one audio file.

    Engines are deliberately dumb. Pacing, pauses, breaths and loudness are
    handled by :mod:`studio.voice.assemble` so every backend sounds consistent.
    """

    name: str = "base"
    #: Languages the backend can speak (ISO-639-1). Empty means "no claim".
    languages: tuple[str, ...] = ()
    #: True when the engine writes 44.1 kHz mono wav already.
    native_wav: bool = False
    #: File suffix the engine writes (edge-tts emits mp3).
    output_suffix: str = ".wav"

    def supports(self, language: str) -> bool:
        return not self.languages or language_code(language) in self.languages

    @abstractmethod
    def synth(
        self,
        text: str,
        out_path: Path,
        *,
        language: str = "hi",
        profile: PacingProfile,
        reference: Path | None = None,
    ) -> Path:
        """Synthesize ``text`` and return the written file."""

    def prepare(self) -> None:
        """Optional warm-up (model loading, connection checks)."""

    def close(self) -> None:
        """Release any heavy resources."""

    def __enter__(self) -> "TTSEngine":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def describe(self) -> dict[str, object]:
        return {"name": self.name, "languages": list(self.languages)}


__all__ = ["TTSEngine", "EngineUnavailable"]
