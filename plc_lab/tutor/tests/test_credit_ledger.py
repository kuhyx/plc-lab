# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""What the credit writer counts as paid: legacy rows, junk, session minutes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from plc_lab.tutor.credit import credit_span, session_minutes
from plc_lab.tutor.ledger_io import Paths, default_paths
from plc_lab.tutor.tests._credit_support import (
    NOON,
    entries,
    paid,
    put,
    unit,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """Every test writes to a temp ledger with a temp key."""
    key = tmp_path / "hmac.key"
    key.write_bytes(b"test-key-not-the-real-one\n")
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


def test_legacy_and_repeated_rows_count_as_the_earner_reads_them(
    sandbox: Paths,
) -> None:
    put(sandbox, [paid("old-b1", None), paid("dup-m5", 20), paid("dup-m5", 10)])
    # legacy 15 + the smaller repeat 10 + this row's 1
    assert credit_span(unit(), 1, "s1", now=NOON).minutes_today == 26


def test_unusable_minutes_and_foreign_rows_are_ignored(sandbox: Paths) -> None:
    junk: list[object] = [
        "text",
        {"kind": "debit", "entry_id": "x"},
        {"kind": "credit", "entry_id": "y", "detail": {"ended_at": True}},
        {"kind": "credit", "entry_id": "z", "detail": "nope"},
        {"kind": "credit", "entry_id": "u", "detail": {"ended_at": NOON}},
        paid("zero-m1", 0),
        paid("bool-m1", True),
        paid("neg-m1", -4),
        paid("str-m1", "9"),
    ]
    put(sandbox, junk)
    assert credit_span(unit(), 1, "s1", now=NOON).minutes_today == 1
    assert entries(sandbox)[: len(junk)] == junk


def test_session_minutes_reads_the_ledger_for_one_session(sandbox: Paths) -> None:
    tampered = paid("s1-m55", 5)
    tampered["day"] = "2026-10-10"
    put(
        sandbox,
        [
            paid("s1-m5", 3),  # 3..5
            paid("s1-m20", None),  # no minutes: legacy 15 ending at 20 (6..20)
            paid("s1-b2", None),  # legacy block 2: 16..30
            paid("s1-m40", 0),  # pays nothing
            paid("s10-m50", 5),  # another session
            paid("s1-x1", 5),  # not a minute / block id
            tampered,
            {"kind": "debit", "entry_id": "s1-m58"},
            "text",
        ],
    )
    assert session_minutes("s1") == {3, 4, 5, *range(6, 31)}


def test_session_minutes_without_key_or_ledger(
    sandbox: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert session_minutes("s1") == set()  # no ledger yet
    put(sandbox, [paid("s1-m1", 1)])
    sandbox.ledger.write_text("{not json", encoding="utf-8")
    assert session_minutes("s1") == set()
    monkeypatch.setenv("AUTOMATION_TUTOR_KEY", str(sandbox.data_dir / "nope"))
    assert session_minutes("s1") == set()
