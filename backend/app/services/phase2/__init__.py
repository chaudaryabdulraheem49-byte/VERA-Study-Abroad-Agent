"""Phase 2: hybrid extraction and search pipeline.

    [University page] -> crawler_service  (Crawl4AI + LLM -> validated schema)
                      -> ingestion_service (Postgres row + Qdrant vector)
                      -> hybrid_search_service (SQL filter -> vector ranking)
"""

from .schemas import (
    CourseExtractionSchema,
    CourseMatch,
    SearchConstraints,
    StoredCourse,
)

__all__ = [
    "CourseExtractionSchema",
    "CourseMatch",
    "SearchConstraints",
    "StoredCourse",
]
