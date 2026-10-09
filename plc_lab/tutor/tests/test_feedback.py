# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Feedback store: sequential ids, atomic resolve, validation, markdown."""

from __future__ import annotations

import json
from typing import Any

import pytest

from plc_lab.tutor import feedback
from plc_lab.tutor.feedback import MAX_TEXT, record, resolve, to_markdown, validate


def body(**fields: Any) -> dict[str, Any]:
    return {"category": "ui", "text": "button is cut off", **fields}


def test_path_follows_the_data_dir() -> None:
    assert feedback.feedback_path().name == "feedback.jsonl"
    assert feedback.load() == []


def test_record_assigns_sequential_ids_and_persists() -> None:
    first = record({"category": "ui", "text": "a"})
    second = record({"category": "other", "text": "b"})
    assert (first["id"], second["id"]) == (1, 2)
    assert first["status"] == "open"
    assert [e["text"] for e in feedback.load()] == ["a", "b"]


def test_blank_lines_are_skipped_on_load() -> None:
    record({"text": "a"})
    path = feedback.feedback_path()
    path.write_text(path.read_text(encoding="utf-8") + "\n  \n", encoding="utf-8")
    assert len(feedback.load()) == 1


def test_resolve_rewrites_in_place_and_leaves_no_temp() -> None:
    record({"text": "a"})
    record({"text": "b"})
    assert resolve(2) is True
    rows = feedback.load()
    assert [r["status"] for r in rows] == ["open", "resolved"]
    assert "resolved_at" in rows[1]
    assert not feedback.feedback_path().with_suffix(".tmp").exists()
    assert record({"text": "c"})["id"] == 3


def test_resolve_unknown_id_changes_nothing() -> None:
    record({"text": "a"})
    before = feedback.feedback_path().read_text(encoding="utf-8")
    assert resolve(9) is False
    assert feedback.feedback_path().read_text(encoding="utf-8") == before


def test_validate_accepts_a_good_report() -> None:
    assert validate(body(text="  hi  "), 3) == ("ui", "hi", None)
    assert validate(body(message_index=2), 3) == ("ui", "button is cut off", 2)
    assert validate(body(message_index=None), 0)[2] is None


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"category": "nope"}, "unknown category"),
        ({"category": None}, "unknown category"),
        ({"text": ""}, "text is required"),
        ({"text": "   "}, "text is required"),
        ({"text": 5}, "text is required"),
        ({"text": "x" * (MAX_TEXT + 1)}, "the limit is"),
        ({"message_index": True}, "not a message"),
        ({"message_index": "1"}, "not a message"),
        ({"message_index": -1}, "not a message"),
        ({"message_index": 3}, "not a message"),
    ],
)
def test_validate_refuses(fields: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate(body(**fields), 3)


def test_markdown_minimal_entry() -> None:
    md = to_markdown({"id": 4, "category": "weird", "text": ""})
    lines = md.splitlines()
    assert lines[0] == "### Tutor feedback #4 (open): weird"
    assert lines[2] == ">"
    assert "- Session: -" in lines
    assert "- Page: -" in lines
    assert not any(line.startswith("Reported message") for line in lines)


def test_markdown_with_snapshot() -> None:
    entry = {
        "id": 1,
        "status": "resolved",
        "category": "response",
        "text": "line one\n\nline two",
        "created_at": "2026-10-09T12:00:00+00:00",
        "session_id": "s1",
        "card_id": "c1",
        "message_index": 2,
        "page_url": "http://x/",
        "user_agent": "UA",
        "snapshot": {
            "message": {
                "role": "tutor",
                "text": "the answer",
                "images": [{"title": "Coil", "url": "/media/a.png"}],
                "diagrams": ["/media/b.svg"],
            },
            "preceding": [{"index": 1, "role": "learner", "text": "my reply"}],
        },
    }
    md = to_markdown(entry)
    assert "(resolved): Tutor's response" in md
    assert "> line one\n>\n> line two" in md
    assert "- Reported message: #2 (tutor)" in md
    assert "  - image: Coil (/media/a.png)" in md
    assert "  - diagram: /media/b.svg" in md
    assert "Message #1 (learner), trimmed:\n> my reply" in md
    assert md.endswith("Reported message #2:\n> the answer")
    assert json.dumps(entry)  # round-trips as stored
