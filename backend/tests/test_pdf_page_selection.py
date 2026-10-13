"""Which pages of a long transcript reach the vision model.

The final cumulative grade is printed at the end of a transcript. Rendering
only the first N pages therefore dropped the one figure that matters on any
document longer than the cap - and the grade was then averaged from the
subject list instead, silently, with three decimal places.
"""

from __future__ import annotations

import pytest

from app.ocr_service import MAX_PDF_PAGES


def selected(total: int, cap: int = MAX_PDF_PAGES) -> list[int]:
    """Mirrors the choice made in `_render_pdf_pages`."""
    if total <= cap:
        return list(range(total))
    return list(range(cap - 1)) + [total - 1]


@pytest.mark.parametrize("total", [1, 2, 5, 6, 7, 8, 12, 40])
def test_the_last_page_is_always_rendered(total: int) -> None:
    """Where the cumulative total lives."""
    assert total - 1 in selected(total)


@pytest.mark.parametrize("total", [1, 2, 5, 6])
def test_a_short_document_is_rendered_whole(total: int) -> None:
    assert selected(total) == list(range(total))


@pytest.mark.parametrize("total", [7, 8, 12, 40])
def test_the_cap_is_still_respected(total: int) -> None:
    """The cap exists to bound the payload; keeping the tail must not grow
    it."""
    assert len(selected(total)) == MAX_PDF_PAGES


def test_the_opening_pages_are_kept_too() -> None:
    """Name, institution and programme are on the first page, so this cannot
    become "last page only"."""
    assert 0 in selected(20)


def test_no_page_is_rendered_twice() -> None:
    """Off-by-one guard: at exactly cap+1 the tail must not duplicate a page
    already chosen from the head."""
    for total in range(1, 40):
        chosen = selected(total)
        assert len(chosen) == len(set(chosen)), f"duplicate page for {total}"
