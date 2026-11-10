"""Turn written script text into human-sounding speech units.

The trick to a human-sounding narration is not a single "voice" button: it is
sentence-level synthesis with deliberate, *varied* pauses, slight tempo
changes and occasional breaths.  This module does the planning; the engines
only have to say the words.

Everything is deterministic for a given text + profile because each chunk gets
its own seeded RNG, so cached audio stays reproducible.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable

from studio.voice.types import (
    PacingProfile,
    SpeechChunk,
    Utterance,
    language_code,
)

# --------------------------------------------------------------------------- #
# number words
# --------------------------------------------------------------------------- #
_EN_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()

_HI_NUMBERS = [
    "शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ",
    "दस", "ग्यारह", "बारह", "तेरह", "चौदह", "पंद्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस",
    "बीस", "इक्कीस", "बाईस", "तेईस", "चौबीस", "पच्चीस", "छब्बीस", "सत्ताईस", "अट्ठाईस", "उनतीस",
    "तीस", "इकतीस", "बत्तीस", "तैंतीस", "चौंतीस", "पैंतीस", "छत्तीस", "सैंतीस", "अड़तीस", "उनतालीस",
    "चालीस", "इकतालीस", "बयालीस", "तैंतालीस", "चवालीस", "पैंतालीस", "छियालीस", "सैंतालीस", "अड़तालीस", "उनचास",
    "पचास", "इक्यावन", "बावन", "तिरपन", "चौवन", "पचपन", "छप्पन", "सत्तावन", "अट्ठावन", "उनसठ",
    "साठ", "इकसठ", "बासठ", "तिरसठ", "चौंसठ", "पैंसठ", "छियासठ", "सड़सठ", "अड़सठ", "उनहत्तर",
    "सत्तर", "इकहत्तर", "बहत्तर", "तिहत्तर", "चौहत्तर", "पचहत्तर", "छिहत्तर", "सतहत्तर", "अठहत्तर", "उनासी",
    "अस्सी", "इक्यासी", "बयासी", "तिरासी", "चौरासी", "पचासी", "छियासी", "सत्तासी", "अट्ठासी", "नवासी",
    "नब्बे", "इक्यानवे", "बानवे", "तिरानवे", "चौरानवे", "पचानवे", "छियानवे", "सत्तानवे", "अट्ठानवे", "निन्यानवे",
]

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _english_below_thousand(n: int) -> str:
    words: list[str] = []
    if n >= 100:
        words.append(f"{_EN_ONES[n // 100]} hundred")
        n %= 100
    if n >= 20:
        words.append(_EN_TENS[n // 10])
        n %= 10
    if n:
        words.append(_EN_ONES[n])
    return " ".join(words)


def number_to_words_en(n: int) -> str:
    if n < 0:
        return "minus " + number_to_words_en(-n)
    if n == 0:
        return "zero"
    scales = ((10**9, "billion"), (10**6, "million"), (10**3, "thousand"))
    parts: list[str] = []
    for value, name in scales:
        if n >= value:
            parts.append(f"{_english_below_thousand(n // value)} {name}")
            n %= value
    if n:
        parts.append(_english_below_thousand(n))
    return " ".join(parts)


def number_to_words_hi(n: int) -> str:
    if n < 0:
        return "माइनस " + number_to_words_hi(-n)
    if n <= 99:
        return _HI_NUMBERS[n]
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = "सौ" if hundreds == 1 else f"{_HI_NUMBERS[hundreds]} सौ"
        return f"{head} {_HI_NUMBERS[rest]}" if rest else head
    for value, name in ((10**7, "करोड़"), (10**5, "लाख"), (1000, "हज़ार")):
        if n >= value:
            count, rest = divmod(n, value)
            head = f"{number_to_words_hi(count)} {name}"
            return f"{head} {number_to_words_hi(rest)}" if rest else head
    return str(n)


def number_to_words(n: int, language: str = "hi") -> str:
    return number_to_words_en(n) if language_code(language) == "en" else number_to_words_hi(n)


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "no", "fig",
    "approx", "st", "mt", "rs", "e.g", "i.e", "u.s", "u.k", "a.m", "p.m",
}
_MULTI_SPACE = re.compile(r"[ \t]+")
_SENTENCE_END = re.compile(r"[।.!?…]+(?=\s|$)")


def _replace_symbols(text: str, language: str) -> str:
    hindi = language_code(language) != "en"
    table = {
        "%": " प्रतिशत" if hindi else " percent",
        "₹": " रुपये " if hindi else " rupees ",
        "$": " डॉलर " if hindi else " dollars ",
        "€": " यूरो " if hindi else " euros ",
        "&": " और " if hindi else " and ",
        "=": " बराबर " if hindi else " equals ",
        "+": " प्लस " if hindi else " plus ",
        "≈": " लगभग " if hindi else " about ",
    }
    for symbol, spoken in table.items():
        text = text.replace(symbol, spoken)
    return text


def _expand_numbers(text: str, language: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(0).replace(",", "")
        try:
            if "." in raw:
                whole, frac = raw.split(".", 1)
                point = "पॉइंट" if language_code(language) != "en" else "point"
                digits = " ".join(number_to_words(int(d), language) for d in frac if d.isdigit())
                return f"{number_to_words(int(whole), language)} {point} {digits}".strip()
            if len(raw) > 1 and raw.startswith("0"):
                # years like 2024 read digit-by-digit feel wrong; read as a number
                raw = raw.lstrip("0") or "0"
            return number_to_words(int(raw), language)
        except (ValueError, IndexError):
            return match.group(0)

    return re.sub(r"\d+(?:,\d{3})*(?:\.\d+)?", repl, text)


def normalize_text(text: str, language: str = "hi", *, expand_numbers_flag: bool = True) -> str:
    """Clean markdown/HTML noise and make digits speakable.

    Paragraph breaks (blank lines) are preserved because they drive the longer
    "paragraph" pause in the humaniser.
    """
    if not text:
        return ""
    text = str(text).translate(_DEVANAGARI_DIGITS)
    paragraphs = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    cleaned: list[str] = []
    for para in paragraphs:
        para = re.sub(r"<[^>]+>", " ", para)
        para = re.sub(r"[*_#`]+", "", para)
        para = para.replace("—", " - ").replace("–", " - ")
        para = re.sub(r"\s*\n\s*", " ", para)
        para = _MULTI_SPACE.sub(" ", para).strip()
        if not para:
            continue
        para = _replace_symbols(para, language)
        if expand_numbers_flag:
            para = _expand_numbers(para, language)
        # normalise punctuation spacing
        para = re.sub(r"\s+([,;:.!?।…])", r"\1", para)
        para = re.sub(r"([,;:])(?=\S)", r"\1 ", para)
        para = re.sub(r"\.{2,}", "…", para)
        cleaned.append(para.strip())
    return "\n\n".join(cleaned)


def _is_abbreviation(token: str) -> bool:
    core = token.strip().strip("()[]\"'").lower()
    if core in _ABBREVIATIONS:
        return True
    # single initials such as "R." or "A.K."
    return bool(re.fullmatch(r"(?:[a-z]\.){1,3}[a-z]?", core))


def split_sentences(text: str) -> list[str]:
    """Split on danda, ``.``, ``?``, ``!`` and ellipses without breaking "Dr."."""
    text = (text or "").strip()
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        segment = text[start:end].strip()
        if not segment:
            start = end
            continue
        if match.group(0).startswith("."):
            previous = re.search(r"([\w.'’]+)\.$", segment)
            if previous and _is_abbreviation(previous.group(1)):
                continue
        sentences.append(segment)
        start = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if s]


def _ensure_terminal(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] not in ".!?।…":
        text += "."
    # Devanagari danda confuses some models; a full stop is safer.
    return text.replace("।", ".")


def _pause_for(sentence: str, profile: PacingProfile, rng) -> float:
    stripped = sentence.rstrip()
    if stripped.endswith("?"):
        base = profile.question_pause
    elif stripped.endswith("!"):
        base = profile.exclaim_pause
    elif stripped.endswith("…"):
        base = profile.sentence_pause + 0.18
    else:
        base = profile.sentence_pause
    # Shorter sentences get slightly shorter gaps — the way people actually
    # breathe between clipped lines.
    words = len(stripped.split())
    if words <= 4:
        base *= 0.8
    elif words >= 24:
        base *= 1.15
    return max(0.05, base * rng.uniform(1 - profile.pause_jitter, 1 + profile.pause_jitter))


def _is_emphasis(sentence: str) -> bool:
    stripped = sentence.strip()
    words = stripped.split()
    if not words:
        return False
    if stripped.endswith(("!", "?")):
        return True
    if len(words) <= 5:
        return True
    return any(w.isupper() and len(w) > 2 for w in words if w.isascii())


def build_utterances(
    text: str,
    profile: PacingProfile,
    *,
    language: str = "hi",
    tag: str = "",
    seed: int | None = None,
) -> list[Utterance]:
    """Plan sentence-level utterances (text, pause, tempo, emphasis) for a chunk."""
    normalized = normalize_text(text, language)
    if not normalized:
        return []
    rng_seed = seed if seed is not None else zlib.crc32(f"{tag}|{text}".encode())
    rng = _rng(rng_seed)
    paragraphs = [p for p in normalized.split("\n\n") if p.strip()]
    utterances: list[Utterance] = []
    for p_index, paragraph in enumerate(paragraphs):
        sentences = split_sentences(paragraph)
        for s_index, sentence in enumerate(sentences):
            pause = _pause_for(sentence, profile, rng)
            is_last_in_paragraph = s_index == len(sentences) - 1
            if is_last_in_paragraph and p_index != len(paragraphs) - 1:
                pause = max(pause, profile.paragraph_pause * rng.uniform(0.9, 1.15))
            emphasis = _is_emphasis(sentence)
            speed = profile.speed * (1 + rng.uniform(-profile.speed_jitter, profile.speed_jitter))
            exaggeration = profile.exaggeration + (profile.emphasis_boost if emphasis else 0.0)
            breath = (
                profile.breath_probability > 0
                and pause >= 0.22
                and rng.random() < profile.breath_probability
            )
            utterances.append(
                Utterance(
                    text=_ensure_terminal(sentence),
                    pause_after=round(pause, 3),
                    speed=round(speed, 4),
                    exaggeration=round(exaggeration, 3),
                    cfg_weight=profile.cfg_weight,
                    emphasis=emphasis,
                    breath_after=breath,
                    tag=tag,
                )
            )
    if utterances:
        last = utterances[-1]
        utterances[-1] = Utterance(
            text=last.text, pause_after=0.0, speed=last.speed,
            exaggeration=last.exaggeration, cfg_weight=last.cfg_weight,
            emphasis=last.emphasis, breath_after=False, tag=last.tag,
        )
    return utterances


def build_utterances_for_chunks(
    chunks: Iterable[SpeechChunk],
    profile: PacingProfile,
    *,
    language: str = "hi",
) -> list[Utterance]:
    planned: list[Utterance] = []
    for index, chunk in enumerate(chunks):
        tag = chunk.tag or f"chunk{index}"
        planned.extend(
            build_utterances(
                chunk.text, profile, language=language, tag=tag,
                seed=zlib.crc32(f"{index}|{tag}".encode()),
            )
        )
    return planned


def _rng(seed: int):
    import random

    return random.Random(seed)


def estimate_speech_seconds(text: str, language: str = "hi", speed: float = 1.0) -> float:
    """Rough duration estimate used by the silent engine and dry runs."""
    words = len(normalize_text(text, language).split())
    wps = 3.1 if language_code(language) == "en" else 2.5
    return max(0.35, words / (wps * max(speed, 0.5)))


__all__ = [
    "normalize_text", "split_sentences", "build_utterances",
    "build_utterances_for_chunks", "number_to_words", "number_to_words_en",
    "number_to_words_hi", "estimate_speech_seconds",
]
