# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Around a card: Next card (a new session), Stop here, the manual override."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor.engine import Engine
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from pathlib import Path

CHECK = {"question": "Why?", "concept": "coil"}
FAIL = {"passed": False, "feedback": "not yet"}


def make(tmp_path: Path, fake: FakeSession) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=ManualClock(),
        session_factory=lambda _prompt: fake,
    )


def log_of(engine: Engine, sid: str) -> list[dict[str, Any]]:
    path = engine.store.root / "sessions" / f"{sid}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_next_card_ends_this_session_and_starts_a_new_one(tmp_path: Path) -> None:
    fake = FakeSession(turn(), turn("Second card?"))
    engine = make(tmp_path, fake)
    first, second = engine.deck[0], engine.deck[1]
    asyncio.run(engine.start(first.id))
    old = engine.session_id
    state = asyncio.run(engine.next_card())
    assert state["card"]["id"] == second.id
    assert engine.session_id != old
    assert [m["text"] for m in state["messages"]] == ["Second card?"]
    assert fake.closed == 1  # the ended session's model process is stopped
    ended = log_of(engine, old)
    assert [e["type"] for e in ended] == ["start", "tutor", "next_card", "stop"]
    assert ended[2]["card"] == second.id
    assert [e["type"] for e in log_of(engine, engine.session_id)] == ["start", "tutor"]


def test_next_card_skips_finished_cards_and_the_current_one(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(turn(), turn()))
    asyncio.run(engine.start(engine.deck[0].id))
    engine.store.finish_card(engine.deck[1].id, "earlier")
    state = asyncio.run(engine.next_card())
    assert state["card"]["id"] == engine.deck[2].id


def test_next_card_with_none_left_changes_nothing(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(turn()))
    asyncio.run(engine.start(engine.deck[0].id))
    for card in engine.deck[1:]:
        engine.store.finish_card(card.id, "earlier")
    before = engine.state()
    with pytest.raises(ValueError, match="no unfinished card left"):
        asyncio.run(engine.next_card())
    assert engine.state() == before
    assert [e["type"] for e in log_of(engine, engine.session_id)] == ["start", "tutor"]


def test_next_card_before_any_session(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no session started"):
        asyncio.run(make(tmp_path, FakeSession()).next_card())


def test_stop_ends_the_session_for_good(tmp_path: Path) -> None:
    fake = FakeSession(turn())
    engine = make(tmp_path, fake)
    asyncio.run(engine.start(engine.deck[0].id))
    sid = engine.session_id
    state = asyncio.run(engine.stop())
    assert state["session_id"] == ""
    assert state["card"] is None
    assert state["messages"] == []
    assert fake.closed == 1
    assert log_of(engine, sid)[-1]["type"] == "stop"
    assert make(tmp_path, FakeSession()).resume_latest() is False  # never resumed
    assert asyncio.run(engine.stop())["session_id"] == ""  # nothing live: no-op
    assert fake.closed == 1


def test_manual_done_on_the_live_card_opens_the_choice(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(turn()))
    card = engine.deck[0]
    asyncio.run(engine.start(card.id))
    state = asyncio.run(engine.set_card_done(card.id, done=True))
    assert state["card_done"] is True
    done = engine.store.progress()["cards_done"][card.id]
    assert done["session"] == engine.session_id
    manual = log_of(engine, engine.session_id)[-1]
    assert (manual["type"], manual["card"], manual["done"]) == (
        "card_done_manual",
        card.id,
        True,
    )
    state = asyncio.run(engine.set_card_done(card.id, done=False))
    assert state["card_done"] is False
    assert card.id not in engine.store.progress()["cards_done"]
    assert log_of(engine, engine.session_id)[-1]["done"] is False


def test_manual_done_on_another_card_leaves_the_session_alone(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(turn()))
    asyncio.run(engine.start(engine.deck[0].id))
    other = engine.deck[1].id
    state = asyncio.run(engine.set_card_done(other, done=True))
    assert state["card_done"] is False
    assert engine.store.progress()["cards_done"][other]["session"] == engine.session_id
    assert [e["type"] for e in log_of(engine, engine.session_id)] == ["start", "tutor"]


def test_manual_done_with_no_session_keeps_the_old_session_or_says_manual(
    tmp_path: Path,
) -> None:
    engine = make(tmp_path, FakeSession())
    first, second = engine.deck[0].id, engine.deck[1].id
    asyncio.run(engine.set_card_done(first, done=True))
    assert engine.store.progress()["cards_done"][first]["session"] == "manual"
    engine.store.finish_card(second, "20261010-120000-abcd")
    asyncio.run(engine.set_card_done(second, done=True))
    done = engine.store.progress()["cards_done"][second]
    assert done["session"] == "20261010-120000-abcd"
    asyncio.run(engine.set_card_done(second, done=False))
    assert second not in engine.store.progress()["cards_done"]


def test_manual_done_for_an_unknown_card(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession())
    with pytest.raises(ValueError, match="unknown card 'nope'"):
        asyncio.run(engine.set_card_done("nope", done=True))
    assert engine.store.progress()["cards_done"] == {}


def test_a_third_check_attempt_is_refused_and_the_model_is_told(
    tmp_path: Path,
) -> None:
    fake = FakeSession(
        turn("Explain.", check=CHECK),
        turn("Again.", check_result=FAIL, check=CHECK),
        turn("Last go.", check_result=FAIL, check=CHECK),
        turn("Moving on."),
    )
    engine = make(tmp_path, fake)
    assert asyncio.run(engine.start(engine.deck[0].id))["check_open"] is True
    retry = asyncio.run(engine.reply("a guess"))
    assert retry["messages"][-1]["check"] == CHECK  # attempt 2 is shown
    refused = asyncio.run(engine.reply("another guess"))
    assert refused["messages"][-1]["check"] is None  # a third is not
    assert refused["check_open"] is False
    asyncio.run(engine.reply("fine"))
    assert "NOT opened" in str(fake.prompts[-1])
