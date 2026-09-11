"""Assembly of the Phase 1 diagnostic card from session state.

Conversion maths lives in `gpa_converter`; this module only decides what the
numbers mean for the student's chosen destination.
"""

from __future__ import annotations

from typing import Final

from .gpa_converter import ConversionError, convert
from .schemas import (
    DiagnosticCardPayload,
    EducationLevel,
    GradeConversion,
    LanguageScore,
    LanguageTest,
    SessionState,
    UKClassification,
)


class DiagnosticsUnavailable(RuntimeError):
    """Raised when the onboarding barrier has not actually been cleared."""


# Destination thresholds, expressed on the normalised percentage scale plus the
# usual minimum language requirement. Deliberately conservative: these are
# "typical public university" bars, not guarantees.
COUNTRY_RULES: Final[dict[str, dict[str, object]]] = {
    "germany": {
        "min_percentage": 60.0,
        "ielts": 6.5,
        "note": (
            "German public universities read your grade on the 1-5 scale via the "
            "Modified Bavarian Formula — the figure below is what uni-assist will "
            "compute. Competitive Master's programmes usually want 2.5 or better."
        ),
    },
    "europe": {
        "min_percentage": 60.0,
        "ielts": 6.5,
        "note": (
            "Most EU programmes map your grade onto the ECTS scale; a B or better "
            "keeps scholarship options such as Erasmus Mundus open."
        ),
    },
    "canada": {
        "min_percentage": 70.0,
        "ielts": 6.5,
        "note": (
            "Canadian universities typically ask for a 3.0/4.0 in the final two "
            "years of study, and IELTS 6.5 with no band under 6.0."
        ),
    },
    "australia": {
        "min_percentage": 65.0,
        "ielts": 6.5,
        "note": (
            "Australian Group of Eight universities usually ask for 65%+ and "
            "IELTS 6.5; other providers admit from 60%."
        ),
    },
    "uk": {
        "min_percentage": 60.0,
        "ielts": 6.5,
        "note": (
            "UK admissions are stated in honours classifications — a 2:1 is the "
            "standard bar for a taught Master's, with some programmes taking a 2:2."
        ),
    },
    "usa": {
        "min_percentage": 70.0,
        "ielts": 6.5,
        "note": (
            "US graduate programmes read the 4.0 GPA directly; 3.0 is the common "
            "minimum and funded programmes look for 3.5+."
        ),
    },
}

_COUNTRY_ALIASES: Final[dict[str, str]] = {
    "united kingdom": "uk",
    "great britain": "uk",
    "england": "uk",
    "scotland": "uk",
    "united states": "usa",
    "united states of america": "usa",
    "us": "usa",
    "america": "usa",
    "deutschland": "germany",
    "eu": "europe",
    "european union": "europe",
    "netherlands": "europe",
    "sweden": "europe",
    "france": "europe",
    "italy": "europe",
    "spain": "europe",
    "poland": "europe",
    "finland": "europe",
    "norway": "europe",
    "ireland": "europe",
}


