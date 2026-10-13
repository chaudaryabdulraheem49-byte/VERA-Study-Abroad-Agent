"""Regression tests for slot extraction.

Each block pins a bug that was reported from the live app. These run offline
(no API key), exercising the deterministic extraction layer that also guards
the LLM's output.

    cd backend && .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import pytest

from app.main import _destinations_named, _list_countries

from app.llm_service import (
    _extract_field,
    _extract_score,
    extract_countries,
    _merge_patches,
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
from app.schemas import (
    EducationLevel,
    OnboardingSlots,
    SessionState,
    SlotName,
    SlotPatch,
)


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
    "text", ["graphic design", "IT", "information technology", "economics"]
)
def test_real_majors_survive(text: str) -> None:
    assert _normalise_patch(SlotPatch(field_of_study=text)).field_of_study == text


@pytest.mark.parametrize("text", ["BS", "BFA", "MSc", "bachelors", "intermediate", "phd"])
def test_degree_token_is_a_level_not_a_field(text: str) -> None:
    """Reported: answering "BS" to the level question also set the field."""
    state = awaiting(SlotName.EDUCATION_LEVEL, SlotName.FIELD_OF_STUDY)
    patch = heuristic_extract(text, state)
    assert patch.education_level is not None  # the level is still captured
    assert patch.field_of_study is None
    assert interpret_bare_answer(text, SlotName.FIELD_OF_STUDY) is None
    assert _normalise_patch(SlotPatch(field_of_study=text)).field_of_study is None


def test_degree_plus_subject_keeps_both() -> None:
    patch = heuristic_extract("BS computer science", SessionState())
    assert patch.field_of_study == "computer science"
    assert patch.education_level is EducationLevel.BACHELORS


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


# --------------------------------------------------------------------------- #
# Level of study
#
# The live bug: a student said "intermediate" and the checklist still read
# "Level of study - not provided yet". Two separate faults, both silent.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("level", list(EducationLevel))
def test_the_models_own_answer_survives_normalisation(level: EducationLevel) -> None:
    """`_extract_level` normalises the extraction model's output as well as a
    student's typing, and the model is told to answer with the schema's own
    values. `high_school` is the only one containing an underscore, so it
    matched none of the prose patterns and a *correct* answer became None.
    The other four passed only because their values are single words."""
    assert _extract_level(level.value) is level


@pytest.mark.parametrize(
    "written",
    ["HIGH_SCHOOL", "high-school", "High_School", "  high_school  "],
)
def test_the_canonical_value_is_read_however_it_is_cased(written: str) -> None:
    assert _extract_level(written) is EducationLevel.HIGH_SCHOOL


@pytest.mark.parametrize(
    "typo",
    ["intermidiate", "intermidate", "intermedate", "inter mediate", "Intermidiate"],
)
def test_a_mistyped_intermediate_is_still_intermediate(typo: str) -> None:
    """It is the level a student is most likely to type out in full rather
    than abbreviate, and it is mistyped constantly."""
    state = SessionState()
    state.awaiting = [SlotName.EDUCATION_LEVEL]
    assert heuristic_extract(typo, state).education_level is EducationLevel.HIGH_SCHOOL


def test_a_mistyped_level_inside_a_sentence_is_found() -> None:
    state = SessionState()
    patch = heuristic_extract(
        "i have done intermidiate in medical with percentage of 85", state
    )
    assert patch.education_level is EducationLevel.HIGH_SCHOOL


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("BS", EducationLevel.BACHELORS),
        ("bachelors", EducationLevel.BACHELORS),
        ("MSc", EducationLevel.MASTERS),
        ("PhD", EducationLevel.DOCTORATE),
        ("diploma", EducationLevel.DIPLOMA),
        ("masters in data science", EducationLevel.MASTERS),
        ("A-levels", EducationLevel.HIGH_SCHOOL),
        ("FSc", EducationLevel.HIGH_SCHOOL),
    ],
)
def test_the_other_levels_are_unaffected(text: str, expected: EducationLevel) -> None:
    """The loosened spelling must not start swallowing other answers."""
    state = SessionState()
    state.awaiting = [SlotName.EDUCATION_LEVEL]
    assert heuristic_extract(text, state).education_level is expected


# --------------------------------------------------------------------------- #
# Wanting a level versus holding one
#
# The live bug: "I want to study masters in business" was read as the student's
# existing qualification, flipping a Bachelor's holder to Master's. The search
# then inferred they were shopping for a PhD and put two doctorates at the top
# of a shortlist they had asked to be Master's.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "message",
    [
        "but i want to study masters in business can you show some results",
        "i want to do masters in business",
        "i am planning to do a masters",
        "looking for masters programs",
        "thinking about a masters in finance",
    ],
)
def test_wanting_a_level_does_not_rewrite_what_they_hold(message: str) -> None:
    state = SessionState()
    state.slots.education_level = EducationLevel.BACHELORS
    patch = heuristic_extract(message, state)
    assert patch.desired_level is EducationLevel.MASTERS
    assert patch.education_level is None


@pytest.mark.parametrize(
    "message",
    [
        "i have done my masters in business",
        "i completed my masters",
        "did my masters last year",
    ],
)
def test_holding_a_level_is_still_recorded(message: str) -> None:
    state = SessionState()
    patch = heuristic_extract(message, state)
    assert patch.education_level is EducationLevel.MASTERS
    assert patch.desired_level is None


def test_a_completed_qualification_wins_over_an_intention() -> None:
    """"I want to apply now that I have finished my bachelors" is a statement
    of fact with an intention wrapped around it."""
    state = SessionState()
    patch = heuristic_extract(
        "i want to apply now that i have finished my bachelors", state
    )
    assert patch.education_level is EducationLevel.BACHELORS
    assert patch.desired_level is None


def test_the_preference_survives_the_merge() -> None:
    """`_merge_patches` walks SlotName, and this is not a slot - so it was
    found by the heuristic and then dropped on every turn the model ran,
    which is every turn."""
    heuristic = SlotPatch(desired_level=EducationLevel.MASTERS)
    model = SlotPatch(field_of_study="business")
    merged = _merge_patches(primary=model, secondary=heuristic)
    assert merged.desired_level is EducationLevel.MASTERS
    assert merged.field_of_study == "business"


def test_the_model_may_not_override_a_stated_preference() -> None:
    model = SlotPatch(desired_level=EducationLevel.DOCTORATE)
    heuristic = SlotPatch(desired_level=EducationLevel.MASTERS)
    assert (
        _merge_patches(primary=model, secondary=heuristic).desired_level
        is EducationLevel.DOCTORATE
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Masters", EducationLevel.MASTERS),
        ("master's", EducationLevel.MASTERS),
        ("PhD", EducationLevel.DOCTORATE),
        ("Bachelor", EducationLevel.BACHELORS),
        ("undergraduate", EducationLevel.BACHELORS),
        ("high school", EducationLevel.HIGH_SCHOOL),
    ],
)
def test_a_label_from_the_model_does_not_fail_the_whole_patch(
    label: str, expected: EducationLevel
) -> None:
    """The enum rejected "Masters" outright, and Pydantic fails the *whole*
    patch - so one stylistic choice by the model threw away every other field
    it had correctly extracted."""
    patch = SlotPatch.model_validate(
        {"desired_level": label, "field_of_study": "business"}
    )
    assert patch.desired_level is expected
    assert patch.field_of_study == "business"


# --------------------------------------------------------------------------- #
# Keyboard mashing must not become somebody's name
#
# The live bug: "dldajsfdk" was stored as the full name "Dldajsfdk". The regex
# path had always refused it - the model's output was simply never put through
# the same test, and the model files anything as a name because mashing
# answers the question syntactically.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mash",
    [
        "dldajsfdk",
        "wdladjsdvz",
        "qwertyuiop",
        "asdfgh",
        "zxcvbnm",
        "sdkfjsdlkfj",
        "aaaaaa",
    ],
)
def test_the_models_name_is_refused_when_it_is_mashing(mash: str) -> None:
    assert _normalise_patch(SlotPatch(full_name=mash)).full_name is None


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("Ravi", "Ravi"),
        ("usama khan", "Usama Khan"),
        ("ayesha", "Ayesha"),
        ("McDonald", "McDonald"),
        ("O'Brien", "O'Brien"),
        ("Jan van der Berg", "Jan van der Berg"),
    ],
)
def test_real_names_still_pass(typed: str, stored: str) -> None:
    assert _normalise_patch(SlotPatch(full_name=typed)).full_name == stored


@pytest.mark.parametrize(
    "name",
    [
        "Ng", "Wu", "Nguyen", "Srivastava", "Mwangi", "Bhattacharya",
        "Krzysztof", "Grzegorz", "Wojciech", "Siddharth", "Thandiwe",
        "Chukwuemeka", "Oluwaseun", "Kanokwan", "Phumzile", "Tshepo",
        "Mxolisi", "Qiang", "Xiaoyan", "Yevgeny", "Aaliyah",
    ],
)
def test_the_guard_does_not_reject_real_names(name: str) -> None:
    """Wrongly refusing a real person's name is far worse than storing one
    odd-looking string, so the guard is checked against names from Polish,
    Yoruba, Zulu, Vietnamese, Thai, Mandarin and Arabic."""
    assert not looks_like_noise(name)
    assert _normalise_patch(SlotPatch(full_name=name)).full_name == name


def test_a_single_repeated_character_is_not_a_name() -> None:
    """It has vowels, no consonant run and no keyboard run, so every other
    test passed it."""
    assert looks_like_noise("aaaaaa")
    assert looks_like_noise("ooo")
    assert not looks_like_noise("Lee")  # a real repeat, and a real name


# --------------------------------------------------------------------------- #
# More than one destination
#
# The live bug: answering "Australia , UK" recorded Australia and discarded the
# UK without a word. The dropped country is never mentioned again, so there is
# nothing for the student to notice.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Australia , UK", ["Australia", "UK"]),
        ("Australia and the UK", ["Australia", "UK"]),
        ("germany or canada", ["Germany", "Canada"]),
        ("Australia, UK, Canada", ["Australia", "UK", "Canada"]),
        ("united states and britain", ["USA", "UK"]),
        ("uk", ["UK"]),
    ],
)
def test_every_country_named_is_found(message: str, expected: list[str]) -> None:
    assert extract_countries(message) == expected


def test_two_names_for_one_place_collapse() -> None:
    """"UK and Britain" is one destination, not two."""
    assert extract_countries("uk and britain") == ["UK"]


@pytest.mark.parametrize("message", ["indiana jones", "graphic design", "chilly weather"])
def test_prose_is_not_mistaken_for_a_country(message: str) -> None:
    """Anchored on the country table and word-bounded, so "indiana" is not
    read as "india".

    A word that genuinely *is* a country still matches - "chile con carne"
    yields Chile - and that is correct rather than a miss. The gate above it
    only fires when two or more countries are named on a turn that is already
    about destinations, so a stray food reference goes nowhere."""
    assert extract_countries(message) == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # The label after the number, which _CGPA_RE alone cannot read.
        ("I have a 3.2 GPA", 3.2),
        ("What can I do with my 3.2 GPA?", 3.2),
        ("graduated with a 3.45 GPA", 3.45),
        ("3.2/4.0 CGPA", 3.2),
        # Still works with the label first.
        ("my GPA is 3.2", 3.2),
        ("my cgpa 2.8 out of 4", 2.8),
    ],
)
def test_a_grade_is_read_whichever_side_its_label_sits_on(
    message: str, expected: float
) -> None:
    score = _extract_score(message)
    assert score is not None, f"no grade found in {message!r}"
    assert score.raw_value == expected


@pytest.mark.parametrize(
    "message",
    [
        "I want to study in Australia",
        "I studied for 4 years",
        "I am 22 years old",
        # A label with no figure is not a grade.
        "What can I do with a GPA?",
    ],
)
def test_a_number_near_no_grade_label_is_not_a_grade(message: str) -> None:
    assert _extract_score(message) is None


def test_destinations_are_only_read_when_the_turn_is_about_them() -> None:
    """"I am from India and want to study in Australia" names two countries
    and one destination."""
    state = SessionState()
    assert _destinations_named(
        "I am from India and want to study in Australia", state
    ) == []


def test_citizenship_is_not_counted_as_a_destination() -> None:
    state = SessionState()
    state.slots.merge(SlotPatch(nationality="India"))
    assert _destinations_named(
        "I am from India and want to study in Australia", state
    ) == []


def test_two_destinations_are_reported_when_asked_for() -> None:
    state = SessionState()
    state.slots.merge(SlotPatch(nationality="Pakistan"))
    state.awaiting = [SlotName.TARGET_COUNTRY]
    assert _destinations_named("Australia , UK", state) == ["Australia", "UK"]


def test_one_destination_needs_no_question() -> None:
    state = SessionState()
    state.slots.merge(SlotPatch(nationality="Pakistan"))
    state.awaiting = [SlotName.TARGET_COUNTRY]
    assert _destinations_named("Australia", state) == []


def test_a_misspelt_destination_still_counts_toward_the_question() -> None:
    """"Austraalia UK" names two places, but the literal matcher only sees the
    UK - the model reads the typo. Reported as one destination, the student is
    silently filed under whichever source won, which is the bug this prevents.
    """
    state = SessionState()
    state.slots.merge(SlotPatch(nationality="Pakistan"))
    state.awaiting = [SlotName.TARGET_COUNTRY]
    assert _destinations_named(
        "Austraalia UK", state, SlotPatch(target_country="Australia")
    ) == ["Australia", "UK"]


def test_the_same_country_from_both_sources_is_one_destination() -> None:
    """The model answering "UK" to a message saying "United Kingdom" is
    agreement, not two places to apply to."""
    state = SessionState()
    state.slots.merge(SlotPatch(nationality="Pakistan"))
    state.awaiting = [SlotName.TARGET_COUNTRY]
    assert _destinations_named(
        "United Kingdom", state, SlotPatch(target_country="UK")
    ) == []


def test_citizenship_arriving_in_the_same_patch_is_not_a_destination() -> None:
    """Nothing is on the profile yet, so the home country is only knowable
    from the patch being applied this turn."""
    state = SessionState()
    assert _destinations_named(
        "I am from India and want to study in Australia",
        state,
        SlotPatch(nationality="India", target_country="Australia"),
    ) == []


def test_confirmed_destinations_are_all_kept() -> None:
    slots = OnboardingSlots()
    slots.merge(SlotPatch(target_country="Australia", extra_countries=["UK"]))
    assert slots.destinations() == ["Australia", "UK"]


def test_a_companion_lands_even_when_the_primary_is_unchanged() -> None:
    """A student already recorded as Australia who confirms "Australia and
    Canada" moves only `extra_countries`. The merge skipped the whole slot
    because the primary had not changed, so Canada was dropped in silence -
    and the shortlist, and the directive sent to the model, covered one
    country while the student had agreed to two.
    """
    slots = OnboardingSlots()
    slots.merge(SlotPatch(target_country="Australia"))
    slots.merge(SlotPatch(target_country="Australia", extra_countries=["Canada"]))
    assert slots.destinations() == ["Australia", "Canada"]


def test_restating_the_primary_alone_keeps_the_companions() -> None:
    """Guard on the fix above: repeating "Australia" is not a decision to drop
    Canada, only naming a different single destination is."""
    slots = OnboardingSlots()
    slots.merge(SlotPatch(target_country="Australia", extra_countries=["Canada"]))
    slots.merge(SlotPatch(target_country="Australia"))
    assert slots.destinations() == ["Australia", "Canada"]


def test_choosing_one_destination_clears_the_others() -> None:
    """"Actually, just Canada" has to be able to shrink the list, not add to
    it."""
    slots = OnboardingSlots()
    slots.merge(SlotPatch(target_country="Australia", extra_countries=["UK"]))
    slots.merge(SlotPatch(target_country="Canada"))
    assert slots.destinations() == ["Canada"]


def test_no_destination_is_an_empty_list() -> None:
    assert OnboardingSlots().destinations() == []


@pytest.mark.parametrize(
    ("countries", "phrasing"),
    [
        (["Australia", "UK"], "Australia and the UK"),
        (["Australia", "UK", "Canada"], "Australia, the UK and Canada"),
        (["Germany"], "Germany"),
        (["USA", "Netherlands"], "the USA and the Netherlands"),
    ],
)
def test_the_question_names_them_readably(countries: list[str], phrasing: str) -> None:
    assert _list_countries(countries) == phrasing


def test_the_model_filing_two_countries_as_one_string_is_caught() -> None:
    """The live bug. A model answers "Australia , UK" with
    `target_country="Australia and UK"`, and stored verbatim that becomes a
    country nothing in the index is in - the filter then matches nothing and
    says so without anyone being able to see why.

    No turn-context test is applied here: the model has already decided both
    are destinations by putting them in that field."""
    patch = SlotPatch(target_country="Australia and UK")
    assert _destinations_named("", SessionState(), patch) == ["Australia", "UK"]


@pytest.mark.parametrize(
    "phrasing", ["Australia and UK", "Australia, UK", "Australia and the UK"]
)
def test_every_phrasing_of_two_destinations_is_caught(phrasing: str) -> None:
    patch = SlotPatch(target_country=phrasing)
    assert _destinations_named("", SessionState(), patch) == ["Australia", "UK"]


@pytest.mark.parametrize(
    ("phrase", "resolved"),
    [("the UK", "UK"), ("in Germany", "Germany"), ("study in canada", "Canada")],
)
def test_a_phrase_naming_one_country_resolves_to_it(
    phrase: str, resolved: str
) -> None:
    """A single destination wrapped in prose should be stored as the country,
    not as the prose."""
    assert _normalise_patch(SlotPatch(target_country=phrase)).target_country == resolved


def test_one_destination_does_not_trigger_the_question() -> None:
    patch = SlotPatch(target_country="Germany")
    assert _destinations_named("", SessionState(), patch) == []
