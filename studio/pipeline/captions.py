"""ASS subtitle generation with real speech timings.

Captions are aligned to the synthesized sentence timings instead of an even
split, which is what makes the on-screen text feel locked to the voice.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from studio.voice.humanize import split_sentences
from studio.voice.types import Timing

W_S, H_S = 1080, 1920
W_L, H_L = 1920, 1080


def timestamp(seconds: float) -> str:
    """Seconds → ``H:MM:SS.cc`` (ASS format)."""
    centiseconds = round(max(seconds, 0.0) * 100)
    return (
        f"{centiseconds // 360000}:{(centiseconds // 6000) % 60:02d}:"
        f"{(centiseconds // 100) % 60:02d}.{centiseconds % 100:02d}"
    )


def _clean(text: str) -> str:
    """Escape characters that would break ASS overrides."""
    text = (text or "").replace("\n", " ").replace("\r", " ")
    return text.replace("{", "(").replace("}", ")").strip()


def _header(width: int, height: int, wrap_style: int, styles: str) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: {wrap_style}

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
{styles}
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def _chunk_words(text: str, size: int) -> list[str]:
    words = _clean(text).split()
    if not words:
        return []
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def align_caption(caption: str, timings: Sequence[Timing]) -> list[tuple[float, float, str]]:
    """Fit a (possibly Roman) caption onto the timings of its spoken sentences.

    When the caption has the same sentence count as the narration each line gets
    its exact window; otherwise the caption is distributed by character length
    across the narration span.
    """
    caption = (caption or "").strip()
    if not caption or not timings:
        return []
    span_start = timings[0].start
    span_end = timings[-1].end
    sentences = split_sentences(caption) or [caption]
    if len(sentences) == len(timings):
        return [
            (t.start, max(t.end, t.start + 0.2), sentence)
            for sentence, t in zip(sentences, timings)
        ]
    weights = [max(len(s), 1) for s in sentences]
    total_weight = sum(weights)
    span = max(span_end - span_start, 0.4)
    cursor = span_start
    aligned: list[tuple[float, float, str]] = []
    for sentence, weight in zip(sentences, weights):
        duration = span * weight / total_weight
        aligned.append((cursor, cursor + duration, sentence))
        cursor += duration
    return aligned


def _karaoke(
    items: Iterable[tuple[float, float, str]],
    words_per_chunk: int,
    style: str,
    *,
    layer: int = 0,
    pop: bool = True,
) -> list[str]:
    lines: list[str] = []
    for start, end, text in items:
        chunks = _chunk_words(text, words_per_chunk)
        if not chunks:
            continue
        weights = [max(len(c), 1) for c in chunks]
        total_weight = sum(weights)
        span = max(end - start, 0.25)
        cursor = start
        for chunk, weight in zip(chunks, weights):
            duration = span * weight / total_weight
            if pop:
                effect = "{\\fscx85\\fscy85\\t(0,110,\\fscx100\\fscy100)}"
            else:
                effect = ""
            lines.append(
                f"Dialogue: {layer},{timestamp(cursor)},{timestamp(cursor + duration)},"
                f"{style},,0,0,0,,{effect}{chunk}"
            )
            cursor += duration
    return lines


# --------------------------------------------------------------------------- #
# Shorts (9:16)
# --------------------------------------------------------------------------- #
SHORTS_STYLES = {
    "Cap": (
        "Style: Cap,Noto Sans Devanagari,96,&H0000FFFF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,0,0,1,9,3,2,70,70,640,1"
    ),
    "Hook": (
        "Style: Hook,Noto Sans Devanagari,88,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,0,0,1,8,3,8,90,90,300,1"
    ),
    "Label": (
        "Style: Label,Noto Sans,52,&H0000D7FF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,3,0,1,6,2,8,80,80,175,1"
    ),
    "End": (
        "Style: End,Noto Sans Devanagari,68,&H0000A5FF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,0,0,1,7,3,2,80,80,1000,1"
    ),
    "Mark": (
        "Style: Mark,Noto Sans,38,&H66FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,2,0,1,2,0,7,50,50,90,1"
    ),
    "Disc": (
        "Style: Disc,Noto Sans,32,&H99FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,1,0,1,3,0,2,60,60,310,1"
    ),
}


def make_ass_shorts(
    captions: Sequence[tuple[float, float, str]],
    *,
    path: Path,
    total: float,
    hook: str = "",
    cta: str = "",
    labels: Sequence[tuple[float, float, str]] = (),
    disclaimer: bool = False,
    channel: str = "Power Codex",
    tail: float = 0.6,
) -> Path:
    end_time = total + tail
    lines = [f"Dialogue: 0,{timestamp(0)},{timestamp(end_time)},Mark,,0,0,0,,{_clean(channel)}"]
    if disclaimer:
        lines.append(
            f"Dialogue: 0,{timestamp(0)},{timestamp(end_time)},Disc,,0,0,0,,"
            "Sirf educational jaankari  |  Investment advice nahi"
        )
    if hook:
        hook_end = min(3.2, (captions[0][1] + 0.3) if captions else 3.0)
        lines.append(
            f"Dialogue: 1,{timestamp(0.1)},{timestamp(hook_end)},Hook,,0,0,0,,"
            f"{{\\fad(250,350)}}{_clean(hook)}"
        )
    for start, end, label in labels:
        if label:
            lines.append(
                f"Dialogue: 1,{timestamp(start + 0.1)},{timestamp(max(end - 0.1, start + 0.3))},"
                f"Label,,0,0,0,,{{\\fad(220,220)}}{_clean(label)}"
            )
    lines += _karaoke(captions, 2, "Cap")
    if cta:
        lines.append(
            f"Dialogue: 1,{timestamp(max(total - 1.4, 0))},{timestamp(end_time)},End,,0,0,0,,"
            f"{{\\fad(300,200)}}{_clean(cta)}"
        )
    header = _header(W_S, H_S, 0, "\n".join(SHORTS_STYLES.values()))
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Long-form (16:9)
# --------------------------------------------------------------------------- #
LONGFORM_STYLES = {
    "Cap": (
        "Style: Cap,Noto Sans Devanagari,58,&H00FFFFFF,&H000000FF,&H00000000,&HC0000000,"
        "0,0,0,0,100,100,0,0,1,5,2,2,120,120,60,1"
    ),
    "Lower": (
        "Style: Lower,Noto Sans,46,&H00FFFFFF,&H000000FF,&H00FFFFFF,&HC0000014,"
        "1,0,0,0,100,100,2,0,1,3,2,7,80,80,80,1"
    ),
    "Mark": (
        "Style: Mark,Noto Sans,30,&H66FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,2,0,7,40,40,40,1"
    ),
    "Disc": (
        "Style: Disc,Noto Sans,32,&H99FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,2,0,9,80,80,40,1"
    ),
}


def make_ass_longform(
    timings: Sequence[Timing],
    *,
    path: Path,
    total: float,
    section_spans: dict[str, tuple[float, float]] | None = None,
    section_titles: dict[str, str] | None = None,
    disclaimer: bool = False,
    channel: str = "Power Codex",
    tail: float = 1.5,
) -> Path:
    end_time = total + tail
    lines = [f"Dialogue: 0,{timestamp(0)},{timestamp(end_time)},Mark,,0,0,0,,{_clean(channel)}"]
    if disclaimer:
        lines.append(
            f"Dialogue: 0,{timestamp(0)},{timestamp(end_time)},Disc,,0,0,0,,"
            "Sirf educational jaankari  |  Investment advice nahi"
        )
    for tag, title in (section_titles or {}).items():
        if not title:
            continue
        start, _ = (section_spans or {}).get(tag, (0.0, 0.0))
        lines.append(
            f"Dialogue: 1,{timestamp(start + 0.2)},{timestamp(start + 3.5)},Lower,,0,0,0,,"
            f"{{\\fad(300,400)}}{_clean(title[:40])}"
        )
    lines += _karaoke(
        [(t.start, t.end, t.text) for t in timings], 3, "Cap", pop=False
    )
    header = _header(W_L, H_L, 1, "\n".join(LONGFORM_STYLES.values()))
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


__all__ = [
    "timestamp", "align_caption", "make_ass_shorts", "make_ass_longform",
    "W_S", "H_S", "W_L", "H_L",
]
