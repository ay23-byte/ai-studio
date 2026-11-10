"""Assemble a narration track from planned utterances.

Pipeline per sentence: synthesize → decode to 44.1 kHz mono → trim model
silence → apply tempo → micro-fades.  Then all sentences are concatenated with
the planned pauses, optional breath samples are mixed into the gaps, and the
whole track gets EQ, gentle compression and broadcast loudness.

Synthesis results are cached in ``<build>/voice/`` keyed by a hash of the text
and voice settings, so rebuilding a video after a visual tweak is instant.
"""

from __future__ import annotations

import hashlib
import json
import os
import wave
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from studio.artifacts import atomic_path
from studio.logs import get_logger
from studio.media import ffmpeg
from studio.resilience import RetryExhausted, retry_call
from studio.voice.engines import get_engine
from studio.voice.engines.base import TTSEngine, VoiceUnavailable
from studio.voice.humanize import build_utterances_for_chunks
from studio.voice.types import (
    PacingProfile,
    SpeechChunk,
    Timing,
    VoiceTrack,
    get_profile,
    language_code,
)

log = get_logger(__name__)

SAMPLE_RATE = 44100
LOUDNESS_I = -16.0  # broadcast-ish for spoken-word

ProgressFn = Callable[[int, int, str], None]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _coerce_chunks(chunks: str | Sequence[SpeechChunk] | Sequence[tuple[str, str]]) -> list[SpeechChunk]:
    if isinstance(chunks, str):
        return [SpeechChunk(text=chunks, tag="main")]
    coerced: list[SpeechChunk] = []
    for index, item in enumerate(chunks):
        if isinstance(item, SpeechChunk):
            coerced.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            coerced.append(SpeechChunk(text=str(item[0]), tag=str(item[1])))
        else:
            coerced.append(SpeechChunk(text=str(item), tag=f"chunk{index}"))
    return coerced


