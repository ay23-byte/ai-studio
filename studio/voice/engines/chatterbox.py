"""Chatterbox TTS engine (Resemble AI) — local model, voice cloning, expressive.

Upstream: https://github.com/resemble-ai/chatterbox  (``pip install chatterbox-tts``)

Two model families are supported:

* ``multilingual`` (default) — 23 languages including Hindi, loaded through
  ``chatterbox.mtl_tts.ChatterboxMultilingualTTS``.
* ``english`` / ``turbo`` / ``nano`` — English-only checkpoints.

Chatterbox generates best on short passages, so the assembler feeds it one
sentence at a time.  ``exaggeration`` adds energy, while a lower ``cfg_weight``
is the upstream-recommended way to make a fast-speaking reference sound natural
(see "Original Chatterbox Tips" in the README).  The per-utterance tempo and
pauses are applied later, in :mod:`studio.voice.assemble`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from studio.logs import get_logger
from studio.voice.engines.base import EngineUnavailable, TTSEngine
from studio.voice.types import PacingProfile, language_code

log = get_logger(__name__)

# Chatterbox speaks these languages with the multilingual checkpoint.
SUPPORTED_LANGUAGES = (
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
    "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
)
ENGLISH_ONLY_MODELS = ("english", "turbo", "nano")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _detect_device() -> str:
    explicit = _env("CHATTERBOX_DEVICE")
    if explicit:
        return explicit
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:  # pragma: no cover - torch optional
        pass
    return "cpu"


def _save_audio(wav: Any, sample_rate: int, path: Path) -> Path:
    """Persist a ``(1, N)`` waveform tensor, tolerating torchaudio gaps."""
    try:
        import torchaudio  # type: ignore

        torchaudio.save(str(path), wav, sample_rate)
        return path
    except Exception as exc:  # noqa: BLE001 - fall through to other writers
        log.debug("torchaudio.save failed (%s); trying soundfile", exc)

    try:
        import numpy as np  # type: ignore
        import soundfile as sf  # type: ignore

        array = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
        if array.ndim == 2:
            array = array.squeeze(0)
        sf.write(str(path), array, sample_rate)
        return path
    except Exception as exc:  # noqa: BLE001
        log.debug("soundfile failed (%s); falling back to raw wav writer", exc)

    import wave

    import numpy as np  # type: ignore

    array = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
    array = np.asarray(array, dtype="float32").squeeze()
    pcm = np.clip(array, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    return path


class ChatterboxEngine(TTSEngine):
    """In-process Chatterbox model with lazy loading and voice cloning."""

    name = "chatterbox"
    languages = SUPPORTED_LANGUAGES

    def __init__(
        self,
        *,
        model: str | None = None,
        device: str | None = None,
        t3_model: str | None = None,
        ckpt_dir: str | Path | None = None,
        reference: str | Path | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        min_p: float | None = None,
        repetition_penalty: float | None = None,
    ) -> None:
        self.model_kind = (model or _env("CHATTERBOX_MODEL", "multilingual")).lower()
        self.device = device or _detect_device()
        self.t3_model = t3_model or _env("CHATTERBOX_T3", "v3")
        self.ckpt_dir = Path(ckpt_dir) if ckpt_dir else (
            Path(_env("CHATTERBOX_CKPT_DIR")) if _env("CHATTERBOX_CKPT_DIR") else None
        )
        default_ref = _env("CHATTERBOX_REF") or _env("VOICE_REFERENCE")
        ref = reference or default_ref
        self.reference = Path(ref).expanduser() if ref else None
        self.temperature = _env_float("CHATTERBOX_TEMPERATURE", 0.8) if temperature is None else temperature
        self.top_p = _env_float("CHATTERBOX_TOP_P", 0.95) if top_p is None else top_p
        self.min_p = _env_float("CHATTERBOX_MIN_P", 0.05) if min_p is None else min_p
        self.repetition_penalty = (
            _env_float("CHATTERBOX_REPETITION_PENALTY", 1.2)
            if repetition_penalty is None else repetition_penalty
        )
        self._models: dict[str, Any] = {}

    # -- loading ---------------------------------------------------------- #
    @property
    def is_multilingual(self) -> bool:
        return self.model_kind not in ENGLISH_ONLY_MODELS

    def _load_class(self):
        try:
            if self.model_kind == "english":
                from chatterbox.tts import ChatterboxTTS  # type: ignore

                return ChatterboxTTS
            if self.model_kind in ("turbo", "nano"):
                from chatterbox.tts_turbo import ChatterboxTurboTTS  # type: ignore

                return ChatterboxTurboTTS
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # type: ignore

            return ChatterboxMultilingualTTS
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise EngineUnavailable(
                "Chatterbox is not installed. Run `pip install chatterbox-tts` "
                "(torch is pulled in automatically) or set CHATTERBOX_API_URL to "
                "use a remote Chatterbox server."
            ) from exc

    def _build_model(self, language: str):
        cls = self._load_class()
        log.info(
            "loading Chatterbox %s on %s (first call downloads weights)",
            self.model_kind, self.device,
        )
        if self.ckpt_dir:
            loader = getattr(cls, "from_local", None)
            if loader is None:
                raise EngineUnavailable(
                    f"{cls.__name__} has no from_local(); unset CHATTERBOX_CKPT_DIR "
                    "to use the Hugging Face checkpoint."
                )
            return loader(device=self.device, ckpt_dir=str(self.ckpt_dir))

        kwargs: dict[str, Any] = {"device": self.device}
        if self.model_kind in ("turbo", "nano"):
            kwargs["nano"] = self.model_kind == "nano"
        if self.is_multilingual and self.t3_model:
            kwargs["t3_model"] = self.t3_model
        try:
            return cls.from_pretrained(**kwargs)
        except TypeError:
            # Older chatterbox releases have a smaller from_pretrained signature.
            for optional in ("t3_model", "nano"):
                kwargs.pop(optional, None)
            return cls.from_pretrained(**kwargs)

    def _model_for(self, language: str):
        code = language_code(language)
        if not self.is_multilingual and code != "en":
            raise EngineUnavailable(
                f"CHATTERBOX_MODEL={self.model_kind} is English-only. "
                "Use CHATTERBOX_MODEL=multilingual (or the Hindi language pack) "
                "for Hindi/Hinglish narration."
            )
        key = code if self.is_multilingual else "en"
        if key not in self._models:
            self._models[key] = self._build_model(code)
        return self._models[key]

    def prepare(self) -> None:
        self._model_for("hi" if self.is_multilingual else "en")

    # -- generation ------------------------------------------------------- #
    def _generate(self, model, text: str, kwargs: dict[str, Any], language: str):
        attempts = [
            dict(kwargs),
            {k: v for k, v in kwargs.items() if k not in ("min_p", "top_p")},
            {k: v for k, v in kwargs.items()
             if k not in ("min_p", "top_p", "repetition_penalty", "temperature")},
            {k: v for k, v in kwargs.items()
             if k not in ("min_p", "top_p", "repetition_penalty", "temperature",
                          "exaggeration", "cfg_weight")},
        ]
        last_error: TypeError | None = None
        for attempt in attempts:
            try:
                return model.generate(text, **attempt)
            except TypeError as exc:
                last_error = exc
                log.debug("chatterbox.generate TypeError, retrying with fewer kwargs: %s", exc)
        raise RuntimeError(f"Chatterbox generate() rejected all argument sets: {last_error}")

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
        model = self._model_for(code)
        out_path = Path(out_path)

        kwargs: dict[str, Any] = {
            "exaggeration": profile.exaggeration,
            "cfg_weight": profile.cfg_weight,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "min_p": self.min_p,
            "repetition_penalty": self.repetition_penalty,
        }
        if self.is_multilingual:
            kwargs["language_id"] = code
        ref = Path(reference) if reference else self.reference
        if ref and ref.exists():
            kwargs["audio_prompt_path"] = str(ref)

        wav = self._generate(model, text, kwargs, code)
        sample_rate = int(getattr(model, "sr", 24000))
        return _save_audio(wav, sample_rate, out_path)

    def close(self) -> None:
        self._models.clear()
        try:
            import torch  # type: ignore

            if self.device == "cuda":
                torch.cuda.empty_cache()
        except Exception:  # pragma: no cover
            pass

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "model": self.model_kind,
            "device": self.device,
            "reference": str(self.reference) if self.reference else None,
            "multilingual": self.is_multilingual,
        }


__all__ = ["ChatterboxEngine", "SUPPORTED_LANGUAGES"]
