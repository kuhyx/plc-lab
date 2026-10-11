# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Gating: a card whose required cards are not all done is locked."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor import gating, resume
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from pathlib import Path

GATED = "fund-five-languages"


def make(tmp_path: Path, fake: FakeSession) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=ManualClock(),
        session_factory=lambda _prompt: fake,
    )


def needs(engine: Engine) -> list[str]:
    return list(next(c for c in engine.deck if c.id == GATED).requires)


def finish(engine: Engine, ids: list[str]) -> None:
    for card_id in ids:
        engine.store.finish_card(card_id, "earlier")


def events(engine: Engine, sid: str) -> list[dict[str, Any]]:
    path = engine.store.root / "sessions" / f"{sid}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_missing_and_first_open(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession())
    gated = next(c for c in engine.deck if c.id == GATED)
    assert gating.missing(gated, set()) == needs(engine)
    assert gating.missing(gated, set(needs(engine))) == []
    done = {c.id for c in engine.deck if c.id != GATED}
    assert gating.first_open(engine.deck, done) is gated
    assert gating.first_open(engine.deck, done, skip=GATED) is None
    reopened = gating.first_open(engine.deck, done - {needs(engine)[0]})
    assert reopened is not None
    assert reopened.id == needs(engine)[0]


def test_cards_lists_requires_missing_and_locked(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession())
    finish(engine, needs(engine)[:3])
    rows = {r["id"]: r for r in engine.cards()}
    assert rows[GATED]["requires"] == needs(engine)
    assert rows[GATED]["missing"] == needs(engine)[3:]
    assert rows[GATED]["locked"] is True
    row = rows[needs(engine)[0]]
    assert (row["done"], row["locked"], row["missing"]) == (True, False, [])


def test_starting_a_locked_card_is_refused_and_keeps_the_live_session(
    tmp_path: Path,
) -> None:
    fake = FakeSession(turn("Hello"))
    engine = make(tmp_path, fake)
    asyncio.run(engine.start(engine.deck[0].id))
    live = engine.session_id
    with pytest.raises(ValueError, match=f"cannot start '{GATED}': locked until"):
        asyncio.run(engine.start(GATED))
    assert engine.session_id == live
    assert fake.closed == 0


def test_auto_start_skips_a_locked_card(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(turn()))
    finish(engine, [c.id for c in engine.deck if c.topic.stem == "fundamentals"][:-1])
    engine.store.unfinish_card(GATED)
    state = asyncio.run(engine.start())
    assert state["card"]["id"] != GATED
    first_open = gating.first_open(engine.deck, engine.store.progress()["cards_done"])
    assert first_open is not None
    assert state["card"]["id"] == first_open.id


def test_a_locked_card_opens_once_its_requires_are_done(tmp_path: Path) -> None:
    engine = make(tmp_path, FakeSession(turn()))
    finish(engine, needs(engine))
    assert asyncio.run(engine.start(GATED))["card"]["id"] == GATED


def test_marking_a_locked_card_done_is_refused_but_not_done_is_allowed(
    tmp_path: Path,
) -> None:
    engine = make(tmp_path, FakeSession())
    with pytest.raises(ValueError, match=f"cannot mark done '{GATED}'"):
        asyncio.run(engine.set_card_done(GATED, done=True))
    assert GATED not in engine.store.progress()["cards_done"]
    asyncio.run(engine.set_card_done(GATED, done=False))
    assert GATED not in engine.store.progress()["cards_done"]


def session_on_a_card_that_became_locked(
    tmp_path: Path, fake: FakeSession | None = None
) -> Engine:
    """A session started on GATED while open; one required card is then undone."""
    first = make(tmp_path, FakeSession(turn("Name them?")))
    finish(first, needs(first))
    asyncio.run(first.start(GATED))
    first.store.unfinish_card(needs(first)[-1])
    engine = make(tmp_path, fake or FakeSession())
    assert engine.resume_latest() is True
    return engine


def test_resuming_a_now_locked_card_keeps_the_conversation(tmp_path: Path) -> None:
    engine = session_on_a_card_that_became_locked(tmp_path)
    state = engine.state()
    assert state["card"]["id"] == GATED
    assert [m["text"] for m in state["messages"]] == ["Name them?"]


def test_the_tutors_card_done_on_a_locked_card_is_refused(tmp_path: Path) -> None:
    fake = FakeSession(turn("Done!", card_done=True), turn("Go on"))
    engine = session_on_a_card_that_became_locked(tmp_path, fake)
    sid = engine.session_id
    state = asyncio.run(engine.reply("LD FBD ST SFC IL", msg_id="m1"))
    assert state["card_done"] is False
    assert "card_done" not in state["messages"][-1]
    assert GATED not in engine.store.progress()["cards_done"]
    logged = events(engine, sid)[-1]["turn"]
    assert logged["card_done"] is False
    assert logged["card_done_refused"] == [needs(engine)[-1]]
    asyncio.run(engine.reply("ok", msg_id="m2"))  # the note reaches the model
    assert "card_done refused" in str(fake.prompts[-1])
    replayed = resume.replay(engine.store.root / "sessions" / f"{sid}.jsonl")
    assert replayed is not None
    assert replayed.conversation.card_done is False


def test_next_card_from_a_locked_card_steers_to_the_first_open_one(
    tmp_path: Path,
) -> None:
    engine = session_on_a_card_that_became_locked(tmp_path, FakeSession(turn("New")))
    state = asyncio.run(engine.next_card())
    assert state["card"]["id"] == engine.deck[0].id
    assert engine.deck[0].id != GATED