def normalise_country(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    key = _COUNTRY_ALIASES.get(key, key)
    return key if key in COUNTRY_RULES else None


def build_card(state: SessionState) -> DiagnosticCardPayload:
    """Convert the student's grade and attach destination-specific notes."""
    score = state.slots.cgpa
    if score is None or not state.slots.is_complete():
        raise DiagnosticsUnavailable(
            "Every onboarding field is required before diagnostics."
        )

    conversion = convert(score, country=state.slots.nationality)
    transcript = state.transcript

    return DiagnosticCardPayload(
        session_id=state.session_id,
        student_name=state.slots.full_name,
        institution_name=transcript.institution_name if transcript else None,
        field_of_study=state.slots.field_of_study,
        education_level=(
            state.slots.education_level.label if state.slots.education_level else None
        ),
        target_country=state.slots.target_country,
        conversion=conversion,
        backlogs=transcript.backlogs if transcript else 0,
        gap_years=transcript.gap_years if transcript else None,
        total_credits=transcript.total_credits if transcript else None,
        subject_count=len(transcript.subjects) if transcript else 0,
        eligibility_notes=eligibility_notes(state, conversion),
    )


def eligibility_notes(
    state: SessionState, conversion: GradeConversion
) -> list[str]:
    """Plain-language flags a human counsellor would raise first."""
    notes: list[str] = []
    slots = state.slots
    key = normalise_country(slots.target_country)

    if key is not None:
        rules = COUNTRY_RULES[key]
        notes.append(str(rules["note"]))
        min_percentage = float(rules["min_percentage"])  # type: ignore[arg-type]
        if conversion.normalized_percentage >= min_percentage:
            notes.append(
                f"Your grade clears the typical academic bar for {slots.target_country} "
                f"({min_percentage:.0f}% equivalent)."
            )
        else:
            notes.append(
                f"Your grade sits below the typical {slots.target_country} bar of "
                f"{min_percentage:.0f}% equivalent — we will target universities that "
                "weigh work experience and your statement of purpose more heavily."
            )
        notes.extend(_language_notes(slots.language_score, float(rules["ielts"])))  # type: ignore[arg-type]
    else:
        notes.append(
            "Destination-specific thresholds are not yet mapped for "
            f"{slots.target_country or 'your target'} — the conversions below still apply."
        )

    level = slots.education_level
    if level is EducationLevel.HIGH_SCHOOL:
        notes.append(
            "This grade is from a school-level qualification, so it is read as "
            "an undergraduate entry profile. Universities will also weigh your "
            "subject combination and any entrance test."
        )
    elif level is EducationLevel.BACHELORS:
        notes.append(
            "As a Bachelor's holder you are being assessed for Master's entry, "
            "where the final two years of your transcript carry the most weight."
        )
    elif level in (EducationLevel.MASTERS, EducationLevel.DOCTORATE):
        notes.append(
            "With a postgraduate qualification already in hand, research fit and "
            "your publications or work experience will matter as much as the grade."
        )

    if conversion.uk_classification is UKClassification.FIRST:
        notes.append(
            "A First Class equivalent puts merit scholarships genuinely in reach."
        )

    transcript = state.transcript
    if transcript is not None:
        if transcript.backlogs >= 3:
            notes.append(
                f"{transcript.backlogs} backlogs are visible on your transcript. "
                "Several countries cap this at 5 for visa or admission purposes — "
                "clear what you can before applying."
            )
        elif transcript.backlogs:
            notes.append(
                f"{transcript.backlogs} backlog(s) noted; at this level most "
                "universities will still consider your application."
            )
        if transcript.gap_years and transcript.gap_years >= 2:
            notes.append(
                f"A gap of about {transcript.gap_years:g} year(s) will need a short "
                "written explanation in your application."
            )
        if transcript.confidence and transcript.confidence < 0.6:
            notes.append(
                "Your transcript scan was hard to read — please double-check the "
                "figures above before we rely on them."
            )
        notes.extend(transcript.warnings)

    notes.extend(conversion.assumptions)
    return notes


def _language_notes(score: LanguageScore | None, required_ielts: float) -> list[str]:
    if score is None:
        return []
    if score.test in (LanguageTest.PLANNED, LanguageTest.NONE):
        return [
            f"You have not sat a language test yet — plan for IELTS {required_ielts:g} "
            "overall, since most offers are conditional on it."
        ]
    if score.overall is None:
        return []
    if score.test is LanguageTest.IELTS:
        if score.overall >= required_ielts:
            return [f"IELTS {score.overall:g} meets the usual {required_ielts:g} requirement."]
        return [
            f"IELTS {score.overall:g} is below the usual {required_ielts:g} requirement; "
            "a retake is the single highest-leverage improvement available to you."
        ]
    if score.test is LanguageTest.TOEFL:
        equivalent = 79 if required_ielts <= 6.5 else 94
        verdict = "meets" if score.overall >= equivalent else "is below"
        return [f"TOEFL {score.overall:g} {verdict} the usual iBT {equivalent} requirement."]
    return [f"{score.test.value} {score.overall:g} recorded."]


def conversion_or_none(state: SessionState) -> GradeConversion | None:
    """Best-effort conversion for previews; never raises."""
    if state.slots.cgpa is None:
        return None
    try:
        return convert(state.slots.cgpa, country=state.slots.nationality)
    except ConversionError:
        return None
