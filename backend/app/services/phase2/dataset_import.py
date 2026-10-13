"""Load courses from a file instead of crawling for them.

The crawler exists for pages nobody has structured yet. When a dataset or an
API export is already to hand, going out to the live web to rediscover the
same facts is slower, less reliable, and sends page text to a third-party
model for no benefit - so this path does none of that. Nothing here makes a
network call except the embedding needed to store a vector.

Real datasets never use our column names, so the mapping is the whole job:
headers are matched against a table of common spellings, and anything unusual
is named explicitly in a small JSON mapping file. Rows that cannot be made
valid are reported with their row number and the reason, never dropped
silently - a dataset that half-imports without saying so is worse than one
that refuses outright.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable

from pydantic import ValidationError

from .schemas import CourseExtractionSchema

logger = logging.getLogger(__name__)

# Header spellings seen across university datasets, per schema field. Matching
# is case- and separator-insensitive, so "Course Title", "course_title" and
# "COURSE-TITLE" all resolve to the same key.
_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "course_title": (
        "course_title", "title", "course", "program", "programme",
        "program_name", "programme_name", "course_name", "degree_name",
    ),
    "university_name": (
        "university_name", "university", "institution", "institution_name",
        "school", "college", "provider", "organisation", "organization",
    ),
    "country": ("country", "country_name", "location", "nation"),
    "degree_level": (
        "degree_level", "level", "degree", "qualification", "study_level",
        "degree_type", "award",
    ),
    "tuition_fee_amount": (
        "tuition_fee_amount", "tuition", "tuition_fee", "fee", "fees",
        "tuition_fees", "annual_fee", "cost", "price", "international_fee",
    ),
    "currency": ("currency", "currency_code", "fee_currency", "ccy"),
    "tuition_fee_usd": ("tuition_fee_usd", "fee_usd", "tuition_usd", "usd"),
    "min_gpa_percent": (
        "min_gpa_percent", "min_gpa", "gpa", "minimum_gpa", "entry_gpa",
        "gpa_requirement", "academic_requirement", "min_percentage",
    ),
    "min_ielts_score": (
        "min_ielts_score", "ielts", "min_ielts", "ielts_score",
        "ielts_requirement", "english_requirement", "min_english",
    ),
    "deadline_date": (
        "deadline_date", "deadline", "application_deadline", "apply_by",
        "closing_date", "application_close",
    ),
    "post_study_work_eligible": (
        "post_study_work_eligible", "post_study_work", "psw", "work_visa",
        "psw_eligible", "work_rights",
    ),
    "syllabus_description": (
        "syllabus_description", "description", "syllabus", "overview",
        "about", "summary", "modules", "curriculum", "course_description",
        "content",
    ),
}

_TRUE: Final = frozenset({"true", "yes", "y", "1", "eligible", "available"})
_FALSE: Final = frozenset({"false", "no", "n", "0", "none", "not eligible"})

# Values datasets use to mean "empty". Left as text they fail validation with a
# confusing type error instead of simply being absent.
_BLANK: Final = frozenset(
    {"", "n/a", "na", "null", "none", "-", "--", "unknown", "tbc", "tba"}
)


def _norm(header: str) -> str:
    """Fold a header to its comparison form: lowercase, alphanumeric only."""
    return "".join(ch for ch in header.lower() if ch.isalnum())


_ALIAS_INDEX: Final[dict[str, str]] = {
    _norm(alias): field_name
    for field_name, aliases in _ALIASES.items()
    for alias in aliases
}


@dataclass
class ImportReport:
    """What happened to every row, so a partial import is never silent."""

    total: int = 0
    courses: list[CourseExtractionSchema] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)
    synthesised_descriptions: int = 0
    unmapped_columns: list[str] = field(default_factory=list)
    mapped: dict[str, str] = field(default_factory=dict)

    @property
    def accepted(self) -> int:
        return len(self.courses)

    def summary(self) -> str:
        lines = [f"{self.accepted}/{self.total} row(s) valid."]
        if self.synthesised_descriptions:
            lines.append(
                f"{self.synthesised_descriptions} row(s) had no description "
                "column; one was composed from the title and university. Those "
                "courses will still be found, but less accurately - a real "
                "syllabus is what makes subject matching work."
            )
        if self.unmapped_columns:
            lines.append("Ignored columns: " + ", ".join(self.unmapped_columns))
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Reading files
# --------------------------------------------------------------------------- #


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read CSV, TSV, JSON or JSON Lines into a list of dicts.

    A JSON file may be a bare list, or an object wrapping one under a key such
    as `data`, `results` or `courses` - which is how most APIs return a page of
    results, so an API response can be saved to disk and imported unedited.
    """
    suffix = path.suffix.lower()

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=delimiter))

    if suffix in {".jsonl", ".ndjson"}:
        with path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "results", "courses", "items", "records", "rows"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            raise ValueError(
                "JSON object contains no list of records. Expected a top-level "
                "list, or one under 'data', 'results', 'courses', 'items', "
                f"'records' or 'rows'; found keys: {sorted(payload)[:10]}"
            )
        raise ValueError("JSON must be a list of records or an object wrapping one.")

    raise ValueError(
        f"Unsupported file type {suffix!r}. Use .csv, .tsv, .json, .jsonl or .ndjson."
    )


