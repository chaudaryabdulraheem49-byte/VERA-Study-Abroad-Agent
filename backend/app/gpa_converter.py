"""Deterministic grade conversion between US, German and UK/ECTS systems.

Pure functions only: no I/O, no LLM calls, no randomness. Every number a
student sees on a diagnostic card comes from here, so two runs over the same
transcript can never disagree.

The pivot representation is *percentage* (0-100). Each source scale is
normalised to a percentage once, and every target system is derived from that
single normalised value plus the source-scale bounds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import (
    AcademicScore,
    GradeConversion,
    GradingScale,
    SubjectGrade,
    UKClassification,
)

# --------------------------------------------------------------------------- #
# Scale bounds
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ScaleBounds:
    """Nmax / Nmin for one grading scale.

    `min_pass` is the *minimum passing mark* (Nmin), not the bottom of the
    scale: the Bavarian formula is defined over the passing range only.
    """

    max_score: float
    min_pass: float
    inverted: bool = False  # True when a lower number is the better grade

    def __post_init__(self) -> None:
        if self.max_score == self.min_pass:
            raise ValueError("max_score and min_pass must differ")


# Defaults are the most widely used convention per scale. They stay overridable
# because the minimum pass mark genuinely varies by institution (a 10-point
# Indian scale passes at 4.0, a UK percentage at 40).
SCALE_BOUNDS: dict[GradingScale, ScaleBounds] = {
    GradingScale.PERCENTAGE: ScaleBounds(100.0, 50.0),
    GradingScale.US_4_0: ScaleBounds(4.0, 2.0),
    GradingScale.SCALE_5_0: ScaleBounds(5.0, 2.5),
    GradingScale.SCALE_10_0: ScaleBounds(10.0, 4.0),
    GradingScale.SCALE_20_0: ScaleBounds(20.0, 10.0),
    GradingScale.GERMAN_1_5: ScaleBounds(1.0, 4.0, inverted=True),
}

# Country-specific min-pass overrides, keyed by (scale, lowercased country).
# The wrong Nmin skews the Bavarian result by a full grade step, so the common
# conventions are encoded rather than guessed.
COUNTRY_MIN_PASS: dict[tuple[GradingScale, str], float] = {
    (GradingScale.PERCENTAGE, "pakistan"): 40.0,
    (GradingScale.PERCENTAGE, "india"): 40.0,
    (GradingScale.PERCENTAGE, "bangladesh"): 40.0,
    (GradingScale.PERCENTAGE, "nepal"): 40.0,
    (GradingScale.PERCENTAGE, "sri lanka"): 40.0,
    (GradingScale.PERCENTAGE, "nigeria"): 40.0,
    (GradingScale.PERCENTAGE, "china"): 60.0,
    (GradingScale.PERCENTAGE, "iran"): 50.0,
    (GradingScale.SCALE_20_0, "france"): 10.0,
    (GradingScale.SCALE_10_0, "india"): 4.0,
    (GradingScale.SCALE_10_0, "spain"): 5.0,
}


class ConversionError(ValueError):
    """Raised when a grade cannot be converted deterministically."""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def resolve_bounds(
    scale: GradingScale,
    *,
    scale_max: float | None = None,
    min_pass: float | None = None,
    country: str | None = None,
) -> ScaleBounds:
    """Pick Nmax / Nmin for a scale, honouring explicit and country overrides."""
    base = SCALE_BOUNDS.get(scale)
    if base is None:
        if scale_max is None:
            raise ConversionError(
                f"Unknown grading scale {scale!r} and no explicit scale_max given."
            )
        base = ScaleBounds(scale_max, scale_max * 0.5)

    resolved_max = scale_max if scale_max is not None else base.max_score
    resolved_min = min_pass

    if resolved_min is None and country:
        resolved_min = COUNTRY_MIN_PASS.get((scale, country.strip().lower()))

    if resolved_min is None:
        if scale_max is not None and not base.inverted and base.max_score:
            # Rescale the default pass mark proportionally to a custom Nmax.
            resolved_min = base.min_pass * (resolved_max / base.max_score)
        else:
            resolved_min = base.min_pass

    return ScaleBounds(resolved_max, resolved_min, inverted=base.inverted)


# --------------------------------------------------------------------------- #
# Step 1: normalise any source scale to a percentage
# --------------------------------------------------------------------------- #

# Anchors for the US 4.0 <-> percentage mapping, ascending by GPA and used for
# piecewise-linear interpolation in both directions. Strictly monotonic in both
# coordinates, which is what makes the mapping invertible.
US_GPA_ANCHORS: tuple[tuple[float, float], ...] = (
    # (us_gpa, percentage)
    (0.0, 0.0),
    (1.0, 52.0),
    (1.7, 57.0),
    (2.0, 62.0),
    (2.3, 67.0),
    (2.7, 72.0),
    (3.0, 77.0),
    (3.3, 82.0),
    (3.7, 87.0),
    (4.0, 95.0),
)

US_LETTER_BANDS: tuple[tuple[float, str], ...] = (
    # (minimum us_gpa, letter) — evaluated highest-first
    (3.85, "A"),
    (3.50, "A-"),
    (3.15, "B+"),
    (2.85, "B"),
    (2.50, "B-"),
    (2.15, "C+"),
    (1.85, "C"),
    (1.50, "C-"),
    (0.85, "D"),
    (0.00, "F"),
)


def _interpolate(value: float, anchors: tuple[tuple[float, float], ...]) -> float:
    """Piecewise-linear interpolation over ascending (x, y) anchors."""
    first_x, first_y = anchors[0]
    if value <= first_x:
        return first_y
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if value <= x1:
            if x1 == x0:
                return y1
            return y0 + (value - x0) / (x1 - x0) * (y1 - y0)
    return anchors[-1][1]


def us_gpa_to_percentage(gpa: float) -> float:
    """Project a 4.0 GPA back onto a percentage via the shared anchors."""
    return clamp(_interpolate(clamp(gpa, 0.0, 4.0), US_GPA_ANCHORS), 0.0, 100.0)


def percentage_to_us_gpa(percentage: float) -> float:
    """Map a percentage onto the 4.0 scale (inverse of `us_gpa_to_percentage`)."""
    inverted = tuple((pct, gpa) for gpa, pct in US_GPA_ANCHORS)
    return round(clamp(_interpolate(clamp(percentage, 0.0, 100.0), inverted), 0.0, 4.0), 2)


def us_gpa_to_letter(gpa: float) -> str:
    for threshold, letter in US_LETTER_BANDS:
        if gpa >= threshold:
            return letter
    return "F"


def german_grade_to_percentage(grade: float, *, min_pass: float = 4.0) -> float:
    """Invert the German 1-5 scale: 1.0 -> 100%, `min_pass` -> 50%."""
    span = min_pass - 1.0
    if span <= 0:
        raise ConversionError("German min_pass must be greater than 1.0")
    return clamp(100.0 - (clamp(grade, 1.0, 5.0) - 1.0) * (50.0 / span), 0.0, 100.0)


def to_percentage(value: float, scale: GradingScale, *, bounds: ScaleBounds) -> float:
    """Normalise a cumulative grade on any supported scale to 0-100."""
    if scale is GradingScale.PERCENTAGE:
        return clamp(value, 0.0, 100.0)
    if scale is GradingScale.US_4_0:
        return us_gpa_to_percentage(value)
    if scale is GradingScale.GERMAN_1_5:
        return german_grade_to_percentage(value, min_pass=bounds.min_pass)
    if scale in (
        GradingScale.SCALE_5_0,
        GradingScale.SCALE_10_0,
        GradingScale.SCALE_20_0,
    ):
        if bounds.max_score <= 0:
            raise ConversionError("scale_max must be positive")
        return clamp(value / bounds.max_score * 100.0, 0.0, 100.0)
    raise ConversionError(f"Cannot normalise a {scale!r} grade without a known scale.")


# --------------------------------------------------------------------------- #
# Step 2: German — Modified Bavarian Formula
# --------------------------------------------------------------------------- #

GERMAN_LABELS: tuple[tuple[float, str], ...] = (
    # (inclusive upper bound, label) — evaluated best-first, 1.0 is best
    (1.5, "Sehr gut (Very good)"),
    (2.5, "Gut (Good)"),
    (3.5, "Befriedigend (Satisfactory)"),
    (4.0, "Ausreichend (Sufficient)"),
    (5.0, "Nicht bestanden (Fail)"),
)


def modified_bavarian(nd: float, n_max: float, n_min: float) -> float:
    """The Modified Bavarian Formula.

        V = 1 + 3 * ((Nmax - Nd) / (Nmax - Nmin))

    Nmax is the best achievable score, Nmin the minimum passing score and Nd
    the student's score, all on the *same* source scale. Returns the German
    grade clamped to [1.0, 5.0], where 1.0 is best.
    """
    denominator = n_max - n_min
    if denominator == 0:
        raise ConversionError("Nmax and Nmin must differ (division by zero).")
    return round(clamp(1.0 + 3.0 * ((n_max - nd) / denominator), 1.0, 5.0), 2)


def german_label(grade: float) -> str:
    for upper, label in GERMAN_LABELS:
        if grade <= upper:
            return label
    return GERMAN_LABELS[-1][1]


# --------------------------------------------------------------------------- #
# Step 3: UK honours + ECTS
# --------------------------------------------------------------------------- #

UK_BANDS: tuple[tuple[float, UKClassification], ...] = (
    (70.0, UKClassification.FIRST),
    (60.0, UKClassification.UPPER_SECOND),
    (50.0, UKClassification.LOWER_SECOND),
    (40.0, UKClassification.THIRD),
)

ECTS_BANDS: tuple[tuple[float, str], ...] = (
    (70.0, "A"),
    (60.0, "B"),
    (50.0, "C"),
    (45.0, "D"),
    (40.0, "E"),
)


def uk_classification(percentage: float) -> UKClassification:
    for threshold, classification in UK_BANDS:
        if percentage >= threshold:
            return classification
    return UKClassification.FAIL


def ects_grade(percentage: float) -> str:
    for threshold, grade in ECTS_BANDS:
        if percentage >= threshold:
            return grade
    return "F"


# --------------------------------------------------------------------------- #
# Credit-weighted cumulative GPA (when a transcript states no overall figure)
# --------------------------------------------------------------------------- #


def weighted_cumulative(subjects: list[SubjectGrade]) -> float | None:
    """Credit-weighted mean of subject grades; unweighted when credits are absent.

    Returns None when there is nothing numeric to average, so the caller can
    ask the student rather than invent a number.
    """
    graded = [s for s in subjects if s.numeric_grade is not None]
    if not graded:
        return None
    if all(s.credits for s in graded):
        total_credits = sum(s.credits or 0.0 for s in graded)
        if total_credits > 0:
            weighted = sum((s.numeric_grade or 0.0) * (s.credits or 0.0) for s in graded)
            return round(weighted / total_credits, 3)
    return round(sum(s.numeric_grade or 0.0 for s in graded) / len(graded), 3)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def convert(score: AcademicScore, *, country: str | None = None) -> GradeConversion:
    """Convert one cumulative grade into US / German / UK-ECTS equivalents.

    `country` is the student's nationality, used only to pick the right minimum
    passing mark when the transcript does not state one.
    """
    scale = score.scale
    assumptions: list[str] = []

    if scale is GradingScale.UNKNOWN:
        if score.scale_max is None:
            raise ConversionError(
                "The grading scale is unknown. Ask the student for the maximum "
                "possible grade before converting."
            )
        assumptions.append(
            f"Grading scale not stated; treated as a linear 0-{score.scale_max:g} scale."
        )
        if score.scale_max == 100.0:
            scale = GradingScale.PERCENTAGE

    bounds = resolve_bounds(
        scale,
        scale_max=score.scale_max,
        min_pass=score.scale_min_pass,
        country=country,
    )

    if score.scale_min_pass is None:
        from_country = (
            country is not None
            and (scale, country.strip().lower()) in COUNTRY_MIN_PASS
        )
        source = "country convention" if from_country else "scale default"
        assumptions.append(
            f"Minimum passing mark taken as {bounds.min_pass:g} ({source}); a "
            "different institutional pass mark shifts the German grade."
        )

    percentage = round(to_percentage(score.raw_value, scale, bounds=bounds), 2)

    # A source that already is a 4.0 GPA passes through untouched — round
    # tripping it through a percentage would only add error.
    if scale is GradingScale.US_4_0:
        us_gpa = round(clamp(score.raw_value, 0.0, 4.0), 2)
    else:
        us_gpa = percentage_to_us_gpa(percentage)

    if scale is GradingScale.GERMAN_1_5:
        german = round(clamp(score.raw_value, 1.0, 5.0), 2)
        formula = "Source grade is already on the German 1-5 scale."
    else:
        german = modified_bavarian(score.raw_value, bounds.max_score, bounds.min_pass)
        formula = (
            f"V = 1 + 3 x (({bounds.max_score:g} - {score.raw_value:g}) / "
            f"({bounds.max_score:g} - {bounds.min_pass:g})) = {german:.2f}"
        )

    if scale in (GradingScale.SCALE_10_0, GradingScale.SCALE_5_0):
        assumptions.append(
            "CGPA converted to a percentage linearly (CGPA / max x 100). Some "
            "universities publish their own multiplier — use it when your "
            "transcript states one."
        )

    return GradeConversion(
        source_value=score.raw_value,
        source_scale=score.scale,
        normalized_percentage=percentage,
        us_gpa=us_gpa,
        us_letter=us_gpa_to_letter(us_gpa),
        german_grade=german,
        german_label=german_label(german),
        german_formula=formula,
        uk_classification=uk_classification(percentage),
        ects_grade=ects_grade(percentage),
        assumptions=assumptions,
    )
