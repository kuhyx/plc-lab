# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Shared builders for the credit-writer tests (ledger rows, minutes)."""

from __future__ import annotations

from datetime import datetime
import json
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import earned_time

from plc_lab.tutor.clock import BlockReady

if TYPE_CHECKING:
    from plc_lab.tutor.ledger_io import Paths

ZONE = ZoneInfo("Europe/Warsaw")
NOON = datetime(2026, 10, 9, 12, 0, tzinfo=ZONE).timestamp()
KEY = b"test-key-not-the-real-one"


def unit(n: int = 1, ended_at: float = NOON) -> BlockReady:
    """The n-th active minute, earned at ``ended_at``."""
    return BlockReady(n, 60.0 * n + 0.5, ended_at, 1, 2)


def entries(where: Paths) -> list[dict[str, Any]]:
    """The ledger's rows as written."""
    rows: list[dict[str, Any]] = json.loads(where.ledger.read_text(encoding="utf-8"))[
        "entries"
    ]
    return rows


def put(where: Paths, rows: list[object]) -> None:
    """Replace the ledger with ``rows`` verbatim."""
    where.data_dir.mkdir(parents=True, exist_ok=True)
    where.ledger.write_text(json.dumps({"entries": rows}), encoding="utf-8")


def signed(entry: str, detail: object) -> dict[str, Any]:
    """A genuine credit row for ``entry`` carrying ``detail`` (any shape)."""
    row: dict[str, Any] = {
        "kind": "credit",
        "entry_id": entry,
        "day": "2026-10-09",
        "created_at": NOON,
        "detail": detail,
    }
    row["hmac"] = earned_time.entry_signature(row, KEY)
    return row


def paid(entry: str, minutes: object = 15) -> dict[str, Any]:
    """A signed row ended at noon; ``minutes=None`` makes it a legacy row."""
    detail: dict[str, Any] = {"ended_at": NOON}
    if minutes is not None:
        detail["minutes"] = minutes
    return signed(entry, detail)
