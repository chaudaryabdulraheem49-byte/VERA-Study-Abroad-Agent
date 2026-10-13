"""The Phase 1 -> Phase 2 seam: turning a profile into a search filter.

Nothing here touches a database. The subject is the translation itself, which
is where the two phases can silently disagree: the filter compares strings and
numbers exactly, so a mismatch produces an empty grid rather than an error.
"""

from __future__ import annotations

import pytest

from uuid import uuid4

from app.course_matching import (
    MatchResult,
    build_constraints,
    build_guidance,
    build_query,
    expand_field,
    filter_by_relevance,
    related_fields,
    target_degree_levels,
)
from app.diagnostics import build_card
from app.llm_service import country_aliases
from app.services.phase2.schemas import CourseMatch
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
        "full_name": "Ali Raza",
        "nationality": "Pakistan",
        "cgpa": AcademicScore(raw_value=3.4, scale=GradingScale.US_4_0, scale_max=4.0),
        "field_of_study": "Computer Science",
        "education_level": EducationLevel.BACHELORS,
        "target_country": "UK",
        "language_score": LanguageScore(test="IELTS", overall=7.0),
    }
    values.update(overrides)
    state.slots.merge(SlotPatch(**values))  # type: ignore[arg-type]
    return state


# --------------------------------------------------------------------------- #
# Country spelling
# --------------------------------------------------------------------------- #


def test_destination_expands_to_every_spelling() -> None:
    """The live bug: the interview stores "UK", every crawled page stored
    "United Kingdom", and an exact filter matched none of them."""
    countries = build_constraints(profile(), build_card(profile())).countries
    assert "UK" in countries
    assert "United Kingdom" in countries
    assert "England" in countries


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        ("UK", "United Kingdom"),
        ("USA", "United States"),
        ("UAE", "United Arab Emirates"),
        ("Netherlands", "Holland"),
        ("Germany", "Deutschland"),
    ],
)
def test_aliases_include_the_long_form(canonical: str, expected: str) -> None:
    assert expected in country_aliases(canonical)


def test_aliases_always_contain_the_canonical_name() -> None:
    for name in ("UK", "USA", "Germany", "Canada", "South Korea"):
        assert name in country_aliases(name)


def test_a_region_expands_to_countries() -> None:
    """"Europe" is not a value in the country column; filtering on it
    literally returns nothing at all."""
    state = profile(target_country="Europe")
    countries = build_constraints(state, build_card(state)).countries
    assert "Germany" in countries and "France" in countries
    assert "Europe" not in countries


# --------------------------------------------------------------------------- #
# Degree level
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("held", "applying_for"),
    [
        (EducationLevel.HIGH_SCHOOL, "Bachelors"),
        (EducationLevel.DIPLOMA, "Bachelors"),
        (EducationLevel.BACHELORS, "Masters"),
        (EducationLevel.MASTERS, "PhD"),
        (EducationLevel.DOCTORATE, "PhD"),
    ],
)
def test_the_filter_targets_the_next_degree_up(
    held: EducationLevel, applying_for: str
) -> None:
    """A student holding a Bachelor's is shopping for a Master's. Filtering on
    what they hold would return the course they just finished."""
    assert target_degree_levels(held)[0] == applying_for


def test_a_masters_holder_may_still_want_a_masters() -> None:
    assert set(target_degree_levels(EducationLevel.MASTERS)) == {"PhD", "Masters"}


def test_no_level_means_no_degree_filter() -> None:
    assert target_degree_levels(None) == []


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #


def test_the_card_supplies_the_grade_the_filter_uses() -> None:
    """Both phases must quote one number. If they each derived their own from
    the raw CGPA, the symptom would be courses the student does not qualify
    for."""
    state = profile()
    card = build_card(state)
    constraints = build_constraints(state, card)
    assert constraints.student_gpa_percent == card.conversion.normalized_percentage


def test_tuition_is_not_filtered_on() -> None:
    """No budget is ever collected, so an invented ceiling would silently hide
    options the student might well afford."""
    state = profile()
    assert build_constraints(state, build_card(state)).max_budget_usd is None


def test_an_unheld_language_score_does_not_constrain() -> None:
    """"Planned" means unknown. Filtering on an unknown drops every course that
    states any language requirement at all."""
    state = profile(language_score=LanguageScore(test="PLANNED", overall=None))
    assert build_constraints(state, build_card(state)).student_ielts is None


