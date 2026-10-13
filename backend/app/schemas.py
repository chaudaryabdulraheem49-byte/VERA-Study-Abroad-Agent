"""Pydantic V2 models for the Phase 1 Smart Diagnostics pipeline."""

from __future__ import annotations

import json
import time
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class SlotName(StrEnum):
    """The mandatory onboarding fields, in the order we ask for them."""

    FULL_NAME = "full_name"
    NATIONALITY = "nationality"
    CGPA = "cgpa"
    FIELD_OF_STUDY = "field_of_study"
    EDUCATION_LEVEL = "education_level"
    TARGET_COUNTRY = "target_country"
    LANGUAGE_SCORE = "language_score"


class EducationLevel(StrEnum):
    """The qualification a grade belongs to.

    "Graphic design, 3.2" means very different things at intermediate level and
    at Master's level, so the level is collected rather than assumed.
    """

    HIGH_SCHOOL = "high_school"  # Intermediate / FSc / A-levels / 12th grade
    DIPLOMA = "diploma"
    BACHELORS = "bachelors"
    MASTERS = "masters"
    DOCTORATE = "doctorate"

    @property
    def label(self) -> str:
        return {
            EducationLevel.HIGH_SCHOOL: "Intermediate / High school",
            EducationLevel.DIPLOMA: "Diploma",
            EducationLevel.BACHELORS: "Bachelor's",
            EducationLevel.MASTERS: "Master's",
            EducationLevel.DOCTORATE: "Doctorate",
        }[self]


class GradingScale(StrEnum):
    """Source grading scales we know how to normalise deterministically."""

    PERCENTAGE = "percentage"  # 0 - 100
    US_4_0 = "us_4_0"  # 0.00 - 4.00
    SCALE_5_0 = "scale_5_0"  # 0.00 - 5.00 (NG, RU, parts of PK)
    SCALE_10_0 = "scale_10_0"  # 0.00 - 10.00 (IN, ES)
    SCALE_20_0 = "scale_20_0"  # 0.00 - 20.00 (FR, PT, IR)
    GERMAN_1_5 = "german_1_5"  # 1.0 (best) - 5.0 (fail), inverted
    UNKNOWN = "unknown"


class UKClassification(StrEnum):
    FIRST = "First Class Honours"
    UPPER_SECOND = "Upper Second Class (2:1)"
    LOWER_SECOND = "Lower Second Class (2:2)"
    THIRD = "Third Class Honours"
    FAIL = "Below Honours / Fail"


class LanguageTest(StrEnum):
    IELTS = "IELTS"
    TOEFL = "TOEFL"
    PTE = "PTE"
    DUOLINGO = "DUOLINGO"
    NONE = "NONE"  # explicitly not taken and not planned
    PLANNED = "PLANNED"  # booked, or intends to sit the test


class SSEEventType(StrEnum):
    """Wire contract shared with the Next.js client."""

    # Wire name is "text_delta": the frames carry an incremental slice of the
    # reply, and naming them for what they are keeps the contract readable
    # from the client side.
    TOKEN = "text_delta"
    SLOT_UPDATE = "slot_update"
    TRANSCRIPT_PARSED = "transcript_parsed"
    DIAGNOSTIC_CARD = "diagnostic_card"
    UNIVERSITY_MATCHES = "university_matches"
    STATUS = "status"
    ERROR = "error"
    DONE = "done"


# --------------------------------------------------------------------------- #
# Onboarding slots
# --------------------------------------------------------------------------- #

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


# Module-level, not a class attribute: a leading-underscore annotated attribute
# inside a Pydantic V2 model becomes a private attr and is not readable off the class.
LANGUAGE_SCORE_BOUNDS: dict[LanguageTest, tuple[float, float]] = {
    LanguageTest.IELTS: (0.0, 9.0),
    LanguageTest.TOEFL: (0.0, 120.0),
    LanguageTest.PTE: (10.0, 90.0),
    LanguageTest.DUOLINGO: (10.0, 160.0),
}


