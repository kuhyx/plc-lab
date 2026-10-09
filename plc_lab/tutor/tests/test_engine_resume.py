# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""A restart mid-session: resume from the transcript, dedupe, signed credit."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import earned_time

from plc_lab.tutor import credit
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock, turn
from plc_lab.tutor.tests.conftest import KEY

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady

CARD = "io-24vdc-relay-coil"
ANSWER = "the coil becomes a magnet and pulls the contact closed"


def make(tmp_path: Path, fake: FakeSession, clock: ManualClock, **kw: Any) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=clock,
        session_factory=lambda _prompt: fake,
        **kw,
    )


def study_to_a_block(engine: Engine, clock: ManualClock) -> dict[str, Any]:
    """Six 170 s answers with a check posed first and passed last."""
    for _ in range(6):
        clock.advance(170)
        state = asyncio.run(engine.reply(ANSWER, msg_id=f"m{clock.t}"))
    return state


def block_script() -> list[Any]:
    replies: list[Any] = [turn(check={"question": "Why?", "concept": "coil"})]
    replies += [turn() for _ in range(5)]
    replies.append(turn(check_result={"passed": True, "feedback": "yes"}))
    return replies


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


def test_unlogged_block_is_credited_on_resume(tmp_path: Path) -> None:
    calls: list[int] = []

    def refuse(block: BlockReady, sid: str) -> credit.CreditReceipt:
        calls.append(block.block)
        return credit.CreditReceipt(False, 0, f"{sid}-b{block.block}", "disk full")

    clock = ManualClock()
    first = make(tmp_path, FakeSession(*block_script()), clock, credit_fn=refuse)
    asyncio.run(first.start(CARD))
    state = study_to_a_block(first, clock)
    assert calls == [1]
    assert state["credited_minutes"] == 0  # a refused credit counts for nothing
    path = tmp_path / "data/sessions" / f"{first.session_id}.jsonl"
    kept = [line for line in path.read_text().splitlines() if '"credit"' not in line]
    path.write_text("\n".join(kept) + "\n")

    second = make(tmp_path, FakeSession(), clock, credit_fn=refuse)
    assert second.resume_latest() is True
    assert calls == [1, 1]
    assert second.receipts[-1]["error"] == "disk full"


def test_resume_restores_units_from_recorded_receipts(tmp_path: Path) -> None:
    clock = ManualClock()
    first = make(tmp_path, FakeSession(*block_script()), clock)
    asyncio.run(first.start(CARD))
    assert study_to_a_block(first, clock)["credited_minutes"] == 15
    second = make(tmp_path, FakeSession(), clock)
    assert second.resume_latest() is True
    assert second.state()["credited_minutes"] == 15


def test_default_writer_signs_the_row_with_the_key(tmp_path: Path) -> None:
    """The real credit path, sandboxed by conftest: signed, verified, read back."""
    clock = ManualClock()
    engine = make(tmp_path, FakeSession(*block_script()), clock)
    asyncio.run(engine.start(CARD))
    state = study_to_a_block(engine, clock)
    receipt = state["receipts"][0]
    assert receipt["recorded"] is True
    assert receipt["error"] is None
    ledger = credit.default_paths().ledger
    assert ledger.parent == tmp_path / "data"
    (row,) = json.loads(ledger.read_text())["entries"]
    unsigned = {k: v for k, v in row.items() if k != "hmac"}
    assert row["hmac"] == earned_time.entry_signature(unsigned, KEY)
    assert earned_time.verified(row, KEY)
    assert row["entry_id"] == f"{engine.session_id}-b1"
    assert row["created_at"] == clock.t
    assert row["detail"]["checks_passed"] == 1
