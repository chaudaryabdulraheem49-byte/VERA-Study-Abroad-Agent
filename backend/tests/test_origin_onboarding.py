import pytest
from app.llm_service import heuristic_extract, interpret_bare_answer
from app.main import _event_stream
from app.schemas import EducationLevel, SessionState, SlotName, SlotPatch


def test_user_intro_with_origin_extracts_correct_slots() -> None:
    text = "hey this is ahmad from pakistan I have compeleted inter in medical subjects with 85 percent marks"
    state = SessionState()
    patch = heuristic_extract(text, state)

    assert patch.full_name == "Ahmad"
    assert patch.nationality == "Pakistan"
    assert patch.target_country is None
    assert patch.field_of_study == "Medicine"
    assert patch.education_level == EducationLevel.HIGH_SCHOOL
    assert patch.cgpa is not None
    assert patch.cgpa.raw_value == 85.0


def test_clarifying_origin_never_sets_field_of_study_or_target_country() -> None:
    text = "i am from pakistan"
    state = SessionState()
    patch = heuristic_extract(text, state)

    assert patch.nationality == "Pakistan"
    assert patch.target_country is None
    assert patch.field_of_study is None
    assert interpret_bare_answer(text, SlotName.FIELD_OF_STUDY) is None
