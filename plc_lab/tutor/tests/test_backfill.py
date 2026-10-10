# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Backfill: replay today's transcripts and credit the minutes nobody paid."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from plc_lab.tutor import backfill, credit, unit_credit

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady

T0 = 1_800_000_000.0
ANSWER = "the coil pulls the contact closed"
DAY = "20270115"


def write(path: Path, events: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def session(path: Path, minutes: int) -> Path:
    """A transcript whose one 'ok' exchange of ``minutes`` minutes earns that many."""
    tutor = {"message": "Next?", "low_effort": False, "check": None}
    return write(
        path,
        [
            {"type": "start", "card": "c1", "t": T0},
            {"type": "tutor", "t": T0, "turn": tutor},
            {"type": "learner", "t": T0 + 60 * minutes, "text": ANSWER, "msg_id": "1"},
            {"type": "tutor", "t": T0 + 60 * minutes, "turn": tutor},
        ],
    )


def receipt(
    entry: str, *, recorded: bool, today: int, error: str | None
) -> dict[str, Any]:
    return {
        "block": 1,
        "span": 1,
        "recorded": recorded,
        "minutes": int(recorded),
        "minutes_today": today,
        "entry_id": entry,
        "error": error,
    }


class Spy:
    """A credit function and a log that record how backfill used them."""

    def __init__(self, *rows: dict[str, Any]) -> None:
        self.rows = list(rows)
        self.credited: list[tuple[list[int], str]] = []
        self.logged: list[tuple[str, dict[str, Any]]] = []

    def credit(self, units: list[BlockReady], sid: str) -> list[dict[str, Any]]:
        self.credited.append(([u.block for u in units], sid))
        return [self.rows.pop(0)] if self.rows else []

    def log(self, sid: str, event: dict[str, Any]) -> None:
        self.logged.append((sid, event))


def test_no_transcripts_means_nothing_to_do(tmp_path: Path) -> None:
    spy = Spy()
    assert backfill.backfill_day(tmp_path, DAY, spy.credit, spy.log) == 0
    assert spy.credited == []


def test_other_days_and_unresumable_files_are_skipped(tmp_path: Path) -> None:
    session(tmp_path / "20270114-090000-aaaa.jsonl", 3)
    write(tmp_path / f"{DAY}-080000-bbbb.jsonl", [{"type": "learner", "t": T0}])
    spy = Spy()
    assert backfill.backfill_day(tmp_path, DAY, spy.credit, spy.log) == 0
    assert spy.credited == []


def test_a_session_with_no_earned_minute_is_not_credited(tmp_path: Path) -> None:
    session(tmp_path / f"{DAY}-080000-aaaa.jsonl", 0)
    spy = Spy()
    assert backfill.backfill_day(tmp_path, DAY, spy.credit, spy.log) == 0
    assert spy.credited == []


def test_credits_oldest_first_logs_rows_and_returns_the_newest_total(
    tmp_path: Path,
) -> None:
    session(tmp_path / f"{DAY}-100000-bbbb.jsonl", 1)
    session(tmp_path / f"{DAY}-090000-aaaa.jsonl", 2)
    spy = Spy(
        receipt("a-m2", recorded=True, today=2, error=None),
        receipt("b-m1", recorded=True, today=1, error=None),
    )
    assert backfill.backfill_day(tmp_path, DAY, spy.credit, spy.log) == 2
    assert spy.credited == [
        ([1, 2], f"{DAY}-090000-aaaa"),
        ([1], f"{DAY}-100000-bbbb"),
    ]
    assert [sid for sid, _ in spy.logged] == [
        f"{DAY}-090000-aaaa",
        f"{DAY}-100000-bbbb",
    ]
    assert spy.logged[0][1]["type"] == "credit"
    assert spy.logged[0][1]["entry_id"] == "a-m2"


def test_a_failed_write_does_not_stop_the_others(tmp_path: Path) -> None:
    session(tmp_path / f"{DAY}-090000-aaaa.jsonl", 1)
    session(tmp_path / f"{DAY}-100000-bbbb.jsonl", 1)
    spy = Spy(
        receipt("a-m1", recorded=False, today=0, error="disk full"),
        receipt("b-m1", recorded=True, today=1, error=None),
    )
    assert backfill.backfill_day(tmp_path, DAY, spy.credit, spy.log) == 1
    assert len(spy.credited) == 2


def test_the_daily_cap_stops_the_backfill(tmp_path: Path) -> None:
    session(tmp_path / f"{DAY}-090000-aaaa.jsonl", 1)
    session(tmp_path / f"{DAY}-100000-bbbb.jsonl", 1)
    spy = Spy(
        receipt("a-m1", recorded=True, today=60, error=None),
        receipt("b-m1", recorded=False, today=60, error=credit.DAILY_CAP_ERROR),
    )
    session(tmp_path / f"{DAY}-110000-cccc.jsonl", 1)
    assert backfill.backfill_day(tmp_path, DAY, spy.credit, spy.log) == 60
    assert len(spy.credited) == 2  # the third transcript is never replayed


def test_real_ledger_backfill_is_idempotent(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    path = session(sessions / f"{DAY}-090000-aaaa.jsonl", 3)
    logged: list[tuple[str, dict[str, Any]]] = []

    def run() -> int:
        return backfill.backfill_day(
            sessions,
            DAY,
            lambda units, sid: unit_credit.credit_units(units, sid, now=T0 + 999),
            lambda sid, event: logged.append((sid, event)),
        )

    assert run() == 3
    assert [(sid, e["entry_id"], e["minutes"]) for sid, e in logged] == [
        (path.stem, f"{path.stem}-m3", 3)
    ]
    assert run() == 0  # the ledger already pays minutes 1..3
    assert len(logged) == 1
