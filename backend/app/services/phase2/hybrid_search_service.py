"""Step 4: hard filter in Postgres, then rank the survivors in Qdrant.

The ordering is the whole point. Budget, IELTS and country are facts a student
either meets or does not, and a vector store cannot enforce them — a semantic
search alone will happily return a course they cannot afford or qualify for.
So Postgres decides *eligibility* and Qdrant decides *relevance*, over the
narrowed set.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Final

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from .db import Course, session_scope
from . import embedding_cache
from .embeddings import embed_text
from .ingestion_service import get_qdrant_client
from .schemas import CourseMatch, SearchConstraints

logger = logging.getLogger(__name__)


class SearchError(RuntimeError):
    """Raised when a search could not be completed."""


async def search_courses(
    query: str,
    constraints: SearchConstraints,
    *,
    top_k: int | None = None,
) -> list[CourseMatch]:
    """Convenience entry point: embed the query, then run the hybrid search.

    The query vector is cached. Students repeat subjects heavily, and on a
    metered tier a repeated search that costs nothing is the difference
    between the feature working and the whole search going offline once the
    day's allowance is spent.
    """
    # The async forms keep the cache's disk work off the event loop. Reading
    # and rewriting a ~920 KB JSON file inline blocked every other request in
    # the process for about 40 ms on each miss.
    vector = await embedding_cache.aget(query)
    if vector is None:
        vector = await embed_text(query)
        await embedding_cache.aput(query, vector)
    else:
        logger.info("Query vector served from cache (no allowance spent): %r", query)
    async with session_scope() as session:
        return await execute_hybrid_search(
            db_session=session,
            qdrant_client=get_qdrant_client(),
            user_constraints=constraints,
            user_query_vector=vector,
            top_k=top_k,
            query_text=query,
        )


_LEXICAL_STOPWORDS: Final[set[str]] = {
    "in", "at", "and", "or", "of", "the", "a", "an", "for", "to", "with",
    "bachelors", "masters", "master", "bachelor", "phd", "degree", "program",
    "programme", "study", "studies", "msc", "bsc", "ba", "ma", "postgraduate",
    "undergraduate", "international", "university",
}


def _compute_lexical_score(query_text: str, course: Course) -> float:
    """Fallback similarity score when vectors are not yet indexed."""
    if not query_text:
        return 0.0

    q_lower = query_text.lower()
    t_lower = (course.course_title or "").lower()
    s_lower = (course.syllabus_description or "").lower()

    words = re.findall(r"\b[a-zA-Z]{2,}\b", q_lower)
    keywords = [w for w in words if w not in _LEXICAL_STOPWORDS]
    if not keywords:
        keywords = words
    if not keywords:
        return 0.65

    phrase = " ".join(keywords[:2])
    if phrase and phrase in t_lower:
        return 0.85

    matched_title = sum(1 for kw in keywords if kw in t_lower)
    title_ratio = matched_title / len(keywords)

    matched_syllabus = sum(1 for kw in keywords if kw in s_lower)
    syllabus_ratio = matched_syllabus / len(keywords)

    if title_ratio >= 1.0:
        return 0.82
    elif title_ratio >= 0.5:
        return 0.75
    elif matched_title >= 1:
        return 0.68
    elif syllabus_ratio >= 0.5:
        return 0.62
    elif matched_syllabus >= 1:
        return 0.50
    return 0.25


async def execute_hybrid_search(
    db_session: AsyncSession,
    qdrant_client: AsyncQdrantClient,
    user_constraints: SearchConstraints,
    user_query_vector: list[float],
    *,
    top_k: int | None = None,
    query_text: str | None = None,
) -> list[CourseMatch]:
    """Run the two-step search and return the top matches, best first."""
    settings = get_settings()
    limit = top_k or settings.search_top_k

    # --- Step 1: Postgres hard filter ------------------------------------
    candidates = await _filter_candidates(db_session, user_constraints)
    if not candidates:
        logger.info("Hybrid search: no course met the hard constraints")
        return []

    # --- Step 2: Qdrant similarity over those ids only --------------------
    scores = await _rank_candidates(
        qdrant_client,
        user_query_vector,
        list(candidates.keys()),
        limit=limit,
    )
    if not scores:
        # The filter matched but nothing is embedded yet. Rank lexically by
        # course title & syllabus rather than returning unranked 0.0 scores
        # that get dropped by the downstream relevance filter.
        logger.warning(
            "Hybrid search: %d candidates had no vectors; ranking lexically",
            len(candidates),
        )
        scored_candidates = [
            (row, _compute_lexical_score(query_text or "", row))
            for row in candidates.values()
        ]
        scored_candidates.sort(
            key=lambda pair: (pair[1], -(pair[0].tuition_fee_usd or 0.0)),
            reverse=True,
        )
        return [_to_match(row, score) for row, score in scored_candidates[:limit]]

    return [
        _to_match(candidates[course_id], score)
        for course_id, score in scores
        if course_id in candidates
    ][:limit]


# --------------------------------------------------------------------------- #
# Step 1
# --------------------------------------------------------------------------- #


def build_candidate_query(constraints: SearchConstraints, limit: int) -> Select[Any]:
    """The SQL side of the filter, exposed separately so it can be tested."""
    statement = select(Course)

    if constraints.max_budget_usd is not None:
        statement = statement.where(Course.tuition_fee_usd <= constraints.max_budget_usd)

    # NULL means the source states no requirement, which must stay eligible
    # rather than being read as a bar the student failed - the same rule the
    # deadline already follows. Reading an unstated requirement as a real one
    # would, on this index, take a student with IELTS 6.0 from 3,795 eligible
    # Australian Master's programmes to none at all.
    if constraints.student_ielts is not None:
        statement = statement.where(
            (Course.min_ielts_score.is_(None))
            | (Course.min_ielts_score <= constraints.student_ielts)
        )

    if constraints.student_gpa_percent is not None:
        statement = statement.where(
            (Course.min_gpa_percent.is_(None))
            | (Course.min_gpa_percent <= constraints.student_gpa_percent)
        )

    if constraints.countries:
        statement = statement.where(Course.country.in_(constraints.countries))

    if constraints.degree_levels:
        statement = statement.where(Course.degree_level.in_(constraints.degree_levels))

    if constraints.post_study_work_required:
        statement = statement.where(Course.post_study_work_eligible.is_(True))

    if constraints.deadline_after:
        # String comparison is exact for ISO dates, and NULL means "no stated
        # deadline", which should stay eligible rather than be filtered out.
        statement = statement.where(
            (Course.deadline_date.is_(None))
            | (Course.deadline_date >= constraints.deadline_after)
        )

    # Cheapest first, so a truncated candidate set is the affordable end of it
    # rather than an arbitrary slice.
    return statement.order_by(Course.tuition_fee_usd.asc()).limit(limit)


async def _filter_candidates(
    session: AsyncSession, constraints: SearchConstraints
) -> dict[str, Course]:
    settings = get_settings()
    statement = build_candidate_query(constraints, settings.max_sql_candidates)

    try:
        result = await session.execute(statement)
    except Exception as exc:  # noqa: BLE001
        raise SearchError(f"Candidate query failed: {exc}") from exc

    rows = result.scalars().all()
    logger.info("Hybrid search: %d candidates passed the hard filter", len(rows))
    return {str(row.course_id): row for row in rows}


# --------------------------------------------------------------------------- #
# Step 2
# --------------------------------------------------------------------------- #


async def _rank_candidates(
    client: AsyncQdrantClient,
    query_vector: list[float],
    candidate_ids: list[str],
    *,
    limit: int,
) -> list[tuple[str, float]]:
    """Score the candidate ids by syllabus similarity, best first."""
    settings = get_settings()
    query_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="course_id",
                match=models.MatchAny(any=candidate_ids),
            )
        ]
    )

    try:
        response = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        points = response.points
    except AttributeError:
        # Older qdrant-client: query_points does not exist, fall back to search.
        points = await client.search(  # type: ignore[attr-defined]
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise SearchError(f"Vector search failed: {exc}") from exc

    scored: list[tuple[str, float]] = []
    for point in points:
        payload = point.payload or {}
        course_id = payload.get("course_id") or str(point.id)
        scored.append((course_id, float(point.score)))
    return scored


def _to_match(row: Course, score: float) -> CourseMatch:
    return CourseMatch(
        course_id=row.course_id
        if isinstance(row.course_id, uuid.UUID)
        else uuid.UUID(str(row.course_id)),
        course_title=row.course_title,
        university_name=row.university_name,
        country=row.country,
        degree_level=row.degree_level,
        tuition_fee_usd=row.tuition_fee_usd,
        currency=row.currency,
        tuition_fee_amount=row.tuition_fee_amount,
        min_gpa_percent=row.min_gpa_percent,
        min_ielts_score=row.min_ielts_score,
        deadline_date=row.deadline_date,
        deadline_type=row.deadline_type,
        intakes=row.intakes,
        post_study_work_eligible=row.post_study_work_eligible,
        syllabus_description=row.syllabus_description,
        similarity_score=round(score, 6),
    )
