"""A CGPA that was averaged must not be shown as one that was printed.

A transcript with no overall grade gets one averaged from its subject list.
That is reasonable - but the student was then told "From your transcript -
please confirm", which is false, and the warning the parser had already
written was never displayed. An institution's own formula may weight, cap or
exclude attempts, so the averaged figure can legitimately disagree with the
CGPA on their official record.
"""

from __future__ import annotations

from app.ocr_service import _post_process
from app.schemas import ExtractedTranscript, SubjectGrade


def subjects() -> list[SubjectGrade]:
    return [
        SubjectGrade(name="Thermodynamics", numeric_grade=3.0, credits=3),
        SubjectGrade(name="Dynamics", numeric_grade=3.33, credits=3),
        SubjectGrade(name="Mathematics", numeric_grade=2.85, credits=3),
    ]


def test_an_averaged_cgpa_is_flagged() -> None:
    result = _post_process(ExtractedTranscript(subjects=subjects()))
    assert result.cumulative_gpa is not None
    assert result.cumulative_gpa_computed is True


def test_an_averaged_cgpa_says_so_in_a_warning() -> None:
    result = _post_process(ExtractedTranscript(subjects=subjects()))
    assert result.warnings, "an averaged grade must explain itself"
    warning = result.warnings[0].lower()
    assert "averaged" in warning
    # It has to say the official figure may differ, not merely that it was
    # computed - that is the part a student needs to act on.
    assert "differ" in warning


def test_a_printed_cgpa_is_not_flagged_or_warned_about() -> None:
    """Guard on the above: a grade read off the page is exactly that."""
    result = _post_process(
        ExtractedTranscript(cumulative_gpa=3.05, gpa_scale_max=4.0)
    )
    assert result.cumulative_gpa == 3.05
    assert result.cumulative_gpa_computed is False
    assert result.warnings == []


def test_the_flag_defaults_off_for_older_saved_transcripts() -> None:
    """Saved conversations predate the field and must still load."""
    assert ExtractedTranscript().cumulative_gpa_computed is False


# --------------------------------------------------------------------------- #
# Not saying the same thing twice
# --------------------------------------------------------------------------- #


def test_the_models_own_missing_cgpa_note_is_replaced_not_stacked() -> None:
    """The model usually reports the missing total in its own words. Adding
    ours on top printed the same fact twice, which reads as two separate
    problems rather than one."""
    result = _post_process(
        ExtractedTranscript(
            subjects=subjects(),
            warnings=[
                "Cumulative GPA not explicitly stated as a single final "
                "value on the document."
            ],
        )
    )
    assert len(result.warnings) == 1
    assert "averaged from the subject grades" in result.warnings[0]


def test_an_unrelated_warning_survives() -> None:
    """Grades shown for unfinished courses is a different problem, and the one
    most likely to make an averaged figure wrong - it must not be swept up."""
    result = _post_process(
        ExtractedTranscript(
            subjects=subjects(),
            warnings=[
                "Cumulative GPA not explicitly stated on the document.",
                "Some grades are visible for ongoing or uncompleted courses.",
            ],
        )
    )
    assert len(result.warnings) == 2
    assert any("ongoing or uncompleted" in note for note in result.warnings)


def test_a_warning_that_quotes_a_cgpa_is_not_a_duplicate() -> None:
    """"CGPA appears to be 3.05 but the digit is blurred" mentions the total
    and is not a report that it is missing."""
    from app.ocr_service import _is_about_missing_cgpa

    assert not _is_about_missing_cgpa(
        "CGPA appears to be 3.05 but the digit is blurred."
    )
