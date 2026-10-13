"""Naming a conversation from the finished profile.

The label was taken from the first message, when the student had usually said
one thing - "I want to study in Au..." - and everything else arrived over the
next few turns. By the time the report unlocks the slots hold the level they
are applying for, their subject and where, which is a far better answer.

Assembled from those values rather than generated: they are things the student
stated, so a model could only change one, not improve it.
"""

from __future__ import annotations

import pytest

from app.main import _list_countries, profile_title
from app.schemas import EducationLevel, SessionState, SlotPatch


def profile(**fields: object) -> SessionState:
    state = SessionState()
    desired = fields.pop("desired_level", None)
    if fields:
        state.slots.merge(SlotPatch(**fields))
    if desired is not None:
        state.desired_level = desired
    return state


def test_the_case_from_the_screenshot() -> None:
    """A Bachelor's in graphic design, aiming at Australia."""
    state = profile(
        field_of_study="graphic design",
        education_level=EducationLevel.BACHELORS,
        target_country="Australia",
    )
    assert profile_title(state) == "Masters Graphic Design - Australia"


def test_the_level_is_the_one_being_applied_for() -> None:
    """Not the one already held. Titling a Bachelor's graduate's conversation
    "Bachelors" names the thing they have finished."""
    state = profile(
        field_of_study="chemical engineering",
        education_level=EducationLevel.MASTERS,
        target_country="Australia",
    )
    assert profile_title(state).startswith("PhD")


def test_a_stated_preference_wins_over_the_inferred_level() -> None:
    state = profile(
        field_of_study="computer science",
        education_level=EducationLevel.BACHELORS,
        target_country="Germany",
        desired_level=EducationLevel.MASTERS,
    )
    assert profile_title(state) == "Masters Computer Science - Germany"


def test_every_destination_appears() -> None:
    """A student who asked for two countries should not see one of them
    quietly dropped from their own conversation's name."""
    state = profile(
        field_of_study="software engineering",
        education_level=EducationLevel.BACHELORS,
        target_country="Australia",
        extra_countries=["UK"],
    )
    assert profile_title(state) == (
        "Masters Software Engineering - Australia and the UK"
    )


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("graphic design", "Graphic Design"),
        # str.title() turns these into "It" and "Mba", which reads as a typo.
        ("IT", "IT"),
        ("MBA", "MBA"),
        ("data science", "Data Science"),
    ],
)
def test_subjects_are_capitalised_without_flattening_acronyms(
    subject: str, expected: str
) -> None:
    state = profile(
        field_of_study=subject,
        education_level=EducationLevel.BACHELORS,
        target_country="Canada",
    )
    assert profile_title(state) == f"Masters {expected} - Canada"


def test_an_empty_profile_keeps_the_existing_label() -> None:
    """None, not a placeholder - the thread already has a label taken from the
    first message, and that beats something emptier."""
    assert profile_title(SessionState()) is None


def test_listing_no_countries_is_empty_not_an_error() -> None:
    """This raised IndexError. Every existing caller happened to check first,
    which made it a trap for the next one rather than a safe helper."""
    assert _list_countries([]) == ""
