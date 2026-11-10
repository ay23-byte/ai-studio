"""Scene visuals: AI images with a stock-footage fallback.

Order: Cloudflare Workers AI (FLUX) → Pollinations (free) → Pixabay clips.
Every provider is optional; missing keys simply fall through.
"""

from __future__ import annotations

import base64
import os
import random
import time
import urllib.parse
from pathlib import Path

import requests

from studio import config
from studio.logs import get_logger
from studio.media import ffmpeg
from studio.resilience import RetryExhausted, retry_call

log = get_logger(__name__)


def _offline() -> bool:
    """STUDIO_OFFLINE=1 skips all network providers (CI, dry runs)."""
    return os.getenv("STUDIO_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}


def make_placeholder(path: str | Path, seed: str = "", width: int = 1024, height: int = 1536) -> Path:
    """Deterministic dark gradient used when no image provider is reachable."""
    import zlib

    path = Path(path)
    accent = zlib.crc32((seed or "power-codex").encode()) % 0x30 + 0x10
    colour = f"0x0a{accent:02x}3a"
    ffmpeg.run([
        "-f", "lavfi", "-i", f"color=c={colour}:s={width}x{height}",
        "-vf", "noise=alls=6:allf=t+u,vignette=PI/5,format=yuv420p",
        "-frames:v", "1", path,
    ])
    return path


def _valid_image(path: Path) -> bool:
    try:
        if path.stat().st_size < 10_000:
            return False
        width, height = ffmpeg.image_size(path)
        return width >= 200 and height >= 200
    except Exception:
        return False


def _cloudflare(prompt: str, path: Path) -> bool:
    if not config.CF_ACCOUNT_ID or not config.CF_API_TOKEN:
        return False
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{config.CF_ACCOUNT_ID}"
        "/ai/run/@cf/black-forest-labs/flux-1-schnell"
    )
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {config.CF_API_TOKEN}"},
                json={"prompt": prompt[:2000], "steps": 4},
                timeout=120,
            )
            if response.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                data = base64.b64decode((response.json().get("result") or {}).get("image", ""))
            else:
                data = response.content
            if not data:
                return False
            path.write_bytes(data)
            return _valid_image(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Cloudflare attempt %s: %s", attempt + 1, exc)
    return False


def _pollinations_once(prompt: str, path: Path) -> bool:
    response = requests.get(
        "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900]),
        params={
            "width": 768, "height": 1344, "model": "flux",
            "nologo": "true", "seed": random.randint(1, 10**6),
        },
        timeout=150,
    )
    response.raise_for_status()
    if "image" not in response.headers.get("content-type", "image"):
        raise RuntimeError(f"unexpected content-type {response.headers.get('content-type')!r}")
    path.write_bytes(response.content)
    if not _valid_image(path):
        raise RuntimeError("downloaded image failed validation")
    return True


def _pollinations(prompt: str, path: Path) -> bool:
    time.sleep(config.POLLINATIONS_GAP)
    try:
        return retry_call(
            lambda: _pollinations_once(prompt, path),
            attempts=3, base_delay=4, max_delay=30, label="pollinations",
        )
    except RetryExhausted as exc:
        log.warning("Pollinations: %s", exc.last_error)
        return False


def generate_image(scene_prompt: str, path: str | Path) -> bool:
    """Try to create an image for ``scene_prompt``; True on success."""
    if _offline():
        return False
    path = Path(path)
    full_prompt = config.IMAGE_STYLE + (scene_prompt or "cinematic abstract")
    if _cloudflare(full_prompt, path):
        log.info("image ok (cloudflare)")
        return True
    if _pollinations(full_prompt, path):
        log.info("image ok (pollinations)")
        return True
    log.warning("image failed: %s", (scene_prompt or "")[:60])
    return False


def _search_pixabay(query: str) -> list[dict]:
    if not config.PIXABAY_API_KEY:
        return []
    for attempt in range(3):
        try:
            response = requests.get(
                "https://pixabay.com/api/videos/",
                params={
                    "key": config.PIXABAY_API_KEY, "q": query, "per_page": 30,
                    "safesearch": "true", "video_type": "film",
                },
                timeout=30,
            )
            if response.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            if response.status_code != 200:
                return []
            return response.json().get("hits", [])
        except Exception:  # noqa: BLE001
            continue
    return []


def fetch_clip(keywords: list[str], path: str | Path, used: set) -> bool:
    """Download a stock clip matching one of ``keywords``."""
    if _offline():
        return False
    path = Path(path)
    for query in keywords:
        time.sleep(1.2)
        hits = _search_pixabay(query)
        fresh = [h for h in hits if h.get("id") not in used and (h.get("duration") or 0) >= 3]
        random.shuffle(fresh)
        for hit in (fresh or hits)[:3]:
            url = None
            for size in ("small", "medium", "tiny"):
                variant = hit.get("videos", {}).get(size, {})
                if variant.get("url") and (variant.get("size") or 0) < 60_000_000:
                    url = variant["url"]
                    break
            if not url:
                continue
            def download(target: str = url, destination: Path = path) -> bool:
                with requests.get(target, stream=True, timeout=120) as response:
                    response.raise_for_status()
                    destination.write_bytes(response.content)
                if destination.stat().st_size <= 50_000:
                    raise RuntimeError("downloaded clip is too small")
                return True

            try:
                if retry_call(download, attempts=3, base_delay=3, label="pixabay clip"):
                    used.add(hit.get("id"))
                    log.info("clip ok (pixabay '%s')", query)
                    return True
            except RetryExhausted as exc:
                log.warning("clip download: %s", exc.last_error)
    return False


__all__ = ["generate_image", "fetch_clip", "make_placeholder"]
