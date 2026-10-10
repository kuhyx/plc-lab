# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Units to ledger rows: span splitting, skipping paid minutes, the receipts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from plc_lab.tutor import credit, ledger_io, unit_credit
from plc_lab.tutor.clock import BlockReady
from plc_lab.tutor.credit import CreditReceipt

if TYPE_CHECKING:
    import pytest

NOON = 1_800_000_000.0  # a winter midday: no DST edge near it
DAY = 86_400.0


def unit(n: int, ended_at: float = NOON) -> BlockReady:
    """The n-th active minute, earned at ``ended_at``."""
    return BlockReady(n, 60.0 * n, ended_at, 2, 3)


def run(n: int) -> list[BlockReady]:
    """Minutes ``1..n`` of one session, earned at noon."""
    return [unit(i) for i in range(1, n + 1)]


def ledger_ids() -> list[str]:
    """The entry ids in the sandbox ledger, in order."""
    ledger = ledger_io.default_paths().ledger
    entries = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    return [e["entry_id"] for e in entries]


def blocks(groups: list[list[BlockReady]]) -> list[list[int]]:
    return [[u.block for u in g] for g in groups]


def test_spans_of_nothing() -> None:
    assert unit_credit.spans([]) == []


def test_consecutive_minutes_form_one_span() -> None:
    assert blocks(unit_credit.spans(run(3))) == [[1, 2, 3]]


def test_a_gap_splits_the_span() -> None:
    gapped = [unit(1), unit(2), unit(4), unit(5), unit(7)]
    assert blocks(unit_credit.spans(gapped)) == [[1, 2], [4, 5], [7]]


def test_local_midnight_splits_the_span() -> None:
    crossing = [unit(1), unit(2, NOON + DAY), unit(3, NOON + DAY)]
    assert blocks(unit_credit.spans(crossing)) == [[1], [2, 3]]


def test_spans_accept_any_iterable() -> None:
    assert blocks(unit_credit.spans(u for u in run(2))) == [[1, 2]]


def test_credit_row_is_the_receipt_plus_the_unit() -> None:
    receipt = CreditReceipt(True, 4, 9, "s1-m5", None)
    assert unit_credit.credit_row(unit(5), 4, receipt) == {
        "block": 5,
        "span": 4,
        "checks_passed": 2,
        "recorded": True,
        "minutes": 4,
        "minutes_today": 9,
        "entry_id": "s1-m5",
        "error": None,
    }


def test_one_row_per_span_is_written_to_the_ledger() -> None:
    rows = unit_credit.credit_units([*run(3), unit(5), unit(6)], "s1", now=NOON)
    assert [(r["block"], r["span"], r["minutes"]) for r in rows] == [
        (3, 3, 3),
        (6, 2, 2),
    ]
    assert [r["minutes_today"] for r in rows] == [3, 5]
    assert all(r["recorded"] and r["error"] is None for r in rows)
    assert ledger_ids() == ["s1-m3", "s1-m6"]


def test_minutes_the_ledger_already_pays_are_skipped() -> None:
    unit_credit.credit_units(run(3), "s1", now=NOON)
    rows = unit_credit.credit_units(run(5), "s1", now=NOON + 60)
    assert [(r["block"], r["span"]) for r in rows] == [(5, 2)]
    assert unit_credit.credit_units(run(5), "s1", now=NOON + 120) == []
    assert ledger_ids() == ["s1-m3", "s1-m5"]


def test_nothing_to_credit_writes_nothing() -> None:
    assert unit_credit.credit_units([], "s1", now=NOON) == []
    assert not ledger_io.default_paths().ledger.exists()


def test_daily_cap_refusal_stops_the_later_spans() -> None:
    assert unit_credit.credit_units(run(60), "full", now=NOON)[0]["minutes"] == 60
    rows = unit_credit.credit_units([unit(1), unit(3), unit(5)], "late", now=NOON)
    assert len(rows) == 1
    assert (rows[0]["recorded"], rows[0]["error"]) == (False, credit.DAILY_CAP_ERROR)
    assert ledger_ids() == ["full-m60"]


def test_other_errors_do_not_stop_the_later_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(last: BlockReady, n: int, sid: str, **_: object) -> CreditReceipt:
        return CreditReceipt(False, 0, 0, f"{sid}-m{last.block}", "disk full")

    monkeypatch.setattr(credit, "credit_span", fail)
    rows = unit_credit.credit_units([unit(1), unit(3)], "s1", now=NOON)
    assert [(r["block"], r["error"]) for r in rows] == [
        (1, "disk full"),
        (3, "disk full"),
    ]


def legacy(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"recorded": True, "block": 2, "units_today": 2, **(extra or {})}


def span_row(minutes: int, today: int, *, recorded: bool = True) -> dict[str, Any]:
    return {"recorded": recorded, "span": minutes, "minutes": minutes} | {
        "minutes_today": today
    }


def test_paid_minutes_counts_recorded_rows_only() -> None:
    receipts = [span_row(7, 7), span_row(9, 16, recorded=False), legacy()]
    assert unit_credit.paid_minutes(receipts) == 7 + unit_credit.LEGACY_BLOCK_MINUTES
    assert unit_credit.paid_minutes([]) == 0


def test_minutes_today_is_the_newest_total_the_rows_saw() -> None:
    receipts = [span_row(7, 7), span_row(5, 12), span_row(4, 99, recorded=False)]
    assert unit_credit.minutes_today(receipts) == 12
    assert unit_credit.minutes_today([]) == 0


def test_minutes_today_reads_legacy_rows_in_blocks() -> None:
    assert unit_credit.minutes_today([legacy()]) == 2 * 15
    assert unit_credit.minutes_today([{"recorded": True}]) == 0
