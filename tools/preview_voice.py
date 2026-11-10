#!/usr/bin/env python3
"""Audition the voice: render one passage in every pacing profile.

    python tools/preview_voice.py --engine chatterbox --reference assets/voices/reference.wav
    python tools/preview_voice.py --engine edge --language english

Samples land in ``output/voice_samples/`` so you can A/B them in any player.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import config  # noqa: E402
from studio.logs import configure, get_logger  # noqa: E402
from studio.voice import (  # noqa: E402
    PROFILES,
    EngineUnavailable,
    engine_status,
    preview,
)

log = get_logger(__name__)

PASSAGE = (
    "Kya aapne kabhi socha hai ki paise ki value chupchap kyun ghat jaati hai? "
    "Chalo ek simple example se samjhein. "
    "Paanch saal pehle sau rupaye mein jitna milta tha, aaj utna nahi milta. "
    "Isi ko inflation kehte hain. "
    "Toh kya sirf paise bachana kaafi hai? Bilkul nahi!"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render voice samples for every profile")
    parser.add_argument("--engine", default=None,
                        choices=["auto", "chatterbox", "chatterbox-http", "edge", "silent"])
    parser.add_argument("--reference", default=None,
                        help="reference clip for Chatterbox voice cloning")
    parser.add_argument("--language", default="hindi")
    parser.add_argument("--text", default=PASSAGE)
    parser.add_argument("--profiles", nargs="*", default=list(PROFILES),
                        choices=list(PROFILES))
    parser.add_argument("--out-dir", default=str(config.OUTPUT_DIR / "voice_samples"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure(verbose=args.verbose)
    config.ensure_directories()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    engine_name = args.engine or config.VOICE_ENGINE or "auto"
    if engine_name != "auto":
        ok, detail = engine_status(engine_name)
        if not ok:
            print(f"Engine {engine_name!r} unavailable: {detail}")
            return 2

    written: list[tuple[str, Path, float]] = []
    for profile in args.profiles:
        target = out_dir / f"{engine_name.replace('-', '_')}_{profile}.wav"
        try:
            track = preview(
                args.text, target, language=args.language,
                engine=args.engine, profile=profile, reference=args.reference,
            )
        except EngineUnavailable as exc:
            print(f"Engine unavailable: {exc}")
            return 2
        written.append((profile, track.path, track.duration))
        print(f"{profile:>12}: {track.duration:5.2f}s → {track.path}")

    print("\nCompare the files and pick a profile with VOICE_PROFILE=<name>.")
    print(f"engine: {engine_name}   samples: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