def test_a_held_band_does_constrain() -> None:
    state = profile(language_score=LanguageScore(test="IELTS", overall=6.5))
    assert build_constraints(state, build_card(state)).student_ielts == 6.5


# --------------------------------------------------------------------------- #
# Relevance floor
#
# The live bug: an English Literature graduate was shown a literature MA at
# 0.647 followed by three data-science degrees at 0.555, 0.547 and 0.540. All
# four passed the grade and country filters, and ranking put the wrong three
# second to fourth because nothing else was left to rank.
# --------------------------------------------------------------------------- #


def match(score: float, title: str = "A course") -> CourseMatch:
    return CourseMatch(
        course_id=uuid4(),
        course_title=title,
        university_name="Somewhere",
        country="United Kingdom",
        degree_level="Masters",
        tuition_fee_usd=30_000,
        currency="GBP",
        tuition_fee_amount=24_000,
        min_gpa_percent=50,
        min_ielts_score=6.5,
        deadline_date=None,
        post_study_work_eligible=True,
        syllabus_description="Modules and assessment.",
        similarity_score=score,
    )


def test_the_tail_below_the_cliff_is_dropped() -> None:
    kept = filter_by_relevance(
        [match(0.647, "Literature MA"), match(0.555), match(0.547), match(0.540)]
    )
    assert [m.course_title for m in kept] == ["Literature MA"]


def test_a_genuine_cluster_is_kept_whole() -> None:
    """The same rule must not trim a subject the index really does cover."""
    kept = filter_by_relevance([match(0.680), match(0.653), match(0.640), match(0.541)])
    assert [m.similarity_score for m in kept] == [0.680, 0.653, 0.640]


def test_a_subject_the_index_does_not_cover_returns_nothing() -> None:
    """Every score mediocre and no cliff to find - a relative rule alone would
    happily return the best of a bad set."""
    assert filter_by_relevance([match(0.541), match(0.531), match(0.528)]) == []


def test_the_best_match_alone_still_has_to_clear_the_floor() -> None:
    assert filter_by_relevance([match(0.587)]) == []
    assert len(filter_by_relevance([match(0.61)])) == 1


def test_no_candidates_is_not_an_error() -> None:
    assert filter_by_relevance([]) == []


# --------------------------------------------------------------------------- #
# Which step emptied the grid
#
# Three outcomes, not two: nothing in the catalogue, something in the
# catalogue the student cannot get into, or plenty they qualify for in the
# wrong subject. Each asks for a different action, so collapsing any two of
# them loses the only part a student can act on.
# --------------------------------------------------------------------------- #


def test_nothing_anywhere_is_reported_as_an_empty_catalogue() -> None:
    assert MatchResult(matches=[], eligible_count=0).shortfall == "catalogue"


def test_eligible_but_off_subject_is_reported_as_a_subject_gap() -> None:
    assert MatchResult(matches=[], eligible_count=4).shortfall == "subject"


def test_a_full_grid_reports_no_shortfall() -> None:
    assert MatchResult(matches=[{}], eligible_count=4).shortfall is None


# --------------------------------------------------------------------------- #
# Writing the subject out in full
#
# The live bug: a student whose field was "Ai" got nothing. Measured against
# the index, "Ai UK Masters" peaked at 0.592 and was rejected by the relevance
# floor; "Artificial Intelligence UK Masters" reached 0.639 on the very same
# courses. Two characters carry almost no signal.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("typed", "expanded"),
    [
        ("Ai", "Artificial Intelligence"),
        ("ai", "Artificial Intelligence"),
        ("AI", "Artificial Intelligence"),
        ("  cs  ", "Computer Science"),
        ("IT", "Information Technology"),
        ("MBA", "Business Administration"),
        ("mbbs", "Medicine"),
        ("maths", "Mathematics"),
    ],
)
def test_an_abbreviated_subject_is_written_out(typed: str, expanded: str) -> None:
    assert expand_field(typed) == expanded


def test_expansion_reaches_inside_a_phrase() -> None:
    """"AI and robotics" must keep the phrase while still writing out the part
    that carries the meaning."""
    assert expand_field("AI and robotics") == "Artificial Intelligence and robotics"


@pytest.mark.parametrize(
    "field",
    ["Mechanical Engineering", "English Literature", "graphic design", "Nursing"],
)
def test_an_ordinary_subject_passes_through_untouched(field: str) -> None:
    assert expand_field(field) == field


