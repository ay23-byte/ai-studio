"""YouTube OAuth refresh failures are actionable and never expose credentials."""

from __future__ import annotations

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from studio import config
from studio.publishing.youtube import YouTubeAuthError, _creds


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
