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
