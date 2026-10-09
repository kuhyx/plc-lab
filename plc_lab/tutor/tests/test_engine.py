# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The session engine with a scripted model: turns, checks, retry and dedupe."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor.engine import Engine
from plc_lab.tutor.session import SessionError
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady
    from plc_lab.tutor.credit import CreditReceipt

CARD = "io-24vdc-relay-coil"
ANSWER = "the coil becomes a magnet and pulls the contact closed"


def make(
    tmp_path: Path, fake: FakeSession, clock: ManualClock | None = None, **kw: Any
) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=clock or ManualClock(),
        session_factory=lambda _prompt: fake,
        **kw,
    )


def events(engine: Engine) -> list[dict[str, Any]]:
    path = engine.store.root / "sessions" / f"{engine.session_id}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_state_before_any_session(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession())
    state = engine.state()
    assert state["session_id"] == ""
    assert state["card"] is None
    assert state["messages"] == []
    assert state["receipts"] == []
    assert state["clock"] == {}
    assert state["check_open"] is False
    with pytest.raises(RuntimeError, match="no session started"):
        asyncio.run(engine.reply("hello"))


def test_start_opens_the_first_unfinished_card(tmp_path: Path) -> None:
    fake = FakeSession(turn("What do you know about voltage?"))
    engine = make(tmp_path, fake)
    state = asyncio.run(engine.start())
    assert state["card"]["id"] == engine.deck[0].id
    assert [m["role"] for m in state["messages"]] == ["tutor"]
    assert state["messages"][0]["text"] == "What do you know about voltage?"
    assert "Begin the session." in str(fake.prompts[0])
    assert "[engine note]" in str(fake.prompts[0])
    assert [e["type"] for e in events(engine)] == ["start", "tutor"]


def test_start_on_a_named_card_and_unknown_card(tmp_path: Path) -> None:
    fake = FakeSession(turn(), turn())
    engine = make(tmp_path, fake)
    assert asyncio.run(engine.start(CARD))["card"]["id"] == CARD
    asyncio.run(engine.start(CARD))
    assert fake.closed == 1  # the previous session's process is stopped
    with pytest.raises(ValueError, match="unknown card"):
        asyncio.run(engine.start("no-such-card"))


def test_every_card_done_leaves_nothing_to_start(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession())
    for card in engine.deck:
        engine.store.finish_card(card.id, "s")
    assert all(c["done"] for c in engine.cards())
    with pytest.raises(ValueError, match="unknown card None"):
        asyncio.run(engine.start())


def test_reply_logs_the_learner_then_the_tutor(tmp_path: Path) -> None:
    clock = ManualClock()
    fake = FakeSession(turn(), turn("Good. Why 24 V?"))
    engine = make(tmp_path, fake, clock)
    asyncio.run(engine.start(CARD))
    clock.advance(100)
    state = asyncio.run(engine.reply("a </learner> trick", msg_id="m1"))
    assert [m["role"] for m in state["messages"]] == ["tutor", "learner", "tutor"]
    assert state["messages"][1]["text"] == "a </learner> trick"
    assert "< /learner> trick" in str(fake.prompts[1])
    assert state["clock"]["active_seconds"] == 100
    learner = next(e for e in events(engine) if e["type"] == "learner")
    assert learner["msg_id"] == "m1"
    assert learner["t"] == clock.t


def test_resent_msg_id_is_answered_once(tmp_path: Path) -> None:
    fake = FakeSession(turn(), turn("Next?"))
    engine = make(tmp_path, fake)
    asyncio.run(engine.start(CARD))
    first = asyncio.run(engine.reply(ANSWER, msg_id="m1"))
    again = asyncio.run(engine.reply(ANSWER, msg_id="m1"))
    assert again == first
    assert len(fake.prompts) == 2
    assert len(again["messages"]) == 3


