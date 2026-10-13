"""Asking for a transcript to be read, before sending one.

Answering that by carrying on with the interview - "what is your name?" -
reads as not having listened, and asks for figures the document itself
carries. The turn stops and waits for the file instead.
"""

from __future__ import annotations

import pytest

from app.llm_service import asks_to_share_transcript
from app.main import _plan_turn
from app.schemas import SessionState, SlotPatch


@pytest.mark.parametrize(
    "message",
    [
        "Read my transcript for me",
        "can you read my transcript?",
        "please check my transcript",
        "I want to upload my transcript",
        "can I send you my marksheet",
        "go through my result card",
        "analyse my academic record",
        "could you look at my mark sheet",
        "I'll attach my transcript",
        # South Asian terms, since that is most of who this serves.
        "let me share my DMC",
        "review my detailed marks certificate",
    ],
)
def test_a_request_to_read_a_transcript_is_recognised(message: str) -> None:
    assert asks_to_share_transcript(message)


@pytest.mark.parametrize(
    "message",
    [
        # Quoting the document is not asking us to read it.
        "my transcript says 3.2",
        "I don't have a transcript",
        # A question about the concept, not a request.
        "what is a transcript?",
        "I want to study in Australia",
        "my name is Raheem",
        "read the news",
    ],
)
def test_other_mentions_do_not_stall_the_interview(message: str) -> None:
    assert not asks_to_share_transcript(message)


def test_the_turn_waits_and_asks_for_nothing_else() -> None:
    state = SessionState()
    directive, fallback, card = _plan_turn(
        state, had_upload=False, awaiting_transcript=True
    )

    assert "transcript" in fallback.lower()
    # The whole point: no slot question goes out with it.
    assert "do not ask for their name" in directive.lower()
    # No report can exist yet, and the next message is the upload rather than
    # an answer to a question nobody asked.
    assert card is None
    assert state.awaiting == []


def test_it_still_waits_part_way_through_the_interview() -> None:
    """The request can arrive at any point, not just on a fresh session."""
    state = SessionState()
    state.slots.merge(SlotPatch(full_name="Raheem", nationality="Pakistan"))
    _, fallback, card = _plan_turn(
        state, had_upload=False, awaiting_transcript=True
    )
    assert "transcript" in fallback.lower()
    assert card is None


def test_an_arrived_transcript_is_parsed_not_awaited() -> None:
    """Once the file is actually here there is nothing left to wait for."""
    state = SessionState()
    directive, _, _ = _plan_turn(
        state, had_upload=True, awaiting_transcript=False
    )
    assert "once they share" not in directive
