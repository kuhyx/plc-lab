# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The signed credit writer: one HMAC-signed ledger row per span of minutes.

The learner must know *when minutes are earned* and whether they counted, so
every write is read back and verified; only a row surviving that is "recorded".

The row contract is ``earned_time`` 0.8.0's (its README, "tutor row
contract"): ``detail.minutes`` is the positive int of active minutes the row
pays (a row without it is a legacy 15-minute block); ``entry_id`` is
``<session>-m<n>`` with ``n`` the session's LAST credited minute in the row, so
a retry rewrites the same id and rows never overlap; ``detail.ended_at`` is
when that last minute ended and picks the day, so a row never spans local
midnight (the caller splits). An ``entry_id`` is never written twice; the
writer's own cap sums verified minutes (legacy rows as 15) up to
:data:`DAILY_CAP_MINUTES` a local day, trimming a row that would cross it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Final

import earned_time

from plc_lab.tutor.ledger_io import (
    LedgerError,
    Paths,
    default_paths,
    exclusive,
    read_key,
    read_rows,
    write_rows,
)
from plc_lab.tutor.ledger_pay import (
    CREDIT,
    DAILY_CAP_MINUTES,
    LEGACY_MINUTES,
    minutes_between,
    minutes_of,
    paying,
)

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady

DAILY_CAP_ERROR: Final = "daily cap"
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreditReceipt:
    """``recorded`` only if the re-read file holds the row verified; else ``error``.

    ``minutes`` is what the row finally paid (0 when refused); ``minutes_today``
    is today's verified total in the ledger, capped at the daily cap.
    """

    recorded: bool
    minutes: int
    minutes_today: int
    entry_id: str
    error: str | None


def local_day(ts: float) -> tuple[str, float, float]:
    """``ts``'s local date and that day's [midnight, next midnight) bounds."""
    moment = datetime.fromtimestamp(ts, tz=UTC).astimezone()
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    # Re-localise the next midnight so a DST change in between is honoured.
    following = (midnight + timedelta(days=1)).replace(tzinfo=None).astimezone()
    return moment.date().isoformat(), midnight.timestamp(), following.timestamp()


def entry_id_for(session_id: str, last_minute: int) -> str:
    """The deterministic id of the row whose last minute is ``last_minute``."""
    return f"{session_id}-m{int(last_minute)}"


def session_minutes(session_id: str, *, paths: Paths | None = None) -> set[int]:
    """The minutes of ``session_id`` the LEDGER's verified rows pay.

    The only truth for "already paid" (a receipt can say "failed" for a write
    that landed). ``-m<n>`` with ``detail.minutes`` k covers ``n-k+1..n``, a
    legacy ``-b<n>`` covers ``15 (n-1)+1..15 n``. Unreadable key or ledger:
    nothing is known paid; the write that follows reports the failure.
    """
    where = paths or default_paths()
    key = read_key(where.key_file)
    try:
        rows = read_rows(where.ledger) if key else []
    except LedgerError as exc:
        _logger.warning("ledger unreadable, no minutes known paid: %s", exc)
        return set()
    own = re.compile(rf"{re.escape(session_id)}-([bm])(\d+)", re.ASCII)
    paid: set[int] = set()
    for row in rows:
        if not (key and isinstance(row, dict) and row.get("kind") == CREDIT):
            continue
        found = own.fullmatch(str(row.get("entry_id")))
        if found is None or not earned_time.verified(row, key):
            continue
        n = int(found[2])
        if found[1] == "b":
            paid.update(range(LEGACY_MINUTES * (n - 1) + 1, LEGACY_MINUTES * n + 1))
        else:
            paid.update(range(n - minutes_of(row) + 1, n + 1))
    return paid


