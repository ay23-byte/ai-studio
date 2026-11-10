"""Gemini script generation with retries and schema validation.

Three layers of protection:

* :func:`_ask_gemini` retries transient failures (429/5xx/timeouts) with
  exponential backoff, and falls back to the next configured model when a model
  is retired (HTTP 404) or still failing after its retries;
* :func:`_ask_json` re-prompts when the model returns prose instead of JSON,
  and the result is normalised by :mod:`studio.validation` before anything
  expensive happens.

Model fallback exists because Google retires model ids: a pinned, retired model
returns 404 on every request, and retrying the same id can never succeed.
"""

from __future__ import annotations

import json

import requests

from studio import config
from studio.logs import get_logger
from studio.resilience import RetryExhausted, retry_call
from studio.validation import validate_longform_script, validate_shorts_script

log = get_logger(__name__)

SHORTS_PROMPT = """Write ONE Shorts script for a Hindi/Hinglish YouTube channel about: "{topic}" (category: {category})

RULES:
- "say": Devanagari Hindi only, no English letters or digits, spell numbers in words
- "caption": Roman Hinglish, same number of sentences as "say"
- 5-6 scenes, 10-22 spoken words per scene, 70-110 total words
- Finance topics: education only, no advice, no company names, no promised returns
- Last scene: disclaimer + follow call to action
- "label": 1-3 Roman words max 22 chars
- "image": English AI image prompt (no text, faces, logos, charts with data)
- "keywords": 1-2 English stock footage words

Return ONLY valid JSON:
{{"title":"Roman Hinglish title max 80 chars","hook":"Roman hook question max 50 chars","category":"{category}","scenes":[{{"say":"...","caption":"...","label":"...","image":"...","keywords":["..."]}}]}}"""

LONGFORM_PROMPT = """Write ONE long-form script for a Hindi/Hinglish YouTube channel about: "{topic}"
Category: {category}, Target: {duration_min}-{duration_max} minutes, Language: {language}

Structure: Hook (30s) > Intro (1min) > 3-5 Main Sections (2-3min each) > Summary (1min) > CTA (30s)

Each section needs: "title", "narration" (natural spoken Hinglish), "visuals" (3-5 descriptions),
"image" (AI image prompt, no text/faces/logos), "keywords" (2-3 stock footage words)

Finance: education only, no investment advice, no company names, no promised returns.
Sound like a real person speaking, not an essay.

Return ONLY valid JSON:
{{"title":"...","description":"100 word SEO description","tags":["..."],"hook":"...","category":"{category}","format":"longform","sections":[{{"title":"...","narration":"...","visuals":["..."],"image":"...","keywords":["..."]}}]}}"""

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class GeminiError(RuntimeError):
    """Gemini could not produce a usable answer."""


class TransientHTTPError(GeminiError):
    """A retryable HTTP status was returned."""


class ModelUnavailableError(GeminiError):
    """This model id does not exist for the key (retired, renamed or wrong)."""


def _is_model_unavailable(status: int, body: str) -> bool:
    """A retired model answers 404, or 400 with an explicit explanation."""
    if status == 404:
        return True
    if status != 400:
        return False
    text = body.lower()
    return "no longer available" in text or "is not found" in text or "not supported" in text


def configured_models() -> list[str]:
    """Primary model followed by the fallbacks, de-duplicated, order preserved."""
    raw = [config.GEMINI_MODEL]
    raw += (config.GEMINI_FALLBACK_MODELS or "").split(",")
    models: list[str] = []
    for name in raw:
        name = name.strip()
        if name and name not in models:
            models.append(name)
    return models


def _post(model: str, prompt: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    response = requests.post(
        url,
        headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.85, "maxOutputTokens": 4096},
        },
        timeout=120,
    )
    if _is_model_unavailable(response.status_code, response.text or ""):
        raise ModelUnavailableError(
            f"Gemini model {model!r} is unavailable "
            f"(HTTP {response.status_code}): {(response.text or '')[:200]}"
        )
    if response.status_code in RETRYABLE_STATUS:
        raise TransientHTTPError(f"Gemini HTTP {response.status_code}")
    if response.status_code >= 400:
        raise GeminiError(f"Gemini HTTP {response.status_code}: {response.text[:300]}")

    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini returned no candidates (prompt may have been blocked)")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text.strip():
        raise GeminiError("Gemini returned empty text")
    return text