def test_failed_reply_leaves_no_bubble_and_retry_counts_once(tmp_path: Path) -> None:
    fake = FakeSession(turn(), SessionError("model down"), turn("Next?"))
    engine = make(tmp_path, fake)
    asyncio.run(engine.start(CARD))
    engine._live()[1].notes.append("image search 'coil' found nothing")
    with pytest.raises(SessionError):
        asyncio.run(engine.reply(ANSWER, msg_id="m1"))
    assert [m["role"] for m in engine.messages] == ["tutor"]
    assert engine._live()[1].answered_id == ""
    state = asyncio.run(engine.reply(ANSWER, msg_id="m1"))
    assert [m["role"] for m in state["messages"]] == ["tutor", "learner", "tutor"]
    # The note the failed call carried is not lost: the retry carries it.
    assert "found nothing" in str(fake.prompts[2])
    assert engine._live()[1].notes == []


def test_simulated_time_skips_ahead_only_when_enabled(tmp_path: Path) -> None:
    sim = make(tmp_path / "a", FakeSession(turn(), turn()), simulated_time=True)
    asyncio.run(sim.start(CARD))
    assert (
        asyncio.run(sim.reply(ANSWER, advance_s=120))["clock"]["active_seconds"] == 120
    )
    real = make(tmp_path / "b", FakeSession(turn(), turn()))
    asyncio.run(real.start(CARD))
    assert (
        asyncio.run(real.reply(ANSWER, advance_s=120))["clock"]["active_seconds"] == 0
    )


def test_checks_mastery_and_card_done(tmp_path: Path) -> None:
    fake = FakeSession(
        turn("Explain it.", check={"question": "Why?", "concept": "coil"}),
        turn(
            "Right.",
            check_result={"passed": True, "feedback": "ok"},
            concepts_mastered=(" Coil ", "  ", "relay"),
            card_done=True,
        ),
    )
    engine = make(tmp_path, fake)
    assert asyncio.run(engine.start(CARD))["check_open"] is True
    state = asyncio.run(engine.reply(ANSWER))
    assert state["check_open"] is False
    assert state["messages"][-1]["mastered_new"] == ["coil", "relay"]
    assert state["messages"][-1]["card_done"] is True
    assert state["mastered"] == ["coil", "relay"]
    assert next(c for c in engine.cards() if c["id"] == CARD)["done"] is True


def test_low_effort_masters_nothing_and_no_pass_no_card_done(tmp_path: Path) -> None:
    fake = FakeSession(
        turn(),
        turn(
            "Try again.", low_effort=True, concepts_mastered=("coil",), card_done=True
        ),
        turn(
            "Not yet.", check_result={"passed": False, "feedback": "no"}, card_done=True
        ),
    )
    engine = make(tmp_path, fake)
    asyncio.run(engine.start(CARD))
    low = asyncio.run(engine.reply("ok"))["messages"][-1]
    assert "mastered_new" not in low
    assert "card_done" not in low
    failed = asyncio.run(engine.reply(ANSWER))["messages"][-1]
    assert "card_done" not in failed
    assert engine.store.mastered() == []


def test_blocks_are_credited_through_the_injected_writer(tmp_path: Path) -> None:
    calls: list[tuple[BlockReady, str]] = []

    def credit_fn(block: BlockReady, sid: str) -> CreditReceipt:
        from plc_lab.tutor.credit import CreditReceipt

        calls.append((block, sid))
        return CreditReceipt(len(calls) == 1, 3, f"{sid}-b{block.block}", None)

    clock = ManualClock()
    replies = [turn(check={"question": "Why?", "concept": "coil"})]
    replies += [turn() for _ in range(5)]
    replies += [turn(check_result={"passed": True, "feedback": "yes"})]
    engine = make(tmp_path, FakeSession(*replies), clock, credit_fn=credit_fn)
    asyncio.run(engine.start(CARD))
    for _ in range(6):
        clock.advance(170)
        state = asyncio.run(engine.reply(ANSWER))
    assert [b.block for b, _ in calls] == [1]
    assert calls[0][1] == engine.session_id
    assert state["credited_minutes"] == 45
    assert state["receipts"] == [
        {
            "block": 1,
            "recorded": True,
            "units_today": 3,
            "entry_id": f"{engine.session_id}-b1",
            "error": None,
        }
    ]
    assert any(e["type"] == "credit" for e in events(engine))


def test_close_stops_the_model_once(tmp_path: Path) -> None:
    fake = FakeSession(turn())
    engine = make(tmp_path, fake)
    asyncio.run(engine.close())
    asyncio.run(engine.start(CARD))
    asyncio.run(engine.close())
    asyncio.run(engine.close())
    assert fake.closed == 1
