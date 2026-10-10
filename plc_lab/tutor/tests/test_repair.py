# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The one-off repair of cards a tutor finished while a gate dropped the result."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plc_lab.tutor import repair
from plc_lab.tutor.store import Store

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

DONE = {"type": "tutor", "turn": {"card_done": True}}


def log(store: Store, sid: str, *events: dict[str, Any]) -> None:
    for event in events:
        store.log(sid, event)


def test_marks_the_cards_a_tutor_finished_with_their_session(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = Store(tmp_path)
    log(store, "s1", {"type": "start", "card": "c1"}, DONE)
    log(store, "s2", {"type": "start", "card": "c2"}, {"type": "tutor", "turn": {}})
    with caplog.at_level("INFO"):
        marked = repair.repair_done_cards(store)
    assert marked == [("c1", "s1")]
    assert store.progress()["cards_done"]["c1"]["session"] == "s1"
    assert "c2" not in store.progress()["cards_done"]
    assert "marked c1 done from session s1" in caplog.text


def test_next_card_moves_the_card_and_done_cards_are_left_alone(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    store.finish_card("c1", "manual")
    log(
        store,
        "s1",
        {"type": "start", "card": "c1"},
        DONE,
        {"type": "next_card", "card": "c2"},
        DONE,
    )
    assert repair.repair_done_cards(store) == [("c2", "s1")]
    assert store.progress()["cards_done"]["c1"]["session"] == "manual"


def test_runs_once_so_a_manual_undo_survives_a_restart(tmp_path: Path) -> None:
    store = Store(tmp_path)
    log(store, "s1", {"type": "start", "card": "c1"}, DONE)
    assert repair.repair_done_cards(store) == [("c1", "s1")]
    store.unfinish_card("c1")  # the learner's override
    assert repair.repair_done_cards(store) == []
    assert "c1" not in store.progress()["cards_done"]
    assert store.repaired(repair.NAME) is True


def test_a_done_turn_before_any_start_has_no_card_to_mark(tmp_path: Path) -> None:
    store = Store(tmp_path)
    log(store, "s1", DONE)
    assert repair.repair_done_cards(store) == []
    assert store.repaired(repair.NAME) is True


def test_unreadable_lines_are_skipped(tmp_path: Path) -> None:
    store = Store(tmp_path)
    log(store, "s1", {"type": "start", "card": "c1"})
    path = tmp_path / "sessions/s1.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "tut\n[1, 2]\n"text"\n')
    log(store, "s1", DONE)
    assert repair.repair_done_cards(store) == [("c1", "s1")]


def test_no_sessions_dir_is_nothing_to_repair(tmp_path: Path) -> None:
    store = Store(tmp_path / "empty")
    assert repair.repair_done_cards(store) == []
    assert store.repaired(repair.NAME) is True