def build_row(
    last: BlockReady, minutes: int, session_id: str, key: bytes, *, now: float
) -> dict[str, object]:
    """The signed row for ``minutes`` ending at ``last`` (values coerced first)."""
    row: dict[str, object] = {
        "kind": CREDIT,
        "entry_id": entry_id_for(session_id, last.block),
        "day": local_day(float(last.ended_at))[0],
        "created_at": float(now),
        "detail": {
            "session_id": str(session_id),
            "block": int(last.block),
            "minutes": int(minutes),
            "active_seconds": float(last.active_seconds),
            "ended_at": float(last.ended_at),
            "checks_passed": int(last.checks_passed),
            "checks_total": int(last.checks_total),
        },
    }
    row["hmac"] = str(earned_time.entry_signature(row, key))
    return row


def _append_locked(
    row: dict[str, Any], ledger: Path, key: bytes
) -> tuple[str | None, int]:
    """Dedupe, cap and append ``row`` (caller holds the lock).

    Returns the refusal, if any, and the minutes the row ended up paying.
    """
    rows = read_rows(ledger)
    detail = row["detail"]  # a dict, built by build_row
    same_id = [
        r for r in rows if isinstance(r, dict) and r.get("entry_id") == row["entry_id"]
    ]
    if same_id:  # idempotent only for a genuine row of the same day
        if any(
            earned_time.verified(r, key) and r.get("day") == row["day"] for r in same_id
        ):
            return None, 0
        return "entry_id already present (unverified or another day)", 0
    _, lo, hi = local_day(float(detail["ended_at"]))
    room = DAILY_CAP_MINUTES - minutes_between(paying(rows, key), lo, hi)
    if room <= 0:
        return DAILY_CAP_ERROR, 0
    if detail["minutes"] > room:  # trim to the remainder; the id is unchanged
        detail["minutes"] = room
        unsigned = {k: v for k, v in row.items() if k != "hmac"}
        row["hmac"] = str(earned_time.entry_signature(unsigned, key))
    write_rows(ledger, [*rows, row])
    return None, int(detail["minutes"])


def _refused(entry_id: str, error: str) -> CreditReceipt:
    """A receipt for a credit that could not even be attempted."""
    return CreditReceipt(
        recorded=False, minutes=0, minutes_today=0, entry_id=entry_id, error=error
    )


def _read_back(
    paid_rows: dict[str, tuple[float, int]],
    entry_id: str,
    refusal: str | None,
    paid: int,
    moment: float,
) -> CreditReceipt:
    """The receipt from the re-read ledger: recorded only if the row is there."""
    if refusal is None and entry_id not in paid_rows:
        refusal = "row not found verified on read-back"
    _, lo, hi = local_day(moment)
    today = minutes_between(paid_rows, lo, hi)
    if refusal is None and not paid:  # an identical row was already there
        paid = paid_rows[entry_id][1]
    return CreditReceipt(refusal is None, paid, today, entry_id, refusal)


def credit_span(
    last: BlockReady,
    minutes: int,
    session_id: str,
    *,
    paths: Paths | None = None,
    now: float | None = None,
) -> CreditReceipt:
    """Append the row for ``minutes`` ending at ``last``, read back, say if it counts.

    Raises:
        ValueError: ``session_id`` is empty, or ``minutes`` / ``last.block`` is
            not positive, or ``minutes`` exceeds ``last.block``.
    """
    if not session_id or minutes < 1 or not minutes <= last.block:
        msg = (
            f"bad credit request: session {session_id!r}, {minutes} min to {last.block}"
        )
        raise ValueError(msg)
    where = paths or default_paths()
    moment = time.time() if now is None else now
    entry_id = entry_id_for(session_id, last.block)
    key = read_key(where.key_file)
    if key is None:
        return _refused(entry_id, f"signing key unreadable: {where.key_file}")
    row = build_row(last, minutes, session_id, key, now=moment)
    try:
        with exclusive(where.lock):
            refusal, paid = _append_locked(row, where.ledger, key)
            stored = read_rows(where.ledger)
    except (LedgerError, OSError) as exc:
        _logger.warning("credit %s not recorded: %s", entry_id, exc)
        return _refused(entry_id, str(exc))
    return _read_back(paying(stored, key), entry_id, refusal, paid, moment)
