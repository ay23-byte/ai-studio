"""Scheduled runner for GitHub Actions / cron.

* picks the next unused topic from ``topics.json`` (or asks Gemini for one)
* builds the video with the configured voice engine
* ``--upload-latest`` publishes the newest built-but-unpublished video

Usage::

    python run_daily.py --format shorts
    python run_daily.py --upload-latest
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from studio import config, qa
from studio.db import list_videos, pending_upload, save_video, update_video
from studio.logs import configure, get_logger
from studio.notify import send
from studio.pipeline import build_longform, build_shorts
from studio.script_engine import (
    generate_longform_script,
    generate_seo,
    generate_shorts_script,
)

log = get_logger(__name__)

FALLBACK_TOPICS = [
    ("Compound interest kya hai", "finance"),
    ("Bull aur Bear market kya hota hai", "markets"),
    ("CIBIL score kaise improve karen", "money"),
    ("Risk aur return ka rishta", "markets"),
    ("Emergency fund kyun zaroori hai", "money"),
]

CATEGORY_PLAYLISTS = {
    "finance": "Finance Explained | Power Codex",
    "markets": "Share Market | Power Codex",
    "money": "Paise ki Samajh | Power Codex",
    "power": "पावर के नियम | Power Codex",
    "human": "इंसानी व्यवहार | Power Codex",
}

DISCLAIMER = (
    "\n\nयह वीडियो सिर्फ़ शैक्षणिक जानकारी के लिए है।"
    " यह निवेश सलाह नहीं है।"
)


# --------------------------------------------------------------------------- #
# topics
# --------------------------------------------------------------------------- #
def load_topics() -> list[dict[str, Any]]:
    path = config.TOPICS_PATH
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.error("topics.json is not valid JSON")
        return []


def save_topics(topics: list[dict[str, Any]]) -> None:
    config.TOPICS_PATH.write_text(
        json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def next_topic(topics: list[dict[str, Any]], fmt: str) -> dict[str, Any] | None:
    for topic in topics:
        if topic.get("done") or topic.get("skipped") or topic.get("approved") is False:
            continue
        if topic.get("format", fmt) == fmt or not topic.get("format"):
            return topic
    return None


def mark_done(topics: list[dict[str, Any]], topic: dict[str, Any], youtube_id: str | None = None) -> None:
    for item in topics:
        if item.get("title") == topic.get("title"):
            item["done"] = True
            if youtube_id:
                item["youtube_id"] = youtube_id
    save_topics(topics)


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def build_topic(
    topic: dict[str, Any],
    fmt: str,
    *,
    engine: str | None = None,
    profile: str | None = None,
    device: str | None = None,
) -> Path:
    """Build one topic dict into a video, returning the output path."""
    if topic.get("scenes") or topic.get("sections"):
        script = topic
    else:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("topic has no script and GEMINI_API_KEY is not set")
        title = topic.get("title") or topic.get("topic", "")
        category = topic.get("category", "finance")
        generate = generate_shorts_script if fmt == "shorts" else generate_longform_script
        script = generate(title, category)

    language = topic.get("language", "hindi")
    category = topic.get("category", "finance")
    vid = save_video(script.get("title", ""), fmt, language, category, script)
    builder = build_shorts if fmt == "shorts" else build_longform
    return builder(script, vid, engine=engine, profile=profile, device=device)


def _build_fallback(fmt: str, existing: list[dict[str, Any]], **kwargs: Any) -> Path | None:
    """Generate the first unused fallback topic with Gemini."""
    known = {item.get("title", "") for item in existing}
    for title, category in FALLBACK_TOPICS:
        if title in known:
            continue
        try:
            generate = generate_shorts_script if fmt == "shorts" else generate_longform_script
            script = generate(title, category)
            vid = save_video(script.get("title", title), fmt, "hindi", category, script)
            builder = build_shorts if fmt == "shorts" else build_longform
            return builder(script, vid, **kwargs)
        except Exception as exc:  # noqa: BLE001
            send(f"❌ Auto-generate failed: {str(exc)[:200]}")
            raise
    return None


# --------------------------------------------------------------------------- #
# upload
# --------------------------------------------------------------------------- #
def upload_latest() -> bool:
    """Upload the newest built video that has no YouTube id yet."""
    from studio.publishing import (
        YouTubeAuthError,
        add_to_playlist,
        post_comment,
        upload,
        wait_processed,
    )

    for row in pending_upload():
        video_path = Path(row.get("video_path") or "")
        if not video_path.is_file():
            log.warning("job #%s file vanished: %s", row["id"], video_path)
            update_video(row["id"], notes="video file missing")
            continue

        script = json.loads(row.get("script_json") or "{}")
        seo = generate_seo(script)
        title = row.get("title") or "Untitled"
        if row.get("format") == "shorts":
            title = title[:88] + " #Shorts"
        description = script.get("description", f"{config.CHANNEL_NAME} - roz ek naya concept.")
        category = row.get("category", "")
        if category in ("finance", "markets", "money"):
            description += DISCLAIMER
        if row.get("format") == "shorts":
            description += "\n\n#Shorts"

        if os.getenv("SKIP_QA", "").strip().lower() not in {"1", "true", "yes"}:
            report = qa.inspect_video(video_path)
            if not report.ok:
                log.error("QA gate blocked job #%s:\n%s", row["id"], report.summary())
                update_video(row["id"], notes=report.summary())
                send(
                    f"❌ QA gate blocked upload for '{title}': "
                    + ", ".join(check.name for check in report.failures)
                )
                return False
            log.info("QA gate passed (%.1fs, %.1f dBFS)",
                     report.duration, report.mean_volume_db or 0.0)

        log.info("uploading job #%s: %s", row["id"], title)
        try:
            youtube_id = upload(video_path, title, description, seo["tags"],
                                contains_synthetic=True)
            update_video(row["id"], youtube_id=youtube_id, status="uploaded")
            state = wait_processed(youtube_id)
            if state == "failed":
                send(f"❌ YouTube processing failed for: {title}")
                return False
            playlist = CATEGORY_PLAYLISTS.get(category, config.CHANNEL_NAME)
            for step, action in (
                ("playlist", lambda vid=youtube_id, pl=playlist: add_to_playlist(vid, pl)),
                ("comment", lambda vid=youtube_id, text=seo["pinned_comment"]: post_comment(vid, text)),
            ):
                try:
                    action()
                except Exception as exc:  # noqa: BLE001
                    log.warning("%s: %s", step, exc)
            link = (
                f"https://youtube.com/shorts/{youtube_id}"
                if row.get("format") == "shorts"
                else f"https://youtube.com/watch?v={youtube_id}"
            )
            send(f"✅ Uploaded: {title}\n{link}\nTip: pin your comment in Studio.")
            print(f"Uploaded: {link}")
            return True
        except YouTubeAuthError as exc:
            # A revoked/expired refresh token is not transient. Return a clear
            # failed job for Actions/alerts; never retry the same token or upload.
            log.error("YouTube authentication failed: %s", exc)
            send(f"❌ YouTube authentication failed: {str(exc)[:500]}")
            return False
        except Exception as exc:  # noqa: BLE001
            send(f"❌ Upload failed: {str(exc)[:200]}")
            raise

    print("No built-but-unuploaded video found.")
    return False


# --------------------------------------------------------------------------- #
# watchdog
# --------------------------------------------------------------------------- #
def check_freshness(max_age_hours: float = 26.0) -> bool:
    """Fail when the channel has not published within ``max_age_hours``."""
    rows = list_videos(limit=100)
    uploaded = [row for row in rows if row.get("youtube_id")]
    if not uploaded:
        message = "⚠️ Watchdog: no uploaded video found in the studio database."
        send(message)
        print(message)
        return False

    latest = max(uploaded, key=lambda row: row.get("created_at") or "")
    stamp = latest.get("created_at") or ""
    try:
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        message = f"⚠️ Watchdog: unreadable timestamp {stamp!r}"
        send(message)
        print(message)
        return False

    age_hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    ok = age_hours <= max_age_hours
    message = (
        f"{'✅' if ok else '⚠️'} Latest upload {age_hours:.1f}h ago "
        f"(limit {max_age_hours:.0f}h): {latest.get('title')}"
    )
    print(message)
    if not ok:
        send(message)
    return ok


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily AI Studio runner")
    parser.add_argument("--format", choices=["shorts", "long"], default="shorts")
    parser.add_argument("--upload-latest", action="store_true")
    parser.add_argument("--engine", default=None,
                        choices=["auto", "chatterbox", "chatterbox-http", "edge", "silent"])
    parser.add_argument("--profile", default=None)
    parser.add_argument("--device", default=None, choices=["cpu", "cuda", "mps", "xpu"])
    parser.add_argument(
        "--check-freshness", nargs="?", const=26.0, type=float, default=None,
        metavar="HOURS", help="watchdog: fail when nothing was published recently",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure(verbose=args.verbose)
    config.ensure_directories()

    if args.check_freshness is not None:
        return 0 if check_freshness(args.check_freshness) else 1

    if args.upload_latest:
        return 0 if upload_latest() else 1

    voice = {"engine": args.engine, "profile": args.profile, "device": args.device}
    topics = load_topics()
    topic = next_topic(topics, args.format)

    if topic is None:
        if not config.GEMINI_API_KEY:
            send("⚠️ No unused topics in topics.json and no GEMINI_API_KEY set.")
            return 1
        log.info("no pending topics — generating one with Gemini")
        output = _build_fallback(args.format, topics, **voice)
        if output is None:
            send("⚠️ All fallback topics already used. Add new topics to topics.json.")
            return 1
        print(f"Built auto-generated video: {output}")
        return 0

    log.info("building: %s", topic.get("title") or topic.get("topic", ""))
    try:
        output = build_topic(topic, args.format, **voice)
        mark_done(topics, topic)
        print(f"Built: {output}")
        remaining = sum(1 for item in load_topics()
                        if not item.get("done") and not item.get("skipped"))
        if remaining <= 3:
            send(f"⚠️ Only {remaining} topics left in topics.json. Add more soon.")
        return 0
    except Exception as exc:  # noqa: BLE001
        topic["attempts"] = int(topic.get("attempts", 0)) + 1
        if topic["attempts"] >= 3:
            topic["skipped"] = True
        save_topics(topics)
        send(f"❌ Build failed for '{topic.get('title', '')}': {str(exc)[:200]}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
