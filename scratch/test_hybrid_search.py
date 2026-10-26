import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(r"c:\Users\chaud\study-abroad-agent")
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.phase2.hybrid_search_service import search_courses
from app.services.phase2.schemas import SearchConstraints

async def test_search():
    queries = [
        "Doctor of Medicine clinical rotations residency MBBS",
        "Dentistry DDS oral surgery periodontics BDS",
        "Experimental Surgery surgical oncology robotics",
        "Executive MBA and strategic finance management",
        "Interaction UX UI design digital media",
        "Quantum physics astrophysics and theoretical mechanics"
    ]

    for q in queries:
        constraints = SearchConstraints(
            countries=["Canada"],
            degree_levels=["Masters", "Bachelors"]
        )
        results = await search_courses(query=q, constraints=constraints, top_k=3)
        print(f"\n[Semantic Match: '{q}']")
        for r in results:
            print(f"  * {r.course_title} ({r.university_name}) | score: {r.similarity_score:.3f}")

if __name__ == '__main__':
    asyncio.run(test_search())
