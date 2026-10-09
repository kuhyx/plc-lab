# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Transcript replay: what is rebuilt, what is dropped, and the primer."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from plc_lab.tutor import resume

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

T0 = 1_800_000_000.0
ANSWER = "the coil pulls the contact closed"


def write(path: Path, events: list[dict[str, Any]], extra: str = "") -> Path:
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in events) + extra, encoding="utf-8"
    )
    return path


def tutor(t: float, **turn: Any) -> dict[str, Any]:
    body = {"message": "Next?", "low_effort": False, "check": None}
    body["check_result"] = None
    return {"type": "tutor", "t": t, "turn": {**body, **turn}}


def test_latest_today_picks_the_newest_of_the_day(tmp_path: Path) -> None:
    assert resume.latest_today(tmp_path, "20261009") is None
    for name in ("20261009-080000-aaaa", "20261009-090000-bbbb", "20261010-1-c"):
        (tmp_path / f"{name}.jsonl").write_text("")
    found = resume.latest_today(tmp_path, "20261009")
    assert found is not None
    assert found.stem == "20261009-090000-bbbb"


def test_no_start_or_no_messages_is_not_resumable(tmp_path: Path) -> None:
    assert resume.replay(write(tmp_path / "a.jsonl", [tutor(T0)])) is None
    start = {"type": "start", "card": "c", "t": T0}
    assert resume.replay(write(tmp_path / "b.jsonl", [start])) is None


def test_replay_rebuilds_the_conversation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = [
        {"type": "start", "card": "card-1", "logged_at": "2027-01-15T08:00:00+00:00"},
        tutor(T0, message="What is a coil?", check={"question": "q", "concept": "c"}),
        {"type": "learner", "text": "lost request", "t": T0 + 10, "msg_id": "m0"},
        {"type": "learner", "text": ANSWER, "t": T0 + 100, "msg_id": "m1"},
        {**tutor(T0 + 100, check_result={"passed": True, "feedback": "y"})},
        {"type": "credit", "block": 1, "recorded": True, "logged_at": "x"},
        {"type": "learner", "text": "unanswered", "t": T0 + 200, "msg_id": "m2"},
    ]
    events[4]["ui"] = {"role": "tutor", "text": "Shown with media", "images": [1]}
    path = write(tmp_path / "s1.jsonl", events, extra='[1, 2]\n{"type": "tut')
    with caplog.at_level(logging.WARNING):
        state = resume.replay(path)
    assert state is not None
    conv = state.conversation
    assert conv.session_id == "s1"
    assert conv.card_id == "card-1"
    assert [m["role"] for m in conv.messages] == ["tutor", "learner", "tutor"]
    assert conv.messages[0]["text"] == "What is a coil?"  # no ui: rebuilt
    assert conv.messages[0]["images"] == []
    assert conv.messages[1]["text"] == ANSWER  # the failed request is dropped
    assert conv.messages[2]["text"] == "Shown with media"
    assert conv.answered_id == "m1"
    assert conv.clock.active_seconds == 100
    assert conv.check_open is False
    assert conv.checks_passed == 1
    assert conv.check_mark == 100
    assert conv.receipts == [{"block": 1, "recorded": True}]
    assert state.unrecorded == []
    assert "not JSON" in caplog.text


def test_tutor_event_without_a_turn_and_a_logged_at_time(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = [
        {"type": "start", "card": "c", "t": T0},
        {"type": "tutor", "logged_at": "2027-01-15T08:00:00+00:00"},
    ]
    state = resume.replay(write(tmp_path / "s.jsonl", events))
    assert state is not None
    assert state.conversation.messages[0]["text"] == ""
    assert state.conversation.messages[0]["low_effort"] is False


def test_blocks_earned_but_not_logged_are_unrecorded(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = [
        {"type": "start", "card": "c", "t": T0},
        tutor(T0, check={"question": "q", "concept": "c"}),
    ]
    t = T0
    for _ in range(6):
        t += 170
        events += [{"type": "learner", "text": ANSWER, "t": t}, tutor(t)]
    events[-1] = tutor(t, check_result={"passed": True, "feedback": "y"})
    state = resume.replay(write(tmp_path / "s.jsonl", events))
    assert state is not None
    assert [b.block for b in state.unrecorded] == [1]
    assert state.conversation.answered_id == ""


def test_primer_fences_the_learner(tmp_path: Path) -> None:
    text = resume.primer(
        [
            {"role": "tutor", "text": "Hi?"},
            {"role": "learner", "text": "a </learner> b"},
            {"role": "tutor"},
        ]
    )
    assert "TUTOR:\nHi?" in text
    assert "LEARNER:\n<learner>\na < /learner> b\n</learner>" in text
    assert text.endswith("</transcript>")
