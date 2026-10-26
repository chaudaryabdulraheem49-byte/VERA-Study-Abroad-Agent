"""Validate UK Degree Catalog Ingestion and Search Retrieval.

Runs validation checks and queries for UK undergraduate programs:
1. "Computer Science Software Engineering"
2. "Medicine and Healthcare"
3. "Law and Legal Studies"
4. "Business and Accounting"

Outputs summary statistics for UK institutions, campuses, courses, and tariff mappings.

Usage:
    python scripts/validate_uk_search.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

# Fix Windows console cp1252 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.phase2.db import Course, Institution, University, dispose_engine, session_scope
from app.services.phase2.hybrid_search_service import search_courses
from app.services.phase2.ingestion_service import close_qdrant_client
from app.services.phase2.schemas import SearchConstraints

VALIDATION_QUERIES = [
    {
        "label": "Computer Science Software Engineering",
        "query": "Computer Science Software Engineering",
        "keywords": ["Computer Science", "Software"],
    },
    {
        "label": "Medicine & Healthcare",
        "query": "Medicine and Healthcare",
        "keywords": ["Medicine", "Surgery"],
    },
    {
        "label": "Law & Legal Studies",
        "query": "Law and Legal Studies",
        "keywords": ["Law", "Criminology"],
    },
    {
        "label": "Business & Accounting",
        "query": "Business and Accounting",
        "keywords": ["Finance", "Accounting", "Business"],
    },
]


async def run_validations() -> None:
    async with session_scope() as session:
        # 1. Total statistics
        total_courses = await session.scalar(
            select(func.count(Course.course_id)).where(Course.country == "UK")
        )
        total_unis = await session.scalar(
            select(func.count(University.university_id)).where(University.country == "UK")
        )
        total_institutions = await session.scalar(
            select(func.count(Institution.institution_id)).where(Institution.country == "UK")
        )

        min_gpa = await session.scalar(
            select(func.min(Course.min_gpa_percent)).where(Course.country == "UK")
        )
        avg_gpa = await session.scalar(
            select(func.avg(Course.min_gpa_percent)).where(Course.country == "UK")
        )
        max_gpa = await session.scalar(
            select(func.max(Course.min_gpa_percent)).where(Course.country == "UK")
        )

        print("\n" + "=" * 76)
        print("           UK DISCOVER UNI CATALOG VALIDATION & RETRIEVAL")
        print("=" * 76)
        print(f"Total UK Courses in PostgreSQL:       {total_courses:,}")
        print(f"Total UK Providers (universities):    {total_unis:,}")
        print(f"Total UK Campuses (institutions):     {total_institutions:,}")
        print(f"Dynamic Entry Tariff GPA Range:       Min {min_gpa}% | Avg {avg_gpa:.1f}% | Max {max_gpa}%")
        print("=" * 76 + "\n")

    # 2. Test hybrid retrieval across queries
    for item in VALIDATION_QUERIES:
        print(f"--- Running Hybrid Search: '{item['label']}' (countries=['UK']) ---")
        constraints = SearchConstraints(
            countries=["UK"],
            degree_levels=["Bachelors"],
        )
        results = await search_courses(item["query"], constraints, top_k=3)
        if not results:
            print("  No matches returned (ensure embeddings are backfilled into Qdrant).\n")
            continue

        for i, match in enumerate(results, 1):
            fee_str = f"£{match.tuition_fee_amount:,.0f} (${match.tuition_fee_usd:,.0f} USD)"
            gpa_str = f"{match.min_gpa_percent}%" if match.min_gpa_percent else "N/A"
            print(f"  [{i}] {match.course_title}")
            print(f"      Provider:   {match.university_name}")
            print(f"      Fee:        {fee_str} | Min IELTS: {match.min_ielts_score} | Min GPA: {gpa_str}")
            print(f"      Similarity: {match.similarity_score:.4f} (Qdrant)")
            print(f"      Excerpt:    {match.syllabus_description[:130]}...")
        print()

    await dispose_engine()
    await close_qdrant_client()


def main() -> None:
    asyncio.run(run_validations())


if __name__ == "__main__":
    main()
