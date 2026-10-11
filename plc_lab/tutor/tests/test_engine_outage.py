# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Engine-level outage excuses: restarts and retried sends (kuhy, 2026-10-11)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from plc_lab.tutor.clock import GENERATION_CAP, REPLY_TIMEOUT, SEND_GRACE
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeCredit, FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from pathlib import Path

CARD = "io-24vdc-relay-coil"
ANSWER = "the coil becomes a magnet and pulls the contact closed"


def make(tmp_path: Path, fake: FakeSession, clock: ManualClock) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=clock,
        credit_fn=FakeCredit(),
        session_factory=lambda _prompt: fake,
    )


def test_a_retried_send_is_timed_from_the_first_press(tmp_path: Path) -> None:
    clock = ManualClock()
    engine = make(tmp_path, FakeSession(turn(), turn()), clock)
    asyncio.run(engine.start(CARD))
    pressed = clock.t + REPLY_TIMEOUT - 30
    clock.advance(REPLY_TIMEOUT - 30 + SEND_GRACE)  # arrives 5 min after the press
    state = asyncio.run(engine.reply(ANSWER, msg_id="m1", sent_at=pressed))
    # The press-to-tutor wait then counts as generation, capped as ever.
    assert state["clock"]["active_seconds"] == REPLY_TIMEOUT - 30 + GENERATION_CAP


def test_a_restart_mid_answer_excuses_the_window(tmp_path: Path) -> None:
    """The 2026-10-11 session: a deploy mid-answer, the reply past the window."""
    clock = ManualClock()
    first = make(tmp_path, FakeSession(turn()), clock)
    asyncio.run(first.start(CARD))
    clock.advance(REPLY_TIMEOUT - 60)
    second = make(tmp_path, FakeSession(turn()), clock)
    assert second.resume_latest() is True
    clock.advance(300)  # past the 10 min since the tutor spoke
    assert second.state()["clock"]["paused"] is False
    state = asyncio.run(second.reply(ANSWER, msg_id="m1"))
    assert state["clock"]["active_seconds"] == REPLY_TIMEOUT - 60 + 300
    third = make(tmp_path, FakeSession(), clock)  # the replay agrees
    assert third.resume_latest() is True
    assert third.state()["clock"]["active_seconds"] == REPLY_TIMEOUT - 60 + 300


def test_resume_keeps_a_larger_total_backfill_paid(tmp_path: Path) -> None:
    """2026-10-11: backfill paid 6 more minutes, resume then showed only 3."""
    clock = ManualClock()
    engine = make(tmp_path, FakeSession(turn()), clock)
    asyncio.run(engine.start(CARD))
    engine._set_today(9)  # what backfill_today leaves behind
    assert engine.resume_latest() is True
    assert engine.minutes_today == 9
