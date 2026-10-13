"""Readable labels for saved conversations.

The sidebar showed the first message truncated - "I want to study in Au...",
"this is ali from pakis..." - which is no use for telling conversations apart
once there are a dozen of them.
"""

from __future__ import annotations

import pytest

from app.llm_service import TITLE_MAX_CHARS, _clean_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Masters in CS - Australia", "Masters in CS - Australia"),
        # The one instruction models ignore most reliably.
        ("Title: Ali - Study in UK", "Ali - Study in UK"),
        ("Conversation Title:  Nursing in Canada ", "Nursing in Canada"),
        ('"Low GPA Options"', "Low GPA Options"),
        ("“Low GPA Options”", "Low GPA Options"),
        ("Hassan - Pakistan to Abroad.", "Hassan - Pakistan to Abroad"),
        ("  Study   in    Australia  ", "Study in Australia"),
    ],
)
def test_the_wrappers_models_add_are_stripped(raw: str, expected: str) -> None:
    assert _clean_title(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, '""', "Title:"])
def test_nothing_usable_returns_none(raw: str | None) -> None:
    """None, not a placeholder: the caller keeps the label it already stored,
    which is better than replacing it with something emptier."""
    assert _clean_title(raw) is None


def test_a_sentence_is_rejected_rather_than_cut_down() -> None:
    """Checked before truncation. Cutting a paragraph to 35 characters turns
    its first few words into a plausible-looking title and hides the fact that
    the model never produced one."""
    rambling = (
        "Here is a good title for this conversation: it describes a student "
        "who wants to study abroad somewhere"
    )
    assert _clean_title(rambling) is None


def test_a_long_title_is_cut_on_a_word_boundary() -> None:
    long_title = "Master of Engineering Chemical Australia"
    cleaned = _clean_title(long_title)
    assert cleaned is not None
    assert len(cleaned) <= TITLE_MAX_CHARS
    # Not mid-word.
    assert long_title.startswith(cleaned)
    assert not cleaned.endswith(" ")


@pytest.mark.asyncio
async def test_no_provider_means_no_title_not_an_error(monkeypatch) -> None:
    """History must keep working with no LLM configured - the feature is an
    upgrade to a label, never a precondition for saving a conversation."""
    from app import llm_service

    monkeypatch.setattr(llm_service, "get_client", lambda: None)
    assert await llm_service.generate_title("I want to study in Australia") is None


@pytest.mark.asyncio
async def test_a_provider_failure_keeps_the_existing_label(monkeypatch) -> None:
    from app import llm_service

    class Boom:
        class chat:  # noqa: N801 - mirrors the SDK's shape
            class completions:
                @staticmethod
                async def create(**_kwargs: object) -> object:
                    raise RuntimeError("provider down")

    monkeypatch.setattr(llm_service, "get_client", lambda: Boom())
    assert await llm_service.generate_title("hello") is None


def test_greeting_detection_and_derive_title() -> None:
    from app import chat_history

    # Short greetings and basic pleasantries return "New conversation"
    for greeting in [
        "hey",
        "hello",
        "hi",
        "good morning",
        "hey vera",
        "hello there",
        "salam",
        "aoa",
        "test",
        "testing",
        "",
        "   ",
    ]:
        assert chat_history.is_greeting_or_generic(greeting) is True
        assert chat_history.derive_title(greeting) == "New conversation"

    # Greetings with introductions without academic intent return "New conversation"
    for intro in [
        "hey this iss abdullah from pakiistan",
        "hey this is abdul from pakistan",
        "this is hasan from pakistan",
        "my name is ahmad",
        "hello my name is ali",
    ]:
        assert chat_history.is_greeting_or_generic(intro) is True
        assert chat_history.derive_title(intro) == "New conversation"

    # Messages with actual study abroad intent or substance are not treated as greetings
    substantive = "I want to study in Australia for Masters in CS"
    assert chat_history.is_greeting_or_generic(substantive) is False
    assert chat_history.derive_title(substantive) == substantive

    gpa_query = "What can I do with a 2.5 GPA?"
    assert chat_history.is_greeting_or_generic(gpa_query) is False


def test_is_generic_title() -> None:
    from app import chat_history

    assert chat_history.is_generic_title(None) is True
    assert chat_history.is_generic_title("") is True
    assert chat_history.is_generic_title("New conversation") is True
    assert chat_history.is_generic_title("Getting started") is True
    assert chat_history.is_generic_title("hey") is True
    assert chat_history.is_generic_title("hey this iss abdullah f...") is True
    assert chat_history.is_generic_title("hey this is abdul from pakistan") is True
    assert chat_history.is_generic_title("this is hasan from pakistan") is True
    assert chat_history.is_generic_title("Masters in CS - Australia") is False
    assert chat_history.is_generic_title("Low GPA Options") is False


def test_profile_title_topic_formatting() -> None:
    from app.main import profile_title
    from app.schemas import EducationLevel, OnboardingSlots, SessionState

    # 1. Level + Field + Country -> "Masters CS - Australia"
    state = SessionState(
        slots=OnboardingSlots(
            education_level=EducationLevel.BACHELORS,  # Applying for Masters
            field_of_study="CS",
            target_country="Australia",
        )
    )
    assert profile_title(state) == "Masters CS - Australia"

    # 2. Desired Level + Field + Country -> "Masters Computer Science - Germany"
    state2 = SessionState(
        desired_level=EducationLevel.MASTERS,
        slots=OnboardingSlots(
            field_of_study="computer science",
            target_country="Germany",
        ),
    )
    assert profile_title(state2) == "Masters Computer Science - Germany"

    # 3. Level + Country (field not yet specified) -> "Masters - Australia"
    state3 = SessionState(
        desired_level=EducationLevel.MASTERS,
        slots=OnboardingSlots(target_country="Australia"),
    )
    assert profile_title(state3) == "Masters - Australia"

    # 4. Field + Country (level not yet specified) -> "Computer Science - Canada"
    state4 = SessionState(
        slots=OnboardingSlots(
            field_of_study="computer science",
            target_country="Canada",
        )
    )
    assert profile_title(state4) == "Computer Science - Canada"

    # 5. Level + Field (no country yet) -> "Masters Economics"
    state5 = SessionState(
        desired_level=EducationLevel.MASTERS,
        slots=OnboardingSlots(field_of_study="economics"),
    )
    assert profile_title(state5) == "Masters Economics"

    # 6. Isolated single attribute is too vague on its own -> None
    state_vague1 = SessionState(slots=OnboardingSlots(target_country="Australia"))
    assert profile_title(state_vague1) is None

    state_vague2 = SessionState(desired_level=EducationLevel.MASTERS)
    assert profile_title(state_vague2) is None


def test_extract_title_context_multi_turn() -> None:
    from app.main import extract_title_context
    from app.schemas import OnboardingSlots, SessionState

    state = SessionState(
        slots=OnboardingSlots(
            target_country="Australia",
            field_of_study="CS",
        )
    )
    state.append("user", "hey")
    state.append("assistant", "Hi, I am Vera! Tell me about yourself.")
    state.append("user", "I want to study in Australia for Masters in CS")

    context = extract_title_context(state)
    assert "Profile: Field: CS; Country: Australia" in context
    assert "Student: I want to study in Australia for Masters in CS" in context