def _hash_key(engine: str, text: str, speed: float, exaggeration: float, cfg_weight: float) -> str:
    payload = json.dumps(
        {"e": engine, "t": text, "s": round(speed, 4),
         "x": round(exaggeration, 3), "c": round(cfg_weight, 3)},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _process_segment(
    raw: Path,
    out: Path,
    *,
    speed: float,
    trim: bool,
) -> Path:
    """Decode, de-silence, tempo-shift and fade one sentence."""
    filters: list[str] = []
    if trim:
        de_silence = (
            "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB:detection=peak"
        )
        filters.append(de_silence)
        filters.append("areverse")
        filters.append(de_silence)
        filters.append("areverse")
    if abs(speed - 1.0) > 0.004:
        filters.append(f"atempo={min(max(speed, 0.5), 2.0):.4f}")
    # click-free edges: fade in, then reverse-fade-reverse for the tail
    filters += [
        "afade=t=in:st=0:d=0.010",
        "areverse",
        "afade=t=in:st=0:d=0.015",
        "areverse",
        f"aresample={SAMPLE_RATE}",
        "aformat=sample_fmts=s16:channel_layouts=mono",
    ]
    ffmpeg.run(["-i", raw, "-af", ",".join(filters), "-c:a", "pcm_s16le", out])
    return out


def _write_silence(path: Path, seconds: float) -> Path:
    frames = max(int(seconds * SAMPLE_RATE), 1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"\x00\x00" * frames)
    return path


def _make_breath(path: Path) -> Path:
    """Short, band-limited noise burst that reads as an intake of breath."""
    ffmpeg.run([
        "-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink:r=44100:a=0.45",
        "-af",
        "highpass=f=380,lowpass=f=2600,afade=t=in:st=0:d=0.10,"
        "afade=t=out:st=0.18:d=0.28,volume=0.55",
        "-ac", "1", path,
    ])
    return path


def _spans_from_timings(timings: Sequence[Timing], total: float) -> dict[str, tuple[float, float]]:
    """Contiguous tag spans; boundaries sit in the middle of the pause."""
    if not timings:
        return {}
    groups: list[tuple[str, float, float]] = []
    for timing in timings:
        if groups and groups[-1][0] == timing.tag:
            tag, start, _ = groups[-1]
            groups[-1] = (tag, start, timing.end)
        else:
            groups.append((timing.tag, timing.start, timing.end))
    spans: dict[str, tuple[float, float]] = {}
    for index, (tag, start, end) in enumerate(groups):
        span_start = 0.0 if index == 0 else (groups[index - 1][2] + start) / 2
        span_end = total if index == len(groups) - 1 else (end + groups[index + 1][1]) / 2
        spans[tag] = (span_start, span_end)
    return spans


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
def synthesize(
    chunks: str | Sequence[SpeechChunk] | Sequence[tuple[str, str]],
    *,
    build_dir: str | Path,
    language: str = "hindi",
    engine: str | TTSEngine | None = None,
    profile: str | PacingProfile | None = None,
    reference: str | Path | None = None,
    device: str | None = None,
    cache: bool = True,
    on_progress: ProgressFn | None = None,
) -> VoiceTrack:
    """Build the narration wav and return its timeline.

    ``chunks`` may be a plain string, a list of :class:`SpeechChunk`, or
    ``(text, tag)`` pairs — one chunk per scene/section, so the returned
    ``spans`` line up exactly with the visuals.
    """
    build_dir = Path(build_dir)
    voice_dir = build_dir / "voice"
    segment_dir = voice_dir / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)

    pacing = get_profile(profile)
    language = language_code(language)
    if isinstance(engine, TTSEngine):
        engine_obj = engine
    elif device:
        engine_obj = get_engine(engine, device=device)
    else:
        engine_obj = get_engine(engine)
    if not engine_obj.supports(language):
        raise ValueError(
            f"Engine {engine_obj.name!r} cannot speak language {language!r}. "
            "Pick another engine or set CHATTERBOX_MODEL=multilingual."
        )

    try:
        engine_obj.prepare()
    except Exception as exc:  # noqa: BLE001 - surfaced with engine context
        raise RuntimeError(f"Voice engine {engine_obj.name!r} failed to start: {exc}") from exc

    planned_chunks = _coerce_chunks(chunks)
    utterances = build_utterances_for_chunks(planned_chunks, pacing, language=language)
    if not utterances:
        raise ValueError("Nothing to synthesize: the script text is empty")

    manifest_path = voice_dir / "cache.json"
    manifest: dict[str, dict] = {}
    if cache and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    segment_paths: list[Path] = []
    durations: list[float] = []
    suffix = getattr(engine_obj, "output_suffix", ".wav")

    for index, utterance in enumerate(utterances):
        if on_progress:
            on_progress(index + 1, len(utterances), utterance.text)
        key = _hash_key(
            engine_obj.name, utterance.text, utterance.speed,
            utterance.exaggeration or pacing.exaggeration,
            utterance.cfg_weight if utterance.cfg_weight is not None else pacing.cfg_weight,
        )
        processed = segment_dir / f"{index:04d}_{key}.wav"
        cached = manifest.get(key)
        if cache and cached and processed.exists() and cached.get("duration"):
            segment_paths.append(processed)
            durations.append(float(cached["duration"]))
            continue

        raw = segment_dir / f"{index:04d}_{key}.raw{suffix}"
        per_utterance = replace(
            pacing,
            exaggeration=utterance.exaggeration if utterance.exaggeration is not None
            else pacing.exaggeration,
            cfg_weight=utterance.cfg_weight if utterance.cfg_weight is not None
            else pacing.cfg_weight,
        )
        attempts = int(os.getenv("VOICE_SYNTH_ATTEMPTS", "3") or 3)

        def _synth_once(
            text: str = utterance.text,
            destination: Path = raw,
            voice: PacingProfile = per_utterance,
        ) -> Path:
            return engine_obj.synth(
                text, destination, language=language, profile=voice,
                reference=Path(reference) if reference else None,
            )

        def _drop_partial(
            _attempt: int, _error: BaseException, _delay: float,
            destination: Path = raw,
        ) -> None:
            destination.unlink(missing_ok=True)

        try:
            retry_call(
                _synth_once,
                attempts=attempts,
                base_delay=float(os.getenv("VOICE_RETRY_DELAY", "2") or 2),
                max_delay=30,
                give_up_on=(VoiceUnavailable,),
                label=f"{engine_obj.name} sentence {index + 1}/{len(utterances)}",
                on_retry=_drop_partial,
            )
        except RetryExhausted as exc:
            raise RuntimeError(
                f"Voice synthesis failed on sentence {index + 1}/{len(utterances)} "
                f"({engine_obj.name}) after {attempts} attempts: {exc.last_error}"
            ) from exc

        # The silent engine emits pure silence: trimming would erase it.
        trim = pacing.trim_silence and engine_obj.name != "silent"
        _process_segment(raw, processed, speed=utterance.speed, trim=trim)
        if not cache:
            raw.unlink(missing_ok=True)
        audio_duration = ffmpeg.duration(processed)
        if audio_duration <= 0:
            raise RuntimeError(f"Empty audio produced for sentence {index + 1}")
        durations.append(audio_duration)
        manifest[key] = {"file": processed.name, "duration": round(audio_duration, 4)}
        segment_paths.append(processed)

    if cache:
        manifest_path.write_text(json.dumps(manifest, indent=0), encoding="utf-8")

    final_path = voice_dir / "voice.wav"
    with atomic_path(final_path) as temp_audio:
        total, breath_times = _mix_track(
            segment_paths,
            durations,
            [u.pause_after for u in utterances],
            [u.breath_after for u in utterances],
            lead_in=pacing.lead_in,
            breath_dir=voice_dir,
            out=temp_audio,
        )

    timings: list[Timing] = []
    cursor = pacing.lead_in
    for utterance, audio_duration in zip(utterances, durations):
        timings.append(Timing(
            start=round(cursor, 3),
            end=round(cursor + audio_duration, 3),
            text=utterance.text,
            tag=utterance.tag,
        ))
        cursor += audio_duration + utterance.pause_after

    log.info(
        "voice ready: %s sentences, %.1fs, engine=%s profile=%s breaths=%d",
        len(utterances), total, engine_obj.name, pacing.name, len(breath_times),
    )
    return VoiceTrack(
        path=final_path,
        duration=total,
        timings=timings,
        spans=_spans_from_timings(timings, total),
        engine=engine_obj.name,
        profile=pacing.name,
        utterances=utterances,
    )


