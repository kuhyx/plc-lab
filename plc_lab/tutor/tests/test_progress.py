# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Deck progress and progress over time (``progress`` and ``/api/progress``)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from plc_lab.cards import load_deck
from plc_lab.tutor import progress
from plc_lab.tutor.engine import DECK_DIR, Engine
from plc_lab.tutor.ledger_io import Paths
from plc_lab.tutor.server import create_app
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests import _credit_support as cs
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock

if TYPE_CHECKING:
    from pathlib import Path


def paths(tmp_path: Path, key: bytes | None = cs.KEY) -> Paths:
    key_file = tmp_path / "key"
    if key is not None:
        key_file.write_bytes(key)
    return Paths(data_dir=tmp_path / "data", key_file=key_file)


def test_deck_summary_counts_done_pending_and_topics() -> None:
    deck = load_deck(DECK_DIR)
    first = deck[0].topic.title
    done = {c.id for c in deck if c.topic.title == first}
    done.add("not-a-card")
    summary = progress.deck_summary(deck, done)
    assert summary["total"] == len(deck)
    assert summary["done"] == len(done) - 1
    assert summary["pending"] == len(deck) - summary["done"]
    assert summary["percent"] == round(100 * summary["done"] / len(deck))
    assert summary["topics"][0] == {
        "title": first,
        "done": len(done) - 1,
        "total": len(done) - 1,
    }
    assert all(t["done"] == 0 for t in summary["topics"][1:])


def test_deck_summary_of_an_empty_deck() -> None:
    assert progress.deck_summary([], set())["percent"] == 0


def test_minutes_by_day_sums_verified_rows_capped(tmp_path: Path) -> None:
    where = paths(tmp_path)
    forged = {**cs.paid("x-m3", 5), "hmac": "0" * 64}
    cs.put(where, [cs.paid("a-m40", 40), cs.paid("b-m30", 30), forged])
    assert progress.ledger_minutes_by_day(where) == {"2026-10-09": 60}


def test_minutes_by_day_without_key_or_ledger(tmp_path: Path) -> None:
    assert progress.ledger_minutes_by_day(paths(tmp_path, key=None)) == {}
    where = paths(tmp_path)
    where.data_dir.mkdir()
    where.ledger.write_text("not json", encoding="utf-8")
    assert progress.ledger_minutes_by_day(where) == {}


def test_timeline_fills_every_day_to_today() -> None:
    done = {
        "a": {"at": "2026-10-09T10:00:00+00:00"},
        "b": {"at": "2026-10-11T10:00:00+00:00"},
        "c": {},  # no date: counted nowhere
    }
    rows = progress.timeline(done, {"2026-10-10": 25}, "2026-10-12")
    assert [r["day"] for r in rows] == [
        "2026-10-09",
        "2026-10-10",
        "2026-10-11",
        "2026-10-12",
    ]
    assert [r["cards_done"] for r in rows] == [1, 0, 1, 0]
    assert [r["cards_done_total"] for r in rows] == [1, 1, 2, 2]
    assert [r["minutes"] for r in rows] == [0, 25, 0, 0]


def test_timeline_with_nothing_yet_is_just_today() -> None:
    assert progress.timeline({}, {}, "2026-10-12") == [
        {"day": "2026-10-12", "cards_done": 0, "cards_done_total": 0, "minutes": 0}
    ]


def test_api_progress_reports_the_deck_and_days(tmp_path: Path) -> None:
    clock = ManualClock(time.time())  # finish_card stamps the wall clock
    engine = Engine(
        store=Store(tmp_path / "data"),
        now=clock,
        session_factory=lambda _prompt: FakeSession(),
    )
    card = engine.deck[0].id
    engine.store.finish_card(card, "s")
    engine.store.finish_card("gone-from-the-deck", "s")
    with TestClient(create_app(engine)) as client:
        body = client.get("/api/progress").json()
    assert body["done"] == 1
    assert body["pending"] == len(engine.deck) - 1
    assert body["days"][-1]["day"] == time.strftime("%Y-%m-%d")
    assert body["days"][-1]["cards_done_total"] == 1