class LanguageScore(BaseModel):
    """Normalised language-proficiency slot value."""

    model_config = ConfigDict(extra="forbid")

    test: LanguageTest
    overall: float | None = Field(default=None, description="Overall band / score.")
    planned_date: str | None = Field(
        default=None, description="ISO-ish date string when the test is booked."
    )

    @model_validator(mode="after")
    def _check_score_range(self) -> LanguageScore:
        if self.overall is None:
            return self
        bounds = LANGUAGE_SCORE_BOUNDS.get(self.test)
        if bounds is not None:
            low, high = bounds
            if not low <= self.overall <= high:
                raise ValueError(
                    f"{self.test} score {self.overall} is outside the valid range "
                    f"[{low}, {high}]"
                )
        return self

    def is_satisfied(self) -> bool:
        """Filled if we have a score, or a definite 'not yet / planned' answer."""
        return self.overall is not None or self.test in (
            LanguageTest.PLANNED,
            LanguageTest.NONE,
        )


class AcademicScore(BaseModel):
    """The cumulative grade as reported, together with its source scale."""

    model_config = ConfigDict(extra="forbid")

    raw_value: float = Field(gt=0)
    scale: GradingScale = GradingScale.UNKNOWN
    scale_max: float | None = Field(
        default=None, description="Explicit Nmax when the scale is non-standard."
    )
    scale_min_pass: float | None = Field(
        default=None,
        description="Explicit Nmin (minimum passing mark) for the Bavarian formula.",
    )

    @field_validator("raw_value")
    @classmethod
    def _reject_absurd(cls, v: float) -> float:
        if v > 100.0:
            raise ValueError("raw_value above 100 is not a recognised grading scale")
        return v


