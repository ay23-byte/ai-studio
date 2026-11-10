"""Voice assembly: prompts → one mastered wav with a usable timeline."""

from __future__ import annotations

import dataclasses
import json

import pytest

from studio.voice import SpeechChunk, preview, synthesize
from studio.voice.types import get_profile
from tests.conftest import requires_ffmpeg

TEXT = [
    SpeechChunk("Inflation kya hai? Chalo simple example se samjhein.", "scene0"),
    SpeechChunk("Aaj ek samosa das rupaye ka hai. Kuch saal baad wahi pandrah ka.",
                "scene1"),
    SpeechChunk("Isliye sirf paise rakhna kaafi nahi. Roz naya concept seekho.", "scene2"),
]


@requires_ffmpeg
def test_synthesize_returns_contiguous_timeline(temp_config):
    build = temp_config / "build" / "job1"
    track = synthesize(TEXT, build_dir=build, language="hindi",
                       engine="silent", profile="fast")

    assert track.path.exists()
    assert track.duration > 5
    assert track.engine == "silent"
    assert track.profile == "fast"
    assert len(track.timings) >= len(TEXT)
    assert set(track.spans) == {"scene0", "scene1", "scene2"}

    assert track.spans["scene0"][0] == pytest.approx(0.0, abs=0.05)
    ordered = [track.spans[f"scene{i}"] for i in range(3)]
    for (_, end), (start, _) in zip(ordered, ordered[1:]):
        assert end == pytest.approx(start, abs=0.05)
    assert ordered[-1][1] == pytest.approx(track.duration, abs=0.2)

    # every sentence timing sits inside its scene span
    for timing in track.timings:
        start, end = track.spans[timing.tag]
        assert start - 0.01 <= timing.start <= timing.end <= end + 0.01


@requires_ffmpeg
def test_sentence_timings_are_monotonic(temp_config):
    track = synthesize(TEXT, build_dir=temp_config / "build" / "job2",
                       engine="silent", profile="natural")
    for current, following in zip(track.timings, track.timings[1:]):
        assert current.end <= following.start + 1e-6


@requires_ffmpeg
def test_cache_prevents_resynthesis(temp_config):
    build = temp_config / "build" / "job3"
    synthesize(TEXT, build_dir=build, engine="silent", profile="fast")
    manifest_path = build / "voice" / "cache.json"
    first = json.loads(manifest_path.read_text())
    mtimes = {p.name: p.stat().st_mtime_ns for p in (build / "voice" / "segments").glob("*.wav")}

    synthesize(TEXT, build_dir=build, engine="silent", profile="fast")
    second = json.loads(manifest_path.read_text())
    new_mtimes = {p.name: p.stat().st_mtime_ns
                  for p in (build / "voice" / "segments").glob("*.wav")}

    assert first.keys() == second.keys()
    assert mtimes == new_mtimes


@requires_ffmpeg
def test_fast_profile_is_shorter_than_documentary(temp_config):
    fast = synthesize(TEXT, build_dir=temp_config / "build" / "fast",
                      engine="silent", profile="fast")
    slow = synthesize(TEXT, build_dir=temp_config / "build" / "slow",
                      engine="silent", profile="documentary")
    assert fast.duration < slow.duration


@requires_ffmpeg
def test_breaths_are_mixed_when_enabled(temp_config):
    profile = get_profile("natural")
    breathy = dataclasses.replace(profile, breath_probability=1.0)
    build = temp_config / "build" / "breath"
    track = synthesize(TEXT, build_dir=build, engine="silent", profile=breathy)
    assert track.path.exists()
    assert any(u.breath_after for u in track.utterances)
    assert (build / "voice" / "breath.wav").exists()


@requires_ffmpeg
def test_accepts_plain_string_and_engine_instance(temp_config):
    track = synthesize("Ek chhota vaakya hai.", build_dir=temp_config / "build" / "str",
                       engine="silent")
    assert track.duration > 0
    assert list(track.spans) == ["main"]


@requires_ffmpeg
def test_empty_text_raises(temp_config):
    with pytest.raises(ValueError, match="empty"):
        synthesize("", build_dir=temp_config / "build" / "empty", engine="silent")


@requires_ffmpeg
def test_preview_writes_to_requested_path(temp_config):
    out = temp_config / "samples" / "preview.wav"
    track = preview("Namaste doston, aaj inflation samjhenge.", out,
                    engine="silent", profile="fast")
    assert out.exists()
    assert track.path == out
    assert out.stat().st_size > 1000
