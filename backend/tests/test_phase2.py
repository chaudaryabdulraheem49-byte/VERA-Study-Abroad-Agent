"""Phase 2 pipeline tests: schema coercion, SQL filter shape, hybrid ranking.

These run without Postgres or Qdrant. The SQL is compiled against the real
Postgres dialect so the predicates are asserted as emitted, and the search is
driven through fakes so the two-step ordering is tested rather than mocked
away.

    cd backend && .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.services.phase2.crawler_service import CrawlError, _validate
from app.services.phase2.hybrid_search_service import (
    build_candidate_query,
    execute_hybrid_search,
)
from app.services.phase2.schemas import (
    CourseExtractionSchema,
    SearchConstraints,
)

# --------------------------------------------------------------------------- #
# Fixtures / fakes
# --------------------------------------------------------------------------- #

RAW_COURSE: dict[str, Any] = {
    "course_title": "MSc Data Science",
    "university_name": "TU Munich",
    "country": "Germany",
    "degree_level": "Master's",  # deliberately not the canonical spelling
    "tuition_fee_amount": "€9,500 per year",  # deliberately not a float
    "currency": "eur",
    "min_gpa_percent": "75%",
    "min_ielts_score": "IELTS 6.5",
    "deadline_date": "2026-01-15",
    "post_study_work_eligible": True,
    "syllabus_description": "Statistics, machine learning, data engineering.",
}


def make_course(**overrides: Any) -> CourseExtractionSchema:
    return CourseExtractionSchema.model_validate({**RAW_COURSE, **overrides})


@dataclass
class FakeRow:
    """Stands in for a Course ORM row."""

    course_id: uuid.UUID
    course_title: str
    university_name: str
    country: str
    degree_level: str
    tuition_fee_amount: float
    currency: str
    tuition_fee_usd: float
    min_gpa_percent: float
    min_ielts_score: float
    deadline_date: str | None
    post_study_work_eligible: bool
    syllabus_description: str
    # Mirrors the Course row. Defaulted, so the many constructors below do not
    # all have to name a field none of them cares about.
    deadline_type: str | None = None
    intakes: str | None = None


def row(title: str, usd: float, ielts: float = 6.0) -> FakeRow:
    return FakeRow(
        course_id=uuid.uuid4(),
        course_title=title,
        university_name="TU Munich",
        country="Germany",
        degree_level="Masters",
        tuition_fee_amount=usd,
        currency="USD",
        tuition_fee_usd=usd,
        min_gpa_percent=70.0,
        min_ielts_score=ielts,
        deadline_date=None,
        post_study_work_eligible=True,
        syllabus_description="...",
    )


class FakeSession:
    """Returns preset rows and records the statement it was given."""

    def __init__(self, rows: list[FakeRow]) -> None:
        self._rows = rows
        self.statement: Any = None

    async def execute(self, statement: Any) -> Any:
        self.statement = statement

        class Result:
            def __init__(self, rows: list[FakeRow]) -> None:
                self._rows = rows

            def scalars(self) -> Any:
                return self

            def all(self) -> list[FakeRow]:
                return self._rows

        return Result(self._rows)


@dataclass
class FakePoint:
    id: str
    score: float
    payload: dict[str, Any]


class FakeQdrant:
    """Captures the filter it was called with and returns preset scores."""

    def __init__(self, points: list[FakePoint]) -> None:
        self._points = points
        self.query_filter: Any = None
        self.limit: int | None = None

    async def query_points(self, **kwargs: Any) -> Any:
        self.query_filter = kwargs.get("query_filter")
        self.limit = kwargs.get("limit")

        class Response:
            def __init__(self, points: list[FakePoint]) -> None:
                self.points = points

        return Response(self._points)


# --------------------------------------------------------------------------- #
# A. schemas
# --------------------------------------------------------------------------- #


def test_messy_page_values_are_coerced() -> None:
    course = make_course()
    assert course.degree_level == "Masters"
    assert course.tuition_fee_amount == 9500.0
    assert course.currency == "EUR"
    assert course.min_gpa_percent == 75.0
    assert course.min_ielts_score == 6.5


def test_usd_is_derived_when_absent() -> None:
    """The ranking filter compares USD, so it cannot be left at zero."""
    course = make_course()
    assert course.tuition_fee_usd == pytest.approx(9500 * 1.08, rel=1e-6)


def test_explicit_usd_is_not_overwritten() -> None:
    course = make_course(tuition_fee_usd=10_000)
    assert course.tuition_fee_usd == 10_000


@pytest.mark.parametrize("value", ["rolling", "late January", "", None, "2026-13-45"])
def test_vague_deadlines_become_null(value: Any) -> None:
    """A student plans around these, so a guess is worse than nothing."""
    assert make_course(deadline_date=value).deadline_date is None


def test_real_deadline_survives() -> None:
    assert make_course(deadline_date="2026-01-15").deadline_date == "2026-01-15"


@pytest.mark.parametrize(
    ("field", "value"),
    [("min_ielts_score", 12.0), ("min_gpa_percent", 140.0), ("tuition_fee_amount", -5)],
)
def test_out_of_range_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(Exception):
        make_course(**{field: value})


def test_embedding_text_carries_title_and_level() -> None:
    text = make_course().embedding_text()
    assert "MSc Data Science" in text and "Masters" in text
    assert "machine learning" in text


# --------------------------------------------------------------------------- #
# B. crawler output parsing
# --------------------------------------------------------------------------- #


def test_extraction_block_list_is_unwrapped() -> None:
    course = _validate([RAW_COURSE], "https://example.edu/msc")
    assert course.course_title == "MSc Data Science"


def test_error_blocks_are_discarded() -> None:
    with pytest.raises(CrawlError):
        _validate([{"error": True, "content": "no course"}], "https://example.edu")


def test_non_course_page_is_rejected() -> None:
    with pytest.raises(CrawlError):
        _validate("{}", "https://example.edu/faculty-index")


def test_invalid_json_is_reported_clearly() -> None:
    with pytest.raises(CrawlError, match="non-JSON"):
        _validate("<html>not json</html>", "https://example.edu")


# --------------------------------------------------------------------------- #
# C. Step 1 - the SQL hard filter
# --------------------------------------------------------------------------- #


def compiled(constraints: SearchConstraints, limit: int = 500) -> str:
    statement = build_candidate_query(constraints, limit)
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_numeric_constraints_reach_the_sql() -> None:
    sql = compiled(
        SearchConstraints(max_budget_usd=20_000, student_ielts=7.0, student_gpa_percent=75)
    )
    assert "tuition_fee_usd <= 20000" in sql
    assert "min_ielts_score <= 7.0" in sql
    assert "min_gpa_percent <= 75.0" in sql


def test_categorical_constraints_reach_the_sql() -> None:
    sql = compiled(
        SearchConstraints(countries=["Germany", "Canada"], degree_levels=["Masters"])
    )
    assert "country IN ('Germany', 'Canada')" in sql
    assert "degree_level IN ('Masters')" in sql


def test_candidate_list_is_capped_and_cheapest_first() -> None:
    """Qdrant's MatchAny filter is handed this list, so it must stay bounded."""
    sql = compiled(SearchConstraints(), limit=500)
    assert "LIMIT 500" in sql
    assert "ORDER BY courses.tuition_fee_usd ASC" in sql


