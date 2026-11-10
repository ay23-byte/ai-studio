"""Central configuration for AI Studio.

Everything the application needs to know about paths, credentials and channel
defaults lives here.  Values are read once at import time from the environment
(``.env`` is loaded by the CLI) and can be refreshed in tests with
:func:`reload`.

Path rule: every directory is derived from the repository root, so the project
behaves identically from the CLI, a GitHub Action or a test run.  Set
``AI_STUDIO_HOME`` to store generated media outside the checkout.
"""

from __future__ import annotations

import os
from pathlib import Path

_TRUE = {"1", "true", "yes", "y", "on"}


# --------------------------------------------------------------------------- #
# env helpers
# --------------------------------------------------------------------------- #
def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = _env(name)
    return default if not raw else raw.lower() in _TRUE


def _number(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _dir(name: str, default: Path) -> Path:
    raw = _env(name)
    return Path(raw).expanduser() if raw else default


def project_root() -> Path:
    """Repository root, or ``AI_STUDIO_HOME`` when set."""
    override = _env("AI_STUDIO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _load() -> dict[str, object]:
    root = project_root()
    assets = _dir("AI_STUDIO_ASSETS_DIR", root / "assets")

    return {
        # --- LLM ---------------------------------------------------------- #
        "GEMINI_API_KEY": _env("GEMINI_API_KEY"),
        "GEMINI_MODEL": _env("GEMINI_MODEL", "gemini-3.8-flash"),
        # Tried in order when a model is retired or overloaded. Free-tier only.
        "GEMINI_FALLBACK_MODELS": _env(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite",
        ),
        # --- visuals ------------------------------------------------------ #
        "PIXABAY_API_KEY": _env("PIXABAY_API_KEY"),
        "CF_ACCOUNT_ID": _env("CLOUDFLARE_ACCOUNT_ID"),
        "CF_API_TOKEN": _env("CLOUDFLARE_API_TOKEN"),
        "POLLINATIONS_GAP": _number("POLLINATIONS_GAP", 16),
        # --- YouTube ------------------------------------------------------ #
        "YT_CLIENT_ID": _env("YT_CLIENT_ID"),
        "YT_CLIENT_SECRET": _env("YT_CLIENT_SECRET"),
        "YT_REFRESH_TOKEN": _env("YT_REFRESH_TOKEN"),
        # --- alerts ------------------------------------------------------- #
        "TELEGRAM_BOT_TOKEN": _env("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": _env("TELEGRAM_CHAT_ID"),
        # --- channel ------------------------------------------------------ #
        "CHANNEL_NAME": _env("CHANNEL_NAME", "Power Codex"),
        "PRIVACY": _env("PRIVACY", "private"),
        "PUBLISH_AT_IST": _env("PUBLISH_AT_IST"),
        # --- voice -------------------------------------------------------- #
        "VOICE_ENGINE": _env("VOICE_ENGINE", "auto"),
        "VOICE_PROFILE": _env("VOICE_PROFILE", "natural"),
        "VOICE_HINDI": _env("VOICE_HINDI", "hi-IN-MadhurNeural"),
        "VOICE_ENGLISH": _env("VOICE_ENGLISH", "en-IN-PrabhatNeural"),
        "VOICE_FEMALE": _env("VOICE_FEMALE", "hi-IN-SwaraNeural"),
        # --- paths -------------------------------------------------------- #
        "ROOT": root,
        "DB_DIR": root / "db",
        "DB_PATH": root / "db" / "studio.sqlite",
        "OUTPUT_DIR": _dir("AI_STUDIO_OUTPUT_DIR", root / "output"),
        "BUILD_DIR": _dir("AI_STUDIO_BUILD_DIR", root / "build"),
        "ASSETS_DIR": assets,
        "MUSIC_DIR": assets / "music",
        "CLIPS_DIR": assets / "clips",
        "VOICES_DIR": assets / "voices",
        "TOPICS_PATH": root / "topics.json",
        # --- style -------------------------------------------------------- #
        "IMAGE_STYLE": (
            "Premium cinematic 3D illustration for a financial education video. "
            "Dark navy background with gold and teal accents. Dramatic soft lighting. "
            "Clean simple symbolic composition. No text, letters, numbers, logos, charts with data, "
            "human faces, or real people. Scene: "
        ),
    }


globals().update(_load())


def reload() -> None:
    """Re-read the environment (used by tests and long-lived workers)."""
    globals().update(_load())


def ensure_directories() -> None:
    """Create the writable directories the pipeline needs.

    Importing :mod:`studio` never touches the filesystem; the CLI and the
    pipeline call this once before doing real work.
    """
    for key in ("OUTPUT_DIR", "BUILD_DIR", "DB_DIR", "MUSIC_DIR", "CLIPS_DIR", "VOICES_DIR"):
        Path(globals()[key]).mkdir(parents=True, exist_ok=True)

