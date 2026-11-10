"""Remote Chatterbox engine for CPU-only runners (GitHub Actions, VMs…).

Any server that speaks the popular Chatterbox HTTP API works, e.g.
``chatterbox-tts-api`` which listens on port 4123:

    POST {base}/v1/audio/speech          -> wav bytes
    POST {base}/v1/audio/speech/upload   -> wav bytes + uploaded reference clip

Configure with ``CHATTERBOX_API_URL`` (e.g. ``http://gpu-box:4123``) and an
optional ``CHATTERBOX_API_TOKEN`` (sent as a bearer token).
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

from studio.logs import get_logger
from studio.voice.engines.base import EngineUnavailable, TTSEngine
from studio.voice.engines.chatterbox import SUPPORTED_LANGUAGES
from studio.voice.types import PacingProfile, language_code

log = get_logger(__name__)


class ChatterboxServerEngine(TTSEngine):
    name = "chatterbox-http"
    languages = SUPPORTED_LANGUAGES

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int = 300,
    ) -> None:
        self.base_url = (base_url or os.getenv("CHATTERBOX_API_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("CHATTERBOX_API_TOKEN", "")
        self.timeout = timeout
        if not self.base_url:
            raise EngineUnavailable(
                "CHATTERBOX_API_URL is not set. Point it at a Chatterbox HTTP "
                "server (e.g. http://localhost:4123) or use the local engine."
            )

    def _headers(self, json_mode: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json_mode:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def synth(
        self,
        text: str,
        out_path: Path,
        *,
        language: str = "hi",
        profile: PacingProfile,
        reference: Path | None = None,
    ) -> Path:
        out_path = Path(out_path)
        payload = {
            "input": text,
            "exaggeration": profile.exaggeration,
            "cfg_weight": profile.cfg_weight,
            "language_id": language_code(language),
        }
        ref = reference if reference and Path(reference).exists() else None
        try:
            if ref:
                url = f"{self.base_url}/v1/audio/speech/upload"
                with open(ref, "rb") as handle:
                    response = requests.post(
                        url,
                        data={k: str(v) for k, v in payload.items()},
                        files={"voice_file": (Path(ref).name, handle, "audio/wav")},
                        headers=self._headers(json_mode=False),
                        timeout=self.timeout,
                    )
            else:
                url = f"{self.base_url}/v1/audio/speech"
                response = requests.post(
                    url, json=payload, headers=self._headers(), timeout=self.timeout
                )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EngineUnavailable(f"Chatterbox server error at {self.base_url}: {exc}") from exc

        if not response.content:
            raise EngineUnavailable("Chatterbox server returned empty audio")
        out_path.write_bytes(response.content)
        return out_path

    def prepare(self) -> None:
        try:
            response = requests.get(self.base_url, timeout=10)
            log.debug("chatterbox server reachable (%s)", response.status_code)
        except requests.RequestException as exc:
            raise EngineUnavailable(f"Cannot reach Chatterbox server {self.base_url}: {exc}") from exc

    def describe(self) -> dict[str, object]:
        return {"name": self.name, "base_url": self.base_url}


__all__ = ["ChatterboxServerEngine"]