def test_unstated_deadline_stays_eligible() -> None:
    """NULL means "not stated", which must not be read as "already passed"."""
    sql = compiled(SearchConstraints(deadline_after="2026-01-01"))
    assert "deadline_date IS NULL" in sql


def test_no_constraints_filters_nothing() -> None:
    assert "WHERE" not in compiled(SearchConstraints())


# --------------------------------------------------------------------------- #
# D. Step 2 - hybrid ranking
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_results_are_ordered_by_similarity_not_sql_order() -> None:
    cheap, dear = row("Cheap MSc", 5_000), row("Dear MSc", 30_000)
    session = FakeSession([cheap, dear])
    qdrant = FakeQdrant(
        [
            FakePoint(str(dear.course_id), 0.93, {"course_id": str(dear.course_id)}),
            FakePoint(str(cheap.course_id), 0.41, {"course_id": str(cheap.course_id)}),
        ]
    )

    matches = await execute_hybrid_search(
        db_session=session,
        qdrant_client=qdrant,
        user_constraints=SearchConstraints(),
        user_query_vector=[0.1] * 8,
    )

    assert [m.course_title for m in matches] == ["Dear MSc", "Cheap MSc"]
    assert matches[0].similarity_score == pytest.approx(0.93)


@pytest.mark.asyncio
async def test_vector_search_is_restricted_to_sql_candidates() -> None:
    """The filter is what keeps ineligible courses out of the ranking."""
    eligible = row("Eligible", 5_000)
    session = FakeSession([eligible])
    qdrant = FakeQdrant(
        [FakePoint(str(eligible.course_id), 0.8, {"course_id": str(eligible.course_id)})]
    )

    await execute_hybrid_search(
        db_session=session,
        qdrant_client=qdrant,
        user_constraints=SearchConstraints(max_budget_usd=10_000),
        user_query_vector=[0.1] * 8,
    )

    condition = qdrant.query_filter.must[0]
    assert condition.key == "course_id"
    assert condition.match.any == [str(eligible.course_id)]


