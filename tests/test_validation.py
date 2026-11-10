"""Script validation stops malformed LLM output before media is generated."""

from __future__ import annotations

import pytest

from studio.validation import (
    ScriptValidationError,
    validate_longform_script,
    validate_script,
    validate_shorts_script,
)


def _scene(say: str, caption: str = "") -> dict:
    return {"say": say, "caption": caption, "label": "Label", "image": "scene", "keywords": ["city"]}


def test_shorts_normalises_missing_fields():
    long_sentence = "Ye ek lamba vaakya hai jo kitabon mein chhapta hai."
    script = {
        "title": "Test",
        "scenes": [_scene(long_sentence), _scene(long_sentence), _scene(long_sentence)],
    }
    out = validate_shorts_script(script)
    assert out["format"] == "shorts"
    assert out["language"] == "hindi"
    assert out["hook"] == ""
    assert out["scenes"][0]["caption"] == long_sentence  # falls back to say
    assert out["scenes"][0]["keywords"] == ["city"]


def test_shorts_rejects_missing_scenes():
    with pytest.raises(ScriptValidationError, match="no scenes"):
        validate_shorts_script({"title": "x"})


def test_shorts_rejects_non_object():
    with pytest.raises(ScriptValidationError, match="JSON object"):
        validate_shorts_script(["not", "a", "dict"])


def test_shorts_drops_empty_scenes_but_keeps_valid_ones():
    script = {
        "title": "Test",
        "scenes": [
            _scene("A" * 10 + " " + "b " * 20),
            {"say": "   "},
            "nonsense",
            _scene("Doosra lamba vaakya hai jo pura hai. " * 2),
        ],
    }
    out = validate_shorts_script(script)
    assert len(out["scenes"]) == 2


def test_shorts_rejects_too_short_script():
    with pytest.raises(ScriptValidationError, match="too short"):
        validate_shorts_script({"scenes": [_scene("Hi.")]})


def test_shorts_all_empty_raises():
    with pytest.raises(ScriptValidationError, match="every scene was empty"):
        validate_shorts_script({"scenes": [{"say": ""}, {"caption": ""}]})


def test_longform_normalises_sections():
    script = {
        "title": "Deep dive",
        "sections": [
            {"narration": "Pehla hissa. " * 30},
            {"title": "Doosra", "narration": "Doosra hissa. " * 30},
        ],
    }
    out = validate_longform_script(script)
    assert out["format"] == "longform"
    assert out["sections"][0]["title"] == "Section 1"
    assert out["sections"][1]["title"] == "Doosra"
    assert out["tags"] == []


def test_longform_rejects_thin_script():
    with pytest.raises(ScriptValidationError, match="too short"):
        validate_longform_script({"sections": [{"narration": "bahut chhota"}]})


def test_longform_missing_sections_raises():
    with pytest.raises(ScriptValidationError, match="no sections"):
        validate_longform_script({"title": "x"})


def test_validate_script_infers_longform_from_shape():
    script = {"sections": [{"narration": "Kaafi lamba hissa. " * 40}]}
    out = validate_script(script)
    assert out["format"] == "longform"


def test_validate_script_respects_explicit_format():
    script = {"scenes": [_scene("Ek lamba vaakya jo publish ho sakta hai. " * 4)]}
    assert validate_script(script, "shorts")["format"] == "shorts"


def test_validate_script_unknown_format():
    with pytest.raises(ScriptValidationError, match="unknown script format"):
        validate_script({}, "podcast")
