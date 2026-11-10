"""Hardware detection and voice-engine guidance.

Designed for the common "normal laptop" case: integrated graphics (Intel Iris
Xe, AMD Radeon, Apple GPU) with no CUDA device. Chatterbox's PyTorch path runs
on CPU there, so the studio reports honest throughput expectations and suggests
the lightest model that fits the job.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib.util import find_spec
from typing import Any

from studio.logs import get_logger

log = get_logger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def _available(module: str) -> bool:
    """True when importable (and safe for modules stubbed in tests)."""
    if module in sys.modules:
        return sys.modules[module] is not None
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    cpu: str
    logical_cores: int | None
    physical_cores: int | None
    ram_gb: float | None
    gpus: tuple[str, ...]
    cuda: bool
    mps: bool
    xpu: bool
    torch_version: str | None
    chatterbox_installed: bool

    @property
    def has_gpu_acceleration(self) -> bool:
        return self.cuda or self.mps or self.xpu

    @property
    def intel_gpu(self) -> bool:
        return any("intel" in gpu.lower() for gpu in self.gpus)

    @property
    def device(self) -> str:
        if self.cuda:
            return "cuda"
        if self.xpu:
            return "xpu"
        if self.mps:
            return "mps"
        return "cpu"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gpus"] = list(self.gpus)
        data["device"] = self.device
        data["has_gpu_acceleration"] = self.has_gpu_acceleration
        return data


# --------------------------------------------------------------------------- #
# probes
# --------------------------------------------------------------------------- #
def _cpu_name() -> str:
    system = platform.system()
    try:
        if system == "Linux" and os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if system == "Darwin":
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=3
            ).strip()
    except Exception:  # noqa: BLE001
        pass
    return platform.processor() or platform.machine() or "unknown CPU"


def _physical_cores() -> int | None:
    try:
        if platform.system() == "Linux" and os.path.exists("/proc/cpuinfo"):
            pairs: set[tuple[str, str]] = set()
            physical = core = None
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("physical id"):
                        physical = line.split(":", 1)[1].strip()
                    elif line.startswith("core id"):
                        core = line.split(":", 1)[1].strip()
                    elif not line.strip() and physical and core:
                        pairs.add((physical, core))
                        physical = core = None
            if pairs:
                return len(pairs)
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil  # type: ignore

        return psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001
        return None


def _ram_gb() -> float | None:
    system = platform.system()
    try:
        if system == "Linux" and os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        kib = float(line.split()[1])
                        return round(kib / 1024 / 1024, 1)
        if system == "Darwin":
            value = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=3)
            return round(int(value.strip()) / 1024**3, 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _gpu_names() -> tuple[str, ...]:
    system = platform.system()
    commands: list[list[str]] = []
    if system == "Linux" and shutil.which("lspci"):
        commands.append(["lspci"])
    elif system == "Darwin" and shutil.which("system_profiler"):
        commands.append(["system_profiler", "SPDisplaysDataType"])
    elif system == "Windows" and shutil.which("powershell"):
        commands.append([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ])
    for command in commands:
        try:
            output = subprocess.check_output(command, text=True, timeout=8, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            continue
        names: list[str] = []
        for line in output.splitlines():
            text = line.strip()
            if not text:
                continue
            lowered = text.lower()
            if system == "Linux" and ("vga" in lowered or "3d controller" in lowered
                                      or "display controller" in lowered):
                names.append(text.split(": ", 1)[-1])
            elif system == "Darwin" and "chipset model" in lowered:
                names.append(text.split(":", 1)[-1].strip())
            elif system == "Windows" and not lowered.startswith(("name", "----")):
                names.append(text)
        if names:
            return tuple(dict.fromkeys(names))
    return ()


def _torch_state() -> tuple[str | None, bool, bool, bool]:
    """(version, cuda, mps, xpu) — never imports torch unless it is installed."""
    if not _available("torch"):
        return None, False, False, False
    version = None
    try:
        from importlib.metadata import version as package_version

        version = package_version("torch")
    except Exception:  # noqa: BLE001
        pass
    if os.getenv("STUDIO_SKIP_TORCH_PROBE", "").lower() in _TRUE:
        return version, False, False, False
    cuda = mps = xpu = False
    try:
        import torch  # type: ignore

        cuda = bool(torch.cuda.is_available())
        mps_backend = getattr(torch.backends, "mps", None)
        mps = bool(mps_backend and mps_backend.is_available())
        xpu_module = getattr(torch, "xpu", None)
        xpu = bool(xpu_module and xpu_module.is_available())
    except Exception:  # noqa: BLE001
        pass
    return version, cuda, mps, xpu


@lru_cache(maxsize=1)
def detect() -> HardwareProfile:
    """Cached hardware snapshot (cheap enough for CLI, cached for pipelines)."""
    logical = os.cpu_count()
    try:
        logical = len(os.sched_getaffinity(0))  # respects cgroup limits
    except Exception:  # noqa: BLE001
        pass
    torch_version, cuda, mps, xpu = _torch_state()
    return HardwareProfile(
        os_name=f"{platform.system()} {platform.release()}",
        cpu=_cpu_name(),
        logical_cores=logical,
        physical_cores=_physical_cores(),
        ram_gb=_ram_gb(),
        gpus=_gpu_names(),
        cuda=cuda,
        mps=mps,
        xpu=xpu,
        torch_version=torch_version,
        chatterbox_installed=_available("chatterbox"),
    )


def refresh() -> HardwareProfile:
    detect.cache_clear()
    return detect()


# --------------------------------------------------------------------------- #
# runtime tuning
# --------------------------------------------------------------------------- #
def configure_torch_runtime(device: str = "cpu") -> dict[str, Any]:
    """Pin CPU thread counts for predictable, lower-latency inference.

    PyTorch defaults to every core, which makes long generations compete with
    ffmpeg encoding. One inter-op thread and a bounded intra-op pool is faster
    in practice on laptops.
    """
    info: dict[str, Any] = {"threads": None, "interop_threads": 1, "ipex": False}
    if not _available("torch"):
        return info
    try:
        import torch  # type: ignore
    except Exception:  # noqa: BLE001
        return info

    logical = os.cpu_count() or 1
    requested = int(os.getenv("CHATTERBOX_THREADS", "0") or 0) or logical
    threads = max(1, min(requested, logical))
    try:
        torch.set_num_threads(threads)
        info["threads"] = threads
    except Exception:  # noqa: BLE001
        pass
    try:
        torch.set_num_interop_threads(1)
    except Exception:  # noqa: BLE001
        info["interop_threads"] = None  # already initialised

    if device == "cpu" and _available("intel_extension_for_pytorch"):
        info["ipex"] = True
        log.info(
            "Intel Extension for PyTorch found; Chatterbox stays fp32 for "
            "stability (set CHATTERBOX_THREADS to tune CPU parallelism)"
        )
    return info


# --------------------------------------------------------------------------- #
# guidance
# --------------------------------------------------------------------------- #
def recommendations(profile: HardwareProfile | None = None) -> list[str]:
    """Plain-language advice for picking an engine on this machine."""
    profile = profile or detect()
    tips: list[str] = []

    if profile.cuda:
        tips.append("NVIDIA GPU detected: VOICE_ENGINE=chatterbox with CHATTERBOX_DEVICE=cuda is the best quality/speed.")
    elif profile.xpu:
        tips.append("Intel GPU exposed through torch.xpu: try CHATTERBOX_DEVICE=xpu with intel-extension-for-pytorch.")
    elif profile.mps:
        tips.append("Apple GPU detected: CHATTERBOX_DEVICE=mps works for Chatterbox.")
    else:
        if profile.intel_gpu:
            tips.append(
                "Intel integrated graphics detected: Chatterbox has no Intel GPU path, "
                "so narration runs on the CPU. The iGPU is still used for decoding/playing video."
            )
        else:
            tips.append("No CUDA/MPS/XPU device: Chatterbox narration runs on the CPU.")

    if not profile.chatterbox_installed:
        tips.append(
            "Chatterbox is not installed. For CPU-only laptops start with "
            "VOICE_ENGINE=edge (instant), or `pip install -r requirements-voice.txt` "
            "for the human voice."
        )
    else:
        tips.append(
            "Chatterbox on CPU is typically 2-6x slower than realtime: a 30 s Short "
            "needs roughly 1-3 min, a 7 min long-form 20-40 min. Measure yours with "
            "`python run.py bench`."
        )
        tips.append(
            "English narration: CHATTERBOX_MODEL=nano (110M) is ~3x faster than "
            "realtime on 8 cores. Hindi needs the multilingual checkpoint, which is heavier."
        )
        tips.append(
            "For unattended daily builds on a laptop, run Chatterbox on a GPU box "
            "or Colab/Kaggle and set CHATTERBOX_API_URL (engine chatterbox-http)."
        )

    tips.append("Use VOICE_PROFILE=fast for Shorts: it trims gaps and tempo without speeding the model up.")
    if profile.ram_gb is not None and profile.ram_gb < 10:
        tips.append(
            f"Only {profile.ram_gb:.0f} GB RAM: close other apps; the multilingual "
            "checkpoint needs ~3-4 GB while generating."
        )
    return tips


__all__ = [
    "HardwareProfile", "detect", "refresh", "recommendations",
    "configure_torch_runtime",
]