@pytest.mark.asyncio
async def test_empty_filter_skips_the_vector_call_entirely() -> None:
    qdrant = FakeQdrant([])
    matches = await execute_hybrid_search(
        db_session=FakeSession([]),
        qdrant_client=qdrant,
        user_constraints=SearchConstraints(max_budget_usd=1),
        user_query_vector=[0.1] * 8,
    )
    assert matches == []
    assert qdrant.query_filter is None  # no pointless round trip


@pytest.mark.asyncio
async def test_unembedded_candidates_still_return_unranked() -> None:
    """Eligible-but-unembedded beats returning nothing during a partial ingest."""
    only = row("Not yet embedded", 5_000)
    matches = await execute_hybrid_search(
        db_session=FakeSession([only]),
        qdrant_client=FakeQdrant([]),
        user_constraints=SearchConstraints(),
        user_query_vector=[0.1] * 8,
    )
    assert [m.course_title for m in matches] == ["Not yet embedded"]
    assert matches[0].similarity_score == 0.0


@pytest.mark.asyncio
async def test_top_k_is_respected() -> None:
    rows = [row(f"Course {i}", 1_000 * i) for i in range(1, 6)]
    points = [
        FakePoint(str(r.course_id), 1.0 - i / 10, {"course_id": str(r.course_id)})
        for i, r in enumerate(rows)
    ]
    matches = await execute_hybrid_search(
        db_session=FakeSession(rows),
        qdrant_client=FakeQdrant(points),
        user_constraints=SearchConstraints(),
        user_query_vector=[0.1] * 8,
        top_k=2,
    )
    assert len(matches) == 2


# --------------------------------------------------------------------------- #
# E. embeddings - provider response quirks
# --------------------------------------------------------------------------- #


@dataclass
class FakeEmbeddingItem:
    index: int | None
    embedding: list[float]


class FakeEmbeddings:
    def __init__(self, items: list[FakeEmbeddingItem]) -> None:
        self._items = items
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs

        class Response:
            def __init__(self, items: list[FakeEmbeddingItem]) -> None:
                self.data = items

        return Response(self._items)


class FakeLLMClient:
    def __init__(self, items: list[FakeEmbeddingItem]) -> None:
        self.embeddings = FakeEmbeddings(items)


