"""Validate and normalise LLM-generated scripts before spending money on media.

Gemini is asked for a strict JSON shape but occasionally returns a scene as an
object, drops ``caption``, or writes an empty narration. Validating up front
turns a confusing crash inside the renderer into a clear, retryable error.
"""

from __future__ import annotations

from typing import Any

from studio.logs import get_logger

log = get_logger(__name__)

MIN_SHORTS_WORDS = 20
MAX_SHORTS_WORDS = 220


class ScriptValidationError(ValueError):
    """The script cannot be rendered even after normalisation."""


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _normalise_keywords(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value)[:6] if str(item).strip()]


def validate_shorts_script(script: Any) -> dict[str, Any]:
    """Return a normalised Shorts script or raise :class:`ScriptValidationError`."""
    if not isinstance(script, dict):
        raise ScriptValidationError(f"expected a JSON object, got {type(script).__name__}")

    scenes_in = _as_list(script.get("scenes"))
    if not scenes_in:
        raise ScriptValidationError("script has no scenes")

    scenes: list[dict[str, Any]] = []
    for index, raw in enumerate(scenes_in):
        if not isinstance(raw, dict):
            log.warning("dropping scene %d: expected object, got %s", index, type(raw).__name__)
            continue
        say = _as_text(raw.get("say")) or _as_text(raw.get("narration"))
        caption = _as_text(raw.get("caption")) or say
        if not say and caption:
            say = caption
        if not say:
            log.warning("dropping scene %d: empty narration", index)
            continue
        scenes.append({
            "say": say,
            "caption": caption,
            "label": _as_text(raw.get("label"))[:24],
            "image": _as_text(raw.get("image")) or "cinematic abstract concept",
            "keywords": _normalise_keywords(raw.get("keywords")),
        })

    if not scenes:
        raise ScriptValidationError("every scene was empty")
    if len(scenes) > 12:
        log.warning("script has %d scenes; Shorts work best with 4-8", len(scenes))

    total_words = sum(len(scene["say"].split()) for scene in scenes)
    if total_words < MIN_SHORTS_WORDS:
        raise ScriptValidationError(
            f"script is too short to publish ({total_words} words, need {MIN_SHORTS_WORDS})"
        )
    if total_words > MAX_SHORTS_WORDS:
        log.warning("script has %d words; Shorts usually stay under %d",
                    total_words, MAX_SHORTS_WORDS)

    normalized = dict(script)
    normalized.update({
        "format": "shorts",
        "title": _as_text(script.get("title")) or "Untitled",
        "hook": _as_text(script.get("hook")),
        "category": _as_text(script.get("category")),
        "language": _as_text(script.get("language")) or "hindi",
        "scenes": scenes,
    })
    return normalized


def validate_longform_script(script: Any) -> dict[str, Any]:
    """Return a normalised long-form script or raise."""
    if not isinstance(script, dict):
        raise ScriptValidationError(f"expected a JSON object, got {type(script).__name__}")

    sections_in = _as_list(script.get("sections"))
    if not sections_in:
        raise ScriptValidationError("script has no sections")

    sections: list[dict[str, Any]] = []
    for index, raw in enumerate(sections_in):
        if not isinstance(raw, dict):
            log.warning("dropping section %d: expected object", index)
            continue
        narration = _as_text(raw.get("narration")) or _as_text(raw.get("text"))
        if not narration:
            log.warning("dropping section %d: empty narration", index)
            continue
        sections.append({
            "title": _as_text(raw.get("title")) or f"Section {len(sections) + 1}",
            "narration": narration,
            "visuals": [str(item) for item in _as_list(raw.get("visuals"))][:6],
            "image": _as_text(raw.get("image")) or "cinematic abstract concept",
            "keywords": _normalise_keywords(raw.get("keywords")),
        })

    if not sections:
        raise ScriptValidationError("every section was empty")
    if len(sections) < 2:
        log.warning("long-form script has a single section")

    total_words = sum(len(section["narration"].split()) for section in sections)
    if total_words < 80:
        raise ScriptValidationError(
            f"long-form script is too short ({total_words} words, need 80)"
        )

    tags = [str(tag).strip() for tag in _as_list(script.get("tags")) if str(tag).strip()]
    normalized = dict(script)
    normalized.update({
        "format": "longform",
        "title": _as_text(script.get("title")) or "Untitled",
        "description": _as_text(script.get("description")),
        "hook": _as_text(script.get("hook")),
        "category": _as_text(script.get("category")),
        "language": _as_text(script.get("language")) or "hindi",
        "tags": tags,
        "sections": sections,
    })
    return normalized


def validate_script(script: Any, fmt: str | None = None) -> dict[str, Any]:
    """Validate according to ``fmt`` (or the script's own ``format`` field)."""
    fmt = (fmt or (script.get("format") if isinstance(script, dict) else "") or "").lower()
    if fmt in ("long", "longform"):
        return validate_longform_script(script)
    if fmt in ("short", "shorts", ""):
        # Unknown format: infer from the payload shape.
        if isinstance(script, dict) and "sections" in script and "scenes" not in script:
            return validate_longform_script(script)
        return validate_shorts_script(script)
    raise ScriptValidationError(f"unknown script format {fmt!r}")


__all__ = [
    "ScriptValidationError", "validate_shorts_script", "validate_longform_script",
    "validate_script", "MIN_SHORTS_WORDS", "MAX_SHORTS_WORDS",
]
