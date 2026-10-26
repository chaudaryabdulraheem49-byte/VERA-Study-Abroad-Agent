"""Nationality words: "I am Indian".

A demonym states citizenship and nothing else. A bare country name does not -
"India" could be either slot, so it is asked about. Conflating the two meant
asking a student who had just said they were Indian which slot they meant,
and filing "Indian" as their name over the one read off their transcript.
"""

from __future__ import annotations

import pytest

from app.llm_service import (
    bare_country,
    demonym_country,
    heuristic_extract,
    states_nationality,
)
from app.schemas import SessionState


@pytest.mark.parametrize(
    ("message", "country"),
    [
        ("i am indian", "India"),
        ("I am Pakistani", "Pakistan"),
        ("I'm British", "UK"),
        ("i am iranian", "Iran"),
        # Two-word demonyms: scanning with one alternating pattern pairs words
        # greedily ("a new", then "zealander") and never forms the compound.
        ("I am Sri Lankan", "Sri Lanka"),
        ("I am a new zealander", "New Zealand"),
        ("I am South African", "South Africa"),
        # On its own, with no sentence around it.
        ("indian", "India"),
    ],
)
def test_a_demonym_fills_the_nationality_slot(message: str, country: str) -> None:
    patch = heuristic_extract(message, SessionState())
    assert patch.nationality == country


@pytest.mark.parametrize(
    "message",
    ["i am indian", "I am Pakistani", "I'm British", "I am Sri Lankan", "indian"],
)
def test_a_demonym_is_never_stored_as_a_name(message: str) -> None:
    """"I am X" introduces a person and states a citizenship, and the stopword
    list covered "I am from Pakistan" but not the nationality word itself."""
    assert heuristic_extract(message, SessionState()).full_name is None


@pytest.mark.parametrize(
    "message",
    ["i am indian", "I am Pakistani", "I'm British", "indian"],
)
def test_a_demonym_is_not_ambiguous(message: str) -> None:
    """The either/or question is for a country that could belong to either
    slot. A nationality word cannot."""
    assert bare_country(message) is None


@pytest.mark.parametrize("message", ["India", "Germany", "australia"])
def test_a_bare_country_name_is_still_ambiguous(message: str) -> None:
    """Guard on the fix above: "India" alone genuinely could be either, and
    must keep being asked about."""
    assert bare_country(message) is not None


def test_demonyms_resolve_regardless_of_edit_distance() -> None:
    """Some resolved already by falling through the typo tolerance - "indian"
    is one edit from "india" - but that is luck. "British" and "Iranian" are
    nowhere near their countries and were returning nothing."""
    assert demonym_country("british") == "UK"
    assert demonym_country("iranian") == "Iran"
    assert demonym_country("dutch") == "Netherlands"


@pytest.mark.parametrize(
    "message",
    ["my name is Muhammad Hashim Khan", "I am Raheem", "this is Ayesha"],
)
def test_real_names_are_still_read(message: str) -> None:
    assert heuristic_extract(message, SessionState()).full_name is not None


def test_a_sentence_with_no_demonym_reports_none() -> None:
    assert states_nationality("I want to study in Australia") is None
    assert states_nationality("my name is Raheem") is None


# --------------------------------------------------------------------------- #
# Short forms: "aus", "oz", "nz"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("message", "country"),
    [
        ("I want to study in aus", "Australia"),
        ("study in oz", "Australia"),
        ("masters in nz", "New Zealand"),
    ],
)
def test_a_short_form_is_read_as_a_destination(message: str, country: str) -> None:
    """The prefix rule needs four characters and the typo rule five, so "aus"
    and "nz" were not recognised as countries by any path."""
    assert heuristic_extract(message, SessionState()).target_country == country


@pytest.mark.parametrize(
    "message",
    ["I want to study in aus", "study in oz", "masters in nz"],
)
def test_a_short_form_is_never_the_field_of_study(message: str) -> None:
    """The reported bug: "aus" was resolved to Australia for the destination
    and *also* stored as the student's major, so their diagnostic card read
    "Bachelor's - aus"."""
    assert heuristic_extract(message, SessionState()).field_of_study is None


@pytest.mark.parametrize("short", ["aus", "oz", "nz", "pak", "ksa", "aussie"])
def test_a_short_form_filed_as_a_subject_by_the_model_is_dropped(
    short: str,
) -> None:
    """The model reaches the profile by its own route, so the same test has to
    apply to its output."""
    from app.llm_service import _normalise_patch
    from app.schemas import SlotPatch

    assert _normalise_patch(SlotPatch(field_of_study=short)).field_of_study is None


@pytest.mark.parametrize(
    "subject",
    [
        "graphic design", "computer science", "IT", "economics", "audiology",
        "English Literature", "English", "French Literature", "German Studies",
        "Spanish",
    ],
)
def test_real_subjects_still_survive(subject: str) -> None:
    """Guard on the above: widening what counts as a country must not start
    swallowing actual majors."""
    from app.llm_service import _normalise_patch
    from app.schemas import SlotPatch

    assert _normalise_patch(SlotPatch(field_of_study=subject)).field_of_study == subject


@pytest.mark.parametrize(
    "message",
    [
        "I did a BA in English Literature",
        "BA in English",
        "English Literature",
        "I did a BA in French Literature",
        "I want to study German",
        "My English is good",
        "I need to take an English test",
    ],
)
def test_academic_and_language_mentions_do_not_set_nationality(message: str) -> None:
    """Mentions of academic degrees or languages must never set nationality."""
    assert states_nationality(message) is None
    patch = heuristic_extract(message, SessionState())
    assert patch.nationality is None

