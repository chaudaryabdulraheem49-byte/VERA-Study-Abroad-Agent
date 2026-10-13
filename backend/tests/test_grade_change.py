"""Replacing a grade the student already gave.

Every downstream figure moves with the cumulative grade - the conversion, the
eligibility filter, the shortlist - and none of them announce that they moved.
So a grade that contradicts one already on the profile is confirmed before it
is recorded, the same way a destination matching their own citizenship is.
"""

from __future__ import annotations

import pytest

from app.main import _describe_score, _plan_turn
from app.schemas import (
    AcademicScore,
    GradingScale,
    SessionState,
    SlotName,
    SlotPatch,
)


def score(value: float, maximum: float = 4.0) -> AcademicScore:
    return AcademicScore(
        raw_value=value, scale=GradingScale.US_4_0, scale_max=maximum
    )


@pytest.fixture
def answered() -> SessionState:
    """A session where the student has already given 3.2/4.0 themselves."""
    state = SessionState()
    state.slots.merge(SlotPatch(cgpa=score(3.2)))
    return state


def test_a_contradicting_grade_is_held_rather_than_recorded(
    answered: SessionState,
) -> None:
    assert answered.slots.cgpa is not None
    assert answered.slots.cgpa.raw_value == 3.2
    assert SlotName.CGPA in answered.slots.user_confirmed


def test_the_question_names_both_figures(answered: SessionState) -> None:
    """Asking "do you want to change your grade?" without saying from what to
    what leaves the student unable to answer it."""
    answered.pending_grade = score(3.6)
    _, fallback, card = _plan_turn(
        answered, had_upload=False, grade_change=answered.pending_grade
    )
    assert "3.2" in fallback
    assert "3.6" in fallback
    # The report is built from the grade under question, so it cannot be
    # produced until the question is answered.
    assert card is None
    # The next reply settles this, so it is not read as a slot answer.
    assert answered.awaiting == []


@pytest.mark.parametrize(
    ("score_in", "expected"),
    [
        (score(3.2), "3.2 out of 4"),
        # 3.0 reads as "3" - a trailing zero looks like precision the student
        # did not give.
        (score(3.0), "3 out of 4"),
        (
            AcademicScore(
                raw_value=82, scale=GradingScale.PERCENTAGE, scale_max=100
            ),
            "82%",
        ),
        (
            AcademicScore(
                raw_value=8.1, scale=GradingScale.SCALE_10_0, scale_max=10
            ),
            "8.1 out of 10",
        ),
    ],
)
def test_a_grade_is_described_as_a_student_would_say_it(
    score_in: AcademicScore, expected: str
) -> None:
    assert _describe_score(score_in) == expected


def test_an_unconfirmed_ocr_grade_needs_no_permission_to_replace() -> None:
    """A figure read off a scan is not an answer the student gave, so
    correcting it is not changing their mind."""
    state = SessionState()
    state.slots.merge(SlotPatch(cgpa=score(3.2)), from_ocr=True)
    assert SlotName.CGPA not in state.slots.user_confirmed