class OnboardingSlots(BaseModel):
    """The conversational barrier. `None` means the slot is still open."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    full_name: str | None = None
    nationality: str | None = None
    cgpa: AcademicScore | None = None
    field_of_study: str | None = None
    education_level: EducationLevel | None = None
    target_country: str | None = None
    # Further destinations, once the student has confirmed they want more than
    # one. `target_country` stays the primary: the diagnostic report's advice
    # is country-specific ("Canadian universities typically ask for..."), so
    # one of them has to lead. The search spans all of them equally.
    extra_countries: list[str] = Field(default_factory=list)
    language_score: LanguageScore | None = None

    # Provenance: which slots came from OCR vs. chat. Drives the confirmation step.
    ocr_derived: set[SlotName] = Field(default_factory=set)
    user_confirmed: set[SlotName] = Field(default_factory=set)

    def missing(self) -> list[SlotName]:
        """Slots still required to unlock diagnostics, in ask-order."""
        gaps: list[SlotName] = []
        for name in SlotName:
            value = getattr(self, name.value)
            if value is None:
                gaps.append(name)
            elif name is SlotName.LANGUAGE_SCORE and not value.is_satisfied():
                gaps.append(name)
        return gaps

    def destinations(self) -> list[str]:
        """Every confirmed destination, primary first."""
        if not self.target_country:
            return []
        return [self.target_country, *self.extra_countries]

    def is_complete(self) -> bool:
        return not self.missing()

    def pending_confirmation(self) -> list[SlotName]:
        """OCR-extracted slots the student has not yet acknowledged."""
        return sorted(self.ocr_derived - self.user_confirmed, key=lambda s: s.value)

    def confirm_all_ocr(self) -> None:
        self.user_confirmed |= self.ocr_derived

    def merge(self, patch: SlotPatch, *, from_ocr: bool = False) -> list[SlotName]:
        """Apply a partial extraction; return the slot names actually changed.

        Chat-sourced values outrank OCR-sourced ones for the same slot: a student
        correcting us is the highest-trust signal available.
        """
        changed: list[SlotName] = []
        for name in SlotName:
            new_value = getattr(patch, name.value, None)
            if new_value is None:
                continue
            current = getattr(self, name.value)
            if current is not None and from_ocr and name not in self.ocr_derived:
                continue  # never let OCR clobber what the student typed
            if current == new_value:
                # Companions still have to land when the primary is unchanged.
                # "Australia and Canada" from a student already recorded as
                # Australia moves only `extra_countries`, so skipping here
                # dropped Canada without a word. Guarded on the patch actually
                # carrying companions, so merely re-stating the destination
                # does not wipe the ones already agreed.
                if (
                    name is SlotName.TARGET_COUNTRY
                    and patch.extra_countries
                    and list(patch.extra_countries) != self.extra_countries
                ):
                    self.extra_countries = list(patch.extra_countries)
                    changed.append(name)
                continue
            setattr(self, name.value, new_value)
            changed.append(name)
            if name is SlotName.TARGET_COUNTRY:
                # A newly chosen primary destination replaces the companions
                # rather than accumulating with them - "actually, just Canada"
                # has to be able to clear the list.
                self.extra_countries = list(patch.extra_countries)
            if from_ocr:
                self.ocr_derived.add(name)
                self.user_confirmed.discard(name)
            else:
                self.user_confirmed.add(name)
        return changed


# The forms a model actually writes when asked for a level. Prose ("I did my
# bachelors in 2019") is handled by the extractor's own patterns; this only
# has to stop a reasonable label from failing validation.
_LEVEL_ALIASES: Final[dict[str, str]] = {
    "high_school": "high_school", "highschool": "high_school",
    "intermediate": "high_school", "secondary": "high_school",
    "senior_secondary": "high_school", "a_levels": "high_school",
    "diploma": "diploma", "advanced_diploma": "diploma",
    "associate_degree": "diploma",
    "bachelor": "bachelors", "bachelors": "bachelors",
    "bachelor's": "bachelors", "bachelors_degree": "bachelors",
    "undergraduate": "bachelors",
    "master": "masters", "masters": "masters", "master's": "masters",
    "masters_degree": "masters", "postgraduate": "masters", "msc": "masters",
    "phd": "doctorate", "ph_d": "doctorate", "doctorate": "doctorate",
    "doctoral": "doctorate", "doctoral_degree": "doctorate",
}


class SlotPatch(BaseModel):
    """Partial slot extraction emitted by the LLM (multi-field capable)."""

    model_config = ConfigDict(extra="ignore")

    full_name: str | None = None
    nationality: str | None = None
    cgpa: AcademicScore | None = None
    field_of_study: str | None = None
    education_level: EducationLevel | None = None
    # The level the student wants to *study at*, which is not the level they
    # hold. "I want to study business in masters" says nothing about their
    # existing qualification, and reading it as one flips a Bachelor's holder
    # to Master's - after which the search offers them PhDs.
    desired_level: EducationLevel | None = None
    target_country: str | None = None
    # Companion destinations, confirmed alongside the primary one. Not a
    # slot, so the merge loop never sees it - it is carried explicitly.
    extra_countries: list[str] = Field(default_factory=list)
    language_score: LanguageScore | None = None
    @field_validator("education_level", "desired_level", mode="before")
    @classmethod
    def _coerce_level(cls, value: Any) -> Any:
        """Accept the label a model is likely to write, not just the value.

        Without this the enum rejects "Masters" outright and Pydantic fails
        the *whole* patch - so one stylistic choice by the model throws away
        every other field it correctly extracted, and the turn silently falls
        back to regex. Prose is still handled further on; this only has to
        cover the handful of forms a model actually emits.
        """
        if not isinstance(value, str):
            return value
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        return _LEVEL_ALIASES.get(key, key)

    confirms_ocr: bool = Field(
        default=False,
        description="True when the message affirms previously OCR-extracted values.",
    )


# --------------------------------------------------------------------------- #
# Transcript extraction (Vision / LlamaParse output)
# --------------------------------------------------------------------------- #


class SubjectGrade(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    grade: str | None = None
    credits: float | None = Field(default=None, ge=0)
    numeric_grade: float | None = None
    passed: bool | None = None


class ExtractedTranscript(BaseModel):
    """Structured result of parsing one transcript document."""

    model_config = ConfigDict(extra="ignore")

    student_name: str | None = None
    institution_name: str | None = None
    program_name: str | None = None
    field_of_study: str | None = None
    education_level: EducationLevel | None = None

    subjects: list[SubjectGrade] = Field(default_factory=list)

    cumulative_gpa: float | None = Field(default=None, gt=0)
    gpa_scale_max: float | None = Field(default=None, gt=0)
    percentage: float | None = Field(default=None, ge=0, le=100)
    grading_scale: GradingScale = GradingScale.UNKNOWN

    total_credits: float | None = Field(default=None, ge=0)
    backlogs: int = Field(default=0, ge=0)
    failed_subjects: list[str] = Field(default_factory=list)
    gap_years: float | None = Field(default=None, ge=0)

    # True when no overall grade was printed and one was averaged from the
    # subject list instead. The distinction matters to the student: a computed
    # figure can disagree with their official CGPA, because an institution's
    # own formula may weight, cap or exclude attempts in ways a plain average
    # does not. Defaulted, so older saved transcripts still load.
    cumulative_gpa_computed: bool = False

    graduation_year: int | None = None
    confidence: Confidence = 0.0
    parser: Literal["gpt4o_vision", "gemini_vision", "llamaparse", "unknown"] = (
        "unknown"
    )
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _infer_scale(self) -> ExtractedTranscript:
        """Best-effort scale inference when the document does not state one."""
        if self.grading_scale is not GradingScale.UNKNOWN:
            return self
        if self.percentage is not None and self.cumulative_gpa is None:
            self.grading_scale = GradingScale.PERCENTAGE
        elif self.gpa_scale_max is not None:
            self.grading_scale = scale_from_max(self.gpa_scale_max)
        elif self.cumulative_gpa is not None:
            self.grading_scale = scale_from_max(guess_scale_max(self.cumulative_gpa))
            self.warnings.append(
                "Grading scale inferred from the GPA magnitude; confirm with the student."
            )
        return self

    def to_academic_score(self) -> AcademicScore | None:
        """Project the transcript onto the `cgpa` onboarding slot."""
        if self.cumulative_gpa is not None:
            return AcademicScore(
                raw_value=self.cumulative_gpa,
                scale=self.grading_scale,
                scale_max=self.gpa_scale_max,
            )
        if self.percentage is not None:
            return AcademicScore(
                raw_value=self.percentage,
                scale=GradingScale.PERCENTAGE,
                scale_max=100.0,
            )
        return None


def guess_scale_max(value: float) -> float:
    """Infer Nmax from a bare cumulative figure. Deliberately conservative."""
    if value <= 4.0:
        return 4.0
    if value <= 5.0:
        return 5.0
    if value <= 10.0:
        return 10.0
    if value <= 20.0:
        return 20.0
    return 100.0


def scale_from_max(scale_max: float) -> GradingScale:
    return {
        4.0: GradingScale.US_4_0,
        5.0: GradingScale.SCALE_5_0,
        10.0: GradingScale.SCALE_10_0,
        20.0: GradingScale.SCALE_20_0,
        100.0: GradingScale.PERCENTAGE,
    }.get(round(scale_max, 2), GradingScale.UNKNOWN)


# --------------------------------------------------------------------------- #
# Diagnostics output
# --------------------------------------------------------------------------- #


class GradeConversion(BaseModel):
    """Deterministic multi-system conversion of one cumulative grade."""

    model_config = ConfigDict(extra="forbid")

    source_value: float
    source_scale: GradingScale
    normalized_percentage: float = Field(ge=0, le=100)

    us_gpa: float = Field(ge=0.0, le=4.0)
    us_letter: str

    german_grade: float = Field(ge=1.0, le=5.0)
    german_label: str
    german_formula: str

    uk_classification: UKClassification
    ects_grade: str

    assumptions: list[str] = Field(default_factory=list)


class DiagnosticCardPayload(BaseModel):
    """The JSON body of the `diagnostic_card` SSE event."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    student_name: str | None = None
    institution_name: str | None = None
    field_of_study: str | None = None
    education_level: str | None = None
    target_country: str | None = None

    conversion: GradeConversion
    backlogs: int = 0
    gap_years: float | None = None
    total_credits: float | None = None
    subject_count: int = 0

    eligibility_notes: list[str] = Field(default_factory=list)
    generated_at: float = Field(default_factory=time.time)


