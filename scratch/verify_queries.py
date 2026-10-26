import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(r"c:\Users\chaud\study-abroad-agent")
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select, func, text, or_
from app.services.phase2.db import Course, session_scope
from app.course_matching import expand_field, _FIELD_EXPANSIONS

async def verify():
    async with session_scope() as session:
        # 1. Discipline breakdown
        r = await session.execute(text("""
            SELECT coalesce(field_broad, 'Unclassified') as field, count(*)
            FROM courses
            WHERE country = 'Canada'
            GROUP BY 1 ORDER BY 2 DESC
        """))
        discipline_counts = r.fetchall()

        # 2. Total Canada count
        r = await session.execute(text("SELECT count(*) FROM courses WHERE country = 'Canada'"))
        total_canada = r.scalar()

        print(f"=== TOTAL CANADIAN COURSES IN DATABASE: {total_canada} ===")
        print("\n=== DISCIPLINE SUMMARY TABLE ===")
        for d, cnt in discipline_counts:
            print(f"  {d:<50} : {cnt:>4} courses")

        # 3. Test verification queries
        test_queries = [
            ("MBBS / Medicine", ["MBBS", "Medicine", "Doctor of Medicine"]),
            ("Dentistry", ["Dentistry", "Dental", "DDS", "BDS"]),
            ("Surgery", ["Surgery", "Surgical"]),
            ("Management", ["Management", "MBA", "Finance"]),
            ("Design", ["Design", "Architecture", "UX", "Industrial Design"]),
            ("Physics", ["Physics", "Astrophysics"]),
        ]

        print("\n=== QUERY VERIFICATION TESTS ===")
        for label, keywords in test_queries:
            # Build search conditions simulating discovery search
            conds = []
            for kw in keywords:
                pat = f"%{kw}%"
                conds.extend([
                    Course.course_title.ilike(pat),
                    Course.field_broad.ilike(pat),
                    Course.field_narrow.ilike(pat),
                    Course.syllabus_description.ilike(pat)
                ])
            
            stmt = select(Course).where(
                Course.country == 'Canada',
                or_(*conds)
            ).order_by(Course.university_name).limit(5)
            
            results = (await session.execute(stmt)).scalars().all()

            # Total match count
            count_stmt = select(func.count(Course.course_id)).where(
                Course.country == 'Canada',
                or_(*conds)
            )
            count = (await session.execute(count_stmt)).scalar()

            print(f"\nQuery: '{label}' -> {count} matches found in Canada:")
            for c in results:
                print(f"  - [{c.university_name}] {c.course_title} ({c.degree_level}) | CAD ${c.tuition_fee_amount:,.0f}")

if __name__ == '__main__':
    asyncio.run(verify())
