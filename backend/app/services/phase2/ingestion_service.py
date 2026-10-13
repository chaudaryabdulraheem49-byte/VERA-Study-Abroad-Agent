"""Step 3: write one course to Postgres and its syllabus vector to Qdrant.

Postgres is the system of record and assigns the `course_id`; Qdrant stores
the embedding under that same id. Postgres is written first so the id exists
before the vector references it — the reverse order can leave a vector
pointing at a row that was never committed.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from .db import Course, session_scope
from .embeddings import embed_texts
from .schemas import CourseExtractionSchema, StoredCourse

logger = logging.getLogger(__name__)

# Payload keys kept small on purpose: Qdrant filters on these, and everything
# else is one Postgres lookup away via course_id.
_PAYLOAD_KEYS: Final = ("course_id", "university_name", "country")

_qdrant: AsyncQdrantClient | None = None


class IngestionError(RuntimeError):
    """Raised when a course could not be persisted."""


def get_qdrant_client() -> AsyncQdrantClient:
    """Shared async Qdrant client, built on first use."""
    global _qdrant
    if _qdrant is None:
        settings = get_settings()
        _qdrant = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
    return _qdrant


async def close_qdrant_client() -> None:
    global _qdrant
    if _qdrant is not None:
        await _qdrant.close()
    _qdrant = None


async def ensure_collection(
    client: AsyncQdrantClient | None = None, *, recreate: bool = False
) -> None:
    """Create the syllabus collection if absent, sized to the embedding width.

    Idempotent. The payload index on `course_id` is what makes the Step 2
    MatchAny filter fast rather than a full scan of the collection.

    Raises `IngestionError` when an existing collection was built at a
    different width - every upsert would fail against it, and the Qdrant error
    for that does not say why. Pass `recreate=True` to drop and rebuild it.
    """
    settings = get_settings()
    client = client or get_qdrant_client()

    if recreate and await client.collection_exists(settings.qdrant_collection):
        await client.delete_collection(settings.qdrant_collection)
        logger.warning(
            "Dropped Qdrant collection %s; every vector must be re-ingested",
            settings.qdrant_collection,
        )
    elif await client.collection_exists(settings.qdrant_collection):
        await _assert_collection_width(client, settings)

    if not await client.collection_exists(settings.qdrant_collection):
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=settings.embedding_dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info(
            "Created Qdrant collection %s (%d dims)",
            settings.qdrant_collection,
            settings.embedding_dimensions,
        )

    try:
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="course_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except Exception as exc:  # noqa: BLE001 - already-exists is not an error
        logger.debug("course_id payload index already present: %s", exc)


async def _assert_collection_width(
    client: AsyncQdrantClient, settings: Any
) -> None:
    info = await client.get_collection(settings.qdrant_collection)
    params = info.config.params.vectors
    existing = getattr(params, "size", None)
    if existing is None or existing == settings.embedding_dimensions:
        return
    raise IngestionError(
        f"Qdrant collection {settings.qdrant_collection!r} was created with "
        f"{existing}-dim vectors but the configured embedding width is "
        f"{settings.embedding_dimensions}. Every upsert would be rejected. "
        "Recreate it with `pipeline init --recreate` (this drops all stored "
        "vectors; Postgres rows survive and can be re-embedded)."
    )


async def ingest_course_data(
    course: CourseExtractionSchema,
    *,
    source_url: str | None = None,
    qdrant_client: AsyncQdrantClient | None = None,
) -> StoredCourse:
    """Upsert one course into Postgres, then its vector into Qdrant."""
    stored = await _upsert_postgres(course, source_url=source_url)
    await _upsert_qdrant(stored, client=qdrant_client)
    logger.info(
        "Ingested %s - %s (%s)",
        stored.university_name,
        stored.course_title,
        stored.course_id,
    )
    return stored


async def ingest_many(
    courses: list[CourseExtractionSchema],
    *,
    source_urls: dict[tuple[str, str], str] | None = None,
) -> tuple[list[StoredCourse], dict[str, str]]:
    """Ingest a batch, embedding in one call and reporting per-course failures."""
    if not courses:
        return [], {}

    client = get_qdrant_client()
    await ensure_collection(client)

    stored: list[StoredCourse] = []
    failures: dict[str, str] = {}

    for course in courses:
        key = " - ".join(course.natural_key)
        try:
            row = await _upsert_postgres(
                course,
                source_url=(source_urls or {}).get(course.natural_key),
            )
            stored.append(row)
        except Exception as exc:  # noqa: BLE001
            failures[key] = f"postgres: {exc}"
            logger.error("Postgres ingest failed for %s: %s", key, exc)

    if stored:
        try:
            await _upsert_qdrant_batch(stored, client)
        except Exception as exc:  # noqa: BLE001
            for row in stored:
                failures[" - ".join(row.natural_key)] = f"qdrant: {exc}"
            logger.error("Qdrant batch upsert failed: %s", exc)
            return [], failures

    return stored, failures


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #


async def _upsert_postgres(
    course: CourseExtractionSchema,
    *,
    source_url: str | None = None,
    session: AsyncSession | None = None,
) -> StoredCourse:
    """UPSERT on (university_name, course_title), returning the course id.

    A re-crawl of the same page must update the existing row rather than
    duplicate it, so the id stays stable and the Qdrant point keeps pointing
    at the right course.
    """
    values: dict[str, Any] = {
        "course_id": uuid.uuid4(),
        "course_title": course.course_title,
        "university_name": course.university_name,
        "country": course.country,
        "degree_level": course.degree_level,
        "tuition_fee_amount": course.tuition_fee_amount,
        "currency": course.currency,
        "tuition_fee_usd": course.tuition_fee_usd,
        "min_gpa_percent": course.min_gpa_percent,
        "min_ielts_score": course.min_ielts_score,
        "deadline_date": course.deadline_date,
        "post_study_work_eligible": course.post_study_work_eligible,
        "syllabus_description": course.syllabus_description,
        "source_url": source_url,
    }

    statement = (
        pg_insert(Course)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_courses_university_title",
            # course_id is excluded so a re-ingest keeps the original id.
            set_={
                key: value
                for key, value in values.items()
                if key not in {"course_id", "university_name", "course_title"}
            },
        )
        .returning(Course.course_id)
    )

    async def run(active: AsyncSession) -> uuid.UUID:
        result = await active.execute(statement)
        course_id = result.scalar_one()
        return course_id

    if session is not None:
        course_id = await run(session)
    else:
        async with session_scope() as scoped:
            course_id = await run(scoped)

    return StoredCourse(course_id=course_id, **course.model_dump())


async def fetch_course(course_id: uuid.UUID) -> Course | None:
    async with session_scope() as session:
        result = await session.execute(
            select(Course).where(Course.course_id == course_id)
        )
        return result.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Qdrant
# --------------------------------------------------------------------------- #


async def _upsert_qdrant(
    course: StoredCourse, *, client: AsyncQdrantClient | None = None
) -> None:
    client = client or get_qdrant_client()
    await ensure_collection(client)
    await _upsert_qdrant_batch([course], client)


async def _upsert_qdrant_batch(
    courses: list[StoredCourse], client: AsyncQdrantClient
) -> None:
    settings = get_settings()
    vectors = await embed_texts([course.embedding_text() for course in courses])

    points = [
        models.PointStruct(
            id=str(course.course_id),
            vector=vector,
            payload={
                "course_id": str(course.course_id),
                "university_name": course.university_name,
                "country": course.country,
            },
        )
        for course, vector in zip(courses, vectors, strict=True)
    ]

    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
        wait=True,  # so a search immediately after ingest sees the point
    )
