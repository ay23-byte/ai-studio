"""Edge engine: voices are discovered, probed and rotated, never blindly trusted."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from studio.voice.engines.base import EngineUnavailable, VoiceUnavailable
from studio.voice.engines.edge import PROBE_TEXT, EdgeEngine, normalise_pitch, normalise_rate
from studio.voice.types import get_profile

CATALOGUE = [
    {"ShortName": "hi-IN-MadhurNeural", "Locale": "hi-IN", "Gender": "Male"},
    {"ShortName": "hi-IN-AaravNeural", "Locale": "hi-IN", "Gender": "Male"},
    {"ShortName": "hi-IN-AnanyaNeural", "Locale": "hi-IN", "Gender": "Female"},
    {"ShortName": "en-IN-PrabhatNeural", "Locale": "en-IN", "Gender": "Male"},
    {"ShortName": "en-IN-NeerjaNeural", "Locale": "en-IN", "Gender": "Female"},
]


def install_fake_edge(monkeypatch, *, dead=(), network_error=False, catalogue=CATALOGUE,
                      catalogue_error=False):
    """Replace the edge_tts module with a deterministic fake."""
    module = types.ModuleType("edge_tts")
    calls: list[dict] = []

    class Communicate:
        def __init__(self, text, voice, rate=None, pitch=None):
            self.text = text
            self.voice = voice
            calls.append({"text": text, "voice": voice, "rate": rate, "pitch": pitch})

        async def save(self, path):
            if network_error:
                raise ConnectionError(
                    "Cannot connect to host speech.platform.bing.com:443"
                )
            if self.voice in dead:
                raise RuntimeError(
                    "No audio was received. Please verify that your parameters are correct."
                )
            Path(path).write_bytes(b"ID3" + b"\0" * 512)

    async def list_voices():
        if catalogue_error:
            raise ConnectionError("voice list unavailable")
        return list(catalogue)

    module.Communicate = Communicate
    module.list_voices = list_voices
    monkeypatch.setitem(sys.modules, "edge_tts", module)
    return calls


def test_retired_configured_voice_is_replaced(tmp_path, temp_config, monkeypatch):
    calls = install_fake_edge(monkeypatch, dead={"hi-IN-MadhurNeural"})
    engine = EdgeEngine()

    out = engine.synth("पहला वाक्य।", tmp_path / "a.mp3",
                       profile=get_profile("natural"), language="hi")

    assert out.exists() and out.stat().st_size > 0
    assert engine.describe()["resolved"] == {"hi": "hi-IN-AaravNeural"}
    assert any(c["text"] == PROBE_TEXT["hi"] for c in calls)


def test_resolved_voice_is_probed_only_once(tmp_path, temp_config, monkeypatch):
    calls = install_fake_edge(monkeypatch, dead={"hi-IN-MadhurNeural"})
    engine = EdgeEngine()

    engine.synth("पहला।", tmp_path / "a.mp3", profile=get_profile("natural"), language="hi")
    after_first = len([c for c in calls if c["text"] == PROBE_TEXT["hi"]])
    engine.synth("दूसरा।", tmp_path / "b.mp3", profile=get_profile("natural"), language="hi")

    # the probe round runs at most once per language, even though the first
    # configured voice failed inside it
    assert after_first == 2  # dead configured voice + the working replacement
    assert len([c for c in calls if c["text"] == PROBE_TEXT["hi"]]) == after_first
    assert calls[-1]["voice"] == "hi-IN-AaravNeural"


def test_all_voices_dead_raises_voice_unavailable(tmp_path, temp_config, monkeypatch):
    install_fake_edge(
        monkeypatch,
        dead={"hi-IN-MadhurNeural", "hi-IN-AaravNeural", "hi-IN-AnanyaNeural"},
    )
    engine = EdgeEngine()

    with pytest.raises(VoiceUnavailable, match="could not produce audio"):
        engine.synth("नमस्ते।", tmp_path / "a.mp3",
                     profile=get_profile("natural"), language="hi")


def test_network_failure_is_not_mistaken_for_a_dead_voice(tmp_path, temp_config, monkeypatch):
    calls = install_fake_edge(monkeypatch, network_error=True)
    engine = EdgeEngine()

    with pytest.raises(EngineUnavailable, match="cannot reach the speech service"):
        engine.synth("नमस्ते।", tmp_path / "a.mp3",
                     profile=get_profile("natural"), language="hi")
    assert len(calls) == 1  # no pointless rotation when the network is down


def test_catalogue_failure_falls_back_to_configured_voice(tmp_path, temp_config, monkeypatch):
    install_fake_edge(monkeypatch, catalogue_error=True)
    engine = EdgeEngine()

    out = engine.synth("नमस्ते।", tmp_path / "a.mp3",
                       profile=get_profile("natural"), language="hi")
    assert out.exists()
    assert engine.describe()["resolved"] == {"hi": "hi-IN-MadhurNeural"}


def test_female_profile_prefers_a_female_voice(tmp_path, temp_config, monkeypatch):
    install_fake_edge(monkeypatch, dead={"hi-IN-SwaraNeural"})
    engine = EdgeEngine(gender="female")

    engine.synth("नमस्ते।", tmp_path / "a.mp3", profile=get_profile("natural"), language="hi")
    assert engine.describe()["resolved"] == {"hi": "hi-IN-AnanyaNeural"}


def test_english_uses_the_english_catalogue(tmp_path, temp_config, monkeypatch):
    install_fake_edge(monkeypatch, dead={"en-IN-PrabhatNeural"})
    engine = EdgeEngine()

    engine.synth("Hello there.", tmp_path / "a.mp3",
                 profile=get_profile("natural"), language="en")
    assert engine.describe()["resolved"] == {"en": "en-IN-NeerjaNeural"}


@pytest.mark.parametrize(
    "raw, expected",
    [("+4%", "+4%"), ("-4%", "-4%"), (None, "+0%"), ("loud", "+0%"),
     ("+7", "+0%"), ("+250%", "+100%"), ("0%", "+0%")],
)
def test_rate_normalisation(raw, expected):
    assert normalise_rate(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("-1Hz", "-1Hz"), ("+2hz", "+2Hz"), ("+0Hz", "+0Hz"), (None, "+0Hz"),
     ("high", "+0Hz"), ("-1", "+0Hz")],
)
def test_pitch_normalisation(raw, expected):
    assert normalise_pitch(raw) == expected


def test_pitch_and_rate_reach_the_service(tmp_path, temp_config, monkeypatch):
    calls = install_fake_edge(monkeypatch)
    engine = EdgeEngine()
    engine.synth("नमस्ते।", tmp_path / "a.mp3",
                 profile=get_profile("documentary"), language="hi")
    last = calls[-1]
    assert last["rate"] == "-4%"
    assert last["pitch"] == "-1Hz"
