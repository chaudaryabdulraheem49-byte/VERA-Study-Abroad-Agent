"""Manual end-to-end check against live Postgres + Qdrant (needs an API key).

Skips the crawler so it can run without Crawl4AI installed: it feeds courses
straight into the ingestion service, then searches them back.

    python -m tests.live_phase2
"""

from __future__ import annotations

import asyncio

from app.services.phase2.db import dispose_engine, init_schema
from app.services.phase2.hybrid_search_service import search_courses
from app.services.phase2.ingestion_service import (
    close_qdrant_client,
    ingest_many,
)
from app.services.phase2.schemas import CourseExtractionSchema, SearchConstraints

COURSES = [
    {
        "course_title": "MSc Data Science and Machine Learning",
        "university_name": "TU Munich",
        "country": "Germany",
        "degree_level": "Masters",
        "tuition_fee_amount": 0,
        "currency": "EUR",
        "min_gpa_percent": 75,
        "min_ielts_score": 6.5,
        "deadline_date": "2026-05-31",
        "post_study_work_eligible": True,
        "syllabus_description": (
            "Statistical learning, deep neural networks, large-scale data "
            "engineering, reinforcement learning and a research thesis."
        ),
    },
    {
        "course_title": "LLM International Commercial Law",
        "university_name": "University of Toronto",
        "country": "Canada",
        "degree_level": "Masters",
        "tuition_fee_amount": 38000,
        "currency": "CAD",
        "min_gpa_percent": 80,
        "min_ielts_score": 7.0,
        "deadline_date": "2026-01-15",
        "post_study_work_eligible": True,
        "syllabus_description": (
            "Cross-border contracts, arbitration, competition law, corporate "
            "governance and international trade regulation."
        ),
    },
    {
        "course_title": "MSc Artificial Intelligence",
        "university_name": "University of Melbourne",
        "country": "Australia",
        "degree_level": "Masters",
        "tuition_fee_amount": 48000,
        "currency": "AUD",
        "min_gpa_percent": 70,
        "min_ielts_score": 6.5,
        "deadline_date": None,
        "post_study_work_eligible": True,
        "syllabus_description": (
            "Machine learning, computer vision, natural language processing, "
            "knowledge representation and AI ethics."
        ),
    },
]


async def main() -> int:
    await init_schema()

    courses = [CourseExtractionSchema.model_validate(c) for c in COURSES]
    print("Ingesting:")
    for course in courses:
        print(
            f"  {course.university_name:28} {course.course_title[:40]:42} "
            f"${course.tuition_fee_usd:>9,.0f} USD  IELTS {course.min_ielts_score}"
        )

    stored, failures = await ingest_many(courses)
    for key, reason in failures.items():
        print(f"  FAILED {key}: {reason}")
    print(f"\nStored {len(stored)} course(s) in Postgres + Qdrant.\n")

    # Re-ingest to prove the upsert keeps ids stable rather than duplicating.
    again, _ = await ingest_many(courses)
    stable = {s.course_id for s in stored} == {a.course_id for a in again}
    print(f"Re-ingest kept course ids stable: {stable}\n")

    checks = [
        ("machine learning and neural networks", SearchConstraints(), "semantic"),
        (
            "machine learning and neural networks",
            SearchConstraints(max_budget_usd=20_000),
            "budget <= $20k",
        ),
        (
            "machine learning and neural networks",
            SearchConstraints(student_ielts=6.5),
            "student IELTS 6.5",
        ),
        (
            "contracts and arbitration",
            SearchConstraints(),
            "different query, different winner",
        ),
    ]

    ok = True
    for query, constraints, label in checks:
        matches = await search_courses(query, constraints)
        print(f"[{label}] {query!r}")
        for m in matches:
            print(
                f"   {m.similarity_score:.3f}  {m.course_title[:44]:46} "
                f"${m.tuition_fee_usd:>9,.0f}  IELTS {m.min_ielts_score}"
            )
        if not matches:
            print("   (no matches)")
        print()

        if label == "budget <= $20k":
            ok &= all(m.tuition_fee_usd <= 20_000 for m in matches)
        if label == "student IELTS 6.5":
            ok &= all(m.min_ielts_score <= 6.5 for m in matches)
        if label == "different query, different winner":
            ok &= bool(matches) and "Law" in matches[0].course_title

    print("PASS" if ok else "FAIL: a constraint leaked or ranking was wrong")
    await dispose_engine()
    await close_qdrant_client()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
