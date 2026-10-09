# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The structured turn: every way a model reply can break the schema."""

from __future__ import annotations

from typing import Any

import pytest

from plc_lab.tutor.models import REQUIRED_FIELDS, TurnError, TutorTurn


def raw_turn(**overrides: Any) -> dict[str, Any]:
    """A valid decoded turn; any field can be overridden."""
    raw: dict[str, Any] = {
        "message": "  What is a coil?  ",
        "low_effort": False,
        "check": {"question": "why?", "concept": "coil"},
        "check_result": {"passed": True, "feedback": "yes"},
        "images": ["relay", 7],
        "diagram": {"title": "t", "circuits": []},
        "concepts_mastered": ["coil", 3],
        "card_done": 1,
    }
    raw.update(overrides)
    return raw


def test_from_json_happy_path_strips_and_tuples() -> None:
    parsed = TutorTurn.from_json(raw_turn())
    assert parsed.message == "What is a coil?"
    assert parsed.low_effort is False
    assert parsed.check == {"question": "why?", "concept": "coil"}
    assert parsed.check_result == {"passed": True, "feedback": "yes"}
    assert parsed.images == ("relay", "7")
    assert parsed.diagram == {"title": "t", "circuits": []}
    assert parsed.concepts_mastered == ("coil", "3")
    assert parsed.card_done is True
    assert parsed.extras == {}


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