def _mix_track(
    segments: Sequence[Path],
    durations: Sequence[float],
    pauses: Sequence[float],
    breaths: Sequence[bool],
    *,
    lead_in: float,
    breath_dir: Path,
    out: Path,
) -> tuple[float, list[float]]:
    """Concatenate sentences with pauses, mix breaths, master the result."""
    inputs: list[str] = []
    offset = 0
    lead_present = lead_in > 0.01
    if lead_present:
        inputs += ["-f", "lavfi", "-t", f"{lead_in:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
        offset = 1

    filters: list[str] = []
    pieces: list[str] = []
    if lead_present:
        filters.append("[0:a]aformat=sample_fmts=fltp:channel_layouts=mono[lead]")
        pieces.append("[lead]")

    for index, segment in enumerate(segments):
        inputs += ["-i", str(segment)]
        label = f"s{index}"
        pad = pauses[index] if index < len(pauses) else 0.0
        pad_filter = f",apad=pad_dur={pad:.3f}" if pad > 0.001 else ""
        filters.append(
            f"[{index + offset}:a]aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=mono{pad_filter}[{label}]"
        )
        pieces.append(f"[{label}]")

    breath_indices = [
        i for i, flag in enumerate(breaths)
        if flag and i < len(pauses) and (pauses[i] > 0.15) and i + 1 < len(segments)
    ]
    breath_times: list[float] = []
    breath_labels: list[str] = []
    if breath_indices:
        breath_path = _make_breath(breath_dir / "breath.wav")
        inputs += ["-i", str(breath_path)]
        breath_input = len(segments) + offset
        cursor = lead_in
        for index in range(len(segments)):
            cursor += durations[index]
            if index in breath_indices:
                breath_times.append(cursor + 0.02)
                label = f"br{len(breath_labels)}"
                delay_ms = int(breath_times[-1] * 1000)
                filters.append(
                    f"[{breath_input}:a]aresample=44100,volume=0.12,"
                    f"adelay={delay_ms}|{delay_ms}[{label}]"
                )
                breath_labels.append(label)
            cursor += pauses[index] if index < len(pauses) else 0.0

    filters.append("".join(pieces) + f"concat=n={len(pieces)}:v=0:a=1[cat]")
    mix_labels = ["[cat]"] + [f"[{label}]" for label in breath_labels]
    if len(mix_labels) > 1:
        filters.append(
            "".join(mix_labels) + f"amix=inputs={len(mix_labels)}:duration=first:"
            "dropout_transition=0:normalize=0[bed]"
        )
        bed = "[bed]"
    else:
        bed = "[cat]"
    filters.append(
        f"{bed}highpass=f=70,"
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=60:makeup=2,"
        f"loudnorm=I={LOUDNESS_I}:TP=-1.5:LRA=11,alimiter=limit=0.95,"
        "aresample=44100,"
        "aformat=sample_fmts=s16:channel_layouts=mono[out]"
    )

    ffmpeg.run([
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[out]",
        "-c:a", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
        out,
    ])
    total = ffmpeg.duration(out)
    return total, breath_times


def preview(
    text: str,
    out_path: str | Path,
    *,
    language: str = "hindi",
    engine: str | TTSEngine | None = None,
    profile: str | PacingProfile | None = None,
    reference: str | Path | None = None,
    device: str | None = None,
) -> VoiceTrack:
    """Synthesize a single passage to an explicit file (used by the CLI)."""
    out_path = Path(out_path)
    from studio import config

    build_dir = Path(config.BUILD_DIR) / "voice_previews" / out_path.stem
    track = synthesize(
        [SpeechChunk(text=text, tag="preview")],
        build_dir=build_dir,
        language=language,
        engine=engine,
        profile=profile,
        reference=reference,
        device=device,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(track.path.read_bytes())
    track.path = out_path
    return track


__all__ = ["synthesize", "preview", "SAMPLE_RATE"]
