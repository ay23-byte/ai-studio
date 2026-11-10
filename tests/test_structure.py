"""Guard rails for the package layout.

These tests catch the failure mode this refactor fixed: half-moved modules that
still import the old ``core.*`` package, or dead files left at the repo root.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from studio import __version__

ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    "studio",
    "studio.config",
    "studio.db",
    "studio.logs",
    "studio.notify",
    "studio.script_engine",
    "studio.cli",
    "studio.daily",
    "studio.content",
    "studio.content.demo_scripts",
    "studio.media",
    "studio.media.ffmpeg",
    "studio.media.images",
    "studio.media.thumbnails",
    "studio.media.editor_shorts",
    "studio.media.editor_longform",
    "studio.voice",
    "studio.voice.types",
    "studio.voice.humanize",
    "studio.voice.assemble",
    "studio.voice.engines",
    "studio.voice.engines.base",
    "studio.voice.engines.chatterbox",
    "studio.voice.engines.chatterbox_server",
    "studio.voice.engines.edge",
    "studio.voice.engines.silent",
    "studio.pipeline",
    "studio.pipeline.captions",
    "studio.pipeline.shorts",
    "studio.pipeline.longform",
    "studio.publishing",
    "studio.publishing.youtube",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)


def test_no_legacy_core_imports():
    legacy = "co" + "re"  # built at runtime so this file does not match itself
    offenders = []
    for path in ROOT.rglob("*.py"):
        if {".git", ".venv", "build"} & set(path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if f"from {legacy}" in text or f"import {legacy}" in text:
            offenders.append(path.relative_to(ROOT))
    assert offenders == []


def test_loose_modules_moved_into_package():
    for stale in ("config.py", "db.py", "voice.py", "pipeline.py",
                  "editor_shorts.py", "editor_longform.py", "images.py",
                  "script_engine.py", "uploader.py", "notify.py", "thumbnail.py"):
        assert not (ROOT / stale).exists(), f"{stale} should live under studio/"


def test_entrypoint_shims_exist():
    assert (ROOT / "run.py").is_file()
    assert (ROOT / "run_daily.py").is_file()
    assert (ROOT / "studio" / "__main__.py").is_file()


def test_version_is_semver_like():
    parts = __version__.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts[:2])


def test_workflows_live_in_github_dir():
    workflows = ROOT / ".github" / "workflows"
    assert (workflows / "make-shorts.yml").is_file()
    assert (workflows / "make-longform.yml").is_file()
    assert not (ROOT / "make_shorts.yml").exists()
