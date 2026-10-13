"""Importing courses from a file rather than crawling for them.

Every case here is a shape a real dataset takes. Nothing touches the network
or a database: the subject is the mapping and the validation, which is where a
dataset quietly half-imports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.phase2.dataset_import import (
    build_mapping,
    load_dataset,
    read_records,
)

HEADERS = (
    "Programme Name,Institution,Country,Level,Tuition Fees,Currency,"
    "IELTS Requirement,Minimum GPA,Application Deadline,Work Rights,"
    "Course Description"
)
ROW = (
    'MA English Literature,University of Leeds,United Kingdom,Masters,'
    '"£24,500",GBP,6.5,60,2026-07-31,yes,'
    '"Poetry, the novel and critical theory, with a dissertation."'
)


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Reading the file
# --------------------------------------------------------------------------- #


def test_csv_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, "c.csv", f"{HEADERS}\n{ROW}\n")
    assert len(read_records(path)) == 1


def test_a_bare_json_list_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, "c.json", json.dumps([{"title": "A"}, {"title": "B"}]))
    assert len(read_records(path)) == 2


@pytest.mark.parametrize("key", ["data", "results", "courses", "items", "records"])
def test_an_api_envelope_is_unwrapped(tmp_path: Path, key: str) -> None:
    """Saving an API response straight to disk should import unedited; every
    one of these is a wrapper some API actually uses."""
    path = write(tmp_path, "c.json", json.dumps({key: [{"title": "A"}], "page": 1}))
    assert read_records(path) == [{"title": "A"}]


def test_an_unrecognised_envelope_says_what_it_found(tmp_path: Path) -> None:
    path = write(tmp_path, "c.json", json.dumps({"payload": [{"title": "A"}]}))
    with pytest.raises(ValueError, match="payload"):
        read_records(path)


def test_json_lines_are_read(tmp_path: Path) -> None:
    path = write(tmp_path, "c.jsonl", '{"title": "A"}\n\n{"title": "B"}\n')
    assert len(read_records(path)) == 2


def test_an_unsupported_extension_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        read_records(write(tmp_path, "c.xlsx", "binary"))


# --------------------------------------------------------------------------- #
# Column mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Programme Name", "course_title"),
        ("course-title", "course_title"),
        ("COURSE_TITLE", "course_title"),
        ("Institution", "university_name"),
        ("Tuition Fees", "tuition_fee_amount"),
        ("IELTS Requirement", "min_ielts_score"),
        ("Application Deadline", "deadline_date"),
        ("Work Rights", "post_study_work_eligible"),
        ("Course Description", "syllabus_description"),
    ],
)
def test_common_header_spellings_are_recognised(header: str, expected: str) -> None:
    assert build_mapping([header]) == {header: expected}


def test_an_unknown_column_is_left_alone() -> None:
    assert build_mapping(["Ranking", "Institution"]) == {"Institution": "university_name"}


def test_an_override_wins_over_the_guess() -> None:
    mapping = build_mapping(
        ["Title", "Internal Name"], {"course_title": "Internal Name"}
    )
    assert mapping["Internal Name"] == "course_title"
    assert "Title" not in mapping


def test_an_override_naming_a_field_we_do_not_have_is_refused() -> None:
    with pytest.raises(ValueError, match="ranking"):
        build_mapping(["Ranking"], {"ranking": "Ranking"})


def test_the_first_matching_column_wins() -> None:
    """Two columns can both look like the title; taking both would make the
    later one overwrite the earlier silently."""
    mapping = build_mapping(["Course", "Programme"])
    assert list(mapping.values()) == ["course_title"]


# --------------------------------------------------------------------------- #
# Validation and coercion
# --------------------------------------------------------------------------- #


def test_a_realistic_row_imports(tmp_path: Path) -> None:
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{ROW}\n"))
    course = report.courses[0]
    assert course.course_title == "MA English Literature"
    assert course.degree_level == "Masters"
    assert course.tuition_fee_amount == 24_500  # "£24,500" coerced
    assert course.min_ielts_score == 6.5
    assert course.post_study_work_eligible is True  # "yes" coerced
    assert report.unmapped_columns == []


@pytest.mark.parametrize("spelling", ["MA", "Master's", "masters", "postgraduate"])
def test_degree_wording_varies_by_dataset(tmp_path: Path, spelling: str) -> None:
    row = ROW.replace(",Masters,", f",{spelling},")
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{row}\n"))
    assert report.courses[0].degree_level == "Masters"


@pytest.mark.parametrize("word", ["yes", "y", "TRUE", "1", "eligible"])
def test_truthy_words_become_true(tmp_path: Path, word: str) -> None:
    row = ROW.replace(",yes,", f",{word},")
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{row}\n"))
    assert report.courses[0].post_study_work_eligible is True


@pytest.mark.parametrize("blank", ["n/a", "N/A", "", "-", "TBC", "unknown"])
def test_placeholder_blanks_become_absent_not_text(tmp_path: Path, blank: str) -> None:
    """Left as text these fail with a confusing type error rather than simply
    being missing - and an invented deadline is something a student plans
    around."""
    row = ROW.replace(",2026-07-31,", f",{blank},")
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{row}\n"))
    assert report.accepted == 1
    assert report.courses[0].deadline_date is None


def test_a_bad_row_is_reported_with_its_number_and_fields(tmp_path: Path) -> None:
    """A dataset that half-imports without saying so is worse than one that
    refuses, so every rejection names the row and what was wrong with it."""
    bad = 'No University,,Nowhere,Masters,abc,XYZ,99,200,not a date,maybe,'
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{ROW}\n{bad}\n"))
    assert report.accepted == 1
    row_number, reason = report.rejected[0]
    assert row_number == 2
    assert "university_name" in reason and "currency" in reason


def test_out_of_range_values_are_rejected_not_clamped(tmp_path: Path) -> None:
    """IELTS 99 is a misread of the source, not a very strict university."""
    row = ROW.replace(",6.5,60,", ",99,200,")
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{row}\n"))
    assert report.accepted == 0


def test_a_missing_description_is_composed_and_counted(tmp_path: Path) -> None:
    """The course is still worth having, but its vector is thin - so the count
    is surfaced rather than buried."""
    headers = HEADERS.replace(",Course Description", "")
    row = (
        "MA English Literature,University of Leeds,United Kingdom,Masters,"
        '"£24,500",GBP,6.5,60,2026-07-31,yes'
    )
    report = load_dataset(write(tmp_path, "c.csv", f"{headers}\n{row}\n"))
    assert report.accepted == 1
    assert report.synthesised_descriptions == 1
    assert "MA English Literature" in report.courses[0].syllabus_description
    assert "less accurately" in report.summary()


def test_a_ragged_row_does_not_refuse_the_whole_file(tmp_path: Path) -> None:
    """csv.DictReader files the overflow of an over-long row under a None key,
    which crashed both the header scan and the ignored-column report."""
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n{ROW},extra,junk\n"))
    assert report.accepted == 1
    assert report.unmapped_columns == []


def test_a_rejected_row_is_not_also_counted_as_thin(tmp_path: Path) -> None:
    headers = HEADERS.replace(",Course Description", "")
    bad = "No University,,Nowhere,Masters,abc,XYZ,99,200,not a date,maybe"
    report = load_dataset(write(tmp_path, "c.csv", f"{headers}\n{bad}\n"))
    assert report.accepted == 0
    assert report.synthesised_descriptions == 0


def test_extra_columns_are_named_rather_than_silently_dropped(tmp_path: Path) -> None:
    report = load_dataset(
        write(tmp_path, "c.csv", f"{HEADERS},Ranking\n{ROW},12\n")
    )
    assert report.unmapped_columns == ["Ranking"]


def test_an_empty_file_is_not_an_error(tmp_path: Path) -> None:
    report = load_dataset(write(tmp_path, "c.csv", f"{HEADERS}\n"))
    assert report.total == 0 and report.accepted == 0
