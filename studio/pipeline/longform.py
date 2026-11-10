"""Build a horizontal 16:9 long-form video from a section-based script."""

from __future__ import annotations

from pathlib import Path

from studio import config
from studio.db import update_video
from studio.logs import get_logger
from studio.media import thumbnails
from studio.media.editor_longform import render as render_longform
from studio.media.images import fetch_clip, generate_image, make_placeholder
from studio.pipeline.captions import make_ass_longform
from studio.pipeline.shorts import local_clips, pick_music
from studio.voice import SpeechChunk, synthesize

log = get_logger(__name__)

DISCLAIMER_CATEGORIES = {"finance", "markets", "money"}


def build_longform(
    script: dict,
    job_id: int,
    build_dir: Path | None = None,
    *,
    engine: str | None = None,
    profile: str | None = None,
    voice_reference: str | Path | None = None,
) -> Path:
    """Render a long-form video and return the output path."""
    config.ensure_directories()
    build_dir = Path(build_dir or (config.BUILD_DIR / f"job_{job_id}"))
    build_dir.mkdir(parents=True, exist_ok=True)

    sections = [s for s in script.get("sections", []) if s.get("narration")]
    if not sections:
        raise ValueError("Script has no sections with narration")
    category = script.get("category", "")
    language = script.get("language") or "hindi"

    # 1. Voice
    chunks = [
        SpeechChunk(section.get("narration", ""), f"sec{i}")
        for i, section in enumerate(sections)
    ]
    track = synthesize(
        chunks,
        build_dir=build_dir,
        language=language,
        engine=engine,
        profile=profile or config.VOICE_PROFILE,
        reference=voice_reference,
    )
    log.info("long-form job #%s: %.1fs of narration", job_id, track.duration)

    # 2. Visuals per section
    clips = local_clips()
    used_ids: set = set()
    for index, section in enumerate(sections):
        image_path = build_dir / f"limg{index}.jpg"
        if generate_image(section.get("image", "cinematic abstract scene"), image_path):
            section["_media"] = {"type": "image", "path": str(image_path)}
            continue
        clip_path = build_dir / f"lraw{index}.mp4"
        if fetch_clip(section.get("keywords") or ["city"], clip_path, used_ids):
            section["_media"] = {"type": "video", "path": str(clip_path)}
        elif clips:
            section["_media"] = {"type": "video", "path": str(clips[index % len(clips)])}
        else:
            placeholder = make_placeholder(build_dir / f"lph{index}.jpg",
                                           section.get("image", ""), 1920, 1080)
            section["_media"] = {"type": "image", "path": str(placeholder)}

    # 3. Timeline straight from the voice track
    for index, section in enumerate(sections):
        start, end = track.span(f"sec{index}") or (0.0, track.duration)
        section["_start"] = start
        section["_dur"] = max(end - start, 0.8)

    ass_path = make_ass_longform(
        track.timings,
        path=build_dir / "subs.ass",
        total=track.duration,
        section_spans=track.spans,
        section_titles={f"sec{i}": s.get("title", "") for i, s in enumerate(sections)},
        disclaimer=category in DISCLAIMER_CATEGORIES,
        channel=config.CHANNEL_NAME,
    )

    # 4. Render
    out = config.OUTPUT_DIR / f"longform_{job_id}.mp4"
    render_longform(sections, track.path, ass_path, track.duration, out,
                    pick_music(), work_dir=build_dir)

    # 5. Thumbnail (best effort)
    thumb = None
    try:
        first = sections[0].get("_media", {}).get("path") if sections else None
        thumb = thumbnails.make_thumbnail(
            Path(first) if first else None,
            script.get("title", "Power Codex"),
            config.OUTPUT_DIR / f"longform_{job_id}.jpg",
            channel=config.CHANNEL_NAME,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("thumbnail skipped: %s", exc)

    update_video(
        job_id,
        video_path=str(out),
        thumb_path=str(thumb) if thumb else None,
        status="done",
    )
    log.info("long-form job #%s done → %s", job_id, out)
    return out


__all__ = ["build_longform"]