@pytest.mark.parametrize("ambiguous", ["BA", "ba", "CE"])
def test_ambiguous_abbreviations_are_left_alone(ambiguous: str) -> None:
    """"BA" is a degree as often as business administration, and "CE" is
    claimed by both civil and computer engineering. Expanding either would put
    a student in the wrong discipline, which is worse than not expanding."""
    assert expand_field(ambiguous) == ambiguous


def test_no_field_expands_to_nothing() -> None:
    assert expand_field(None) == ""
    assert expand_field("") == ""


def test_the_query_carries_the_expanded_subject() -> None:
    assert build_query(profile(field_of_study="Ai")).startswith(
        "Artificial Intelligence"
    )


# --------------------------------------------------------------------------- #
# Broadening, and why it is a fallback rather than the default
#
# Measured against the index: "Artificial Intelligence Australia Masters"
# scored the real AI degree at 0.784 with the next course 0.172 behind it.
# Appending the parent terms dropped the true match to 0.743 and lifted the
# runner-up to 0.658 - the gap closing to 0.085. Broadening every search blurs
# the discipline boundary the floor exists to keep.
# --------------------------------------------------------------------------- #


def test_the_ordinary_query_carries_only_the_subject() -> None:
    query = build_query(profile(field_of_study="AI"))
    assert query.startswith("Artificial Intelligence")
    assert "Computer Science" not in query


def test_broadening_adds_neighbouring_disciplines() -> None:
    query = build_query(profile(field_of_study="AI"), broaden=True)
    assert "Artificial Intelligence" in query
    assert "Computer Science" in query
    assert "Data Science" in query


def test_the_students_own_subject_still_leads_the_broadened_query() -> None:
    """Order matters to an embedding; the subject asked for must not be buried
    behind four neighbours."""
    query = build_query(profile(field_of_study="AI"), broaden=True)
    assert query.index("Artificial Intelligence") < query.index("Computer Science")


def test_neighbours_are_found_through_an_abbreviation() -> None:
    assert "Computer Science" in related_fields("AI")


def test_neighbours_are_found_inside_a_phrase() -> None:
    assert "Machine Learning" in related_fields("artificial intelligence and robotics")


def test_the_most_specific_entry_wins() -> None:
    """"data science" and "computer science" both appear in the table; a field
    naming one must not be matched on the other by accident."""
    assert related_fields("Data Science")[0] == "Statistics"


def test_an_unknown_subject_has_no_neighbours() -> None:
    """Better to return nothing than to invent an adjacency - a wrong
    neighbour puts a student in the wrong discipline."""
    assert related_fields("Egyptology") == []
    assert related_fields(None) == []


def test_broadening_a_subject_with_no_neighbours_changes_nothing() -> None:
    """The retry is skipped entirely when it would re-run the same query."""
    state = profile(field_of_study="Egyptology")
    assert build_query(state, broaden=True) == build_query(state)


# --------------------------------------------------------------------------- #
# The relaxed floor
# --------------------------------------------------------------------------- #


def test_the_fallback_floor_admits_what_the_strict_one_rejects() -> None:
    candidates = [match(0.58), match(0.57)]
    assert filter_by_relevance(candidates) == []
    assert len(filter_by_relevance(candidates, floor=0.55)) == 2


def test_the_relative_margin_still_applies_when_relaxed() -> None:
    """A lower floor must not turn the fallback into "return everything": a
    course 0.2 behind the best is still the wrong answer."""
    kept = filter_by_relevance([match(0.70), match(0.56)], floor=0.55)
    assert [m.similarity_score for m in kept] == [0.70]


# --------------------------------------------------------------------------- #
# Reporting which pass produced the results
# --------------------------------------------------------------------------- #


def test_related_results_are_labelled() -> None:
    """The grid says so on the page; a student comparing these needs to know
    they are not in the subject they asked for."""
    assert MatchResult(matches=[{}], eligible_count=3, from_related_fields=True)
    assert MatchResult(matches=[{}], eligible_count=3).from_related_fields is False


# --------------------------------------------------------------------------- #
# Which shortfall emptied the grid
#
# The live bug: a student with IELTS 6.0 targeting Canada was told "nothing in
# the course index is in Canada at Masters level yet ... a gap in the
# catalogue rather than anything about your grades". Both Canadian courses
# were in the index and both ask for IELTS 7.0 - and the report two boxes
# above had already said the IELTS was the thing to fix.
# --------------------------------------------------------------------------- #


def test_courses_exist_but_the_bar_is_too_high() -> None:
    assert (
        MatchResult(matches=[], eligible_count=0, catalogue_count=2).shortfall
        == "requirements"
    )