@pytest.mark.asyncio
async def test_null_index_does_not_crash_ordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini leaves the first item's index null while numbering the rest;
    sorting on it raised "'<' not supported between int and NoneType"."""
    from app.services.phase2 import embeddings as module

    client = FakeLLMClient(
        [
            FakeEmbeddingItem(None, [0.1] * 4),
            FakeEmbeddingItem(1, [0.2] * 4),
        ]
    )
    monkeypatch.setattr(module, "get_client", lambda: client)
    monkeypatch.setattr(
        module, "get_settings", lambda: _settings(dimensions=4)
    )

    vectors = await module.embed_texts(["a", "b"])
    assert [v[0] for v in vectors] == [0.1, 0.2]  # response order preserved


@pytest.mark.asyncio
async def test_integer_indexes_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI does number every item, and may return them out of order."""
    from app.services.phase2 import embeddings as module

    client = FakeLLMClient(
        [
            FakeEmbeddingItem(1, [0.2] * 4),
            FakeEmbeddingItem(0, [0.1] * 4),
        ]
    )
    monkeypatch.setattr(module, "get_client", lambda: client)
    monkeypatch.setattr(module, "get_settings", lambda: _settings(dimensions=4))

    vectors = await module.embed_texts(["a", "b"])
    assert [v[0] for v in vectors] == [0.1, 0.2]  # reordered by index


@pytest.mark.asyncio
async def test_width_mismatch_is_reported_at_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong width is a readable error here, not an opaque Qdrant 400."""
    from app.services.phase2 import embeddings as module

    client = FakeLLMClient([FakeEmbeddingItem(0, [0.1] * 4)])
    monkeypatch.setattr(module, "get_client", lambda: client)
    monkeypatch.setattr(module, "get_settings", lambda: _settings(dimensions=1536))

    with pytest.raises(module.EmbeddingError, match="does not match"):
        await module.embed_texts(["a"])


def _settings(*, dimensions: int) -> Any:
    class S:
        embedding_model = "test-embedding"
        embedding_dimensions = dimensions

    return S()


# --------------------------------------------------------------------------- #
# The courses table's import columns
#
# These are written by the bulk importers and read by nothing in the request
# path, which is exactly why they need a test: a column quietly dropped from
# the model would not fail a search, it would fail the next import.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "column", ["field_broad", "field_narrow", "field_detailed"]
)
def test_the_asced_classification_is_on_the_courses_table(column: str) -> None:
    from app.services.phase2.db import Course

    assert column in Course.__table__.columns


@pytest.mark.parametrize(
    "column",
    ["field_broad", "field_narrow", "field_detailed", "university_id",
     "external_course_code", "duration_weeks", "tuition_fee_aud",
     "course_level_raw"],
)
def test_import_columns_are_nullable(column: str) -> None:
    """A course crawled from a page carries none of them, and the hard filter
    does not read them - so requiring any would break the crawl path."""
    from app.services.phase2.db import Course

    assert Course.__table__.columns[column].nullable is True


def test_the_broad_field_is_indexed() -> None:
    """It is the level a facet groups by; 9,845 rows without an index turns
    every facet into a sequential scan."""
    from app.services.phase2.db import Course

    assert Course.__table__.columns["field_broad"].index is True


@pytest.mark.parametrize(
    "statement",
    [
        "ADD COLUMN IF NOT EXISTS field_broad",
        "ADD COLUMN IF NOT EXISTS field_narrow",
        "ADD COLUMN IF NOT EXISTS field_detailed",
    ],
)
def test_existing_databases_get_the_new_columns(statement: str) -> None:
    """`create_all` creates missing tables but never alters an existing one,
    so a database built before these columns existed would keep the old shape
    and the importer would fail on its first insert."""
    from app.services.phase2.db import _DDL_COLUMNS

    assert any(statement in ddl for ddl in _DDL_COLUMNS)


def test_the_asced_backfill_joins_on_the_register_identifier() -> None:
    """The CRICOS course code is unique in both tables. Joining on title and
    university instead would collapse the same award offered at several
    campuses onto one classification."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
    from ingest_cricos import ASCED_BACKFILL

    assert "c.external_course_code = r.external_course_code" in ASCED_BACKFILL
    # Rewrites only what actually differs, so a re-run is cheap and a changed
    # classification in a later release is still picked up.
    assert "IS DISTINCT FROM" in ASCED_BACKFILL


