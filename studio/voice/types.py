"""Data types shared by every TTS engine and the assembly layer."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

# --------------------------------------------------------------------------- #
# languages
# --------------------------------------------------------------------------- #
LANGUAGE_ALIASES = {
    "hi": "hi", "hindi": "hi", "हिन्दी": "hi", "हिंदी": "hi",
    "en": "en", "english": "en", "eng": "en",
    "hinglish": "hi", "hi-in": "hi", "en-in": "en",
    "mr": "mr", "marathi": "mr",
    "bn": "bn", "bengali": "bn",
    "ta": "ta", "tamil": "ta",
    "te": "te", "telugu": "te",
    "gu": "gu", "gujarati": "gu",
    "ur": "ur", "urdu": "ur",
}


def language_code(language: str | None) -> str:
    """Map free-form names (``hindi``, ``Hinglish``, ``hi-IN``) to ISO-639-1."""
    if not language:
        return "hi"
    key = language.strip().lower().replace("_", "-")
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    return key.split("-")[0]


# --------------------------------------------------------------------------- #
# pacing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PacingProfile:
    """How the voice should breathe, speed up and pause.

    ``speed`` is applied as an ``atempo`` factor after synthesis (pitch-safe),
    the pause values are seconds of silence inserted between sentences, and the
    ``*_jitter`` knobs add deterministic variation so the delivery never sounds
    metronomic.
    """

    name: str = "natural"
    speed: float = 1.0
    lead_in: float = 0.20
    sentence_pause: float = 0.30
    question_pause: float = 0.42
    exclaim_pause: float = 0.34
    paragraph_pause: float = 0.60
    pause_jitter: float = 0.18
    speed_jitter: float = 0.030
    breath_probability: float = 0.15
    emphasis_boost: float = 0.15
    trim_silence: bool = True
    # Chatterbox controls
    exaggeration: float = 0.50
    cfg_weight: float = 0.50
    temperature: float = 0.80
    # edge-tts controls
    edge_rate: str = "+0%"
    edge_pitch: str = "+0Hz"

    def clamp(self) -> "PacingProfile":
        return replace(
            self,
            speed=min(max(self.speed, 0.75), 1.5),
            exaggeration=min(max(self.exaggeration, 0.15), 1.8),
            cfg_weight=min(max(self.cfg_weight, 0.0), 1.0),
        )


PROFILES: dict[str, PacingProfile] = {
    # Balanced narration: the safe default for long-form.
    "natural": PacingProfile(name="natural"),
    # Shorts delivery: shorter gaps, ~8% faster tempo, slightly more energy.
    # Chatterbox's own guide recommends cfg_weight ~0.3 for a fast speaking
    # reference, which also tightens pacing.
    "fast": PacingProfile(
        name="fast", speed=1.08, lead_in=0.12, sentence_pause=0.20,
        question_pause=0.30, exclaim_pause=0.26, paragraph_pause=0.42,
        pause_jitter=0.22, speed_jitter=0.045, breath_probability=0.10,
        emphasis_boost=0.18, exaggeration=0.60, cfg_weight=0.30,
        edge_rate="+0%",
    ),
    # Punchy, high-retention Shorts.
    "energetic": PacingProfile(
        name="energetic", speed=1.12, lead_in=0.10, sentence_pause=0.18,
        question_pause=0.26, exclaim_pause=0.22, paragraph_pause=0.36,
        pause_jitter=0.25, speed_jitter=0.055, breath_probability=0.08,
        emphasis_boost=0.22, exaggeration=0.75, cfg_weight=0.35,
        edge_rate="+4%",
    ),
    # Calm explainer.
    "documentary": PacingProfile(
        name="documentary", speed=0.97, lead_in=0.28, sentence_pause=0.38,
        question_pause=0.50, exclaim_pause=0.38, paragraph_pause=0.75,
        pause_jitter=0.14, speed_jitter=0.02, breath_probability=0.25,
        emphasis_boost=0.10, exaggeration=0.45, cfg_weight=0.55,
        edge_rate="-4%", edge_pitch="-1Hz",
    ),
}

DEFAULT_PROFILE = "natural"


def get_profile(profile: PacingProfile | str | None) -> PacingProfile:
    if isinstance(profile, PacingProfile):
        return profile.clamp()
    name = (profile or DEFAULT_PROFILE).strip().lower()
    if name not in PROFILES:
        raise ValueError(
            f"Unknown voice profile {name!r}. Choose one of: {', '.join(PROFILES)}"
        )
    return PROFILES[name]


# --------------------------------------------------------------------------- #
# speech units
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SpeechChunk:
    """A unit of script text that maps onto one scene or section."""

    text: str
    tag: str = ""


@dataclass(frozen=True)
class Utterance:
    """One sentence ready for the synthesizer."""

    text: str
    pause_after: float = 0.0
    speed: float = 1.0
    exaggeration: float | None = None
    cfg_weight: float | None = None
    emphasis: bool = False
    breath_after: bool = False
    tag: str = ""


@dataclass(frozen=True)
class Timing:
    """Where a sentence sits on the final timeline."""

    start: float
    end: float
    text: str
    tag: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class VoiceTrack:
    """Result of a full voice build."""

    path: Path
    duration: float
    timings: list[Timing] = field(default_factory=list)
    spans: dict[str, tuple[float, float]] = field(default_factory=dict)
    engine: str = ""
    profile: str = ""
    utterances: list[Utterance] = field(default_factory=list)

    def span(self, tag: str) -> tuple[float, float] | None:
        return self.spans.get(tag)

    def timings_for(self, tag: str) -> list[Timing]:
        return [t for t in self.timings if t.tag == tag]


__all__ = [
    "LANGUAGE_ALIASES", "language_code", "PacingProfile", "PROFILES",
    "DEFAULT_PROFILE", "get_profile", "SpeechChunk", "Utterance", "Timing",
    "VoiceTrack",
]
