# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The snapshot of a reported message and the context before it."""

from __future__ import annotations

from typing import Any

from plc_lab.tutor.feedback_snapshot import snapshot


def msgs(*texts: str) -> list[dict[str, Any]]:
    return [{"role": "tutor", "text": t} for t in texts]


def test_plain_message_has_only_the_basics() -> None:
    shot = snapshot([{"role": "learner"}], 0)
    assert shot == {
        "message": {"role": "learner", "text": "", "images": [], "diagrams": []},
        "preceding": [],
    }


def test_media_and_optional_fields_are_carried() -> None:
    message = {
        "role": "tutor",
        "text": "look",
        "images": [{"title": "Coil", "file": "ab.png", "page_url": "http://p"}],
        "diagrams": ["d.svg"],
        "diagram_title": "Ladder",
        "check": {"q": 1},
        "check_result": {"passed": True},
        "low_effort": True,
    }
    shot = snapshot([message], 0)["message"]
    assert shot["images"] == [
        {"title": "Coil", "url": "/media/ab.png", "page_url": "http://p"}
    ]
    assert shot["diagrams"] == ["/media/d.svg"]
    assert shot["diagram_title"] == "Ladder"
    assert shot["check"] == {"q": 1}
    assert shot["check_result"] == {"passed": True}
    assert shot["low_effort"] is True


def test_none_media_lists_are_tolerated() -> None:
    shot = snapshot([{"role": "tutor", "images": None, "diagrams": None}], 0)
    assert shot["message"]["images"] == []
    assert shot["message"]["diagrams"] == []


def test_preceding_is_the_two_messages_before_trimmed() -> None:
    long = "x" * 500
    shot = snapshot(msgs("zero", long, "  two  ", "three"), 3)
    assert [p["index"] for p in shot["preceding"]] == [1, 2]
    assert shot["preceding"][0]["text"] == "x" * 399 + "…"
    assert shot["preceding"][1]["text"] == "two"


def test_exactly_the_limit_is_not_trimmed() -> None:
    text = "y" * 400
    assert snapshot(msgs(text, "now"), 1)["preceding"][0]["text"] == text


def test_index_zero_has_no_preceding() -> None:
    assert snapshot(msgs("a", "b"), 0)["preceding"] == []
    assert snapshot(msgs("a", "b"), 1)["preceding"][0]["index"] == 0
