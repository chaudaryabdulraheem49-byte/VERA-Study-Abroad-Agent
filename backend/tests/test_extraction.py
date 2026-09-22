"""Regression tests for slot extraction.

Each block pins a bug that was reported from the live app. These run offline
(no API key), exercising the deterministic extraction layer that also guards
the LLM's output.

    cd backend && .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import pytest

from app.llm_service import (
    _extract_field,
    _extract_level,
    _lookup_country,
    _normalise_patch,
    bare_country,
    heuristic_extract,
    interpret_bare_answer,
    looks_like_noise,
    resolve_country_role,
    same_country,
    strip_name_filler,
    title_name,
)
from app.schemas import EducationLevel, SessionState, SlotName, SlotPatch


def awaiting(*slots: SlotName) -> SessionState:
    state = SessionState()
    state.awaiting = list(slots)
    return state


# --------------------------------------------------------------------------- #
# Field of study must be a subject, never a destination
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text", ["in uk", "in the uk", "at canada", "to germany", "for australia"]
)
def test_preposition_country_is_not_a_field(text: str) -> None:
    """Reported: "in uk" was stored as the field of study."""
    assert interpret_bare_answer(text, SlotName.FIELD_OF_STUDY) is None
    # The model's own output is checked too - that was the unguarded path.
    assert _normalise_patch(SlotPatch(field_of_study=text)).field_of_study is None


@pytest.mark.parametrize(
    "text",
    [
        "I want to study in Germany",
        "i want to study in the USA",
        "study in the UK",
        "planning to study in sri lanka",
    ],
)
def test_destination_phrase_is_not_a_field(text: str) -> None:
    assert _extract_field(text) is None


@pytest.mark.parametrize("text", ["India", "Indiaa", "Germany", "srilanka"])
def test_bare_country_is_not_a_field(text: str) -> None:
    assert interpret_bare_answer(text, SlotName.FIELD_OF_STUDY) is None


@pytest.mark.parametrize(
    "text", ["graphic design", "IT", "information technology", "economics", "BFA"]
)
def test_real_majors_survive(text: str) -> None:
    assert _normalise_patch(SlotPatch(field_of_study=text)).field_of_study == text


def test_degree_word_is_not_sliced_into_a_field() -> None:
    """Reported: "bachelors" became the field "chelors"."""
    for text in ("bachelors", "bachelor's", "masters", "BS", "MSc"):
        assert _extract_field(text) is None


def test_article_led_major_survives() -> None:
    assert _extract_field("studying the history of art") == "history of art"


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("ahmad heere", "Ahmad"),  # typo'd filler
        ("hey ahmad here", "Ahmad"),
        ("hii ahmad", "Ahmad"),
        ("HAshim here", "Hashim"),  # mixed case
        ("usama khan here", "Usama Khan"),
    ],
)
def test_name_filler_and_casing(raw: str, want: str) -> None:
    assert strip_name_filler(raw) == want


@pytest.mark.parametrize(
    "raw", ["from pakistan", "not sure yet", "i am not sure yet", "my name"]
)
def test_non_names_are_rejected_not_trimmed(raw: str) -> None:
    """Trimming these once produced the names "Pakistan" and "Yet"."""
    assert strip_name_filler(raw) is None


@pytest.mark.parametrize(
    "name", ["McDonald", "O'Brien", "Jean-Pierre", "DeSilva", "Jan van der Berg"]
)
def test_deliberate_capitalisation_preserved(name: str) -> None:
    assert title_name(name) == name


@pytest.mark.parametrize(("raw", "want"), [("hAsHiM", "Hashim"), ("MUHAMMAD", "Muhammad")])
def test_mistyped_capitalisation_normalised(raw: str, want: str) -> None:
    assert title_name(raw) == want


def test_country_never_becomes_a_name() -> None:
    assert interpret_bare_answer("saudi", SlotName.FULL_NAME) is None


def test_lowercase_name_and_nationality_in_one_sentence() -> None:
    patch = heuristic_extract("i am usama khan from pakistan", SessionState())
    assert (patch.full_name, patch.nationality) == ("Usama Khan", "Pakistan")


def test_name_does_not_leak_into_nationality() -> None:
    patch = heuristic_extract(
        "i am usama khan", awaiting(SlotName.FULL_NAME, SlotName.NATIONALITY)
    )
    assert patch.full_name == "Usama Khan"
    assert patch.nationality is None


# --------------------------------------------------------------------------- #
# Countries
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("indiaa", "India"),
        ("srilanka", "Sri Lanka"),
        ("germay", "Germany"),
        ("saudi", "Saudi Arabia"),
        ("czech", "Czechia"),
        ("turkiye", "Turkey"),
    ],
)
def test_country_typos_and_short_forms(text: str, want: str) -> None:
    assert _lookup_country(text) == want


@pytest.mark.parametrize("text", ["united", "south", "usama khan", "sarah"])
def test_ambiguous_or_non_countries_rejected(text: str) -> None:
    assert _lookup_country(text) is None


@pytest.mark.parametrize("text", ["chile", "china", "iran", "iraq"])
def test_near_miss_countries_stay_distinct(text: str) -> None:
    assert _lookup_country(text) == text.title()


def test_same_country_matches_spellings() -> None:
    assert same_country("Turkey", "turkiye")
    assert same_country("USA", "united states")
    assert not same_country("Turkey", "Germany")


def test_bare_country_detection() -> None:
    assert bare_country("Germany") == "Germany"
    assert bare_country("i am from Pakistan") is None
    assert bare_country("i want to study in Germany") is None


@pytest.mark.parametrize(
    ("reply", "want"),
    [
        ("citizenship", "nationality"),
        ("that is my citizenship", "nationality"),
        ("study", "target_country"),
        ("where i want to study", "target_country"),
        ("yes", None),  # reported: "yes" to an either/or filed a guess
        ("ok", None),
        ("both", None),
    ],
)
def test_country_role_resolution(reply: str, want: str | None) -> None:
    assert resolve_country_role(reply) == want


# --------------------------------------------------------------------------- #
# Levels, scores, noise
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("bachelors", EducationLevel.BACHELORS),
        ("BS computer science", EducationLevel.BACHELORS),
        ("MS in data science", EducationLevel.MASTERS),
        ("FSc pre-engineering", EducationLevel.HIGH_SCHOOL),
        ("phd in physics", EducationLevel.DOCTORATE),
        ("graphic design", None),  # a subject alone implies no level
    ],
)
def test_education_level(text: str, want: EducationLevel | None) -> None:
    assert _extract_level(text) == want


def test_cgpa_correction_phrasing() -> None:
    """Reported: "my CGPA is actually 3.25" was one character too long to parse."""
    score = heuristic_extract("no, my CGPA is actually 3.25", SessionState()).cgpa
    assert score is not None and score.raw_value == 3.25


@pytest.mark.parametrize("text", ["wdladjsdvz", "qwertyuiop", "asdfghjkl"])
def test_keyboard_noise_detected(text: str) -> None:
    assert looks_like_noise(text)


@pytest.mark.parametrize("text", ["i am usama khan", "hi", "3.4", "germany"])
def test_real_messages_are_not_noise(text: str) -> None:
    assert not looks_like_noise(text)
