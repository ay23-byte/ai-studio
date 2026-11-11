"""Microsoft edge-tts engine — free fallback when no Chatterbox runtime exists.

It is not as human as Chatterbox, but it keeps the pipeline usable on a laptop
or a CI runner with no GPU. The same pacing layer applies, so the timing,
pauses and emphasis behave identically.

Voice names are **discovered, not trusted**. Microsoft retires and renames voice
ids without notice; a pinned `hi-IN-MadhurNeural` then fails with
``No audio was received`` on every sentence. The engine therefore lists the
available voices once per build, probes the configured voice, and rotates to a
discovered voice for the same locale if the configured one is gone.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from pathlib import Path
from typing import Any

from studio import config
from studio.logs import get_logger
from studio.voice.engines.base import EngineUnavailable, TTSEngine, VoiceUnavailable
from studio.voice.types import PacingProfile, language_code

log = get_logger(__name__)

_LOCALE = {"hi": "hi-IN", "en": "en-IN"}
PROBE_TEXT = {
    "hi": "नमस्ते, यह आवाज़ की जाँच है।",
    "en": "Hello, this is a voice check.",
}
_RATE_RE = re.compile(r"^\s*([+-]?)(\d{1,3})\s*%\s*$")
_PITCH_RE = re.compile(r"^\s*([+-]?)(\d{1,3})\s*Hz\s*$", re.IGNORECASE)
_NETWORK_HINTS = (
    "cannot connect", "connection", "connect", "timeout", "timed out",
    "ssl", "getaddrinfo", "clientconnector", "network", "dns",
)
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_VOICES_TO_PROBE = 3


def normalise_rate(value: str | None) -> str:
    """edge-tts only accepts integers like ``+4%``; anything else becomes ``+0%``."""
    match = _RATE_RE.match(value or "")
    if not match:
        return "+0%"
    sign = match.group(1) or "+"
    amount = min(100, int(match.group(2)))
    return f"{sign}{amount}%"


def normalise_pitch(value: str | None) -> str:
    """edge-tts only accepts integers like ``-1Hz``; anything else becomes ``+0Hz``."""
    match = _PITCH_RE.match(value or "")
    if not match:
        return "+0Hz"
    sign = match.group(1) or "+"
    amount = min(100, int(match.group(2)))
    return f"{sign}{amount}Hz"


def _looks_like_network_error(message: str) -> bool:
    text = message.lower()
    return any(hint in text for hint in _NETWORK_HINTS)


def _is_no_audio_error(error: BaseException | str) -> bool:
    text = str(error).casefold()
    return "no audio was received" in text or "produced no audio" in text


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
        self._catalogue: list[dict[str, Any]] | None = None
        self._resolved: dict[str, str] = {}
        # A voice that returns the service's explicit no-audio response is
        # skipped for the rest of this build; other voices are tried per line.
        self._failed_voices: dict[str, set[str]] = {}

    @property
    def languages(self) -> tuple[str, ...]:  # type: ignore[override]
        return ("hi", "en")

    def pick_voice(self, language: str) -> str:
        if language_code(language) == "en":
            return self.voice_english
        if self.gender == "female":
            return self.voice_female
        return self.voice_hindi

    # ------------------------------------------------------------------ #
    # voice discovery
    # ------------------------------------------------------------------ #
    @property
    def _cache_path(self) -> Path:
        return Path(config.BUILD_DIR) / "edge_voices.json"

    def _read_cache(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        if time.time() - float(payload.get("fetched_at", 0)) > CACHE_TTL_SECONDS:
            return []
        voices = payload.get("voices")
        return voices if isinstance(voices, list) else []

    def _write_cache(self, voices: list[dict[str, Any]]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps({"fetched_at": time.time(), "voices": voices}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:  # caching is best-effort
            log.debug("edge: could not cache voice catalogue: %s", exc)

    def catalogue(self) -> list[dict[str, Any]]:
        """Available voices, cached for a week; empty when offline."""
        if self._catalogue is not None:
            return self._catalogue
        cached = self._read_cache()
        if cached:
            self._catalogue = cached
            return self._catalogue

        try:
            import edge_tts
        except ImportError:
            self._catalogue = []
            return self._catalogue

        try:
            result = edge_tts.list_voices()
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            voices = [v for v in result if isinstance(v, dict) and v.get("ShortName")]
        except Exception as exc:  # noqa: BLE001 - discovery is best effort
            log.warning("edge: could not list voices (%s); using configured names", exc)
            voices = []

        if voices:
            self._write_cache(voices)
        self._catalogue = voices
        return self._catalogue

    def candidates(self, language: str) -> list[str]:
        """Voices to try, configured name first, then discovered ones for the locale."""
        configured = self.pick_voice(language)
        locale = _LOCALE.get(language_code(language), "hi-IN")
        preferred_gender = "Female" if self.gender == "female" else "Male"

        names = [
            str(v["ShortName"]) for v in self.catalogue()
            if str(v.get("Locale", "")).lower() == locale.lower()
        ]
        by_gender = [
            str(v["ShortName"]) for v in self.catalogue()
            if str(v.get("Locale", "")).lower() == locale.lower()
            and str(v.get("Gender", "")).lower() == preferred_gender.lower()
        ]

        ordered: list[str] = []
        for name in [configured, *by_gender, *names]:
            if name and name not in ordered:
                ordered.append(name)
        return ordered or [configured]

    # ------------------------------------------------------------------ #
    # synthesis
    # ------------------------------------------------------------------ #
    async def _synth_async(self, text: str, voice: str, rate: str, pitch: str, path: Path) -> None:
        import edge_tts

        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))

    def _render(self, text: str, voice: str, rate: str, pitch: str, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            asyncio.run(self._synth_async(text, voice, rate, pitch, path))
        except ImportError as exc:
            raise EngineUnavailable("edge-tts is not installed (pip install edge-tts)") from exc
        except Exception as exc:  # noqa: BLE001 - classified by the caller
            path.unlink(missing_ok=True)
            raise exc
        if not path.exists() or path.stat().st_size == 0:
            raise VoiceUnavailable(f"edge-tts produced no audio for voice {voice}")
        return path

    def _candidate_voices(self, language: str) -> list[str]:
        """Order usable locale voices with the current winner first."""
        code = language_code(language)
        candidates = self.candidates(code)[:MAX_VOICES_TO_PROBE]
        failed = self._failed_voices.setdefault(code, set())
        available = [voice for voice in candidates if voice not in failed]
        # If every candidate returned no audio for earlier text, permit one new
        # round on the next retry; the service response can be transient.
        if not available:
            failed.clear()
            available = candidates
        resolved = self._resolved.get(code)
        if resolved in available:
            available.remove(resolved)
            available.insert(0, resolved)
        return available

    def _ensure_voice(self, language: str) -> str:
        """Probe voices once per language and cache the first one that speaks."""
        code = language_code(language)
        resolved = self._resolved.get(code)
        if resolved and resolved not in self._failed_voices.get(code, set()):
            return resolved

        configured = self.pick_voice(code)
        candidates = self._candidate_voices(code)
        probe = PROBE_TEXT.get(code, PROBE_TEXT["en"])
        errors: list[str] = []

        for voice in candidates:
            try:
                self._render(probe, voice, "+0%", "+0Hz", self._probe_path(language))
            except VoiceUnavailable as exc:
                self._failed_voices.setdefault(code, set()).add(voice)
                errors.append(str(exc))
                continue
            except EngineUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - network vs voice failure
                message = str(exc)
                if _looks_like_network_error(message):
                    raise EngineUnavailable(
                        f"edge-tts cannot reach the speech service: {message}"
                    ) from exc
                if _is_no_audio_error(exc):
                    self._failed_voices.setdefault(code, set()).add(voice)
                errors.append(f"{voice}: {message}")
                continue

            self._resolved[code] = voice
            if voice != configured:
                log.warning(
                    "edge: configured voice %s is unavailable; using discovered voice %s",
                    configured, voice,
                )
            else:
                log.info("edge: voice check passed for %s", voice)
            return voice

        raise VoiceUnavailable(
            "edge-tts could not produce audio with any configured or discovered "
            f"voice for {_LOCALE.get(language_code(language), language)}: "
            + "; ".join(errors[:MAX_VOICES_TO_PROBE])
            + ". Check that speech.platform.bing.com is reachable and that "
            "VOICE_HINDI / VOICE_ENGLISH name an existing voice."
        )

    def _probe_path(self, language: str) -> Path:
        return Path(config.BUILD_DIR) / "voice" / f"edge_probe_{language_code(language)}.mp3"

    def synth(
        self,
        text: str,
        out_path: Path,
        *,
        language: str = "hi",
        profile: PacingProfile,
        reference: Path | None = None,
    ) -> Path:
        code = language_code(language)
        original = self._ensure_voice(code)
        candidates = self._candidate_voices(code)
        failures: list[str] = []

        for voice in candidates:
            try:
                rendered = self._render(
                    text,
                    voice,
                    normalise_rate(profile.edge_rate),
                    normalise_pitch(profile.edge_pitch),
                    Path(out_path),
                )
            except Exception as exc:  # noqa: BLE001 - classify service failures
                message = str(exc)
                if _looks_like_network_error(message):
                    raise EngineUnavailable(
                        f"edge-tts cannot reach the speech service: {message}"
                    ) from exc
                if not _is_no_audio_error(exc):
                    if isinstance(exc, EngineUnavailable):
                        raise
                    raise EngineUnavailable(
                        f"edge-tts failed for voice {voice}: {message}"
                    ) from exc

                self._failed_voices.setdefault(code, set()).add(voice)
                failures.append(f"{voice}: {message}")
                log.warning(
                    "edge: voice %s returned no audio for this line; trying another locale voice",
                    voice,
                )
                continue

            self._resolved[code] = voice
            if voice != original:
                log.warning("edge: switched to %s after %s returned no audio", voice, original)
            return rendered

        self._resolved.pop(code, None)
        self._failed_voices.setdefault(code, set()).clear()
        raise EngineUnavailable(
            "edge-tts returned no audio for this sentence from all available "
            f"{_LOCALE.get(code, code)} voices; rotating the next attempt. "
            + "; ".join(failures[:MAX_VOICES_TO_PROBE])
        )

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "hindi": self.voice_hindi,
            "english": self.voice_english,
            "female": self.voice_female,
            "resolved": dict(self._resolved),
            "voices_discovered": len(self.catalogue()),
        }


__all__ = ["EdgeEngine", "normalise_rate", "normalise_pitch", "PROBE_TEXT"]
