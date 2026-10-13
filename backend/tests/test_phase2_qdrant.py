"""Vector-side tests against a real Qdrant engine (local in-memory mode).

These are not fakes: `AsyncQdrantClient(":memory:")` runs Qdrant's own local
implementation, so collection creation, payload indexing, MatchAny filtering
and cosine ranking behave as they do against a server. Only Postgres is
substituted, because it has no in-process equivalent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from qdrant_client import AsyncQdrantClient, models

from app.services.phase2.hybrid_search_service import execute_hybrid_search
from app.services.phase2.schemas import SearchConstraints

DIMS = 8
COLLECTION = "course_syllabi"


def unit(*values: float) -> list[float]:
    """A DIMS-wide vector from the leading values given."""
    vector = list(values) + [0.0] * (DIMS - len(values))
    return vector[:DIMS]


@dataclass(eq=False)  # identity hashing, so rows can key the seed mapping
class FakeRow:
    course_id: uuid.UUID
    course_title: str
    university_name: str = "TU Munich"
    country: str = "Germany"
    degree_level: str = "Masters"
    tuition_fee_amount: float = 9500.0
    currency: str = "EUR"
    tuition_fee_usd: float = 10260.0
    min_gpa_percent: float = 70.0
    min_ielts_score: float = 6.5
    deadline_date: str | None = None
    deadline_type: str | None = None
    intakes: str | None = None
    post_study_work_eligible: bool = True
    syllabus_description: str = "..."


class FakeSession:
    def __init__(self, rows: list[FakeRow]) -> None:
        self._rows = rows

    async def execute(self, statement: Any) -> Any:
        class Result:
            def __init__(self, rows: list[FakeRow]) -> None:
                self._rows = rows

            def scalars(self) -> Any:
                return self

            def all(self) -> list[FakeRow]:
                return self._rows

        return Result(self._rows)


@pytest.fixture
async def qdrant(monkeypatch: pytest.MonkeyPatch) -> AsyncQdrantClient:
    """A live local Qdrant with three courses embedded."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", str(DIMS))
    monkeypatch.setenv("QDRANT_COLLECTION", COLLECTION)
    get_settings.cache_clear()

    client = AsyncQdrantClient(":memory:")
    await client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(size=DIMS, distance=models.Distance.COSINE),
    )
    yield client
    await client.close()
    get_settings.cache_clear()


async def seed(client: AsyncQdrantClient, rows: dict[FakeRow, list[float]]) -> None:
    await client.upsert(
        collection_name=COLLECTION,
        points=[
            models.PointStruct(
                id=str(row.course_id),
                vector=vector,
                payload={
                    "course_id": str(row.course_id),
                    "university_name": row.university_name,
                    "country": row.country,
                },
            )
            for row, vector in rows.items()
        ],
        wait=True,
    )


@pytest.mark.asyncio
async def test_cosine_ranking_is_real(qdrant: AsyncQdrantClient) -> None:
    """The closest syllabus vector must come back first."""
    ml = FakeRow(uuid.uuid4(), "MSc Machine Learning")
    law = FakeRow(uuid.uuid4(), "LLM International Law")
    await seed(qdrant, {ml: unit(1.0, 0.0), law: unit(0.0, 1.0)})

    matches = await execute_hybrid_search(
        db_session=FakeSession([ml, law]),
        qdrant_client=qdrant,
        user_constraints=SearchConstraints(),
        user_query_vector=unit(0.95, 0.05),
    )

    assert [m.course_title for m in matches] == [
        "MSc Machine Learning",
        "LLM International Law",
    ]
    assert matches[0].similarity_score > matches[1].similarity_score


@pytest.mark.asyncio
async def test_ineligible_courses_cannot_be_ranked_in(
    qdrant: AsyncQdrantClient,
) -> None:
    """The real guarantee: a course the SQL filter rejected never surfaces,
    however well its syllabus matches the query."""
    affordable = FakeRow(uuid.uuid4(), "Affordable MSc", tuition_fee_usd=8_000)
    perfect_but_costly = FakeRow(
        uuid.uuid4(), "Ideal but unaffordable MSc", tuition_fee_usd=90_000
    )
    # The expensive one is an exact match for the query vector.
    await seed(
        qdrant,
        {affordable: unit(0.2, 0.9), perfect_but_costly: unit(1.0, 0.0)},
    )

    # Postgres returns only the affordable course.
    matches = await execute_hybrid_search(
        db_session=FakeSession([affordable]),
        qdrant_client=qdrant,
        user_constraints=SearchConstraints(max_budget_usd=10_000),
        user_query_vector=unit(1.0, 0.0),
    )

    titles = [m.course_title for m in matches]
    assert titles == ["Affordable MSc"]
    assert "Ideal but unaffordable MSc" not in titles


@pytest.mark.asyncio
async def test_match_any_filter_narrows_a_populated_collection(
    qdrant: AsyncQdrantClient,
) -> None:
    """Many points embedded, two eligible: only those two may be scored."""
    rows = [FakeRow(uuid.uuid4(), f"Course {i}") for i in range(10)]
    await seed(qdrant, {r: unit(1.0, i / 10) for i, r in enumerate(rows)})

    eligible = rows[3:5]
    matches = await execute_hybrid_search(
        db_session=FakeSession(eligible),
        qdrant_client=qdrant,
        user_constraints=SearchConstraints(),
        user_query_vector=unit(1.0, 0.0),
    )

    assert {m.course_id for m in matches} == {r.course_id for r in eligible}


@pytest.mark.asyncio
async def test_reingest_updates_in_place(qdrant: AsyncQdrantClient) -> None:
    """A re-crawl must overwrite the point, not add a second one."""
    course = FakeRow(uuid.uuid4(), "MSc Data Science")
    await seed(qdrant, {course: unit(1.0, 0.0)})
    await seed(qdrant, {course: unit(0.0, 1.0)})

    count = await qdrant.count(collection_name=COLLECTION, exact=True)
    assert count.count == 1
