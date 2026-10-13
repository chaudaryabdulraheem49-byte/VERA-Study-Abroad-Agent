"""Grade conversion: the arithmetic behind every number shown to a student.

This module is pure and deterministic, and it is the only place a CGPA becomes
a US GPA, a German grade or a UK classification. A silent error here is a
student told they qualify for something they do not, so the formulas are
pinned by worked examples rather than by round-tripping the implementation.
"""

from __future__ import annotations

import pytest

from app.gpa_converter import (
    ConversionError,
    convert,
    ects_grade,
    german_label,
    modified_bavarian,
    percentage_to_us_gpa,
    resolve_bounds,
    uk_classification,
    us_gpa_to_percentage,
    weighted_cumulative,
)
from app.schemas import AcademicScore, GradingScale, SubjectGrade


# --------------------------------------------------------------------------- #
# Modified Bavarian Formula:  V = 1 + 3 * ((Nmax - Nd) / (Nmax - Nmin))
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("nd", "nmax", "nmin", "expected"),
    [
        (80, 100, 40, 2.0),  # worked by hand: 1 + 3*(20/60)
        (3.4, 4.0, 2.0, 1.9),  # 1 + 3*(0.6/2.0)
        (100, 100, 40, 1.0),  # best possible grade -> best possible V
        (40, 100, 40, 4.0),  # exactly the pass mark -> the pass grade
    ],
)
def test_bavarian_worked_examples(
    nd: float, nmax: float, nmin: float, expected: float
) -> None:
    assert modified_bavarian(nd, nmax, nmin) == pytest.approx(expected)


def test_bavarian_clamps_below_the_pass_mark() -> None:
    """The scale stops at 5.0; a failing mark must not extrapolate past it."""
    assert modified_bavarian(20, 100, 40) == 5.0


def test_bavarian_rejects_a_zero_range() -> None:
    with pytest.raises(ConversionError):
        modified_bavarian(50, 100, 100)


def test_pass_mark_varies_by_country() -> None:
    """Pakistan passes at 40%, Germany's default assumes 50 - and the choice
    moves the German grade by a meaningful margin."""
    score = AcademicScore(
        raw_value=82, scale=GradingScale.PERCENTAGE, scale_max=100.0
    )
    pakistani = convert(score, country="Pakistan").german_grade
    default = convert(score).german_grade
    assert pakistani == pytest.approx(modified_bavarian(82, 100, 40))
    assert default == pytest.approx(modified_bavarian(82, 100, 50))
    assert pakistani < default  # a lower pass mark is a better German grade


def test_country_bounds_are_resolved() -> None:
    assert resolve_bounds(GradingScale.PERCENTAGE, country="Pakistan").min_pass == 40.0
    assert resolve_bounds(GradingScale.PERCENTAGE, country="China").min_pass == 60.0


@pytest.mark.parametrize(
    ("grade", "fragment"),
    [(1.2, "Sehr gut"), (2.0, "Gut"), (3.0, "Befriedigend"), (4.0, "Ausreichend")],
)
def test_german_labels(grade: float, fragment: str) -> None:
    assert fragment in german_label(grade)


# --------------------------------------------------------------------------- #
# US 4.0 scale
# --------------------------------------------------------------------------- #


def test_us_mapping_is_monotonic() -> None:
    """A higher percentage may never yield a lower GPA."""
    previous = -1.0
    for percent in range(0, 101):
        current = percentage_to_us_gpa(percent)
        assert current >= previous
        previous = current


@pytest.mark.parametrize("gpa", [1.0, 2.0, 3.0, 3.3, 3.7, 4.0])
def test_us_mapping_round_trips(gpa: float) -> None:
    assert percentage_to_us_gpa(us_gpa_to_percentage(gpa)) == pytest.approx(gpa)


def test_a_us_gpa_passes_through_unchanged() -> None:
    """Converting 3.4/4.0 to a percentage and back would only add error."""
    result = convert(AcademicScore(raw_value=3.4, scale=GradingScale.US_4_0))
    assert result.us_gpa == 3.4


# --------------------------------------------------------------------------- #
# UK honours + ECTS
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (70.0, "First Class Honours"),
        (69.9, "Upper Second Class (2:1)"),  # the boundary is exact
        (60.0, "Upper Second Class (2:1)"),
        (50.0, "Lower Second Class (2:2)"),
        (40.0, "Third Class Honours"),
        (39.9, "Below Honours / Fail"),
    ],
)
def test_uk_classification_boundaries(percent: float, expected: str) -> None:
    assert uk_classification(percent).value == expected


@pytest.mark.parametrize(
    ("percent", "grade"), [(75, "A"), (65, "B"), (55, "C"), (47, "D"), (42, "E"), (30, "F")]
)
def test_ects_bands(percent: float, grade: str) -> None:
    assert ects_grade(percent) == grade


# --------------------------------------------------------------------------- #
# Scale normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "scale", "country", "expected_percent"),
    [
        (82, GradingScale.PERCENTAGE, "Pakistan", 82.0),
        (8.1, GradingScale.SCALE_10_0, "India", 81.0),
        (14, GradingScale.SCALE_20_0, "France", 70.0),
        (4.0, GradingScale.SCALE_5_0, "Russia", 80.0),
    ],
)
def test_scales_normalise_to_percentage(
    value: float, scale: GradingScale, country: str, expected_percent: float
) -> None:
    result = convert(AcademicScore(raw_value=value, scale=scale), country=country)
    assert result.normalized_percentage == pytest.approx(expected_percent, abs=0.01)


def test_german_source_grade_is_kept() -> None:
    result = convert(AcademicScore(raw_value=1.7, scale=GradingScale.GERMAN_1_5))
    assert result.german_grade == 1.7
    assert "already on the German" in result.german_formula


def test_unknown_scale_without_a_max_is_refused() -> None:
    """Guessing the scale would silently fabricate every downstream number."""
    with pytest.raises(ConversionError):
        convert(AcademicScore(raw_value=3.4, scale=GradingScale.UNKNOWN))


def test_assumptions_are_reported() -> None:
    """The card shows these, so a borrowed pass mark is never silent."""
    result = convert(
        AcademicScore(raw_value=82, scale=GradingScale.PERCENTAGE, scale_max=100.0)
    )
    assert any("passing mark" in note for note in result.assumptions)


def test_formula_string_shows_the_real_numbers() -> None:
    result = convert(
        AcademicScore(raw_value=3.45, scale=GradingScale.US_4_0), country="Pakistan"
    )
    assert "1 + 3 x ((4 - 3.45) / (4 - 2))" in result.german_formula


# --------------------------------------------------------------------------- #
# Credit-weighted cumulative
# --------------------------------------------------------------------------- #


def test_credit_weighting_beats_a_plain_mean() -> None:
    subjects = [
        SubjectGrade(name="Heavy", credits=6, numeric_grade=4.0),
        SubjectGrade(name="Light", credits=1, numeric_grade=2.0),
    ]
    assert weighted_cumulative(subjects) == pytest.approx((6 * 4 + 1 * 2) / 7, abs=1e-3)


def test_missing_credits_fall_back_to_an_unweighted_mean() -> None:
    subjects = [
        SubjectGrade(name="A", numeric_grade=4.0),
        SubjectGrade(name="B", numeric_grade=2.0),
    ]
    assert weighted_cumulative(subjects) == pytest.approx(3.0)


def test_nothing_numeric_yields_nothing() -> None:
    """Better to ask the student than to invent a cumulative grade."""
    assert weighted_cumulative([SubjectGrade(name="Pass/Fail", grade="P")]) is None
