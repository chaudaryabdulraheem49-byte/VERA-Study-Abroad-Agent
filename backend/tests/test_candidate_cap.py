"""The cap on candidates handed from Postgres to Qdrant.

Candidates are selected cheapest-first, so this cap is not a neutral
truncation - it decides which programmes are allowed to be scored at all. At
500, on an index holding 3,817 Australian Master's, 3,317 of them were dropped
before similarity was computed, purely for being expensive. The search still
returned plausible results, so nothing looked wrong.
"""

from __future__ import annotations

from app.config import get_settings
from app.services.phase2.db import Course
from app.services.phase2.hybrid_search_service import build_candidate_query
from app.services.phase2.schemas import SearchConstraints


def test_the_cap_covers_a_whole_country_catalogue() -> None:
    """3,817 Australian Master's is the largest single-country slice in this
    index; a cap below it hides the remainder on price alone."""
    assert get_settings().max_sql_candidates >= 3817


def test_the_cap_reaches_the_query() -> None:
    """A setting that never leaves config would be a comment, not a fix."""
    cap = get_settings().max_sql_candidates
    statement = build_candidate_query(SearchConstraints(), cap)
    assert statement._limit == cap


def test_candidates_are_still_ordered_cheapest_first() -> None:
    """The ordering is deliberate - a truncated set should be the affordable
    end rather than an arbitrary slice. Only the cap was raised."""
    statement = build_candidate_query(SearchConstraints(), 10)
    clauses = [str(c) for c in statement._order_by_clauses]
    assert any("tuition_fee_usd" in c for c in clauses)
    assert not any("DESC" in c.upper() for c in clauses)


def test_the_filter_itself_is_unchanged() -> None:
    """Raising the cap must not quietly widen what qualifies."""
    sql = str(
        build_candidate_query(
            SearchConstraints(
                countries=["Australia"],
                degree_levels=["Masters"],
                student_ielts=6.0,
            ),
            100,
        )
    )
    assert "country IN" in sql
    assert "degree_level IN" in sql
    # An unstated requirement stays eligible rather than reading as a bar the
    # student failed.
    assert "min_ielts_score IS NULL" in sql
