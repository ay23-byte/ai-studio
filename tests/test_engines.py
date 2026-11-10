"""Engine registry and Chatterbox adapter tests.

Chatterbox itself needs torch + ~2 GB of weights, so the model is faked at the
module boundary.  These tests pin the exact ``generate()`` contract we rely on:
language id, exaggeration, cfg_weight and the voice-clone reference.
"""

from __future__ import annotations

import sys
import types
import wave
from pathlib import Path

import pytest

from studio.voice.engines import (
    available_engines,
    build_engine,
    engine_status,
    get_engine,
)
from studio.voice.engines.base import EngineUnavailable
from studio.voice.engines.chatterbox import ChatterboxEngine
from studio.voice.engines.edge import EdgeEngine
from studio.voice.engines.silent import SilentEngine
from studio.voice.types import get_profile


def _write_wav(path: Path, seconds: float = 0.2, sample_rate: int = 24000) -> Path:
    path = Path(path)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return path


# --------------------------------------------------------------------------- #
# fake chatterbox package
# --------------------------------------------------------------------------- #
def install_fake_chatterbox(
    monkeypatch,
    *,
    reject_generate=(),
    reject_from_pretrained=(),
    sr: int = 24000,
):
    calls = {"from_pretrained": [], "generate": []}

    class FakeModel:
        def __init__(self, kind: str):
            self.kind = kind
            self.sr = sr

        def generate(self, text, **kwargs):
            for key in reject_generate:
                if key in kwargs:
                    raise TypeError(f"generate() got an unexpected keyword argument '{key}'")
            calls["generate"].append({"text": text, "kwargs": kwargs})
            return "fake-tensor"

    def make_family(kind):
        class Family:
            @classmethod
            def from_pretrained(cls, **kwargs):
                for key in reject_from_pretrained:
                    if key in kwargs:
                        raise TypeError(
                            f"from_pretrained() got an unexpected keyword argument '{key}'"
                        )
                calls["from_pretrained"].append({"kind": kind, "kwargs": dict(kwargs)})
                return FakeModel(kind)

            @classmethod
            def from_local(cls, **kwargs):
                calls["from_pretrained"].append({"kind": f"{kind}-local", "kwargs": dict(kwargs)})
                return FakeModel(kind)

        return Family

    package = types.ModuleType("chatterbox")
    package.__path__ = []
    multilingual = types.ModuleType("chatterbox.mtl_tts")
    multilingual.ChatterboxMultilingualTTS = make_family("multilingual")
    english = types.ModuleType("chatterbox.tts")
    english.ChatterboxTTS = make_family("english")
    turbo = types.ModuleType("chatterbox.tts_turbo")
    turbo.ChatterboxTurboTTS = make_family("turbo")

    torchaudio = types.ModuleType("torchaudio")
    torchaudio.save = lambda path, wav, sample_rate: _write_wav(
        Path(path), seconds=0.2, sample_rate=sample_rate
    )
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    torch.backends = types.SimpleNamespace(mps=None)

    for name, module in {
        "chatterbox": package,
        "chatterbox.mtl_tts": multilingual,
        "chatterbox.tts": english,
        "chatterbox.tts_turbo": turbo,
        "torchaudio": torchaudio,
        "torch": torch,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    return calls


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
def test_registry_lists_every_engine():
    names = {item["name"] for item in available_engines()}
    assert names == {"chatterbox", "chatterbox-http", "edge", "silent"}


def test_unknown_engine_rejected():
    with pytest.raises(EngineUnavailable):
        get_engine("festival")


def test_auto_picks_an_available_engine(monkeypatch):
    monkeypatch.delenv("CHATTERBOX_API_URL", raising=False)
    engine = get_engine("auto")
    assert engine.name in {"chatterbox", "edge"}


def test_missing_chatterbox_reports_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "chatterbox", None)
    ok, detail = engine_status("chatterbox")
    assert ok is False
    assert "chatterbox" in detail.lower()


def test_silent_engine_is_explicit_only():
    ok, _ = engine_status("silent")
    assert ok is True
    assert isinstance(get_engine("silent"), SilentEngine)


# --------------------------------------------------------------------------- #
# silent engine
# --------------------------------------------------------------------------- #
def test_silent_engine_writes_valid_wav(tmp_path):
    engine = SilentEngine()
    out = engine.synth("Ek do teen.", tmp_path / "a.wav", language="hi",
                       profile=get_profile("natural"))
    assert out.exists() and out.stat().st_size > 1000
    with wave.open(str(out), "rb") as handle:
        assert handle.getframerate() == 44100
        assert handle.getnframes() > 0


# --------------------------------------------------------------------------- #
# chatterbox: multilingual happy path
# --------------------------------------------------------------------------- #
def test_chatterbox_multilingual_generate_contract(tmp_path, monkeypatch):
    calls = install_fake_chatterbox(monkeypatch)
    reference = _write_wav(tmp_path / "ref.wav")
    engine = ChatterboxEngine(model="multilingual", device="cpu", t3_model="v3")

    out = engine.synth(
        "Inflation kya hai?", tmp_path / "out.wav",
        language="hindi", profile=get_profile("fast"), reference=reference,
    )

    assert out.exists()
    assert calls["from_pretrained"][0]["kwargs"]["t3_model"] == "v3"
    assert calls["from_pretrained"][0]["kwargs"]["device"] == "cpu"

    generation = calls["generate"][0]
    kwargs = generation["kwargs"]
    assert kwargs["language_id"] == "hi"
    assert kwargs["exaggeration"] == pytest.approx(0.60)
    assert kwargs["cfg_weight"] == pytest.approx(0.30)
    assert kwargs["audio_prompt_path"] == str(reference)
    assert kwargs["temperature"] == pytest.approx(0.8)


