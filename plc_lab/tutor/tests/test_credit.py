# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The signed credit writer: contract shape, read-back, cap, idempotence."""

from __future__ import annotations

from datetime import datetime
import threading
import time
from typing import TYPE_CHECKING

import earned_time
import pytest

from plc_lab.tutor import credit
from plc_lab.tutor.credit import (
    DAILY_CAP_ERROR,
    credit_span,
    session_minutes,
)
from plc_lab.tutor.ledger_io import Paths, default_paths
from plc_lab.tutor.tests._credit_support import (
    KEY,
    NOON,
    ZONE,
    entries,
    put,
    unit,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

DUPLICATE = "entry_id already present (unverified or another day)"


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """Every test writes to a temp ledger with a temp key, in a pinned zone."""
    key = tmp_path / "hmac.key"
    key.write_bytes(KEY + b"\n")
    monkeypatch.setenv("AUTOMATION_TUTOR_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMATION_TUTOR_KEY", str(key))
    return default_paths()


@pytest.fixture(autouse=True)
def pinned_zone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Local time is Warsaw for the test, and whatever it was afterwards."""
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_row_matches_the_contract_and_verifies(sandbox: Paths) -> None:
    receipt = credit_span(unit(5), 3, "s1", now=NOON + 5)
    assert receipt == credit.CreditReceipt(True, 3, 3, "s1-m5", None)
    (row,) = entries(sandbox)
    assert row == {
        "kind": "credit",
        "entry_id": "s1-m5",
        "day": "2026-10-09",
        "created_at": NOON + 5,
        "detail": {
            "session_id": "s1",
            "block": 5,
            "minutes": 3,
            "active_seconds": 300.5,
            "ended_at": NOON,
            "checks_passed": 1,
            "checks_total": 2,
        },
        "hmac": earned_time.entry_signature(row, KEY),
    }
    assert earned_time.verified(row, KEY)


def test_same_entry_is_never_written_twice(sandbox: Paths) -> None:
    first = credit_span(unit(2), 2, "s1", now=NOON)
    again = credit_span(unit(2), 2, "s1", now=NOON + 60)
    assert first.recorded
    assert again == credit.CreditReceipt(True, 2, 2, "s1-m2", None)
    assert len(entries(sandbox)) == 1


def test_row_that_crosses_the_cap_is_trimmed_and_resigned(sandbox: Paths) -> None:
    assert credit_span(unit(50), 50, "morning", now=NOON).minutes == 50
    trimmed = credit_span(unit(30), 30, "evening", now=NOON)
    assert trimmed == credit.CreditReceipt(True, 10, 60, "evening-m30", None)
    row = entries(sandbox)[1]
    assert row["detail"]["minutes"] == 10
    assert earned_time.verified(row, KEY)
    again = credit_span(unit(30), 30, "evening", now=NOON)
    assert (again.recorded, again.minutes, again.minutes_today) == (True, 10, 60)


def test_full_day_refuses_more(sandbox: Paths) -> None:
    assert credit_span(unit(60), 60, "all", now=NOON).recorded
    refused = credit_span(unit(1), 1, "late", now=NOON)
    assert refused == credit.CreditReceipt(False, 0, 60, "late-m1", DAILY_CAP_ERROR)
    assert len(entries(sandbox)) == 1


def test_tampered_row_counts_for_nothing(sandbox: Paths) -> None:
    credit_span(unit(40), 40, "s1", now=NOON)
    rows = entries(sandbox)
    rows[0]["detail"]["active_seconds"] = 99999.0
    put(sandbox, list(rows))
    assert credit_span(unit(40), 40, "s1", now=NOON) == credit.CreditReceipt(
        False, 0, 0, "s1-m40", DUPLICATE
    )
    assert credit_span(unit(40), 40, "s2", now=NOON).minutes == 40


def test_credit_ending_yesterday_is_not_today(sandbox: Paths) -> None:
    late = datetime(2026, 10, 8, 23, 59, tzinfo=ZONE).timestamp()
    receipt = credit_span(unit(1, late), 1, "s1", now=late + 180)
    assert (receipt.recorded, receipt.minutes_today) == (True, 0)
    assert entries(sandbox)[0]["day"] == "2026-10-08"


def test_reused_session_id_on_a_later_day_is_refused(sandbox: Paths) -> None:
    yesterday = datetime(2026, 10, 8, 20, 0, tzinfo=ZONE).timestamp()
    assert credit_span(unit(1, yesterday), 1, "s1", now=yesterday).recorded
    receipt = credit_span(unit(1), 1, "s1", now=NOON)
    assert (receipt.recorded, receipt.error) == (False, DUPLICATE)
    assert len(entries(sandbox)) == 1


def test_cap_is_per_local_day(sandbox: Paths) -> None:
    yesterday = datetime(2026, 10, 8, 20, 0, tzinfo=ZONE).timestamp()
    credit_span(unit(60, yesterday), 60, "old", now=yesterday)
    assert credit_span(unit(1), 1, "new", now=NOON).minutes_today == 1


def test_missing_key_records_nothing(
    sandbox: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOMATION_TUTOR_KEY", str(sandbox.data_dir / "nope"))
    receipt = credit_span(unit(), 1, "s1", now=NOON)
    assert not receipt.recorded
    assert "signing key unreadable" in str(receipt.error)
    assert not sandbox.ledger.exists()


@pytest.mark.parametrize("content", ["{not json", '{"rows": []}', "[]"])
def test_broken_ledger_is_never_overwritten(sandbox: Paths, content: str) -> None:
    sandbox.data_dir.mkdir(parents=True)
    sandbox.ledger.write_text(content, encoding="utf-8")
    receipt = credit_span(unit(), 1, "s1", now=NOON)
    assert (receipt.recorded, receipt.minutes_today) == (False, 0)
    assert sandbox.ledger.read_text(encoding="utf-8") == content


def test_unreadable_ledger_is_an_error(sandbox: Paths) -> None:
    sandbox.ledger.mkdir(parents=True)
    receipt = credit_span(unit(), 1, "s1", now=NOON)
    assert not receipt.recorded
    assert "unreadable" in str(receipt.error)


def test_unwritable_data_dir_is_an_error(sandbox: Paths) -> None:
    sandbox.data_dir.write_text("a file, not a directory", encoding="utf-8")
    receipt = credit_span(unit(), 1, "s1", now=NOON)
    assert (receipt.recorded, receipt.minutes) == (False, 0)
    assert receipt.error


def test_lost_write_is_not_recorded(
    sandbox: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credit, "write_rows", lambda ledger, rows: None)
    receipt = credit_span(unit(), 1, "s1", now=NOON)
    assert receipt == credit.CreditReceipt(
        False, 1, 0, "s1-m1", "row not found verified on read-back"
    )


def test_concurrent_tabs_do_not_lose_rows(sandbox: Paths) -> None:
    receipts: list[credit.CreditReceipt] = []

    def tab(session: str) -> None:
        receipts.append(credit_span(unit(1), 1, session, now=NOON))

    threads = [threading.Thread(target=tab, args=(f"tab{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(r.recorded for r in receipts)
    assert len(entries(sandbox)) == 4


def test_explicit_paths_and_default_now(tmp_path: Path) -> None:
    key = tmp_path / "other.key"
    key.write_bytes(KEY)
    where = Paths(data_dir=tmp_path / "elsewhere", key_file=key)
    receipt = credit_span(unit(1, time.time()), 1, "s1", paths=where)
    assert (receipt.recorded, receipt.minutes_today) == (True, 1)
    assert where.ledger.exists()
    assert session_minutes("s1", paths=where) == {1}


@pytest.mark.parametrize(
    ("n", "minutes", "session"),
    [(0, 1, "s1"), (5, 6, "s1"), (3, 0, "s1"), (1, 1, "")],
)
def test_bad_requests_raise(n: int, minutes: int, session: str) -> None:
    with pytest.raises(ValueError, match="bad credit request"):
        credit_span(unit(n), minutes, session, now=NOON)
