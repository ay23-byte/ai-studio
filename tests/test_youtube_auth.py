"""YouTube OAuth refresh/scope failures are safe and actionable."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from studio import config
from studio.publishing.youtube import (
    YOUTUBE_SCOPE,
    YouTubeAuthError,
    _creds,
    _require_channel_read_access,
    upload,
    wait_processed,
)


def _set_oauth_config(monkeypatch):
    monkeypatch.setattr(config, "YT_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(config, "YT_CLIENT_SECRET", "client-secret-value")
    monkeypatch.setattr(config, "YT_REFRESH_TOKEN", "private-refresh-token-value")


def test_invalid_grant_explains_refresh_token_rotation_without_leaking_secrets(monkeypatch):
    _set_oauth_config(monkeypatch)

    def invalid_grant(self, request):
        raise RefreshError("invalid_grant: Bad Request")

    monkeypatch.setattr(Credentials, "refresh", invalid_grant)

    with pytest.raises(YouTubeAuthError) as caught:
        _creds()

    message = str(caught.value)
    assert "invalid, revoked, or expired" in message
    assert "YT_REFRESH_TOKEN" in message
    assert "same OAuth client" in message
    assert "No video was uploaded" in message
    assert "private-refresh-token-value" not in message
    assert "client-secret-value" not in message


def test_other_refresh_errors_are_actionable_but_do_not_mislabel_as_invalid_grant(monkeypatch):
    _set_oauth_config(monkeypatch)

    def unavailable(self, request):
        raise RefreshError("temporarily unavailable")

    monkeypatch.setattr(Credentials, "refresh", unavailable)

    with pytest.raises(YouTubeAuthError) as caught:
        _creds()

    assert "Could not refresh YouTube OAuth credentials" in str(caught.value)
    assert "invalid, revoked, or expired" not in str(caught.value)


def test_missing_oauth_settings_are_reported_before_refresh(monkeypatch):
    monkeypatch.setattr(config, "YT_CLIENT_ID", "")
    monkeypatch.setattr(config, "YT_CLIENT_SECRET", "")
    monkeypatch.setattr(config, "YT_REFRESH_TOKEN", "")

    with pytest.raises(RuntimeError, match="YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN"):
        _creds()


class _InsufficientScope(Exception):
    def __init__(self):
        super().__init__("403 Insufficient Permission")
        self.resp = SimpleNamespace(status=403)
        self.content = b'{"error":{"message":"Insufficient Permission"}}'


def test_read_scope_is_checked_before_upload_and_names_required_scope():
    class ChannelList:
        def execute(self):
            raise _InsufficientScope()

    youtube = SimpleNamespace(
        channels=lambda: SimpleNamespace(list=lambda **kwargs: ChannelList())
    )
    with pytest.raises(YouTubeAuthError) as caught:
        _require_channel_read_access(youtube)
    assert YOUTUBE_SCOPE in str(caught.value)
    assert "No video was uploaded" in str(caught.value)


def test_upload_preflights_read_scope_before_calling_insert(tmp_path, monkeypatch):
    import studio.publishing.youtube as publishing

    class VideoResource:
        def insert(self, **kwargs):
            raise AssertionError("upload insert must not run without read scope")

    class ChannelList:
        def execute(self):
            raise _InsufficientScope()

    youtube = SimpleNamespace(
        channels=lambda: SimpleNamespace(list=lambda **kwargs: ChannelList()),
        videos=lambda: VideoResource(),
    )
    monkeypatch.setattr(publishing, "_youtube", lambda: youtube)
    with pytest.raises(YouTubeAuthError, match="No video was uploaded"):
        upload(tmp_path / "not-opened.mp4", "title", "description", [])


def test_processing_refresh_error_reports_uploaded_id_and_prevents_duplicate(monkeypatch):
    monkeypatch.setattr(
        "studio.publishing.youtube._youtube",
        lambda: (_ for _ in ()).throw(YouTubeAuthError("refresh failure")),
    )
    with pytest.raises(YouTubeAuthError) as caught:
        wait_processed("already-uploaded-id", max_wait=1)
    message = str(caught.value)
    assert "already-uploaded-id" in message
    assert "already saved" in message
    assert "do not upload it again" in message
    assert YOUTUBE_SCOPE in message


def test_processing_scope_error_retains_video_id_and_blocks_reupload(monkeypatch):
    class VideoList:
        def execute(self):
            raise _InsufficientScope()

    youtube = SimpleNamespace(videos=lambda: SimpleNamespace(list=lambda **kwargs: VideoList()))
    monkeypatch.setattr("studio.publishing.youtube._youtube", lambda: youtube)
    with pytest.raises(YouTubeAuthError) as caught:
        wait_processed("already-uploaded-id", max_wait=1)
    message = str(caught.value)
    assert "already-uploaded-id" in message
    assert "already saved" in message
    assert "do not upload it again" in message
    assert YOUTUBE_SCOPE in message