def _ask_gemini(prompt: str) -> str:
    if not config.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY not set. Get a free key at aistudio.google.com")

    models = configured_models()
    failures: list[str] = []
    for index, model in enumerate(models, start=1):
        try:
            return retry_call(
                lambda m=model: _post(m, prompt),
                attempts=3,
                base_delay=4,
                max_delay=30,
                give_up_on=(ModelUnavailableError,),
                label=f"gemini[{model}]",
            )
        except ModelUnavailableError as exc:
            # Retrying a retired id wastes minutes; move to the next model now.
            log.warning(
                "gemini: %s unavailable (model %d/%d), switching to the next model: %s",
                model, index, len(models), exc,
            )
            failures.append(str(exc))
        except RetryExhausted as exc:
            log.warning(
                "gemini: %s still failing after retries (model %d/%d): %s",
                model, index, len(models), exc.last_error,
            )
            failures.append(f"{model}: {exc.last_error}")
    raise GeminiError(
        "Gemini failed with every configured model ("
        + ", ".join(models)
        + "): "
        + " | ".join(failures)
    )


def _parse(text: str) -> dict:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object in response")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed


def _ask_json(prompt: str, *, label: str = "script") -> dict:
    """Ask for JSON, re-prompting once if the model wrapped it in prose."""
    last_error: Exception | None = None
    for attempt in range(2):
        raw = _ask_gemini(prompt)
        try:
            return _parse(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            log.warning("%s: invalid JSON (attempt %d/2): %s", label, attempt + 1, exc)
            prompt = (
                prompt + "\n\nIMPORTANT: your previous answer was not valid JSON. "
                "Reply with ONLY the JSON object, no prose, no code fences."
            )
    raise GeminiError(f"{label}: Gemini returned invalid JSON twice ({last_error})")


def generate_shorts_script(topic: str, category: str = "finance") -> dict:
    script = _ask_json(
        SHORTS_PROMPT.format(topic=topic, category=category), label="shorts script"
    )
    return validate_shorts_script(script)


def generate_longform_script(
    topic: str,
    category: str = "finance",
    duration_min: int = 5,
    duration_max: int = 8,
    language: str = "Hinglish",
) -> dict:
    script = _ask_json(
        LONGFORM_PROMPT.format(
            topic=topic, category=category,
            duration_min=duration_min, duration_max=duration_max, language=language,
        ),
        label="long-form script",
    )
    return validate_longform_script(script)


def generate_script(topic: str, fmt: str = "shorts", **kwargs) -> dict:
    if fmt in ("long", "longform"):
        return generate_longform_script(topic, **kwargs)
    return generate_shorts_script(topic, **kwargs)


def generate_seo(script: dict) -> dict:
    title = script.get("title", "")
    cat = script.get("category", "") or "education"
    tags = script.get("tags") or ["finance", "hinglish", "education"]
    titles = [
        f"{title} | Engineering Physics",
        f"{title} - Aasaan Hinglish mein",
        f"Kya aap jaante ho? {title}",
        f"{title} | {cat.title()} Explained",
        f"Samjho {title} | Hindi mein",
    ]
    chapters, cursor = [], 0
    for section in script.get("sections", []):
        minutes = cursor // 60
        seconds = cursor % 60
        chapters.append(f"{minutes:02d}:{seconds:02d} {section.get('title', '')}")
        cursor += 120
    return {
        "titles": titles,
        "tags": tags + [cat, "engineering physics", "hindi education"],
        "chapters": chapters,
        "pinned_comment": "कौन सा concept अगले video में समझाएँ? Comment में बताओ 👇",
        "hashtags": [f"#{tag.replace(' ', '')}" for tag in tags[:5]],
    }


__all__ = [
    "GeminiError", "TransientHTTPError", "SHORTS_PROMPT", "LONGFORM_PROMPT",
    "generate_shorts_script", "generate_longform_script", "generate_script",
    "generate_seo",
]