# --------------------------------------------------------------------------- #
# An unstated requirement is not a requirement of zero
#
# The CRICOS register publishes no entry requirements and no intake dates for
# any of its 9,845 courses. Storing that silence as 0.0 made every one of them
# look as though it had published a bar of zero, and the card rendered it as
# "0% . IELTS 0". Filling the gap with plausible defaults instead is worse:
# measured on this index, defaulting to 60% / IELTS 6.5 takes a student with
# IELTS 6.0 from 3,795 eligible Australian Master's programmes to none at all.
# --------------------------------------------------------------------------- #


def test_an_unstated_ielts_requirement_stays_eligible() -> None:
    sql = compiled(SearchConstraints(student_ielts=6.0))
    assert "min_ielts_score IS NULL" in sql
    assert "min_ielts_score <= 6.0" in sql


def test_an_unstated_gpa_requirement_stays_eligible() -> None:
    sql = compiled(SearchConstraints(student_gpa_percent=77.0))
    assert "min_gpa_percent IS NULL" in sql
    assert "min_gpa_percent <= 77.0" in sql


def test_a_stated_requirement_still_excludes() -> None:
    """The relaxation must apply only to silence. A course that genuinely
    asks for IELTS 7.0 must still be filtered out for a student with 6.0."""
    sql = compiled(SearchConstraints(student_ielts=6.0))
    assert "min_ielts_score <= 6.0" in sql


def test_the_requirement_columns_accept_unknown() -> None:
    from app.services.phase2.db import Course

    assert Course.__table__.columns["min_gpa_percent"].nullable is True
    assert Course.__table__.columns["min_ielts_score"].nullable is True


@pytest.mark.parametrize("column", ["deadline_type", "next_deadline", "intakes"])
def test_the_intake_columns_exist_and_are_optional(column: str) -> None:
    """Three fields rather than one, because "we do not know" and
    "applications never close" are different answers and a student plans
    around them differently."""
    from app.services.phase2.db import Course

    assert Course.__table__.columns[column].nullable is True


@pytest.mark.parametrize(
    "statement",
    [
        "ADD COLUMN IF NOT EXISTS deadline_type",
        "ADD COLUMN IF NOT EXISTS intakes",
        "ALTER COLUMN min_gpa_percent DROP NOT NULL",
        "ALTER COLUMN min_ielts_score DROP NOT NULL",
    ],
)
def test_an_existing_database_is_migrated(statement: str) -> None:
    from app.services.phase2.db import _DDL_COLUMNS

    assert any(statement in ddl for ddl in _DDL_COLUMNS)


def test_a_match_may_report_unknown_requirements() -> None:
    """The contract has to carry the distinction all the way to the card, or
    the UI has no way to tell "asks for nothing" from "we have no figure"."""
    from app.services.phase2.schemas import CourseMatch

    match = CourseMatch(
        course_id=uuid.uuid4(),
        course_title="Master of Business",
        university_name="Somewhere",
        country="Australia",
        degree_level="Masters",
        tuition_fee_usd=30_000,
        currency="AUD",
        tuition_fee_amount=45_000,
        min_gpa_percent=None,
        min_ielts_score=None,
        deadline_date=None,
        deadline_type="not_published",
        post_study_work_eligible=True,
        syllabus_description="Modules.",
        similarity_score=0.7,
    )
    assert match.min_gpa_percent is None
    assert match.deadline_type == "not_published"
