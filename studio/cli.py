"""Command line interface.

    python run.py shorts "Inflation kya hai" --profile fast
    python run.py long   "Mutual funds" --minutes 7 --engine chatterbox
    python run.py voice  "Namaste, yeh aawaz kaisi lagi?" -o sample.wav
    python run.py doctor
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

from studio import __version__, config
from studio.content import DEMO_LONG, DEMO_SHORT
from studio.db import get_video, init_db, list_videos, save_video, update_video
from studio.logs import configure, get_logger
from studio.notify import send
from studio.pipeline import build_longform, build_shorts
from studio.script_engine import (
    generate_longform_script,
    generate_seo,
    generate_shorts_script,
)
from studio.voice import available_engines, preview
from studio.voice.types import PROFILES

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_shorts(args: argparse.Namespace) -> int:
    if args.demo:
        script = dict(DEMO_SHORT)
        log.info("using built-in demo script")
    else:
        log.info("generating Shorts script for: %s", args.topic)
        script = generate_shorts_script(args.topic, args.category)
    script.setdefault("language", args.language)

    vid = save_video(
        script.get("title", args.topic), "shorts", args.language, args.category, script
    )
    out = build_shorts(
        script, vid, engine=args.engine, profile=args.profile,
        voice_reference=args.reference,
    )
    send(f"✅ Shorts built: {script.get('title')}\n{out}")
    print(f"\nDone → {out}")
    return 0


def cmd_long(args: argparse.Namespace) -> int:
    if args.demo:
        script = dict(DEMO_LONG)
        log.info("using built-in demo script")
    else:
        log.info("generating long-form script for: %s", args.topic)
        script = generate_longform_script(
            args.topic, args.category, args.minutes - 2, args.minutes, args.language
        )
    script.setdefault("language", args.language)

    vid = save_video(
        script.get("title", args.topic), "longform", args.language, args.category, script
    )
    out = build_longform(
        script, vid, engine=args.engine, profile=args.profile,
        voice_reference=args.reference,
    )
    send(f"✅ Long-form built: {script.get('title')}\n{out}")
    print(f"\nDone → {out}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    from studio.publishing import add_to_playlist, post_comment, upload

    row = get_video(args.id)
    if not row:
        log.error("job #%s not found", args.id)
        return 2
    script = json.loads(row.get("script_json") or "{}")
    seo = generate_seo(script)
    title = row.get("title", "")
    if row.get("format") == "shorts":
        title = title[:88] + " #Shorts"
    description = script.get("description", f"{config.CHANNEL_NAME} - roz ek naya concept.")
    video_path = Path(row.get("video_path") or "")
    if not video_path.is_file():
        log.error("video file missing for job #%s: %s", args.id, video_path)
        return 2

    log.info("uploading: %s", title)
    youtube_id = upload(video_path, title, description, seo["tags"])
    update_video(args.id, youtube_id=youtube_id, status="uploaded")

    playlist = {
        "finance": "Finance Explained | Power Codex",
        "markets": "Share Market | Power Codex",
        "money": "Paise ki Samajh | Power Codex",
    }.get(row.get("category", ""), config.CHANNEL_NAME)
    for step, action in (("playlist", lambda: add_to_playlist(youtube_id, playlist)),
                         ("comment", lambda: post_comment(youtube_id, seo["pinned_comment"]))):
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - non-fatal
            log.warning("%s failed: %s", step, exc)

    link = (f"https://youtube.com/shorts/{youtube_id}"
            if row.get("format") == "shorts"
            else f"https://youtube.com/watch?v={youtube_id}")
    send(f"✅ Uploaded: {title}\n{link}")
    print(f"Uploaded → {link}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    rows = list_videos(limit=args.limit)
    if not rows:
        print("No videos yet. Try: python run.py demo")
        return 0
    print(f"\n{'ID':>4}  {'Format':>8}  {'Status':>10}  Title")
    print("-" * 78)
    for row in rows:
        suffix = f" -> {row['youtube_id']}" if row.get("youtube_id") else ""
        print(f"{row['id']:>4}  {row['format'] or '':>8}  {row['status'] or '':>10}  "
              f"{(row['title'] or '')[:44]}{suffix}")
    print()
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    out = Path(args.out)
    track = preview(
        args.text, out, language=args.language, engine=args.engine,
        profile=args.profile, reference=args.reference,
    )
    print(f"\nVoice sample → {track.path}")
    print(f"engine={track.engine}  profile={track.profile}  duration={track.duration:.2f}s")
    print(f"sentences={len(track.timings)}")
    for timing in track.timings[:5]:
        print(f"  {timing.start:6.2f} → {timing.end:6.2f}  {timing.text[:64]}")
    if len(track.timings) > 5:
        print(f"  … {len(track.timings) - 5} more")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from studio.media import ffmpeg

    print(f"AI Studio {__version__}  •  Python {platform.python_version()}")
    print(f"project root : {config.ROOT}")
    print(f"output dir   : {config.OUTPUT_DIR}")

    binary = ffmpeg.ffmpeg_bin()
    if binary:
        try:
            version = subprocess.check_output([binary, "-version"], text=True).splitlines()[0]
        except Exception:  # noqa: BLE001
            version = "unknown version"
        print(f"ffmpeg       : {binary}\n               {version[:100]}")
    else:
        print("ffmpeg       : MISSING  (pip install imageio-ffmpeg)")
    print(f"ffprobe      : {ffmpeg.ffprobe_bin() or 'not found (fallback timing in use)'}")

    print("\nvoice engines")
    for item in available_engines():
        mark = "✓" if item["available"] else "·"
        print(f"  {mark} {item['name']:<16} {item['detail']}")
    print(f"  default profile: {config.VOICE_PROFILE} "
          f"(profiles: {', '.join(PROFILES)})")

    keys = {
        "GEMINI_API_KEY": config.GEMINI_API_KEY,
        "CLOUDFLARE_ACCOUNT_ID": config.CF_ACCOUNT_ID,
        "CLOUDFLARE_API_TOKEN": config.CF_API_TOKEN,
        "PIXABAY_API_KEY": config.PIXABAY_API_KEY,
        "YT_REFRESH_TOKEN": config.YT_REFRESH_TOKEN,
        "TELEGRAM_BOT_TOKEN": config.TELEGRAM_BOT_TOKEN,
        "CHATTERBOX_API_URL": os.getenv("CHATTERBOX_API_URL", ""),
    }
    print("\ncredentials")
    for name, value in keys.items():
        print(f"  {'✓' if value else '·'} {name:<22} {'set' if value else 'missing'}")

    topics_path = config.TOPICS_PATH
    if topics_path.exists():
        try:
            pending = sum(1 for t in json.loads(topics_path.read_text(encoding="utf-8"))
                          if not t.get("done") and not t.get("skipped"))
            print(f"\ntopics       : {pending} pending in {topics_path.name}")
        except Exception:  # noqa: BLE001
            print(f"\ntopics       : unreadable ({topics_path})")
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def _add_voice_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", default=None,
                        choices=["auto", "chatterbox", "chatterbox-http", "edge", "silent"],
                        help="TTS backend (default: VOICE_ENGINE or auto)")
    parser.add_argument("--profile", default=None, choices=sorted(PROFILES),
                        help="pacing profile; shorts default to 'fast'")
    parser.add_argument("--reference", default=None,
                        help="reference wav for Chatterbox voice cloning")
    parser.add_argument("--language", default="hindi",
                        help="narration language (hindi, english, hinglish…)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-studio", description="Build human-voiced Hindi/Hinglish videos."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    shorts = sub.add_parser("shorts", help="create a YouTube Short")
    shorts.add_argument("topic", nargs="?", default="Inflation kya hai")
    shorts.add_argument("--category", default="finance")
    shorts.add_argument("--demo", action="store_true", help="use the built-in script")
    _add_voice_args(shorts)
    shorts.set_defaults(func=cmd_shorts)

    long = sub.add_parser("long", help="create a long-form video")
    long.add_argument("topic", nargs="?", default="Share Market explained")
    long.add_argument("--category", default="finance")
    long.add_argument("--minutes", type=int, default=7)
    long.add_argument("--demo", action="store_true")
    _add_voice_args(long)
    long.set_defaults(func=cmd_long)

    upload = sub.add_parser("upload", help="upload a built video to YouTube")
    upload.add_argument("--id", type=int, required=True)
    upload.set_defaults(func=cmd_upload)

    listing = sub.add_parser("list", help="list recent jobs")
    listing.add_argument("--limit", type=int, default=30)
    listing.set_defaults(func=cmd_list)

    demo = sub.add_parser("demo", help="build a demo video with no API keys")
    demo.add_argument("--format", choices=["shorts", "long"], default="shorts")
    _add_voice_args(demo)
    demo.set_defaults(func=_cmd_demo)

    voice = sub.add_parser("voice", help="render a voice sample")
    voice.add_argument("text")
    voice.add_argument("-o", "--out", default="voice_preview.wav")
    _add_voice_args(voice)
    voice.set_defaults(func=cmd_voice)

    doctor = sub.add_parser("doctor", help="diagnose environment and engines")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def _cmd_demo(args: argparse.Namespace) -> int:
    namespace = argparse.Namespace(
        topic="demo", category="finance", language=args.language, demo=True,
        engine=args.engine, profile=args.profile, reference=args.reference,
    )
    if args.format == "shorts":
        return cmd_shorts(namespace)
    namespace.minutes = 7
    return cmd_long(namespace)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure(verbose=getattr(args, "verbose", False))
    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    config.ensure_directories()
    init_db()
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level guard for CI logs
        log.error("%s", exc)
        if getattr(args, "verbose", False):
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