def test_an_empty_catalogue_is_reported_as_one() -> None:
    assert (
        MatchResult(matches=[], eligible_count=0, catalogue_count=0).shortfall
        == "catalogue"
    )


def test_eligible_but_off_subject_still_outranks_both() -> None:
    """Passing the hard filter means the bar was cleared, so neither the
    catalogue nor the requirements are what is missing."""
    assert (
        MatchResult(matches=[], eligible_count=4, catalogue_count=9).shortfall
        == "subject"
    )


def test_a_full_grid_has_no_shortfall_whatever_the_catalogue_says() -> None:
    assert (
        MatchResult(matches=[{}], eligible_count=2, catalogue_count=2).shortfall
        is None
    )


def test_the_requirements_are_carried_so_they_can_be_named() -> None:
    """A number the student can act on beats "you do not qualify"."""
    result = MatchResult(
        matches=[],
        eligible_count=0,
        catalogue_count=2,
        lowest_gpa_required=75.0,
        lowest_ielts_required=7.0,
    )
    assert result.lowest_ielts_required == 7.0
    assert result.lowest_gpa_required == 75.0


# --------------------------------------------------------------------------- #
# Query text
# --------------------------------------------------------------------------- #


def test_the_query_names_subject_destination_and_level() -> None:
    assert build_query(profile()) == "Computer Science UK Masters"


def test_an_empty_profile_still_yields_a_query() -> None:
    """An empty string cannot be embedded, so there is a floor."""
    assert build_query(SessionState()).strip()


# --------------------------------------------------------------------------- #
# Country-level guidance
#
# Register-sourced courses publish no entry requirements, so their cards read
# "Not published" - true, but it leaves a student with nothing to aim at. The
# guidance fills that gap without claiming to know any particular course's
# bar, and it is never fed into the filter.
# --------------------------------------------------------------------------- #


def unstated() -> dict[str, object]:
    return {"min_gpa_percent": None, "min_ielts_score": None}


def stated() -> dict[str, object]:
    return {"min_gpa_percent": 70.0, "min_ielts_score": 6.5}


def with_card(**overrides: object) -> SessionState:
    state = profile(**overrides)
    state.last_card = build_card(state)
    return state


def test_guidance_reuses_the_rule_the_report_already_quotes() -> None:
    """One source of truth: a second table would drift from the report card
    and the two would contradict each other on the same page."""
    from app.diagnostics import COUNTRY_RULES

    guidance = build_guidance(with_card(target_country="Australia"), [unstated()])
    assert guidance is not None
    assert guidance["typical_gpa_percent"] == COUNTRY_RULES["australia"]["min_percentage"]
    assert guidance["note"] == COUNTRY_RULES["australia"]["note"]


def test_no_guidance_when_every_course_states_its_own() -> None:
    """It would be noise beside cards that already answer the question."""
    assert build_guidance(with_card(target_country="Australia"), [stated()]) is None


def test_guidance_appears_when_only_some_are_unstated() -> None:
    guidance = build_guidance(
        with_card(target_country="Australia"), [stated(), unstated()]
    )
    assert guidance is not None
    assert guidance["unstated_count"] == 1


def test_no_guidance_without_matches() -> None:
    assert build_guidance(with_card(target_country="Australia"), []) is None


def test_no_guidance_for_a_country_we_have_no_rule_for() -> None:
    """Better to say nothing than to quote a bar invented for the occasion."""
    assert build_guidance(with_card(target_country="Japan"), [unstated()]) is None


def test_guidance_says_whether_the_student_clears_the_bar() -> None:
    clears = build_guidance(
        with_card(
            target_country="Australia",
            cgpa=AcademicScore(raw_value=3.8, scale=GradingScale.US_4_0, scale_max=4.0),
        ),
        [unstated()],
    )
    below = build_guidance(
        with_card(
            target_country="Australia",
            cgpa=AcademicScore(raw_value=2.0, scale=GradingScale.US_4_0, scale_max=4.0),
        ),
        [unstated()],
    )
    assert clears is not None and clears["student_clears"] is True
    assert below is not None and below["student_clears"] is False


def test_guidance_never_reaches_the_filter() -> None:
    """It is advice on a page, not a constraint. If it leaked into the search
    it would exclude the very students it is meant to orient."""
    state = with_card(target_country="Australia")
    constraints = build_constraints(state, state.last_card)
    assert constraints.student_gpa_percent == state.last_card.conversion.normalized_percentage
    assert constraints.student_ielts is None or constraints.student_ielts == 7.0
