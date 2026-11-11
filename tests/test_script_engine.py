"""Gemini client: retries transient errors, re-prompts on bad JSON, validates."""

from __future__ import annotations

import json

import pytest

from studio import config, resilience, script_engine
from studio.validation import ScriptValidationError


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None,
                 text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def gemini_payload(obj: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj, ensure_ascii=False)}]}}]}


def shorts_script() -> dict:
    return {
        "title": "Inflation kya hai",
        "hook": "Paise ghat rahe hain",
        "category": "finance",
        "scenes": [
            {"say": "Kya aapne kabhi socha hai ki paise ki value kyun ghat jaati hai?",
             "caption": "Kya aapne kabhi socha hai ki paise ki value kyun ghat jaati hai?"},
            {"say": "Aaj ek samosa das rupaye ka hai aur kal pandrah ka ho sakta hai.",
             "caption": "Aaj ek samosa 10 rupaye ka hai."},
        ],
    }


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(resilience.time, "sleep", lambda *_: None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")


def test_generate_shorts_success(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(payload=gemini_payload(shorts_script()))

    monkeypatch.setattr(script_engine.requests, "post", fake_post)
    script = script_engine.generate_shorts_script("Inflation kya hai", "finance")
    assert script["format"] == "shorts"
    assert script["scenes"][0]["caption"].startswith("Kya aapne")
    assert len(calls) == 1


def test_gemini_request_timeout_is_bounded_and_configurable(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "GEMINI_REQUEST_TIMEOUT", 999)
    monkeypatch.setattr(
        script_engine.requests,
        "post",
        lambda *a, **kwargs: seen.append(kwargs["timeout"]) or FakeResponse(
            payload={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        ),
    )

    assert script_engine._post("test-model", "prompt") == "ok"
    assert seen == [120]


def test_generate_retries_transient_http_errors(monkeypatch):
    statuses = [500, 503, 200]
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        if status != 200:
            return FakeResponse(status_code=status, text="upstream error")
        return FakeResponse(payload=gemini_payload(shorts_script()))

    monkeypatch.setattr(script_engine.requests, "post", fake_post)
    script = script_engine.generate_shorts_script("topic")
    assert script["title"] == "Inflation kya hai"
    assert len(calls) == 3


def test_generate_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(
        script_engine.requests, "post",
        lambda *a, **k: FakeResponse(status_code=503, text="down"),
    )
    with pytest.raises(script_engine.GeminiError, match="503"):
        script_engine.generate_shorts_script("topic")


def test_invalid_json_is_reasked_then_fails(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(1)
        return FakeResponse(payload={"candidates": [{"content": {"parts": [
            {"text": "Sure! Here is your script: not json"}]}}]})

    monkeypatch.setattr(script_engine.requests, "post", fake_post)
    with pytest.raises(script_engine.GeminiError, match="invalid JSON"):
        script_engine.generate_shorts_script("topic")
    assert len(calls) == 2


def test_invalid_json_then_valid_recovers(monkeypatch):
    responses = [
        FakeResponse(payload={"candidates": [{"content": {"parts": [
            {"text": "Here you go: ``json"}]}}]}),
        FakeResponse(payload=gemini_payload(shorts_script())),
    ]
    monkeypatch.setattr(script_engine.requests, "post", lambda *a, **k: responses.pop(0))
    script = script_engine.generate_shorts_script("topic")
    assert script["scenes"]


def test_schema_violation_surfaces(monkeypatch):
    broken = {"title": "x", "scenes": []}
    monkeypatch.setattr(
        script_engine.requests, "post",
        lambda *a, **k: FakeResponse(payload=gemini_payload(broken)),
    )
    with pytest.raises(ScriptValidationError, match="no scenes"):
        script_engine.generate_shorts_script("topic")


def test_missing_api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(script_engine.GeminiError, match="GEMINI_API_KEY"):
        script_engine.generate_shorts_script("topic")


def test_longform_generation(monkeypatch):
    longform = {
        "title": "Mutual funds",
        "description": "desc",
        "tags": ["finance"],
        "sections": [
            {"title": "Start", "narration": "Pehla hissa bahut lamba hai. " * 20},
            {"title": "End", "narration": "Doosra hissa bhi lamba hai. " * 20},
        ],
    }
    monkeypatch.setattr(
        script_engine.requests, "post",
        lambda *a, **k: FakeResponse(payload=gemini_payload(longform)),
    )
    script = script_engine.generate_longform_script("Mutual funds", duration_min=7)
    assert script["format"] == "longform"
    assert len(script["sections"]) == 2


def test_generate_seo_shape():
    seo = script_engine.generate_seo({
        "title": "Inflation", "category": "finance", "tags": ["inflation"],
        "sections": [{"title": "A"}, {"title": "B"}],
    })
    assert len(seo["titles"]) == 5
    assert seo["chapters"][0].startswith("00:00")
    assert seo["hashtags"] == ["#inflation"]


# --------------------------------------------------------------------------- #
# model retirement (HTTP 404) must not burn the retry budget
# --------------------------------------------------------------------------- #
def test_retired_primary_model_falls_back_immediately(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "gemini-3.8-flash" in url:
            return FakeResponse(
                status_code=404,
                text='{"error":{"code":404,"message":"This model is no longer available."}}',
            )
        return FakeResponse(payload=gemini_payload(shorts_script()))

    monkeypatch.setattr(script_engine.requests, "post", fake_post)
    script = script_engine.generate_shorts_script("topic")

    assert script["title"] == "Inflation kya hai"
    # one request for the retired model, one for the first fallback — not four
    assert len(calls) == 2
    assert "gemini-3.8-flash" in calls[0]
    assert "gemini-3.7-flash" in calls[1]


def test_400_model_retired_message_is_also_a_fallback(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "gemini-3.8-flash" in url:
            return FakeResponse(
                status_code=400,
                text='{"error":{"code":400,"message":"gemini-3.8-flash is no longer available."}}',
            )
        return FakeResponse(payload=gemini_payload(shorts_script()))

    monkeypatch.setattr(script_engine.requests, "post", fake_post)
    script_engine.generate_shorts_script("topic")
    assert len(calls) == 2


def test_every_configured_model_is_tried_once(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=404, text='{"error":{"message":"no longer available"}}')

    monkeypatch.setattr(script_engine.requests, "post", fake_post)
    with pytest.raises(script_engine.GeminiError) as excinfo:
        script_engine.generate_shorts_script("topic")

    models = script_engine.configured_models()
    assert len(models) >= 2
    assert len(calls) == len(models)
    assert len(set(calls)) == len(calls)  # never retries the same dead model
    message = str(excinfo.value)
    for model in models:
        assert model in message


def test_configured_models_dedupes_and_strips(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "primary")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", " fallback , primary ,, other ")
    assert script_engine.configured_models() == ["primary", "fallback", "other"]


def test_retired_default_model_is_gone():
    """Guard against re-pinning a model Google has already withdrawn."""
    assert config.GEMINI_MODEL != "gemini-2.0-flash"
