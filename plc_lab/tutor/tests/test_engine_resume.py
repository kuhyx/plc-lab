# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""A restart mid-session: resume from the transcript, dedupe, signed credit."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import earned_time

from plc_lab.tutor.engine import Engine
from plc_lab.tutor.ledger_io import default_paths
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeCredit, FakeSession, ManualClock, turn
from plc_lab.tutor.tests.conftest import KEY

if TYPE_CHECKING:
    from pathlib import Path

CARD = "io-24vdc-relay-coil"
ANSWER = "the coil becomes a magnet and pulls the contact closed"


def make(tmp_path: Path, fake: FakeSession, clock: ManualClock, **kw: Any) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=clock,
        session_factory=lambda _prompt: fake,
        **kw,
    )


def study_to_17_minutes(engine: Engine, clock: ManualClock) -> dict[str, Any]:
    """Six 170 s answers: 1020 active seconds, 17 minutes."""
    for _ in range(6):
        clock.advance(170)
        state = asyncio.run(engine.reply(ANSWER, msg_id=f"m{clock.t}"))
    return state


def script() -> list[Any]:
    """The start turn poses a check; the first answer passes it."""
    replies: list[Any] = [turn(check={"question": "Why?", "concept": "coil"})]
    replies.append(turn(check_result={"passed": True, "feedback": "yes"}))
    return replies + [turn() for _ in range(5)]


def test_nothing_to_resume(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(), ManualClock())
    assert engine.resume_latest() is False


def test_restart_resumes_messages_clock_and_dedupe(tmp_path: Path) -> None:
    clock = ManualClock()
    first = make(tmp_path, FakeSession(turn(), turn("Why 24 V?")), clock)
    asyncio.run(first.start(CARD))
    clock.advance(90)
    before = asyncio.run(first.reply(ANSWER, msg_id="m1"))

    fake = FakeSession(turn("Carry on: why 24 V?"))
    second = make(tmp_path, fake, clock)
    assert second.resume_latest() is True
    after = second.state()
    assert after["session_id"] == before["session_id"]
    assert after["messages"] == before["messages"]
    assert after["clock"]["active_seconds"] == before["clock"]["active_seconds"]
    assert after["card"] == before["card"]
    # The page retries the answered message through the restart: not re-asked.
    assert asyncio.run(second.reply(ANSWER, msg_id="m1")) == after
    assert fake.prompts == []
    asyncio.run(second.reply("because it is safe to touch", msg_id="m2"))
    assert "[app] The tutor app restarted" in str(fake.prompts[0])
    assert "TUTOR:\nWhy 24 V?" in str(fake.prompts[0])
    log = (tmp_path / "data/sessions" / f"{second.session_id}.jsonl").read_text()
    assert '"type": "resume"' in log


def test_resume_skips_a_card_no_longer_in_the_deck(tmp_path: Path) -> None:
    clock = ManualClock()
    first = make(tmp_path, FakeSession(turn()), clock)
    asyncio.run(first.start(CARD))
    path = tmp_path / "data/sessions" / f"{first.session_id}.jsonl"
    path.write_text(path.read_text().replace(CARD, "retired-card"))
    assert make(tmp_path, FakeSession(), clock).resume_latest() is False


def test_unlogged_minutes_are_credited_on_resume(tmp_path: Path) -> None:
    clock = ManualClock()
    first = make(
        tmp_path, FakeSession(*script()), clock, credit_fn=FakeCredit(error="disk full")
    )
    asyncio.run(first.start(CARD))
    state = study_to_17_minutes(first, clock)
    assert state["credited_minutes"] == 0  # a refused credit counts for nothing
    path = tmp_path / "data/sessions" / f"{first.session_id}.jsonl"
    kept = [line for line in path.read_text().splitlines() if '"credit"' not in line]
    path.write_text("\n".join(kept) + "\n")

    retry = FakeCredit(error="disk full")
    second = make(tmp_path, FakeSession(), clock, credit_fn=retry)
    assert second.resume_latest() is True
    assert retry.blocks == [list(range(1, 18))]  # the whole session, one row
    assert second.receipts[-1]["error"] == "disk full"
    assert '"type": "credit"' in path.read_text()


def test_resume_restores_the_minutes_the_ledger_pays(tmp_path: Path) -> None:
    clock = ManualClock()
    first = make(tmp_path, FakeSession(*script()), clock)
    asyncio.run(first.start(CARD))
    assert study_to_17_minutes(first, clock)["credited_minutes"] == 17
    ledger = default_paths().ledger
    before = json.loads(ledger.read_text())["entries"]
    second = make(tmp_path, FakeSession(), clock)
    assert second.resume_latest() is True
    state = second.state()
    assert state["credited_minutes"] == 17
    assert state["session_credited_minutes"] == 17
    assert len(state["receipts"]) == 6  # nothing re-credited: the ledger had it
    assert json.loads(ledger.read_text())["entries"] == before


def test_default_writer_signs_a_row_per_turn_with_the_key(tmp_path: Path) -> None:
    """The real credit path, sandboxed by conftest: signed, verified, read back."""
    clock = ManualClock()
    engine = make(tmp_path, FakeSession(*script()), clock)
    asyncio.run(engine.start(CARD))
    state = study_to_17_minutes(engine, clock)
    assert [r["recorded"] for r in state["receipts"]] == [True] * 6
    assert {r["error"] for r in state["receipts"]} == {None}
    ledger = default_paths().ledger
    assert ledger.parent == tmp_path / "data"
    rows = json.loads(ledger.read_text())["entries"]
    for row in rows:
        unsigned = {k: v for k, v in row.items() if k != "hmac"}
        assert row["hmac"] == earned_time.entry_signature(unsigned, KEY)
        assert earned_time.verified(row, KEY)
    sid = engine.session_id
    assert [r["entry_id"] for r in rows] == [
        f"{sid}-m{n}" for n in (2, 5, 8, 11, 14, 17)
    ]
    assert sum(r["detail"]["minutes"] for r in rows) == 17
    assert rows[-1]["created_at"] == clock.t
    assert [r["detail"]["checks_passed"] for r in (rows[0], rows[-1])] == [0, 1]


def test_repair_marks_the_cards_a_tutor_finished(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(), ManualClock())
    engine.store.log("sess", {"type": "start", "card": CARD})
    engine.store.log("sess", {"type": "tutor", "turn": {"card_done": True}})
    assert engine.repair_done_cards() == [(CARD, "sess")]
    assert next(c for c in engine.cards() if c["id"] == CARD)["done"] is True
    assert engine.repair_done_cards() == []  # once per data dir


def test_backfill_credits_what_todays_transcripts_earned(tmp_path: Path) -> None:
    clock = ManualClock()
    first = make(
        tmp_path, FakeSession(*script()), clock, credit_fn=FakeCredit(error="down")
    )
    asyncio.run(first.start(CARD))
    study_to_17_minutes(first, clock)
    paid = FakeCredit()
    second = make(tmp_path, FakeSession(), clock, credit_fn=paid)
    second.backfill_today()
    assert paid.blocks == [list(range(1, 18))]
    assert paid.sessions == [first.session_id]
    assert second.minutes_today == 17
    path = tmp_path / "data/sessions" / f"{first.session_id}.jsonl"
    assert path.read_text().count('"recorded": true') == 1
    make(tmp_path / "empty", FakeSession(), clock, credit_fn=paid).backfill_today()
    assert len(paid.calls) == 1
