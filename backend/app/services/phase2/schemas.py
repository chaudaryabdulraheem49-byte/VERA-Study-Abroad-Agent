"""Pydantic V2 contracts for the Phase 2 crawl → structure → ingest pipeline.

`CourseExtractionSchema` is the single source of truth for the whole pipeline:
its JSON schema is handed to the LLM extraction strategy, its validated
instances are what reaches Postgres, and its `syllabus_description` is what
gets embedded into Qdrant. Keeping one model across all three stages is what
stops the crawler, the database and the vector store drifting apart.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

DegreeLevel = Literal["Bachelors", "Masters", "PhD"]
Currency = Literal["EUR", "CAD", "AUD", "USD", "GBP", "CHF", "SEK", "NZD"]

# Fallback conversion table, used only when the crawler could not determine a
# USD figure itself. Deliberately static: a rate that silently drifts would
# make two ingests of the same page disagree, and these are ranking inputs
# rather than quoted prices. Refresh them deliberately, not automatically.
USD_PER_UNIT: Final[dict[str, float]] = {
    "USD": 1.00,
    "EUR": 1.08,
    "GBP": 1.27,
    "CAD": 0.73,
    "AUD": 0.66,
    "CHF": 1.13,
    "SEK": 0.095,
    "NZD": 0.61,
}

_ISO_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Degree wording varies by country; map the common spellings onto our three.
_DEGREE_ALIASES: Final[dict[str, DegreeLevel]] = {
    "bachelor": "Bachelors",
    "bachelors": "Bachelors",
    "bachelor's": "Bachelors",
    "undergraduate": "Bachelors",
    "bsc": "Bachelors",
    "ba": "Bachelors",
    "beng": "Bachelors",
    "master": "Masters",
    "masters": "Masters",
    "master's": "Masters",
    "postgraduate": "Masters",
    "msc": "Masters",
    "ma": "Masters",
    "meng": "Masters",
    "mba": "Masters",
    "phd": "PhD",
    "ph.d.": "PhD",
    "doctorate": "PhD",
    "doctoral": "PhD",
}

Percent = Annotated[float, Field(ge=0.0, le=100.0)]
IeltsBand = Annotated[float, Field(ge=0.0, le=9.0)]


class CourseExtractionSchema(BaseModel):
    """One course as extracted from a university page.

    Validation is deliberately forgiving on *shape* and strict on *range*: an
    LLM reading a messy page will return "Master's" or "9,500 EUR/year", and
    coercing those is cheap, but a tuition figure of -1 or an IELTS band of 12
    is a misread that must not reach the ranking stage.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    course_title: str = Field(min_length=2, max_length=300)
    university_name: str = Field(min_length=2, max_length=300)
    country: str = Field(min_length=2, max_length=100)
    degree_level: DegreeLevel

    tuition_fee_amount: float = Field(ge=0)
    currency: Currency
    tuition_fee_usd: float = Field(default=0.0, ge=0)

    min_gpa_percent: Percent = 0.0
    min_ielts_score: IeltsBand = 0.0

    deadline_date: str | None = Field(default=None, description="YYYY-MM-DD")
    post_study_work_eligible: bool = False

    syllabus_description: str = Field(
        min_length=1,
        description="Course breakdown; the text that becomes the Qdrant vector.",
    )

    # --- coercion ---------------------------------------------------------

    @field_validator("degree_level", mode="before")
    @classmethod
    def _coerce_degree(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return _DEGREE_ALIASES.get(value.strip().lower(), value.strip())

    @field_validator("currency", mode="before")
    @classmethod
    def _coerce_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("tuition_fee_amount", "tuition_fee_usd", mode="before")
    @classmethod
    def _coerce_money(cls, value: Any) -> Any:
        """Accept "€9,500 per year" and similar; pages rarely give bare floats."""
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
            return float(cleaned) if cleaned else 0.0
        return value

    @field_validator("min_gpa_percent", "min_ielts_score", mode="before")
    @classmethod
    def _coerce_score(cls, value: Any) -> Any:
        if value in (None, "", "N/A", "n/a"):
            return 0.0
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            return float(match.group()) if match else 0.0
        return value

    @field_validator("deadline_date", mode="before")
    @classmethod
    def _coerce_deadline(cls, value: Any) -> str | None:
        """Keep only a real ISO date; anything vaguer is dropped, not guessed.

        "Rolling admissions" and "late January" are common on these pages and
        must not become a concrete date that a student could plan around.
        """
        if value in (None, "", "N/A", "n/a", "rolling", "Rolling"):
            return None
        if isinstance(value, date):
            return value.isoformat()
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not _ISO_DATE.match(text):
            return None
        try:
            date.fromisoformat(text)
        except ValueError:
            return None
        return text

    @model_validator(mode="after")
    def _derive_usd(self) -> CourseExtractionSchema:
        """Fill `tuition_fee_usd` when the page (or the model) did not."""
        if self.tuition_fee_usd <= 0 and self.tuition_fee_amount > 0:
            rate = USD_PER_UNIT.get(self.currency)
            if rate is not None:
                object.__setattr__(
                    self, "tuition_fee_usd", round(self.tuition_fee_amount * rate, 2)
                )
        return self

    # --- helpers ----------------------------------------------------------

    @property
    def natural_key(self) -> tuple[str, str]:
        """The pair an upsert conflicts on."""
        return (self.university_name, self.course_title)

    def embedding_text(self) -> str:
        """What actually gets embedded.

        The title and degree level are prepended because a syllabus paragraph
        alone often omits them, and a query like "master's in data science"
        should match on all three signals rather than prose alone.
        """
        return (
            f"{self.course_title} ({self.degree_level}) at {self.university_name}, "
            f"{self.country}.\n{self.syllabus_description}"
        )


class StoredCourse(CourseExtractionSchema):
    """A course that has been through Postgres and carries its assigned id."""

    course_id: UUID


class SearchConstraints(BaseModel):
    """The hard filters applied in Postgres before any vector work happens."""

    model_config = ConfigDict(extra="forbid")

    max_budget_usd: float | None = Field(default=None, ge=0)
    student_ielts: IeltsBand | None = None
    student_gpa_percent: Percent | None = None
    countries: list[str] = Field(default_factory=list)
    degree_levels: list[DegreeLevel] = Field(default_factory=list)
    post_study_work_required: bool = False
    deadline_after: str | None = Field(default=None, description="YYYY-MM-DD")


class CourseMatch(BaseModel):
    """One ranked result: Postgres facts plus the Qdrant similarity score."""

    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    course_title: str
    university_name: str
    country: str
    degree_level: str
    tuition_fee_usd: float
    currency: str
    tuition_fee_amount: float
    # None means "the source states none", which the card must render as
    # unknown rather than as a requirement of zero.
    min_gpa_percent: float | None
    min_ielts_score: float | None
    deadline_date: str | None
    deadline_type: str | None = None
    intakes: str | None = None
    post_study_work_eligible: bool
    syllabus_description: str
    similarity_score: float = Field(
        description="Qdrant cosine score; higher is a closer syllabus match."
    )
