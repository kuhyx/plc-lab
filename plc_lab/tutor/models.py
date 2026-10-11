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
    "questions",
    "low_effort",
    "check",
    "check_result",
    "images",
    "diagram",
    "concepts_mastered",
    "card_done",
)


MAX_ALTERNATIVES: Final = 3
_IMAGE_REQUEST: Final = {
    "type": "object",
    "properties": {"terms": {"type": "array", "items": _STR}},
    "required": ["terms"],
    "additionalProperties": False,
}
_IMAGES_DOC: Final = (
    "One entry per picture wanted, with NO limit on how many. Each entry is "
    '{"terms": [...]}: 1 to 3 alternative Commons search terms for the SAME '
    "thing, best first (2-3 plain words each); the app uses the first that "
    "finds a picture you then approve. A plain string is one term. In the "
    "picture-check reply instead: the numbers of the pictures to keep, as "
    "strings."
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
        # Each question or task for the learner, one per entry; the page gives
        # every one its own answer box, so none is copied out of `message`.
        "questions": {"type": "array", "items": _STR},
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
        "images": {
            "type": "array",
            "description": _IMAGES_DOC,
            "items": {"anyOf": [_IMAGE_REQUEST, _STR]},
        },
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


def asked(message: dict[str, Any]) -> list[str]:
    """Every question a page message puts to the learner: its own, then the check.

    Messages logged before ``questions`` existed have none of their own.
    """
    found = [str(q) for q in message.get("questions") or []]
    check = message.get("check")
    if isinstance(check, dict) and check.get("question"):
        found.append(str(check["question"]))
    return found


class TurnError(ValueError):
    """The model's reply does not match :data:`TURN_SCHEMA`."""


def image_requests(raw: object) -> tuple[tuple[str, ...], ...]:
    """The pictures a turn asks for, each as its alternative search terms.

    Turns logged before alternatives existed hold plain strings (one term per
    picture); both forms are read. Blank terms and empty requests are dropped
    and a request keeps at most :data:`MAX_ALTERNATIVES` terms.
    """
    found = []
    for item in raw if isinstance(raw, (list, tuple)) else ():
        terms = item.get("terms", []) if isinstance(item, dict) else item
        if not isinstance(terms, (list, tuple)):
            terms = [terms]
        kept = tuple(t for x in terms if (t := str(x).strip()))
        if kept:
            found.append(kept[:MAX_ALTERNATIVES])
    return tuple(found)


@dataclass(frozen=True)
class TutorTurn:
    """One tutor turn, validated."""

    message: str
    low_effort: bool
    questions: tuple[str, ...] = ()
    check: dict[str, str] | None = None
    check_result: dict[str, Any] | None = None
    images: tuple[tuple[str, ...], ...] = ()
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
        if not isinstance(raw["questions"], list):
            msg = "questions must be a list"
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
            questions=tuple(str(q).strip() for q in raw["questions"] if str(q).strip()),
            check=raw["check"],
            check_result=result,
            images=image_requests(raw["images"]),
            diagram=raw["diagram"],
            concepts_mastered=tuple(str(x) for x in raw["concepts_mastered"]),
            card_done=bool(raw["card_done"]),
        )
