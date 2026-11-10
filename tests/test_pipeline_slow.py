"""Full render test (slow, opt-in with STUDIO_SLOW_TESTS=1).

It exercises the real ffmpeg path end to end with the silent engine, so no
model, network or GPU is required.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from studio.media import ffmpeg
from studio.pipeline import build_shorts
from tests.conftest import requires_ffmpeg

SLOW = pytest.mark.skipif(
    os.getenv("STUDIO_SLOW_TESTS") != "1", reason="set STUDIO_SLOW_TESTS=1 to run"
)

SCRIPT = {
    "title": "Test Short",
    "hook": "Ye test hai",
    "category": "finance",
    "language": "hindi",
    "scenes": [
        {
            "say": "Kya aapne kabhi socha hai ki paise ki value kyun ghat jaati hai?",
            "caption": "Kya aapne kabhi socha hai ki paise ki value kyun ghat jaati hai?",
            "label": "Inflation",
            "image": "test scene",
        },
        {
            "say": "Aaj ek samosa das rupaye ka hai. Kuch saal baad pandrah ka ho sakta hai.",
            "caption": "Aaj ek samosa 10 rupaye ka hai. Kuch saal baad 15 ka ho sakta hai.",
            "label": "Example",
            "image": "test scene two",
        },
    ],
}


@SLOW
@requires_ffmpeg
def test_build_shorts_end_to_end(temp_config, monkeypatch, tmp_path):
    background = temp_config / "bg.jpg"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=0x0a1a3a:s=1024x1536",
                "-frames:v", "1", background])

    import studio.pipeline.shorts as shorts

    monkeypatch.setattr(
        shorts, "generate_image",
        lambda prompt, path: (Path(path).write_bytes(background.read_bytes()), True)[1],
    )
    monkeypatch.setattr(shorts, "fetch_clip", lambda *args, **kwargs: False)
    monkeypatch.setattr(shorts, "pick_music", lambda: None)

    output = build_shorts(SCRIPT, 4242, build_dir=tmp_path / "build",
                          engine="silent", profile="fast")

    assert output.is_file()
    assert output.stat().st_size > 100_000
    assert ffmpeg.duration(output) > 4
    assert (temp_config / "output" / "shorts_4242.jpg").is_file()