# --------------------------------------------------------------------------- #
# Mapping and validation
# --------------------------------------------------------------------------- #


def build_mapping(
    headers: Iterable[str], overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """Map source column -> schema field.

    `overrides` is the escape hatch for columns the alias table cannot guess,
    given as `{"schema_field": "Source Column"}` - the direction someone
    writing the mapping by hand thinks in.
    """
    mapping: dict[str, str] = {}
    for header in headers:
        # csv.DictReader puts the overflow of a ragged row under a None key.
        # Ragged rows are common in exported data, and crashing on the header
        # scan would refuse the whole file over one bad line.
        if not isinstance(header, str):
            continue
        target = _ALIAS_INDEX.get(_norm(header))
        if target and target not in mapping.values():
            mapping[header] = target

    for schema_field, source_column in (overrides or {}).items():
        if schema_field not in _ALIASES:
            raise ValueError(
                f"Unknown field {schema_field!r} in mapping. "
                f"Valid fields: {', '.join(sorted(_ALIASES))}"
            )
        # An override replaces whatever was guessed for that field.
        mapping = {k: v for k, v in mapping.items() if v != schema_field}
        mapping[source_column] = schema_field

    return mapping


def _clean(value: Any) -> Any:
    """Normalise a single cell: blanks to None, leave everything else alone."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return None if text.lower() in _BLANK else text
    return value


def _coerce_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for source, target in mapping.items():
        value = _clean(row.get(source))
        if value is None:
            continue
        if target == "post_study_work_eligible" and isinstance(value, str):
            lowered = value.lower()
            if lowered in _TRUE:
                value = True
            elif lowered in _FALSE:
                value = False
        payload[target] = value
    return payload


def _synthesise_description(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("course_title", "")),
        str(payload.get("degree_level", "")),
        f"at {payload['university_name']}" if payload.get("university_name") else "",
        f"in {payload['country']}" if payload.get("country") else "",
    ]
    return " ".join(part for part in parts if part).strip()


def load_dataset(path: Path, *, overrides: dict[str, str] | None = None) -> ImportReport:
    """Read a file and validate every row against `CourseExtractionSchema`."""
    records = read_records(path)
    report = ImportReport(total=len(records))
    if not records:
        return report

    headers = list(records[0])
    mapping = build_mapping(headers, overrides)
    report.mapped = dict(mapping)
    report.unmapped_columns = [
        h for h in headers if isinstance(h, str) and h not in mapping
    ]

    for index, row in enumerate(records, start=1):
        payload = _coerce_row(row, mapping)
        # A course with no prose is still worth importing, but the vector it
        # produces is thin, so the count is reported rather than buried. It is
        # only counted once the row validates - a rejected row is not something
        # anyone needs warning about twice.
        was_synthesised = False
        if not payload.get("syllabus_description"):
            synthesised = _synthesise_description(payload)
            if synthesised:
                payload["syllabus_description"] = synthesised
                was_synthesised = True
        try:
            report.courses.append(CourseExtractionSchema.model_validate(payload))
            report.synthesised_descriptions += was_synthesised
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(str(part) for part in error["loc"]) or "?"
                for error in exc.errors()
            )
            report.rejected.append((index, f"invalid or missing: {fields}"))

    return report
