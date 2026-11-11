"""YouTube upload with scheduled publishing and playlist support.

Google's client libraries are imported lazily so the rest of the studio can run
(and be tested) without the publishing extras installed.
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

from studio import config
from studio.logs import get_logger

log = get_logger(__name__)

# This broader scope is required not just to insert videos, but also to read
# processing status and manage the channel's playlists/comments after upload.
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"


class YouTubeAuthError(RuntimeError):
    """YouTube OAuth credentials cannot be refreshed for this account."""


def _creds():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError(
            "YouTube dependencies missing: pip install -r requirements.txt"
        ) from exc

    missing = [
        name for name in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
        if not getattr(config, name)
    ]
    if missing:
        raise RuntimeError(
            "YouTube credentials missing: " + ", ".join(missing)
            + ". See README > Publishing."
        )
    credentials = Credentials(
        None,
        refresh_token=config.YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YT_CLIENT_ID,
        client_secret=config.YT_CLIENT_SECRET,
    )
    try:
        credentials.refresh(Request())
    except Exception as exc:
        # Google returns invalid_grant when the refresh token was revoked or
        # expired, or when it no longer matches this OAuth client. Retrying the
        # upload cannot repair that state; make the required secret rotation
        # explicit without echoing token/client details into Actions logs.
        error_text = " ".join(str(part) for part in getattr(exc, "args", (exc,)))
        if "invalid_grant" in error_text.casefold():
            raise YouTubeAuthError(
                "YouTube OAuth refresh token is invalid, revoked, or expired. "
                "Re-authorise the intended YouTube channel with the same OAuth "
                "client and the youtube scope, then replace the GitHub Actions "
                "secret YT_REFRESH_TOKEN (and verify YT_CLIENT_ID/"
                "YT_CLIENT_SECRET belong to that client). If the OAuth consent "
                "screen is in Testing, move it to Production or issue a fresh "
                "token regularly; testing-mode refresh tokens expire after "
                "7 days. No video was uploaded."
            ) from exc
        raise YouTubeAuthError(
            "Could not refresh YouTube OAuth credentials. Check that "
            "YT_CLIENT_ID, YT_CLIENT_SECRET, and YT_REFRESH_TOKEN are a matching "
            "set and that the OAuth client is still enabled. No video was uploaded."
        ) from exc
    return credentials


def _youtube():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError(
            "YouTube dependencies missing: pip install -r requirements.txt"
        ) from exc
    return build("youtube", "v3", credentials=_creds(), cache_discovery=False)


def _is_insufficient_scope(exc: Exception) -> bool:
    """Recognise Google's 403 insufficient-permission response safely."""
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", None) or getattr(response, "status_code", None)
    if status != 403:
        return False
    payload = getattr(exc, "content", b"")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    detail = f"{exc} {payload}".casefold()
    return "insufficient" in detail and ("permission" in detail or "scope" in detail)


def _require_channel_read_access(youtube) -> None:
    """Check read scope before uploading bytes, so a narrow grant fails safely."""
    try:
        channels = youtube.channels().list(part="id", mine=True).execute()
    except Exception as exc:
        if _is_insufficient_scope(exc):
            raise YouTubeAuthError(
                "The YouTube OAuth token can upload but cannot read channel/video "
                f"status. Re-authorise the intended channel with scope {YOUTUBE_SCOPE}, "
                "then replace only the YT_REFRESH_TOKEN GitHub Actions secret. "
                "Keep YT_CLIENT_ID and YT_CLIENT_SECRET unchanged unless that OAuth "
                "client was changed. No video was uploaded."
            ) from exc
        raise
    if not channels.get("items"):
        raise YouTubeAuthError(
            "The current YouTube OAuth account has no accessible channel. "
            "Re-authorise the intended channel before uploading; no video was uploaded."
        )


def _publish_time() -> str | None:
    """Next occurrence of PUBLISH_AT_IST as an RFC-3339 UTC timestamp."""
    if not config.PUBLISH_AT_IST:
        return None
    hours, minutes = (int(part) for part in config.PUBLISH_AT_IST.split(":"))
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist)
    target = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if target <= now + datetime.timedelta(minutes=15):
        target += datetime.timedelta(days=1)
    return target.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "27",
    contains_synthetic: bool = True,
) -> str:
    """Upload a video and return its YouTube id."""
    from googleapiclient.http import MediaFileUpload

    youtube = _youtube()
    _require_channel_read_access(youtube)
    status = {
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": contains_synthetic,
    }
    publish_at = _publish_time()
    if publish_at:
        status.update({"privacyStatus": "private", "publishAt": publish_at})
    else:
        status["privacyStatus"] = config.PRIVACY

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": status,
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=5)
    return response["id"]


def add_to_playlist(video_id: str, playlist_title: str) -> str:
    """Add the video to a playlist, creating the playlist when missing."""
    youtube = _youtube()
    playlist_id = None
    listing = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
    for item in listing.get("items", []):
        if item["snippet"]["title"] == playlist_title:
            playlist_id = item["id"]
            break
    if playlist_id is None:
        playlist_id = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": playlist_title},
                "status": {"privacyStatus": "public"},
            },
        ).execute()["id"]
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()
    return playlist_id


def post_comment(video_id: str, text: str) -> None:
    youtube = _youtube()
    youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}},
            }
        },
    ).execute()


def wait_processed(video_id: str, max_wait: int = 600) -> str:
    """Poll until YouTube finishes processing (``ok``/error state)."""
    try:
        youtube = _youtube()
    except YouTubeAuthError as exc:
        raise YouTubeAuthError(
            "YouTube accepted the upload, but OAuth credentials could not be "
            "refreshed to check processing. The video id is "
            f"{video_id} and is already saved; do not upload it again. "
            f"Re-authorise with scope {YOUTUBE_SCOPE}, then update the "
            "YT_REFRESH_TOKEN secret."
        ) from exc
    started = time.time()
    while time.time() - started < max_wait:
        try:
            listing = youtube.videos().list(part="status", id=video_id).execute()
        except Exception as exc:
            if _is_insufficient_scope(exc):
                raise YouTubeAuthError(
                    "YouTube accepted the upload, but this OAuth token cannot read "
                    f"video processing status. The video id is {video_id} and is "
                    "already saved; do not upload it again. Re-authorise the intended "
                    f"channel with scope {YOUTUBE_SCOPE}, then replace the "
                    "YT_REFRESH_TOKEN GitHub Actions secret. Keep the existing "
                    "YT_CLIENT_ID and YT_CLIENT_SECRET unless the OAuth client changed. "
                    "Verify the existing video in YouTube Studio."
                ) from exc
            raise
        items = listing.get("items", [])
        if not items:
            return "not_found"
        upload_status = items[0].get("status", {}).get("uploadStatus", "")
        if upload_status == "processed":
            return "ok"
        if upload_status in ("failed", "rejected", "deleted"):
            return upload_status
        time.sleep(20)
    return "timeout"


__all__ = ["upload", "add_to_playlist", "post_comment", "wait_processed"]
