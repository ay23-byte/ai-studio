"""Build a vertical 9:16 YouTube Short from a scene-based script."""

from __future__ import annotations

import os
import random
from pathlib import Path

from studio import config
from studio.db import update_video
from studio.logs import get_logger
from studio.media import thumbnails
from studio.media.editor_shorts import render as render_shorts
from studio.media.images import fetch_clip, generate_image, make_placeholder
from studio.pipeline.captions import align_caption, make_ass_shorts
from studio.voice import SpeechChunk, synthesize

log = get_logger(__name__)

TAIL = 0.6
DISCLAIMER_CATEGORIES = {"finance", "markets", "money"}
CTA = "Roz ek naya video  •  Follow karo"


def pick_music() -> Path | None:
    files = list(config.MUSIC_DIR.glob("*.mp3")) + list(config.MUSIC_DIR.glob("*.wav"))
    return random.choice(files) if files else None


def local_clips() -> list[Path]:
    if not config.CLIPS_DIR.exists():
        return []
    files = [p for p in config.CLIPS_DIR.iterdir()
             if p.suffix.lower() in (".mp4", ".mov", ".webm")]
    random.shuffle(files)
    return files


def resolve_profile(explicit: str | None) -> str:
    """Shorts default to the `fast` profile unless VOICE_PROFILE is set."""
    return explicit or (config.VOICE_PROFILE if os.getenv("VOICE_PROFILE") else "fast")


def _scene_media(scenes: list[dict], build_dir: Path) -> list[dict]:
    media: list[dict] = []
    used_ids: set = set()
    clips = local_clips()
    for index, scene in enumerate(scenes):
        image_path = build_dir / f"img{index}.jpg"
        if generate_image(scene.get("image", "cinematic abstract"), image_path):
            media.append({"type": "image", "path": image_path})
            continue
        clip_path = build_dir / f"raw{index}.mp4"
        keywords = scene.get("keywords") or ["city"]
        if fetch_clip(keywords, clip_path, used_ids):
            media.append({"type": "video", "path": clip_path})
        elif clips:
            media.append({"type": "video", "path": clips[index % len(clips)]})
        elif media:
            media.append(dict(media[-1]))
        else:
            placeholder = make_placeholder(build_dir / f"ph{index}.jpg",
                                           scene.get("image", ""), 1024, 1536)
            media.append({"type": "image", "path": placeholder})
    return media


def build_shorts(
    script: dict,
    job_id: int,
    build_dir: Path | None = None,
    *,
    engine: str | None = None,
    profile: str | None = None,
    voice_reference: str | Path | None = None,
) -> Path:
    """Render a Short and return the output path."""
    config.ensure_directories()
    build_dir = Path(build_dir or (config.BUILD_DIR / f"job_{job_id}"))
    build_dir.mkdir(parents=True, exist_ok=True)

    scenes = [s for s in script.get("scenes", []) if s.get("say") or s.get("caption")]
    if not scenes:
        raise ValueError("Script has no scenes with text")
    category = script.get("category", "")
    language = script.get("language") or "hindi"

    # 1. Voice — one chunk per scene, so span timings map exactly to visuals.
    chunks = [
        SpeechChunk(scene.get("say") or scene.get("caption", ""), f"scene{i}")
        for i, scene in enumerate(scenes)
    ]
    track = synthesize(
        chunks,
        build_dir=build_dir,
        language=language,
        engine=engine,
        profile=resolve_profile(profile),
        reference=voice_reference,
    )
    log.info("shorts job #%s: %.1fs of narration", job_id, track.duration)

    # 2. Visuals
    media = _scene_media(scenes, build_dir)

    # 3. Captions and labels from the real sentence timings
    captions: list[tuple[float, float, str]] = []
    labels: list[tuple[float, float, str]] = []
    for index, scene in enumerate(scenes):
        tag = f"scene{index}"
        scene_timings = track.timings_for(tag)
        captions.extend(
            align_caption(scene.get("caption") or scene.get("say", ""), scene_timings)
        )
        label = scene.get("label", "")
        if label and scene_timings:
            start, end = scene_timings[0].start, scene_timings[-1].end
            labels.append((start, min(start + 2.4, end), label))

    ass_path = make_ass_shorts(
        captions,
        path=build_dir / "subs.ass",
        total=track.duration,
        hook=script.get("hook", ""),
        cta=CTA,
        labels=labels,
        disclaimer=category in DISCLAIMER_CATEGORIES,
        channel=config.CHANNEL_NAME,
        tail=TAIL,
    )

    # 4. Render
    spans = [track.span(f"scene{i}") or (0.0, track.duration) for i in range(len(scenes))]
    lens = [max(end - start, 0.8) for start, end in spans]
    cuts = [end for _, end in spans[:-1]]
    out = config.OUTPUT_DIR / f"shorts_{job_id}.mp4"
    render_shorts(media, lens, cuts, track.path, ass_path, track.duration, out,
                  pick_music(), work_dir=build_dir)

    # 5. Thumbnail (best effort)
    thumb = None
    try:
        first = media[0]["path"] if media and media[0]["type"] == "image" else None
        thumb = thumbnails.make_thumbnail(
            Path(first) if first else None,
            script.get("title", "Power Codex"),
            config.OUTPUT_DIR / f"shorts_{job_id}.jpg",
            channel=config.CHANNEL_NAME,
        )
    except Exception as exc:  # noqa: BLE001 - thumbnails are optional
        log.warning("thumbnail skipped: %s", exc)

    update_video(
        job_id,
        video_path=str(out),
        thumb_path=str(thumb) if thumb else None,
        status="done",
    )
    log.info("shorts job #%s done → %s", job_id, out)
    return out


__all__ = ["build_shorts", "pick_music", "local_clips"]
