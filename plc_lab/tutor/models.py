# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The tutor's structured turn: prose plus the machine-readable fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

ELEMENT_KINDS: Final = (
    "dc_source",
    "ac_source",
    "switch",
    "push_button",
    "resistor",
    "lamp",
    "led",
    "coil",
    "relay_contact",
    "capacitor",
    "diode",
    "fuse",
    "motor",
)
_STR: Final = {"type": "string"}
# Every field a turn must carry, typed so callers can iterate it (the schema's
# own "required" list is inferred as ``object`` inside the nested dict).
REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "message",
    "low_effort",
    "check",
    "check_result",
    "images",
    "diagram",
    "concepts_mastered",
    "card_done",
)


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_ELEMENT: Final = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(ELEMENT_KINDS)},
        "label": _STR,
    },
    "required": ["kind", "label"],
    "additionalProperties": False,
}
_CIRCUIT: Final = {
    "type": "object",
    "properties": {
        "name": _STR,
        "source": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["dc_source", "ac_source"]},
                "label": _STR,
            },
            "required": ["kind", "label"],
            "additionalProperties": False,
        },
        "elements": {"type": "array", "items": _ELEMENT},
    },
    "required": ["name", "source", "elements"],
    "additionalProperties": False,
}
TURN_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "message": _STR,
        "low_effort": {"type": "boolean"},
        "check": _nullable(
            {
                "type": "object",
                "properties": {"question": _STR, "concept": _STR},
                "required": ["question", "concept"],
                "additionalProperties": False,
            }
        ),
        "check_result": _nullable(
            {
                "type": "object",
                "properties": {"passed": {"type": "boolean"}, "feedback": _STR},
                "required": ["passed", "feedback"],
                "additionalProperties": False,
            }
        ),
        "images": {"type": "array", "items": _STR},
        "diagram": _nullable(
            {
                "type": "object",
                "properties": {
                    "title": _STR,
                    "circuits": {"type": "array", "items": _CIRCUIT},
                },
                "required": ["title", "circuits"],
                "additionalProperties": False,
            }
        ),
        "concepts_mastered": {"type": "array", "items": _STR},
        "card_done": {"type": "boolean"},
    },
    "required": list(REQUIRED_FIELDS),
    "additionalProperties": False,
}


class TurnError(ValueError):
    """The model's reply does not match :data:`TURN_SCHEMA`."""


@dataclass(frozen=True)
class TutorTurn:
    """One tutor turn, validated."""

    message: str
    low_effort: bool
    check: dict[str, str] | None = None
    check_result: dict[str, Any] | None = None
    images: tuple[str, ...] = ()
    diagram: dict[str, Any] | None = None
    concepts_mastered: tuple[str, ...] = ()
    card_done: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw: object) -> TutorTurn:
        """Validate a decoded JSON object, or raise :class:`TurnError`."""
        if not isinstance(raw, dict):
            msg = "turn must be a JSON object"
            raise TurnError(msg)
        missing = [key for key in REQUIRED_FIELDS if key not in raw]
        if missing:
            msg = f"turn is missing {missing}"
            raise TurnError(msg)
        if not isinstance(raw["message"], str) or not raw["message"].strip():
            msg = "message must be a non-empty string"
            raise TurnError(msg)
        if not isinstance(raw["low_effort"], bool):
            msg = "low_effort must be a boolean"
            raise TurnError(msg)
        result = raw["check_result"]
        if result is not None and not (
            isinstance(result, dict) and isinstance(result.get("passed"), bool)
        ):
            msg = "check_result.passed must be a boolean"
            raise TurnError(msg)
        return cls(
            message=raw["message"].strip(),
            low_effort=raw["low_effort"],
            check=raw["check"],
            check_result=result,
            images=tuple(str(x) for x in raw["images"]),
            diagram=raw["diagram"],
            concepts_mastered=tuple(str(x) for x in raw["concepts_mastered"]),
            card_done=bool(raw["card_done"]),
        )
