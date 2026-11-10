"""AI Studio — an automated Hindi/Hinglish faceless video studio.

Package layout
--------------
``studio.config``      environment + paths
``studio.db``          SQLite job tracking
``studio.script_engine``  Gemini script/SEO generation
``studio.media``       images, ffmpeg helpers and the two editors
``studio.voice``       Chatterbox / edge-tts engines + human pacing
``studio.pipeline``    end-to-end Shorts and long-form builders
``studio.publishing``  YouTube upload
``studio.cli``         command line entry point
"""

from __future__ import annotations

from pathlib import Path

__version__ = "2.0.0"


def _load_env() -> None:
    """Load ``.env`` before :mod:`studio.config` reads the environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv is optional at import time
        return
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


_load_env()

__all__ = ["__version__"]
