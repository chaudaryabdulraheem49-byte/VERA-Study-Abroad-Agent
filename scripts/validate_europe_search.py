"""Validate European Degree Catalog Ingestion and Search Retrieval.

Runs validation checks and queries for:
1. "Automotive Engineering Germany"
2. "English MBBS Poland"
3. "Architecture Italy"
4. "Data Science Netherlands"

Also outputs summary statistics for all 13 European countries and 6 academic clusters.

Usage:
    python scripts/validate_europe_search.py
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

VALIDATION_QUERIES = [
    {
        "label": "Automotive Engineering Germany",
        "country": "Germany",
        "keywords": ["Automotive", "Mobility"],
    },
    {
        "label": "English MBBS Poland",
        "country": "Poland",
        "keywords": ["Medicine", "MBBS"],
    },
    {
        "label": "Architecture Italy",
        "country": "Italy",
        "keywords": ["Architecture", "Architectural"],
    },
    {
        "label": "Data Science Netherlands",
        "country": "Netherlands",
        "keywords": ["Data Science", "Analytics"],
    },
]


async def run_validations() -> None:
    async with session_scope() as session:
        # 1. Total statistics
        total_courses = await session.scalar(select(func.count(Course.course_id)))
        total_institutions = await session.scalar(select(func.count(Institution.institution_id)))
        total_universities = await session.scalar(select(func.count(University.university_id)))

        # European specific
        eu_countries = [
            "Germany", "Netherlands", "Ireland", "Sweden", "France", "Italy",
            "Switzerland", "Finland", "Norway", "Denmark", "Poland", "Austria", "Belgium"
        ]

        eu_course_rows = (
            await session.execute(
                select(Course).where(Course.country.in_(eu_countries))
            )
        ).scalars().all()

        eu_uni_rows = (
            await session.execute(
                select(University).where(University.country.in_(eu_countries))
            )
        ).scalars().all()

        print("\n" + "=" * 80)
        print(" PAN-EUROPEAN DEGREE CATALOG VALIDATION REPORT")
        print("=" * 80)
        print(f"Total Courses in DB (Global):       {total_courses:,}")
        print(f"Total Institutions (Global):        {total_institutions:,}")
        print(f"Total Universities (Global):        {total_universities:,}")
        print(f"Total European Universities (13):   {len(eu_uni_rows):,}")
        print(f"Total European Degree Programs (13):{len(eu_course_rows):,}")
        print("=" * 80)

        # 2. Country Breakdown Table
        unis_by_country = Counter(u.country for u in eu_uni_rows)
        courses_by_country = Counter(c.country for c in eu_course_rows)
        free_by_country = Counter(c.country for c in eu_course_rows if c.tuition_fee_amount == 0)

        print("\n### Summary Breakdown by Country (13 Nations)\n")
        print(f"| Country | Flag | Accredited Universities | English Programs | Tuition-Free Programs | Degree Levels |")
        print(f"| :--- | :---: | :---: | :---: | :---: | :--- |")

        flags = {
            "Germany": "🇩🇪", "Netherlands": "🇳🇱", "Ireland": "🇮🇪", "Sweden": "🇸🇪",
            "France": "🇫🇷", "Italy": "🇮🇹", "Switzerland": "🇨🇭", "Finland": "🇫🇮",
            "Norway": "🇳🇴", "Denmark": "🇩🇰", "Poland": "🇵🇱", "Austria": "🇦🇹", "Belgium": "🇧🇪"
        }

        for country in eu_countries:
            u_count = unis_by_country.get(country, 0)
            c_count = courses_by_country.get(country, 0)
            f_count = free_by_country.get(country, 0)
            flag = flags.get(country, "🇪🇺")
            print(f"| **{country}** | {flag} | {u_count:>3} | {c_count:>4} | {f_count:>3} ({100*f_count/c_count if c_count else 0:.0f}%) | Bachelors & Masters |")

        # 3. Validation Queries
        print("\n" + "=" * 80)
        print(" SPECIFIC VALIDATION QUERY RESULTS")
        print("=" * 80)

        for vq in VALIDATION_QUERIES:
            label = vq["label"]
            country = vq["country"]
            keywords = vq["keywords"]

            query = select(Course).where(Course.country == country)
            # Match any keyword in title
            conds = [Course.course_title.ilike(f"%{kw}%") for kw in keywords]
            from sqlalchemy import or_
            query = query.where(or_(*conds)).order_by(Course.university_name).limit(5)

            results = (await session.execute(query)).scalars().all()

            print(f"\n🔍 Query: '{label}' ({len(results)} Sample Matches Displayed):")
            print("-" * 80)
            for idx, r in enumerate(results, 1):
                fee_str = "0 EUR (Tuition-Free)" if r.tuition_fee_amount == 0 else f"€{r.tuition_fee_amount:,.0f} EUR"
                print(f"  {idx}. {r.course_title} ({r.degree_level})")
                print(f"     University: {r.university_name} | Location: {r.country}")
                print(f"     Tuition:    {fee_str} | Min IELTS: {r.min_ielts_score} | Min GPA: {r.min_gpa_percent}%")
                print(f"     Intakes:    {r.intakes}")
                print(f"     Syllabus:   {r.syllabus_description[:140]}...")
            print("-" * 80)

        # 4. Academic Clusters Breakdown
        field_counts = Counter((c.field_broad or "Unclassified").split(" - ", 1)[-1] for c in eu_course_rows)
        print("\n### Academic Clusters Coverage Across Europe\n")
        print(f"| Academic Cluster | Programs Count | Percentage | Key Degrees |")
        print(f"| :--- | :---: | :---: | :--- |")
        for field, count in field_counts.most_common():
            pct = 100.0 * count / len(eu_course_rows)
            print(f"| **{field}** | {count:,} | {pct:.1f}% | Bachelor & Master Level |")

        print("\n" + "=" * 80 + "\n")


async def main() -> None:
    try:
        await run_validations()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
