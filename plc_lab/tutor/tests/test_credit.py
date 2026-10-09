# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The signed credit writer: contract shape, read-back, cap, idempotence."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import earned_time
import pytest

from plc_lab.tutor import credit
from plc_lab.tutor.clock import BlockReady
from plc_lab.tutor.credit import DAILY_CAP_ERROR, Paths, credit_block, default_paths

if TYPE_CHECKING:
    from collections.abc import Iterator

ZONE = ZoneInfo("Europe/Warsaw")
NOON = datetime(2026, 10, 9, 12, 0, tzinfo=ZONE).timestamp()
KEY = b"test-key-not-the-real-one"


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


def block(n: int = 1, ended_at: float = NOON) -> BlockReady:
    return BlockReady(n, 900.0 * n + 12.5, ended_at, 1, 2)


def entries(where: Paths) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = json.loads(
        where.ledger.read_text(encoding="utf-8")
    )["entries"]
    return rows


def test_row_matches_the_contract_and_verifies(sandbox: Paths) -> None:
    receipt = credit_block(block(2), "s1", now=NOON + 5)
    assert receipt == credit.CreditReceipt(True, 1, "s1-b2", None)
    (row,) = entries(sandbox)
    assert row == {
        "kind": "credit",
        "entry_id": "s1-b2",
        "day": "2026-10-09",
        "created_at": NOON + 5,
        "detail": {
            "session_id": "s1",
            "block": 2,
            "active_seconds": 1812.5,
            "ended_at": NOON,
            "checks_passed": 1,
            "checks_total": 2,
        },
        "hmac": earned_time.entry_signature(row, KEY),
    }
    assert earned_time.verified(row, KEY)


def test_same_entry_is_never_written_twice(sandbox: Paths) -> None:
    first = credit_block(block(1), "s1", now=NOON)
    again = credit_block(block(1), "s1", now=NOON + 60)
    assert first.recorded
    assert again == credit.CreditReceipt(True, 1, "s1-b1", None)
    assert len(entries(sandbox)) == 1


def test_fifth_credit_of_the_day_hits_the_cap(sandbox: Paths) -> None:
    for n in (1, 2, 3):
        assert credit_block(block(n), "morning", now=NOON).recorded
    assert credit_block(block(1), "evening", now=NOON).units_today == 4
    fifth = credit_block(block(2), "evening", now=NOON)
    assert fifth == credit.CreditReceipt(False, 4, "evening-b2", DAILY_CAP_ERROR)
    assert len(entries(sandbox)) == 4


def test_tampered_rows_count_for_nothing(sandbox: Paths) -> None:
    for n in (1, 2, 3, 4):
        credit_block(block(n), "s1", now=NOON)
    rows = entries(sandbox)
    detail = rows[0]["detail"]
    assert isinstance(detail, dict)
    detail["active_seconds"] = 99999.0
    sandbox.ledger.write_text(json.dumps({"entries": rows}), encoding="utf-8")
    redo = credit_block(block(1), "s1", now=NOON)
    assert redo == credit.CreditReceipt(
        False, 3, "s1-b1", "entry_id already present (unverified or another day)"
    )
    assert credit_block(block(1), "s2", now=NOON) == credit.CreditReceipt(
        True, 4, "s2-b1", None
    )


def test_credit_ending_yesterday_is_not_today(sandbox: Paths) -> None:
    late = datetime(2026, 10, 8, 23, 59, tzinfo=ZONE).timestamp()
    receipt = credit_block(block(1, late), "s1", now=late + 180)
    assert (receipt.recorded, receipt.units_today) == (True, 0)
    assert entries(sandbox)[0]["day"] == "2026-10-08"


def test_reused_session_id_on_a_later_day_is_refused(sandbox: Paths) -> None:
    yesterday = datetime(2026, 10, 8, 20, 0, tzinfo=ZONE).timestamp()
    assert credit_block(block(1, yesterday), "s1", now=yesterday).recorded
    receipt = credit_block(block(1), "s1", now=NOON)
    assert (receipt.recorded, receipt.units_today) == (False, 0)
    assert len(entries(sandbox)) == 1


def test_cap_is_per_local_day(sandbox: Paths) -> None:
    yesterday = datetime(2026, 10, 8, 20, 0, tzinfo=ZONE).timestamp()
    for n in (1, 2, 3, 4):
        credit_block(block(n, yesterday), "old", now=yesterday)
    assert credit_block(block(1), "new", now=NOON).units_today == 1


def test_missing_key_records_nothing(
    sandbox: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOMATION_TUTOR_KEY", str(sandbox.data_dir / "nope"))
    receipt = credit_block(block(), "s1", now=NOON)
    assert not receipt.recorded
    assert "signing key unreadable" in str(receipt.error)
    assert not sandbox.ledger.exists()


@pytest.mark.parametrize("content", ["{not json", '{"rows": []}', "[]"])
def test_broken_ledger_is_never_overwritten(sandbox: Paths, content: str) -> None:
    sandbox.data_dir.mkdir(parents=True)
    sandbox.ledger.write_text(content, encoding="utf-8")
    receipt = credit_block(block(), "s1", now=NOON)
    assert (receipt.recorded, receipt.units_today) == (False, 0)
    assert sandbox.ledger.read_text(encoding="utf-8") == content


def test_unreadable_ledger_is_an_error(sandbox: Paths) -> None:
    sandbox.ledger.mkdir(parents=True)
    receipt = credit_block(block(), "s1", now=NOON)
    assert not receipt.recorded
    assert "unreadable" in str(receipt.error)


def test_foreign_and_malformed_rows_are_ignored(sandbox: Paths) -> None:
    junk: list[object] = [
        "text",
        {"kind": "debit", "entry_id": "x"},
        {"kind": "credit", "entry_id": "y", "detail": {"ended_at": True}},
        {"kind": "credit", "entry_id": "z", "detail": "nope"},
    ]
    sandbox.data_dir.mkdir(parents=True)
    sandbox.ledger.write_text(json.dumps({"entries": junk}), encoding="utf-8")
    assert credit_block(block(), "s1", now=NOON).units_today == 1
    assert entries(sandbox)[:4] == junk


def test_lost_write_is_not_recorded(
    sandbox: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credit, "write_rows", lambda ledger, rows: None)
    receipt = credit_block(block(), "s1", now=NOON)
    assert receipt == credit.CreditReceipt(
        False, 0, "s1-b1", "row not found verified on read-back"
    )


def test_concurrent_tabs_do_not_lose_rows(sandbox: Paths) -> None:
    receipts: list[credit.CreditReceipt] = []

    def tab(session: str) -> None:
        receipts.append(credit_block(block(1), session, now=NOON))

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
    receipt = credit_block(block(1, time.time()), "s1", paths=where)
    assert (receipt.recorded, receipt.units_today) == (True, 1)
    assert where.ledger.exists()


def test_default_paths_without_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOMATION_TUTOR_DATA")
    monkeypatch.delenv("AUTOMATION_TUTOR_KEY")
    where = default_paths()
    assert where.ledger == Path.home() / ".local/share/automation_tutor/ledger.json"
    assert where.key_file == Path("/etc/workout-locker/hmac.key")


@pytest.mark.parametrize(("n", "session"), [(0, "s1"), (5, "s1"), (1, "")])
def test_bad_requests_raise(n: int, session: str) -> None:
    with pytest.raises(ValueError, match="bad credit request"):
        credit_block(block(n), session, now=NOON)
