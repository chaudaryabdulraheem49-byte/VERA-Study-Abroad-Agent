"""The report turn does not go through the model.

Four separate instructions told it never to name a university - leading the
prompt, naming the failure, forbidding examples, forbidding unverified figures
- and it listed Waterloo, UBC and Concordia with invented entry requirements
anyway, directly above the real indexed shortlist.

A lite model will not reliably obey a prohibition, and the cost of it
disobeying is a student acting on admissions figures nobody checked. So the
sentences on that turn are written here, from the computed conversion, and the
card and verified grid carry the actual content.
"""

from __future__ import annotations

import pytest

from app.main import _plan_turn
from app.schemas import (
    AcademicScore,
    EducationLevel,
    GradingScale,
    LanguageScore,
    SessionState,
    SlotPatch,
)


def ready(**overrides: object) -> SessionState:
    state = SessionState()
    patch = SlotPatch(
        full_name="Ali",
        nationality="Pakistan",
        cgpa=AcademicScore(
            raw_value=3.0, scale=GradingScale.US_4_0, scale_max=4.0
        ),
        field_of_study="software engineering",
        education_level=EducationLevel.BACHELORS,
        target_country="Canada",
        extra_countries=["UK"],
        language_score=LanguageScore(test="IELTS", overall=7.0),
        **overrides,
    )
    state.slots.merge(patch)
    return state


def test_the_report_turn_produces_a_card() -> None:
    _, _, card = _plan_turn(ready(), had_upload=False, slots_changed=True)
    assert card is not None


@pytest.mark.parametrize(
    "forbidden",
    [
        # Institutions it actually invented, in this exact scenario.
        "Waterloo",
        "UBC",
        "Concordia",
        # Course names it invented before any search had run.
        "MSc",
        "MEng",
        # Requirements and tests nobody supplied.
        "GRE",
        "typically",
        "letters of recommendation",
        # The bulleted wall of text.
        "*",
    ],
)
def test_the_reply_cannot_contain_what_the_model_kept_adding(
    forbidden: str,
) -> None:
    _, reply, _ = _plan_turn(ready(), had_upload=False, slots_changed=True)
    assert forbidden not in reply


def test_the_reply_names_every_destination() -> None:
    """A student who confirmed two countries was told about one."""
    _, reply, _ = _plan_turn(ready(), had_upload=False, slots_changed=True)
    assert "Canada and the UK" in reply


def test_the_reply_quotes_the_computed_conversion() -> None:
    """The figures come from the converter, not from prose - so they cannot
    disagree with the card printed directly beneath them."""
    _, reply, card = _plan_turn(ready(), had_upload=False, slots_changed=True)
    assert card is not None
    conversion = card.conversion
    assert f"{conversion.normalized_percentage:g}%" in reply
    assert conversion.uk_classification.value in reply
    assert conversion.german_label in reply


def test_a_single_destination_still_reads_naturally() -> None:
    state = ready()
    state.slots.merge(SlotPatch(target_country="Canada"))
    state.slots.extra_countries = []
    _, reply, _ = _plan_turn(state, had_upload=False, slots_changed=True)
    assert "Canada" in reply
    assert " and the " not in reply.split("matched for")[-1]


def test_the_report_reply_is_chunked_so_it_still_streams() -> None:
    """The text is fixed, but it should still arrive progressively. Sent as a
    single frame, the one turn that matters most would be the only turn in the
    conversation that lands as a block."""
    from app.llm_service import _chunk_text

    _, reply, card = _plan_turn(ready(), had_upload=False, slots_changed=True)
    assert card is not None

    chunks = _chunk_text(reply)
    assert len(chunks) > 1
    # Chunking must not alter a single character of it.
    assert "".join(chunks) == reply
