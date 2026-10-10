# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The CLI dies mid-session: the fresh process is re-fed the conversation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor.engine import Engine
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import CliDiedError, FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.models import TutorTurn

CARD = "io-24vdc-relay-coil"
PRIMER = "[app] The tutor app restarted"


def make(tmp_path: Path, *replies: TutorTurn | Exception) -> tuple[Engine, FakeSession]:
    fake = FakeSession(*replies)
    engine = Engine(
        store=Store(tmp_path / "data"),
        now=ManualClock(),
        session_factory=lambda _prompt: fake,
    )
    return engine, fake


def say(engine: Engine, text: str, msg_id: str) -> dict[str, Any]:
    return asyncio.run(engine.reply(text, msg_id=msg_id))


def crash(engine: Engine, text: str, msg_id: str) -> None:
    with pytest.raises(CliDiedError):
        say(engine, text, msg_id)


def primers(prompt: object) -> int:
    return str(prompt).count(PRIMER)


def test_no_crash_no_primer(tmp_path: Path) -> None:
    engine, fake = make(tmp_path, turn(), turn("Why 24 V?"), turn("Good."))
    asyncio.run(engine.start(CARD))
    say(engine, "a magnet", "m1")
    say(engine, "safe to touch", "m2")
    assert [primers(p) for p in fake.prompts] == [0, 0, 0]


def test_crash_mid_card_primes_the_retry_once(tmp_path: Path) -> None:
    engine, fake = make(
        tmp_path,
        turn(),
        turn("Why 24 V?"),
        CliDiedError("cli died"),
        turn("Right."),
        turn(),
    )
    asyncio.run(engine.start(CARD))
    say(engine, "a magnet", "m1")
    before = engine.state()["clock"]
    crash(engine, "safe to touch", "m2")
    assert engine.state()["clock"] == before  # the failed turn moved nothing
    say(engine, "safe to touch", "m2")
    say(engine, "next", "m3")
    retry, after = fake.prompts[3], fake.prompts[4]
    assert primers(retry) == 1
    assert "TUTOR:\nWhy 24 V?" in str(retry)
    assert str(retry).count("a magnet") == 1
    assert str(retry).count("safe to touch") == 1  # in the body, not the transcript
    assert primers(after) == 0
    learner = [m["text"] for m in engine.messages if m["role"] == "learner"]
    assert learner == ["a magnet", "safe to touch", "next"]


def test_every_crash_gets_its_own_primer(tmp_path: Path) -> None:
    engine, fake = make(
        tmp_path,
        turn(),
        CliDiedError("first death"),
        turn("Back."),
        turn("Fine."),
        CliDiedError("second death"),
        CliDiedError("dies again on the primed retry"),
        turn("Back again."),
        turn(),
    )
    asyncio.run(engine.start(CARD))
    crash(engine, "one", "m1")
    say(engine, "one", "m1")
    say(engine, "two", "m2")
    crash(engine, "three", "m3")
    crash(engine, "three", "m3")
    say(engine, "three", "m3")
    say(engine, "four", "m4")
    assert [primers(p) for p in fake.prompts] == [0, 0, 1, 0, 0, 1, 1, 0]
    assert "TUTOR:\nFine." in str(fake.prompts[6])
    learner = [m["text"] for m in engine.messages if m["role"] == "learner"]
    assert learner == ["one", "two", "three", "four"]


def test_a_crash_before_any_message_has_nothing_to_replay(tmp_path: Path) -> None:
    engine, fake = make(tmp_path, CliDiedError("dead on start"), turn(), turn())
    with pytest.raises(CliDiedError):
        asyncio.run(engine.start(CARD))
    say(engine, "hello?", "m1")
    say(engine, "still here", "m2")
    assert [primers(p) for p in fake.prompts] == [0, 0, 0]
