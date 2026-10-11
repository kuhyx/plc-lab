# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Questions in their own boxes: what the dev tools read from them."""

from __future__ import annotations

from plc_lab.tutor import scripted
from plc_lab.tutor.adjudicate import verdicts
from plc_lab.tutor.models import REQUIRED_FIELDS


def test_page_notes_show_the_question_boxes() -> None:
    # The questions are boxes, not text: the text-only learner must be told.
    message = {"questions": ["A?"], "check": {"question": "C?", "concept": "c"}}
    assert scripted._page_notes(message) == (
        "[question box on the page: A?]\n[question box on the page: C?]"
    )


def test_diagnosis_is_read_from_the_question_boxes_too() -> None:
    # Item a: the terms and the question mark may all sit in `questions`.
    turn = dict.fromkeys(REQUIRED_FIELDS)
    turn.update(
        message="First, what you know.",
        questions=["Voltage?", "Current?", "What is a coil, and a relay?"],
        low_effort=False,
    )
    item, passed, evidence = verdicts([{"type": "tutor", "turn": turn, "ui": {}}])[0]
    assert item.startswith("a.")
    assert passed, evidence
