# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The signed credit writer: one HMAC-signed ledger row per earned block.

The learner must know *when a block is earned* whether it counted, so every
write is read back and verified; only a row surviving that is "recorded".

Row shape (:func:`build_row`) and paths are a contract with ``earned_time``'s
matcher. An ``entry_id`` is never written twice; at most :data:`DAILY_CAP`
verified rows per local day (by ``detail.ended_at``); unverified rows count
for nothing, in the cap and in ``units_today`` alike. Paths resolve at call
time: ``AUTOMATION_TUTOR_DATA`` moves the data dir, ``AUTOMATION_TUTOR_KEY``
the key. The real key is root-owned and only read.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING, Final

import earned_time

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from plc_lab.tutor.clock import BlockReady

_REAL_KEY: Final = Path("/etc/workout-locker/hmac.key")
CREDIT: Final = "credit"
DAILY_CAP: Final = 4  # rows per local day, across sessions; also the max block
DAILY_CAP_ERROR: Final = "daily cap"
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Paths:
    """Where the tutor's ledger lives and which key signs it."""

    data_dir: Path
    key_file: Path

    @property
    def ledger(self) -> Path:
        """The signed credit ledger the earner reads."""
        return self.data_dir / "ledger.json"

    @property
    def lock(self) -> Path:
        """Serialises writers, e.g. two browser tabs crediting at once."""
        return self.data_dir / "ledger.lock"


def default_paths() -> Paths:
    """The active locations, honouring the sandbox environment variables."""
    data = os.environ.get("AUTOMATION_TUTOR_DATA")
    key = os.environ.get("AUTOMATION_TUTOR_KEY")
    return Paths(
        data_dir=Path(data) if data else Path.home() / ".local/share/automation_tutor",
        key_file=Path(key) if key else _REAL_KEY,
    )


@dataclass(frozen=True)
class CreditReceipt:
    """``recorded`` only if the re-read file holds the row verified; else ``error``."""

    recorded: bool
    units_today: int
    entry_id: str
    error: str | None


class LedgerError(Exception):
    """The ledger exists but is not a ledger -- never silently emptied."""


def read_key(key_file: Path) -> bytes | None:
    """The signing key, or ``None`` when it is unreadable or empty."""
    try:
        return key_file.read_bytes().strip() or None
    except OSError as exc:
        _logger.warning("signing key %s unreadable: %s", key_file, exc)
        return None


def read_rows(ledger: Path) -> list[object]:
    """The raw ``entries`` array; a missing file is empty.

    Raises:
        LedgerError: The file is unreadable, not JSON, or has no entries array.
    """
    if not ledger.exists():
        return []
    try:
        raw = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"{ledger} is unreadable: {exc}"
        raise LedgerError(msg) from exc
    rows = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        msg = f"{ledger} has no entries array"
        raise LedgerError(msg)
    return rows


def write_rows(ledger: Path, rows: list[object]) -> None:
    """Atomically replace the ledger: readers see the old file or the new one."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ledger.parent, suffix=".tmp", delete=False
    ) as handle:
        json.dump({"entries": rows}, handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    Path(handle.name).replace(ledger)


@contextmanager
def exclusive(lock_file: Path) -> Iterator[None]:
    """Hold the ledger write lock; the kernel drops it if the holder dies."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _credit_times(rows: list[object], key: bytes) -> dict[str, float]:
    """``entry_id`` -> ``detail.ended_at`` of every verified ``credit`` row."""
    times: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != CREDIT:
            continue
        detail = row.get("detail")
        ended = detail.get("ended_at") if isinstance(detail, dict) else None
        if isinstance(ended, bool) or not isinstance(ended, int | float):
            continue
        if bool(earned_time.verified(row, key)):
            times[str(row.get("entry_id"))] = float(ended)
    return times


