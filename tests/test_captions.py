"""Caption alignment and ASS generation."""

from __future__ import annotations

from studio.pipeline.captions import (
    align_caption,
    make_ass_longform,
    make_ass_shorts,
    timestamp,
)
from studio.voice.types import Timing


def _timings(*specs):
    return [Timing(start=s, end=e, text=t, tag=tag) for s, e, t, tag in specs]


def test_timestamp_format():
    assert timestamp(0) == "0:00:00.00"
    assert timestamp(65.42) == "0:01:05.42"
    assert timestamp(3661.5) == "1:01:01.50"


def test_align_caption_uses_exact_sentence_windows():
    timings = _timings((0.2, 1.5, "पहला वाक्य।", "s"), (1.8, 3.0, "दूसरा वाक्य।", "s"))
    aligned = align_caption("Pehla vaakya. Doosra vaakya.", timings)
    assert len(aligned) == 2
    assert aligned[0][:2] == (0.2, 1.5)
    assert aligned[1][:2] == (1.8, 3.0)


def test_align_caption_distributes_when_counts_differ():
    timings = _timings((1.0, 2.0, "a", "s"), (2.0, 4.0, "b", "s"))
    aligned = align_caption("Ek lamba vaakya hai. Aur ek. Teesra bhi.", timings)
    assert len(aligned) == 3
    assert aligned[0][0] == 1.0
    assert aligned[-1][1] == 4.0
    for before, after in zip(aligned, aligned[1:]):
        assert before[1] == after[0]  # contiguous


def test_align_caption_empty_inputs():
    assert align_caption("", _timings((0, 1, "x", "s"))) == []
    assert align_caption("Hello.", []) == []


def test_make_ass_shorts_contains_expected_layers(tmp_path):
    timings = _timings((0.2, 1.4, "पहला।", "scene0"), (1.6, 2.8, "दूसरा।", "scene1"))
    captions = align_caption("Pehla vaakya. Doosra vaakya.", timings)
    path = make_ass_shorts(
        captions,
        path=tmp_path / "subs.ass",
        total=3.0,
        hook="Aapke paise ghat rahe hain",
        cta="Follow karo",
        labels=[(0.2, 1.2, "Inflation")],
        disclaimer=True,
        channel="Power Codex",
    )
    content = path.read_text(encoding="utf-8")
    assert "Style: Cap," in content
    assert "Style: Hook," in content
    assert "Aapke paise ghat rahe hain" in content
    assert "Follow karo" in content
    assert "Inflation" in content
    assert "Investment advice nahi" in content
    assert "0:00:03.60" in content  # total 3.0 + 0.6 tail
    assert content.count("Dialogue:") > 5


def test_ass_escapes_braces(tmp_path):
    path = make_ass_shorts(
        [(0.0, 1.0, "text {\\an8} unsafe")],
        path=tmp_path / "subs.ass",
        total=1.5,
        channel="X",
    )
    content = path.read_text(encoding="utf-8")
    assert "unsafe" in content
    assert "{\\an8}" not in content  # override syntax neutralised
    assert "(\\an8)" in content


def test_make_ass_longform_adds_section_titles(tmp_path):
    timings = _timings((0.5, 2.0, "Narration ek.", "sec0"), (2.5, 4.0, "Narration do.", "sec1"))
    path = make_ass_longform(
        timings,
        path=tmp_path / "long.ass",
        total=4.0,
        section_spans={"sec0": (0.5, 2.2), "sec1": (2.2, 4.0)},
        section_titles={"sec0": "Shuruaat", "sec1": "Ant"},
        disclaimer=True,
    )
    content = path.read_text(encoding="utf-8")
    assert "Shuruaat" in content and "Ant" in content
    assert "Style: Lower," in content
    assert "Narration" in content
    assert "PlayResX: 1920" in content
