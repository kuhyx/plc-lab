# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""What the ledger's verified tutor credit rows pay (earned_time 0.8.0 rules).

A row pays ``detail.minutes`` (15 if absent: a legacy block; 0 if invalid);
repeats of one ``entry_id`` pay their smallest count; a local day is capped
at :data:`DAILY_CAP_MINUTES`.
"""

from __future__ import annotations

from typing import Final

import earned_time

CREDIT: Final = "credit"
LEGACY_MINUTES: Final = 15  # a row without ``detail.minutes`` pays this
DAILY_CAP_MINUTES: Final = 60


def minutes_of(row: dict[str, object]) -> int:
    """What a verified credit row pays: ``detail.minutes``, 15 if absent, 0 if bad."""
    detail = row.get("detail")
    if not isinstance(detail, dict) or "minutes" not in detail:
        return LEGACY_MINUTES
    minutes = detail["minutes"]
    ok = isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0
    return int(minutes) if ok else 0


def paying(rows: list[object], key: bytes) -> dict[str, tuple[float, int]]:
    """``entry_id`` -> (``detail.ended_at``, minutes) of every verified credit row.

    Repeats of one id pay the smallest count, as the earner reads them.
    """
    found: dict[str, tuple[float, int]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != CREDIT:
            continue
        detail = row.get("detail")
        ended = detail.get("ended_at") if isinstance(detail, dict) else None
        if isinstance(ended, bool) or not isinstance(ended, int | float):
            continue
        if not bool(earned_time.verified(row, key)):
            continue
        entry = str(row.get("entry_id"))
        minutes = minutes_of(row)
        if entry in found:
            minutes = min(minutes, found[entry][1])
        found[entry] = (float(ended), minutes)
    return found


def minutes_between(
    paid_rows: dict[str, tuple[float, int]], lo: float, hi: float
) -> int:
    """Minutes verified rows ended in ``[lo, hi)`` pay, capped at the daily cap."""
    total = sum(m for ended, m in paid_rows.values() if lo <= ended < hi)
    return min(total, DAILY_CAP_MINUTES)
