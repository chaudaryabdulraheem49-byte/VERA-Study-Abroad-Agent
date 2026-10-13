"""Live check: a completed profile through to course matches.

Hits the real Postgres, Qdrant and embedding provider, so it is a `live_*`
script rather than a collected test. Run it with the stack up:

    .venv/Scripts/python.exe -m tests.live_phase3
"""

from __future__ import annotations

import asyncio

from app.course_matching import build_constraints, build_query, find_matches
from app.diagnostics import build_card
from app.schemas import (
    AcademicScore,
    EducationLevel,
    GradingScale,
    LanguageScore,
    SessionState,
    SlotPatch,
)


def completed_profile() -> SessionState:
    state = SessionState()
    state.slots.merge(
        SlotPatch(
            full_name="Ali Raza",
            nationality="Pakistan",
            cgpa=AcademicScore(
                raw_value=3.4, scale=GradingScale.US_4_0, scale_max=4.0
            ),
            field_of_study="Computer Science",
            education_level=EducationLevel.BACHELORS,
            target_country="Germany",
            language_score=LanguageScore(test="IELTS", overall=7.0),
        )
    )
    return state


async def main() -> None:
    state = completed_profile()
    card = build_card(state)
    print(f"card: {card.conversion.normalized_percentage}% "
          f"-> US {card.conversion.us_gpa}, DE {card.conversion.german_grade}")
    print(f"query: {build_query(state)!r}")
    print(f"constraints: {build_constraints(state, card)}")

    matches = await find_matches(state, card)
    print(f"\n{len(matches)} match(es):")
    for match in matches:
        print(
            f"  {match['similarity_score']:.3f}  {match['course_title']}"
            f" - {match['university_name']} ({match['country']})"
            f" ${match['tuition_fee_usd']:,.0f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
