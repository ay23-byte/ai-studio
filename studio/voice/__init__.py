"""Human-sounding voice for AI Studio.

Quick start::

    from studio.voice import synthesize, SpeechChunk
    track = synthesize(
        [SpeechChunk("Inflation kya hai? Chalo simple example se samjhein.", "scene0")],
        build_dir="build/demo",
        language="hindi",
        engine="chatterbox",   # or "auto" / "chatterbox-http" / "edge"
        profile="fast",
    )
    print(track.path, track.duration, track.spans)

The pacing layer (pauses, breaths, tempo) is engine-independent, so switching
between a GPU-hosted Chatterbox model and the edge-tts fallback keeps the same
rhythm.
"""

from studio.voice.assemble import preview, synthesize
from studio.voice.engines import (
    EngineUnavailable,
    available_engines,
    build_engine,
    engine_status,
    get_engine,
)
from studio.voice.humanize import (
    build_utterances,
    normalize_text,
    split_sentences,
)
from studio.voice.types import (
    DEFAULT_PROFILE,
    PROFILES,
    PacingProfile,
    SpeechChunk,
    Timing,
    Utterance,
    VoiceTrack,
    get_profile,
    language_code,
)


def synthesise(text, build_dir, language="hindi", gender="male", **kwargs):
    """Legacy helper kept for older scripts.

    Returns ``(wav_path, [(start, end, sentence), ...])``.
    """
    engine = kwargs.pop("engine", None)
    if engine is None and gender == "female":
        engine = "edge"  # only edge-tts offers explicit gender selection
    track = synthesize(
        text, build_dir=build_dir, language=language, engine=engine, **kwargs
    )
    return track.path, [(t.start, t.end, t.text) for t in track.timings]


__all__ = [
    "synthesize", "synthesise", "preview", "get_engine", "build_engine",
    "available_engines", "engine_status", "EngineUnavailable", "PacingProfile",
    "PROFILES", "DEFAULT_PROFILE", "get_profile", "SpeechChunk", "Utterance",
    "Timing", "VoiceTrack", "language_code", "split_sentences",
    "normalize_text", "build_utterances",
]
