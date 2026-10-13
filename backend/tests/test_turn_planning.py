"""When the diagnostic card is reprinted, and what the reply may contain.

Both rules exist because the page was talking over itself: the card was
re-sent in full every time the student refined what they were looking for,
and the model was writing its own invented university shortlist directly
above the real one.
"""

from __future__ import annotations

import pytest

from app.diagnostics import build_card
from app.main import SHORTLIST_DIRECTIVE, _plan_turn, _same_report
from app.schemas import (
    AcademicScore,
    EducationLevel,
    GradingScale,
    LanguageScore,
    SessionState,
    SlotPatch,
)


def profile(**overrides: object) -> SessionState:
    state = SessionState()
    values = {
        "full_name": "Mustafa",
        "nationality": "Pakistan",
        "cgpa": AcademicScore(raw_value=3.0, scale=GradingScale.US_4_0, scale_max=4.0),
        "field_of_study": "English Literature",
        "education_level": EducationLevel.BACHELORS,
        "target_country": "Australia",
        "language_score": LanguageScore(test="PLANNED", overall=None),
    }
    values.update(overrides)
    state.slots.merge(SlotPatch(**values))  # type: ignore[arg-type]
    return state


def delivered() -> SessionState:
    state = profile()
    state.last_card = build_card(state)
    state.diagnostics_unlocked = True
    return state


# --------------------------------------------------------------------------- #
# Reprinting the card
# --------------------------------------------------------------------------- #


def test_the_first_report_is_always_new() -> None:
    assert _same_report(build_card(profile()), None) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("field_of_study", "business"), ("target_country", "Canada")],
)
def test_refining_the_search_does_not_reprint_the_card(field: str, value: str) -> None:
    """The card reports a *grade*. Saying "I want to study business instead"
    changes no converted number, yet it used to reprint the whole card - on
    exactly the turn where the student wants the shortlist, not the
    arithmetic again."""
    state = delivered()
    before = state.last_card
    state.slots.merge(SlotPatch(**{field: value}))  # type: ignore[arg-type]
    assert _same_report(build_card(state), before) is True


def test_a_corrected_grade_does_reprint_the_card() -> None:
    """The numbers actually moved, so the old card is now wrong on screen."""
    state = delivered()
    before = state.last_card
    state.slots.merge(
        SlotPatch(
            cgpa=AcademicScore(raw_value=3.8, scale=GradingScale.US_4_0, scale_max=4.0)
        )
    )
    assert _same_report(build_card(state), before) is False


def test_the_planner_withholds_the_card_once_delivered() -> None:
    state = delivered()
    state.slots.merge(SlotPatch(field_of_study="business"))
    _, _, card = _plan_turn(
        state,
        had_upload=False,
        slots_changed=True,
        noise=False,
        deferred=[],
        ambiguous_country=None,
        same_country_as_home=None,
    )
    assert card is None


# --------------------------------------------------------------------------- #
# What the reply may say
# --------------------------------------------------------------------------- #


def test_the_shortlist_rule_reaches_the_follow_up_turn() -> None:
    state = delivered()
    state.slots.merge(SlotPatch(field_of_study="business"))
    directive, _, _ = _plan_turn(
        state,
        had_upload=False,
        slots_changed=True,
        noise=False,
        deferred=[],
        ambiguous_country=None,
        same_country_as_home=None,
    )
    assert SHORTLIST_DIRECTIVE in directive


def test_the_shortlist_rule_reaches_the_first_report_too() -> None:
    """The model volunteered a university list there as well, and that turn
    took a different branch entirely."""
    directive, _, card = _plan_turn(
        profile(),
        had_upload=False,
        slots_changed=True,
        noise=False,
        deferred=[],
        ambiguous_country=None,
        same_country_as_home=None,
    )
    assert card is not None
    assert SHORTLIST_DIRECTIVE in directive


def test_every_confirmed_destination_reaches_the_directive() -> None:
    """A student who confirmed Australia *and* Canada was described to the
    model as going to Australia. Left to cover the other one with nothing to
    go on, it invented universities for both."""
    state = profile()
    state.slots.merge(SlotPatch(target_country="Australia", extra_countries=["Canada"]))

    directive, _, card = _plan_turn(state, had_upload=False, slots_changed=True)

    assert card is not None
    assert "Australia and Canada" in directive


@pytest.mark.parametrize(
    "forbidden",
    [
        "never name a university",
        "invented",
        "never write a list, numbered or bulleted",
        # The model listed Adelaide, RMIT and Curtin "as examples" - so the
        # rule has to close that door explicitly.
        "not as an example",
        # It also converted the grade itself and quoted entry requirements
        # that were never given to it.
        "not given to you verbatim",
    ],
)
def test_the_rule_names_what_it_forbids(forbidden: str) -> None:
    """A vague instruction was ignored; this one has to be specific about the
    thing the model kept doing. Compared case-insensitively, so rewording a
    sentence boundary does not fail the test for the wrong reason."""
    assert forbidden in SHORTLIST_DIRECTIVE.lower()


def test_the_rule_does_not_forbid_what_the_directive_supplies() -> None:
    """The directive hands the model system-computed entry requirements to
    weave in. An unqualified ban on stating any requirement contradicted that,
    and the model resolved the contradiction by ignoring the rule entirely -
    then invented universities as well. The ban is on unverified specifics.
    """
    rule = SHORTLIST_DIRECTIVE.lower()
    assert "not given to you verbatim" in rule
    # The blanket phrasing that caused it must not come back.
    assert "never state an entry requirement" not in rule
