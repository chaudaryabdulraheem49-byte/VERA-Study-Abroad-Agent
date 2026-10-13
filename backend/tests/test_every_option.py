"""Answering "all of them, or just one?" with "both".

A plain "both" is the commonest answer to that question and is not a yes, so
it settled nothing - and the destinations the student had just agreed to were
dropped without a word, leaving the target country empty.
"""

from __future__ import annotations

import pytest

from app.llm_service import is_affirmation, means_every_option
from app.main import NO_INVENTED_SPECIFICS, _plan_turn
from app.schemas import SessionState, SlotPatch


@pytest.mark.parametrize(
    "message",
    [
        "Both",
        "both",
        "Both of them",
        "Both.",
        "both please",
        "all",
        "all of them",
        "all of those",
        "yes both",
        "the two",
        "each",
        "every one",
    ],
)
def test_these_answers_mean_every_option(message: str) -> None:
    assert means_every_option(message)


@pytest.mark.parametrize(
    "message",
    [
        # "I do not mind which" is a different answer from "all of them", and
        # guessing between them is how a destination gets dropped silently.
        "either",
        "any",
        "just one",
        "one of them",
        "no",
        # A country name settles it by naming, handled on its own branch.
        "Australia",
        # Not a clean answer - it names a preference.
        "both are fine but I prefer UK",
    ],
)
def test_these_answers_do_not(message: str) -> None:
    assert not means_every_option(message)


def test_both_is_not_a_general_yes() -> None:
    """Kept out of `is_affirmation` on purpose: "both" answers *this* question
    and is meaningless as a yes to "do you want to change your grade?"."""
    assert not is_affirmation("both")
    assert not is_affirmation("all of them")


def test_both_records_every_destination() -> None:
    state = SessionState()
    state.slots.merge(SlotPatch(nationality="Pakistan"))
    state.pending_multi_country = ["UK", "Australia"]

    patch = SlotPatch()
    message = "Both"
    if is_affirmation(message) or means_every_option(message):
        chosen = state.pending_multi_country
        patch.target_country = chosen[0]
        patch.extra_countries = chosen[1:]
        state.pending_multi_country = []
    state.slots.merge(patch)

    assert state.slots.destinations() == ["UK", "Australia"]
    assert state.pending_multi_country == []


def test_onboarding_never_asks_for_a_field_that_does_not_exist() -> None:
    """The model asked for a tuition budget, which is not a slot and never
    unlocks anything - so the student is told to meet a requirement that was
    invented on the spot."""
    state = SessionState()
    state.slots.merge(SlotPatch(full_name="Raheem", nationality="Pakistan"))

    directive, _, _ = _plan_turn(state, had_upload=False, slots_changed=True)

    assert "ask for nothing else" in directive.lower()
    assert "there is no budget" in directive.lower()


def test_onboarding_forbids_invented_programmes_too() -> None:
    """It also volunteered "an MSc in Advanced Computer Science" before a
    single search had run."""
    state = SessionState()
    state.slots.merge(SlotPatch(full_name="Raheem", nationality="Pakistan"))

    directive, _, _ = _plan_turn(state, had_upload=False, slots_changed=True)

    assert NO_INVENTED_SPECIFICS in directive


def test_onboarding_does_not_promise_a_shortlist_that_is_not_there() -> None:
    """The shortlist rule ends by telling the model to say the programmes are
    shown below. During onboarding nothing is shown below, so reusing it
    wholesale would have the model state something false."""
    state = SessionState()
    state.slots.merge(SlotPatch(full_name="Raheem", nationality="Pakistan"))

    directive, _, _ = _plan_turn(state, had_upload=False, slots_changed=True)

    assert "shown below" not in directive.lower()


@pytest.mark.parametrize(
    "message",
    [
        # The anchor required the quantifier to open the message, so the
        # commonest phrasings of all were missed.
        "from both",
        "from both countries",
        "both countries",
        "from all of them",
        "search both",
        "in both",
    ],
)
def test_a_quantifier_with_a_preposition_still_means_every_option(
    message: str,
) -> None:
    assert means_every_option(message)


@pytest.mark.parametrize("message", ["from both", "both", "from all of them"])
def test_a_quantifier_is_never_recorded_as_a_country(message: str) -> None:
    """"from both" matched the nationality pattern, which takes a lone
    unlisted word at face value - so "Both" was filed as this student's
    nationality and shown to them as settled fact."""
    from app.llm_service import heuristic_extract

    patch = heuristic_extract(message, SessionState())
    assert patch.nationality is None
    assert patch.target_country is None


def test_a_real_country_after_from_is_still_read() -> None:
    """Guard on the fix above."""
    from app.llm_service import heuristic_extract

    assert heuristic_extract("from Pakistan", SessionState()).nationality == "Pakistan"