def _local_day(ts: float) -> tuple[str, float, float]:
    """``ts``'s local date and that day's [midnight, next midnight) bounds."""
    moment = datetime.fromtimestamp(ts, tz=UTC).astimezone()
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    # Re-localise the next midnight so a DST change in between is honoured.
    following = (midnight + timedelta(days=1)).replace(tzinfo=None).astimezone()
    return moment.date().isoformat(), midnight.timestamp(), following.timestamp()


def build_row(
    block: BlockReady, session_id: str, key: bytes, *, now: float
) -> dict[str, object]:
    """The signed row for ``block``; every value is coerced *before* signing."""
    row: dict[str, object] = {
        "kind": CREDIT,
        "entry_id": f"{session_id}-b{int(block.block)}",
        "day": _local_day(float(block.ended_at))[0],
        "created_at": float(now),
        "detail": {
            "session_id": str(session_id),
            "block": int(block.block),
            "active_seconds": float(block.active_seconds),
            "ended_at": float(block.ended_at),
            "checks_passed": int(block.checks_passed),
            "checks_total": int(block.checks_total),
        },
    }
    row["hmac"] = str(earned_time.entry_signature(row, key))
    return row


def _append_locked(
    row: dict[str, object], ended_at: float, ledger: Path, key: bytes
) -> str | None:
    """Dedupe, cap and append ``row`` (caller holds the lock); the refusal, if any."""
    rows = read_rows(ledger)
    row_id = row["entry_id"]
    same_id = [r for r in rows if isinstance(r, dict) and r.get("entry_id") == row_id]
    if same_id:  # idempotent only for a genuine row of the same day
        day = row["day"]
        if any(earned_time.verified(r, key) and r.get("day") == day for r in same_id):
            return None
        return "entry_id already present (unverified or another day)"
    _, lo, hi = _local_day(ended_at)
    times = _credit_times(rows, key).values()
    if sum(1 for ended in times if lo <= ended < hi) >= DAILY_CAP:
        return DAILY_CAP_ERROR
    write_rows(ledger, [*rows, row])
    return None


def _units_today(ended: Iterable[float], now: float) -> int:
    """Credits ending in today's local window (midnight..now), as the earner counts."""
    lo, hi = earned_time.today_window(datetime.fromtimestamp(now, tz=UTC))
    return sum(1 for ts in ended if float(lo) <= ts <= float(hi))


def _refused(entry_id: str, error: str) -> CreditReceipt:
    """A receipt for a credit that could not even be attempted."""
    return CreditReceipt(recorded=False, units_today=0, entry_id=entry_id, error=error)


def credit_block(
    block: BlockReady,
    session_id: str,
    *,
    paths: Paths | None = None,
    now: float | None = None,
) -> CreditReceipt:
    """Append ``block``'s signed row, read it back, and say whether it counts.

    Raises:
        ValueError: ``session_id`` is empty or ``block.block`` is not 1..4.
    """
    if not session_id or not 1 <= block.block <= DAILY_CAP:
        msg = f"bad credit request: session {session_id!r}, block {block.block}"
        raise ValueError(msg)
    where = paths or default_paths()
    moment = time.time() if now is None else now
    entry_id = f"{session_id}-b{block.block}"
    key = read_key(where.key_file)
    if key is None:
        return _refused(entry_id, f"signing key unreadable: {where.key_file}")
    row = build_row(block, session_id, key, now=moment)
    try:
        with exclusive(where.lock):
            refusal = _append_locked(row, float(block.ended_at), where.ledger, key)
            stored = read_rows(where.ledger)
    except (LedgerError, OSError) as exc:
        _logger.warning("credit %s not recorded: %s", entry_id, exc)
        return _refused(entry_id, str(exc))
    times = _credit_times(stored, key)
    if refusal is None and entry_id not in times:
        refusal = "row not found verified on read-back"
    units = _units_today(times.values(), moment)
    return CreditReceipt(
        recorded=refusal is None, units_today=units, entry_id=entry_id, error=refusal
    )
