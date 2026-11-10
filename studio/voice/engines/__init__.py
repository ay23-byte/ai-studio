"""Engine registry: name → usable TTS backend.

``auto`` (the default) picks the best backend available on this machine:

1. local Chatterbox (GPU/CPU with the model installed)
2. a remote Chatterbox HTTP server (``CHATTERBOX_API_URL``)
3. edge-tts, the always-free fallback

The ``silent`` engine is never auto-selected; it exists for dry runs and tests.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

from studio.logs import get_logger
from studio.voice.engines.base import EngineUnavailable, TTSEngine

log = get_logger(__name__)

ENGINE_NAMES = ("chatterbox", "chatterbox-http", "edge", "silent")
_AUTO_ORDER = ("chatterbox", "chatterbox-http", "edge")


def _installed(module: str) -> bool:
    if module in sys.modules:  # already imported (or stubbed in tests)
        return sys.modules[module] is not None
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # pragma: no cover
        return False


def engine_status(name: str) -> tuple[bool, str]:
    """Return ``(available, human readable detail)`` for an engine name."""
    name = (name or "").strip().lower()
    if name == "chatterbox":
        if not _installed("chatterbox"):
            return False, "chatterbox-tts not installed (pip install chatterbox-tts)"
        if not _installed("torch"):
            return False, "torch not installed"
        return True, "local model ready"
    if name == "chatterbox-http":
        url = (os.getenv("CHATTERBOX_API_URL") or "").strip()
        return (True, f"remote {url}") if url else (False, "CHATTERBOX_API_URL not set")
    if name == "edge":
        return (True, "edge-tts installed") if _installed("edge_tts") else (
            False, "edge-tts not installed",
        )
    if name == "silent":
        return True, "dry-run engine (no audio)"
    return False, f"unknown engine {name!r}"


def available_engines() -> list[dict[str, Any]]:
    return [
        {"name": name, "available": engine_status(name)[0], "detail": engine_status(name)[1]}
        for name in ENGINE_NAMES
    ]


_ENGINE_OPTIONS: dict[str, set[str]] = {
    "chatterbox": {
        "model", "device", "t3_model", "ckpt_dir", "reference",
        "temperature", "top_p", "min_p", "repetition_penalty",
    },
    "chatterbox-http": {"base_url", "token", "timeout"},
    "edge": {"voice_hindi", "voice_english", "voice_female", "gender"},
    "silent": {"sample_rate"},
}


def build_engine(name: str, **options: Any) -> TTSEngine:
    """Instantiate an engine by name (no availability check).

    Unknown kwargs are dropped per engine so shared options such as
    ``device`` can be passed from the CLI without breaking every backend.
    """
    name = name.strip().lower()
    allowed = _ENGINE_OPTIONS.get(name, set())
    options = {key: value for key, value in options.items()
               if key in allowed and value is not None}
    if name == "chatterbox":
        from studio.voice.engines.chatterbox import ChatterboxEngine

        return ChatterboxEngine(**options)
    if name == "chatterbox-http":
        from studio.voice.engines.chatterbox_server import ChatterboxServerEngine

        return ChatterboxServerEngine(**options)
    if name == "edge":
        return _build_edge(**options)
    if name == "silent":
        from studio.voice.engines.silent import SilentEngine

        return SilentEngine(**options)
    raise EngineUnavailable(
        f"Unknown voice engine {name!r}. Choose from: {', '.join(ENGINE_NAMES)}"
    )


def _build_edge(**options: Any) -> TTSEngine:
    from studio.voice.engines.edge import EdgeEngine

    allowed = {"voice_hindi", "voice_english", "voice_female", "gender"}
    return EdgeEngine(**{k: v for k, v in options.items() if k in allowed})


def get_engine(engine: str | None = None, **options: Any) -> TTSEngine:
    """Resolve ``engine`` (or ``VOICE_ENGINE``) into a ready-to-use backend."""
    from studio import config

    requested = (engine or config.VOICE_ENGINE or "auto").strip().lower()
    if requested != "auto":
        ok, detail = engine_status(requested)
        if not ok:
            raise EngineUnavailable(f"Voice engine {requested!r} unavailable: {detail}")
        return build_engine(requested, **options)

    problems: list[str] = []
    for candidate in _AUTO_ORDER:
        ok, detail = engine_status(candidate)
        if ok:
            log.info("voice engine: %s (%s)", candidate, detail)
            return build_engine(candidate, **options)
        problems.append(f"  - {candidate}: {detail}")
    raise EngineUnavailable(
        "No usable voice engine found.\n"
        + "\n".join(problems)
        + "\nInstall Chatterbox (`pip install chatterbox-tts`), point "
        "CHATTERBOX_API_URL at a Chatterbox server, or `pip install edge-tts`."
    )


__all__ = [
    "ENGINE_NAMES", "TTSEngine", "EngineUnavailable", "get_engine",
    "build_engine", "engine_status", "available_engines",
]
