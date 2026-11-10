"""Hardware detection stays cross-platform and produces actionable advice."""

from __future__ import annotations

from studio import hardware
from studio.hardware import HardwareProfile, recommendations


def _profile(**overrides) -> HardwareProfile:
    base = dict(
        os_name="Linux test", cpu="Intel Core i5", logical_cores=8,
        physical_cores=4, ram_gb=16.0, gpus=("Intel Iris Xe Graphics",),
        cuda=False, mps=False, xpu=False, torch_version=None,
        chatterbox_installed=False,
    )
    base.update(overrides)
    return HardwareProfile(**base)


def test_detect_returns_profile():
    profile = hardware.detect()
    assert profile.os_name
    assert profile.cpu
    assert profile.device in {"cpu", "cuda", "mps", "xpu"}
    assert isinstance(profile.gpus, tuple)


def test_profile_dict_round_trip():
    payload = _profile().to_dict()
    assert payload["device"] == "cpu"
    assert payload["has_gpu_acceleration"] is False
    assert payload["gpus"] == ["Intel Iris Xe Graphics"]


def test_intel_igpu_advice_is_specific():
    tips = " ".join(recommendations(_profile()))
    assert "Intel integrated graphics" in tips
    assert "requirements-voice.txt" in tips


def test_cuda_profile_prefers_gpu():
    profile = _profile(gpus=("NVIDIA RTX 3060",), cuda=True, torch_version="2.5.1",
                       chatterbox_installed=True)
    tips = " ".join(recommendations(profile))
    assert "cuda" in tips.lower()
    assert profile.device == "cuda"


def test_cpu_chatterbox_advice_mentions_nano_and_remote():
    profile = _profile(chatterbox_installed=True)
    tips = " ".join(recommendations(profile))
    assert "nano" in tips.lower()
    assert "CHATTERBOX_API_URL" in tips


def test_low_ram_warning():
    tips = " ".join(recommendations(_profile(ram_gb=6.0, chatterbox_installed=True)))
    assert "GB RAM" in tips


def test_configure_runtime_without_torch():
    info = hardware.configure_torch_runtime("cpu")
    assert set(info) >= {"threads", "ipex"}