# --------------------------------------------------------------------------- #
# Session state + transport
# --------------------------------------------------------------------------- #


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"]
    content: str
    created_at: float = Field(default_factory=time.time)


class SessionState(BaseModel):
    """Everything we persist per conversation (in-memory or Redis)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    slots: OnboardingSlots = Field(default_factory=OnboardingSlots)
    transcript: ExtractedTranscript | None = None
    # True once a transcript has been read for this session, whether it was
    # dropped into the chat or posted to /api/chat/upload.
    transcript_parsed: bool = False
    messages: list[ChatMessage] = Field(default_factory=list)
    diagnostics_unlocked: bool = False
    last_card: DiagnosticCardPayload | None = None
    # The matches that accompanied the last card. Kept so reloading the
    # page restores the grid alongside the report it belongs to.
    last_matches: list[dict[str, Any]] = Field(default_factory=list)
    # Slots the last assistant turn asked for. A bare reply ("Usama khan") is
    # resolved against these, since it carries no phrasing to pattern-match on.
    awaiting: list[SlotName] = Field(default_factory=list)
    # A country named with no indication of which slot it belongs to. It is held
    # here, unassigned, until the student says whether it is their citizenship
    # or their destination - answering "yes" to that either/or settles nothing.
    pending_country: str | None = None
    # A destination that matches the student's own citizenship. Studying at
    # home is not what this service is for, so it is confirmed rather than
    # recorded - it is usually a mis-typed answer.
    pending_same_country: str | None = None
    # Two or more destinations named in one message, held unassigned until the
    # student says whether they meant all of them. Storing the first and
    # dropping the rest is silent: the discarded one is never mentioned again,
    # so there is nothing to notice.
    pending_multi_country: list[str] = Field(default_factory=list)
    # A grade that contradicts one the student already gave. Overwriting it
    # silently is the worst kind of quiet change: every downstream figure - the
    # conversion, the eligibility filter, the shortlist - moves with it, and
    # nothing on screen says the old number is gone. So it is confirmed first.
    pending_grade: AcademicScore | None = None
    # The label last written to this conversation's saved thread. Kept so a
    # profile that has not changed does not trigger the same rename on every
    # later turn.
    saved_title: str | None = None
    # A level the student asked for in so many words. It overrides the level
    # inferred from what they hold, because a stated preference beats an
    # inference every time.
    desired_level: EducationLevel | None = None
    # The saved conversation this session is writing to, when the student is
    # signed in and history is configured. None means the turn is not being
    # persisted, which is a normal state rather than an error.
    thread_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def append(self, role: Literal["user", "assistant", "system"], content: str) -> None:
        self.messages.append(ChatMessage(role=role, content=content))
        self.updated_at = time.time()

    def history_for_llm(self, limit: int = 20) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self.messages[-limit:]]


class ChatRequest(BaseModel):
    """JSON variant of the stream endpoint payload (no file attached)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class SSEEvent(BaseModel):
    """Serialisable SSE frame. `format()` produces the wire representation."""

    model_config = ConfigDict(extra="forbid")

    event: SSEEventType
    data: dict[str, Any] | str

    def format(self) -> str:
        payload: dict[str, Any] = (
            {"text": self.data} if isinstance(self.data, str) else self.data
        )
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        # SSE frames are newline-delimited: a raw newline inside `data` would
        # split the frame, so json.dumps escaping them is load-bearing here.
        return f"event: {self.event.value}\ndata: {body}\n\n"
