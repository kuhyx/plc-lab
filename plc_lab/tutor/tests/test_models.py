# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The structured turn: every way a model reply can break the schema."""

from __future__ import annotations

from typing import Any

import pytest

from plc_lab.tutor.models import (
    REQUIRED_FIELDS,
    TURN_SCHEMA,
    TurnError,
    TutorTurn,
    asked,
    image_requests,
)


def raw_turn(**overrides: Any) -> dict[str, Any]:
    """A valid decoded turn; any field can be overridden."""
    raw: dict[str, Any] = {
        "message": "  Coils, then.  ",
        "questions": ["  What is a coil?  ", " ", 4],
        "low_effort": False,
        "check": {"question": "why?", "concept": "coil"},
        "check_result": {"passed": True, "feedback": "yes"},
        "images": [
            "relay",
            7,
            {"terms": [" PLC rack ", "rack", "", "a", "b"]},
            {"terms": []},
        ],
        "diagram": {"title": "t", "circuits": []},
        "concepts_mastered": ["coil", 3],
        "card_done": 1,
    }
    raw.update(overrides)
    return raw


def test_from_json_happy_path_strips_and_tuples() -> None:
    parsed = TutorTurn.from_json(raw_turn())
    assert parsed.message == "Coils, then."
    assert parsed.questions == ("What is a coil?", "4")  # stripped, blanks dropped
    assert parsed.low_effort is False
    assert parsed.check == {"question": "why?", "concept": "coil"}
    assert parsed.check_result == {"passed": True, "feedback": "yes"}
    assert parsed.images == (("relay",), ("7",), ("PLC rack", "rack", "a"))
    assert parsed.diagram == {"title": "t", "circuits": []}
    assert parsed.concepts_mastered == ("coil", "3")
    assert parsed.card_done is True
    assert parsed.extras == {}


def test_image_requests_reads_old_and_new_forms() -> None:
    assert image_requests(["relay", {"terms": ["a", "b"]}]) == (("relay",), ("a", "b"))
    assert image_requests([{"nope": 1}, {"terms": "single"}, ""]) == (("single",),)
    assert image_requests("relay") == ()
    assert image_requests(None) == ()


def test_schema_images_take_alternatives_and_old_strings() -> None:
    properties: Any = TURN_SCHEMA["properties"]
    images = properties["images"]
    assert "NO limit" in images["description"]
    kinds = [alt.get("type") for alt in images["items"]["anyOf"]]
    assert kinds == ["object", "string"]


def test_from_json_accepts_null_check_result() -> None:
    parsed = TutorTurn.from_json(raw_turn(check_result=None, check=None, diagram=None))
    assert parsed.check_result is None
    assert parsed.check is None
    assert parsed.diagram is None


@pytest.mark.parametrize("raw", [None, [], "text", 3])
def test_from_json_rejects_non_object(raw: object) -> None:
    with pytest.raises(TurnError, match="JSON object"):
        TutorTurn.from_json(raw)


@pytest.mark.parametrize("key", REQUIRED_FIELDS)
def test_from_json_rejects_each_missing_key(key: str) -> None:
    raw = raw_turn()
    del raw[key]
    with pytest.raises(TurnError, match="missing"):
        TutorTurn.from_json(raw)


@pytest.mark.parametrize("message", ["", "   \n", None, 5])
def test_from_json_rejects_bad_message(message: object) -> None:
    with pytest.raises(TurnError, match="non-empty string"):
        TutorTurn.from_json(raw_turn(message=message))


@pytest.mark.parametrize("low", ["no", 0, None])
def test_from_json_rejects_non_bool_low_effort(low: object) -> None:
    with pytest.raises(TurnError, match="low_effort"):
        TutorTurn.from_json(raw_turn(low_effort=low))


@pytest.mark.parametrize(
    "result", ["passed", ["passed"], {"feedback": "x"}, {"passed": "yes"}]
)
def test_from_json_rejects_bad_check_result(result: object) -> None:
    with pytest.raises(TurnError, match=r"check_result\.passed"):
        TutorTurn.from_json(raw_turn(check_result=result))


@pytest.mark.parametrize("questions", ["What is a coil?", None, {"q": "x"}])
def test_from_json_rejects_questions_that_are_not_a_list(questions: object) -> None:
    with pytest.raises(TurnError, match="questions must be a list"):
        TutorTurn.from_json(raw_turn(questions=questions))


def test_schema_requires_questions_as_strings() -> None:
    assert "questions" in REQUIRED_FIELDS
    assert TURN_SCHEMA["required"] == list(REQUIRED_FIELDS)
    properties = TURN_SCHEMA["properties"]
    assert isinstance(properties, dict)
    assert properties["questions"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_turn_defaults_to_no_questions() -> None:
    assert TutorTurn(message="hi", low_effort=False).questions == ()


def test_asked_lists_own_questions_then_the_check() -> None:
    message = {"questions": ["a?", "b?"], "check": {"question": "c?", "concept": "x"}}
    assert asked(message) == ["a?", "b?", "c?"]


def test_asked_reads_old_messages_without_questions() -> None:
    # Logged before `questions` existed: no key; also a null or empty check.
    assert asked({"text": "hi"}) == []
    assert asked({"questions": None, "check": None}) == []
    assert asked({"check": {"question": "", "concept": "x"}}) == []