def test_chatterbox_english_language_tag(tmp_path, monkeypatch):
    calls = install_fake_chatterbox(monkeypatch)
    engine = ChatterboxEngine(model="multilingual", device="cpu")
    engine.synth("Hello there.", tmp_path / "en.wav",
                 language="english", profile=get_profile("natural"))
    assert calls["generate"][0]["kwargs"]["language_id"] == "en"


def test_chatterbox_model_cached_between_sentences(tmp_path, monkeypatch):
    calls = install_fake_chatterbox(monkeypatch)
    engine = ChatterboxEngine(model="multilingual", device="cpu")
    profile = get_profile("natural")
    engine.synth("One.", tmp_path / "1.wav", language="hi", profile=profile)
    engine.synth("Two.", tmp_path / "2.wav", language="hi", profile=profile)
    assert len(calls["from_pretrained"]) == 1


# --------------------------------------------------------------------------- #
# chatterbox: resilience
# --------------------------------------------------------------------------- #
def test_chatterbox_drops_unsupported_generate_kwargs(tmp_path, monkeypatch):
    calls = install_fake_chatterbox(
        monkeypatch, reject_generate=("min_p", "top_p", "repetition_penalty")
    )
    engine = ChatterboxEngine(model="multilingual", device="cpu")
    engine.synth("Hello.", tmp_path / "out.wav", language="hi",
                 profile=get_profile("natural"))
    kwargs = calls["generate"][0]["kwargs"]
    assert "min_p" not in kwargs
    assert kwargs["language_id"] == "hi"
    assert kwargs["exaggeration"] is not None


def test_chatterbox_tolerates_old_from_pretrained_signature(tmp_path, monkeypatch):
    calls = install_fake_chatterbox(monkeypatch, reject_from_pretrained=("t3_model",))
    engine = ChatterboxEngine(model="multilingual", device="cpu", t3_model="v3")
    engine.synth("Hello.", tmp_path / "out.wav", language="hi",
                 profile=get_profile("natural"))
    assert "t3_model" not in calls["from_pretrained"][0]["kwargs"]


def test_chatterbox_local_checkpoint(tmp_path, monkeypatch):
    calls = install_fake_chatterbox(monkeypatch)
    engine = ChatterboxEngine(device="cpu", ckpt_dir=tmp_path / "ckpt")
    engine.synth("Hello.", tmp_path / "out.wav", language="hi",
                 profile=get_profile("natural"))
    assert calls["from_pretrained"][0]["kind"] == "multilingual-local"
    assert calls["from_pretrained"][0]["kwargs"]["ckpt_dir"] == str(tmp_path / "ckpt")


def test_chatterbox_english_only_model_rejects_hindi(tmp_path, monkeypatch):
    install_fake_chatterbox(monkeypatch)
    engine = ChatterboxEngine(model="turbo", device="cpu")
    with pytest.raises(EngineUnavailable, match="English-only"):
        engine.synth("Namaste.", tmp_path / "out.wav", language="hindi",
                     profile=get_profile("natural"))


def test_chatterbox_missing_package_raises(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "chatterbox", None)
    engine = ChatterboxEngine(device="cpu")
    with pytest.raises(EngineUnavailable, match="Chatterbox is not installed"):
        engine.synth("Hello.", tmp_path / "out.wav", language="hi",
                     profile=get_profile("natural"))


# --------------------------------------------------------------------------- #
# remote chatterbox server
# --------------------------------------------------------------------------- #
def test_server_engine_requires_url(monkeypatch):
    monkeypatch.delenv("CHATTERBOX_API_URL", raising=False)
    with pytest.raises(EngineUnavailable, match="CHATTERBOX_API_URL"):
        build_engine("chatterbox-http")


def test_server_engine_posts_payload_and_writes_audio(tmp_path, monkeypatch):
    from studio.voice.engines import chatterbox_server

    captured = {}

    class FakeResponse:
        content = b"RIFF-fake-audio"
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json=None, data=None, files=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers, "data": data})
        return FakeResponse()

    monkeypatch.setattr(chatterbox_server.requests, "post", fake_post)
    engine = build_engine("chatterbox-http", base_url="http://gpu:4123")
    out = engine.synth("Namaste.", tmp_path / "remote.wav", language="hindi",
                       profile=get_profile("fast"))
    assert out.read_bytes() == FakeResponse.content
    assert captured["url"].endswith("/v1/audio/speech")
    assert captured["json"]["language_id"] == "hi"
    assert captured["json"]["cfg_weight"] == pytest.approx(0.30)


# --------------------------------------------------------------------------- #
# edge fallback
# --------------------------------------------------------------------------- #
def test_edge_voice_selection():
    engine = EdgeEngine(voice_hindi="hi-IN-Test", voice_english="en-IN-Test")
    assert engine.pick_voice("hindi") == "hi-IN-Test"
    assert engine.pick_voice("english") == "en-IN-Test"
    female = EdgeEngine(voice_hindi="male-voice", voice_female="female-voice", gender="female")
    assert female.pick_voice("hindi") == "female-voice"


def test_engine_language_support():
    assert ChatterboxEngine(device="cpu").supports("hindi")
    assert not ChatterboxEngine(device="cpu").supports("klingon")
    assert SilentEngine().supports("klingon")
