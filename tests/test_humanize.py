"""The humaniser is the part that makes the voice sound alive — test it hard."""

from __future__ import annotations

import pytest

from studio.voice.humanize import (
    build_utterances,
    estimate_speech_seconds,
    normalize_text,
    number_to_words,
    number_to_words_en,
    number_to_words_hi,
    split_sentences,
)
from studio.voice.types import get_profile


# --------------------------------------------------------------------------- #
# sentence splitting
# --------------------------------------------------------------------------- #
def test_split_on_danda_and_question_marks():
    text = "Inflation kya hai? Ye daam badhne ki prakriya hai। Samjhe?"
    assert split_sentences(text) == [
        "Inflation kya hai?",
        "Ye daam badhne ki prakriya hai।",
        "Samjhe?",
    ]


def test_split_keeps_abbreviations_together():
    sentences = split_sentences("Dr. Rao ne kaha ki ye zaroori hai. Phir wo chale gaye.")
    assert len(sentences) == 2
    assert sentences[0].startswith("Dr. Rao")


def test_split_ignores_decimals_and_ellipsis():
    sentences = split_sentences("Mehngai 6.5 percent badhi... Phir kya hoga?")
    assert len(sentences) == 2
    assert sentences[0].endswith("...")


def test_split_empty_text():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #
def test_normalize_expands_symbols_and_digits():
    out = normalize_text("Aapke ₹500 ka 10% kahan gaya?", "hi")
    assert "₹" not in out
    assert "%" not in out
    assert not any(ch.isdigit() for ch in out)
    assert "रुपये" in out
    assert "प्रतिशत" in out


def test_normalize_english_uses_english_words():
    out = normalize_text("Revenue grew 12% to $40.", "en")
    assert "twelve percent" in out
    assert "$" not in out  # symbol table does not claim $, but digits are spoken


def test_normalize_strips_markdown_but_keeps_paragraphs():
    out = normalize_text("**Pehla** paragraph hai.\n\n*Doosra* paragraph hai.", "hi")
    assert "**" not in out and "*" not in out
    assert "\n\n" in out
    assert out.count("paragraph") == 2


def test_normalize_devanagari_digits():
    out = normalize_text("आज २०२६ साल है।", "hi")
    assert not any(ch in "०१२३४५६७८९" for ch in out)


# --------------------------------------------------------------------------- #
# numbers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "zero"),
        (7, "seven"),
        (21, "twenty one"),
        (100, "one hundred"),
        (105, "one hundred five"),
        (1234, "one thousand two hundred thirty four"),
        (1_000_000, "one million"),
    ],
)
def test_english_numbers(value, expected):
    assert number_to_words_en(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(0, "शून्य"), (21, "इक्कीस"), (45, "पैंतालीस"), (100, "सौ"),
     (125, "सौ पच्चीस"), (2500, "दो हज़ार पाँच सौ")],
)
def test_hindi_numbers(value, expected):
    assert number_to_words_hi(value) == expected


def test_number_to_words_dispatch():
    assert number_to_words(21, "en") == "twenty one"
    assert number_to_words(21, "hindi") == "इक्कीस"


# --------------------------------------------------------------------------- #
# utterance planning
# --------------------------------------------------------------------------- #
def test_utterances_have_pauses_and_zero_tail():
    profile = get_profile("natural")
    utterances = build_utterances("Pehla vaakya hai. Doosra vaakya hai? Teesra.", profile, tag="t")
    assert len(utterances) == 3
    assert all(u.pause_after > 0 for u in utterances[:-1])
    assert utterances[-1].pause_after == 0.0
    assert all(u.tag == "t" for u in utterances)


def test_utterances_are_deterministic():
    profile = get_profile("fast")
    first = build_utterances("Ek. Do. Teen. Chaar.", profile, tag="scene1")
    second = build_utterances("Ek. Do. Teen. Chaar.", profile, tag="scene1")
    assert first == second


def test_paragraph_pause_longer_than_sentence_pause():
    profile = get_profile("natural")
    utterances = build_utterances("Pehla para. Dusra vaakya.\n\nNaya para.", profile)
    # index 1 ends the first paragraph and should carry the paragraph gap
    assert utterances[1].pause_after >= profile.paragraph_pause * 0.85


def test_emphasis_raises_exaggeration():
    profile = get_profile("natural")
    plain = build_utterances("Yeh ek lamba aur shaant vaakya hai jo dheere chalta hai.", profile)[0]
    emphatic = build_utterances("Wow!", profile)[0]
    assert emphatic.emphasis is True
    assert emphatic.exaggeration > plain.exaggeration


def test_fast_profile_is_tighter_than_documentary():
    fast = get_profile("fast")
    documentary = get_profile("documentary")
    assert fast.speed > documentary.speed
    assert fast.sentence_pause < documentary.sentence_pause
    assert fast.cfg_weight < documentary.cfg_weight


def test_preview_estimate_scales_with_speed():
    text = "Aaj hum inflation ko simple example se samjhenge."
    normal = estimate_speech_seconds(text)
    quick = estimate_speech_seconds(text, speed=1.3)
    assert normal > quick > 0


def test_unknown_profile_rejected():
    with pytest.raises(ValueError):
        get_profile("robotic")
