# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Credited active minutes ("units") and how they reach the signed ledger.

The clock releases one unit per active minute; this module turns released
units into ledger rows and keeps the books on what was paid.

**Cadence.** One row per engine turn, carrying every minute the clock
released in that turn (the clock only accrues at events anyway), not one row
per minute: each ledger write fires screen-locker's ``earner-bonus.path``,
which rewrites the shutdown schedule. The resume top-up and the day's
back-credit write one row per contiguous span of one session the same way. A
span never crosses local midnight (the row's ``ended_at`` picks the day), so
:func:`spans` splits at it and at any gap.

**Rows.** A logged ``credit`` row (also the receipt shown on the page) has
``block`` = the session's last minute in the row, ``span`` = minutes requested,
``minutes`` = minutes the ledger finally paid (the writer trims at the daily
cap), plus the receipt fields and the session's cumulative ``checks_passed``.
It covers minutes ``(block - span, block]``. A legacy row (a 15-minute block,
no ``span``) with ``block`` = b covers ``(15 (b - 1), 15 b]`` and paid 15.
The page's "credited" figures come from these receipts (a log / UI record);
what is actually paid, and so what still needs a row, is asked of the ledger
(``credit.session_minutes``), never of the receipts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from plc_lab.tutor import credit, ledger_pay

if TYPE_CHECKING:
    from collections.abc import Iterable

    from plc_lab.tutor.clock import BlockReady

LEGACY_BLOCK_MINUTES: Final = ledger_pay.LEGACY_MINUTES


def spans(units: Iterable[BlockReady]) -> list[list[BlockReady]]:
    """``units`` split into runs of consecutive minutes ending on one local day."""
    out: list[list[BlockReady]] = []
    for unit in units:
        same_day = (
            bool(out)
            and credit.local_day(out[-1][-1].ended_at)[0]
            == (credit.local_day(unit.ended_at)[0])
        )
        if out and same_day and out[-1][-1].block + 1 == unit.block:
            out[-1].append(unit)
        else:
            out.append([unit])
    return out


def credit_row(
    last: BlockReady, span: int, receipt: credit.CreditReceipt
) -> dict[str, Any]:
    """The receipt / ``credit`` transcript row for one ledger write."""
    return {
        "block": last.block,
        "span": span,
        "checks_passed": last.checks_passed,
        "recorded": receipt.recorded,
        "minutes": receipt.minutes,
        "minutes_today": receipt.minutes_today,
        "entry_id": receipt.entry_id,
        "error": receipt.error,
    }


def credit_units(
    units: Iterable[BlockReady], session_id: str, *, now: float
) -> list[dict[str, Any]]:
    """Write one ledger row per span of ``units``; the rows to log, in order.

    Minutes the ledger already pays for this session are skipped, whatever the
    transcript's receipts say (a write whose read-back failed did land). Stops
    after a daily-cap refusal: no later minute of the day can pay either.
    """
    rows: list[dict[str, Any]] = []
    paid = credit.session_minutes(session_id)
    for group in spans(u for u in units if u.block not in paid):
        last = group[-1]
        receipt = credit.credit_span(last, len(group), session_id, now=now)
        rows.append(credit_row(last, len(group), receipt))
        if receipt.error == credit.DAILY_CAP_ERROR:
            break
    return rows


def paid_minutes(receipts: Iterable[dict[str, Any]]) -> int:
    """Minutes the recorded rows of one session paid (legacy rows: 15)."""
    return sum(
        int(r["minutes"]) if "span" in r else LEGACY_BLOCK_MINUTES
        for r in receipts
        if r.get("recorded")
    )


def minutes_today(receipts: Iterable[dict[str, Any]]) -> int:
    """Today's ledger total as the newest recorded rows saw it (legacy: x15)."""
    return max(
        (
            int(r["minutes_today"])
            if "span" in r
            else int(r.get("units_today", 0)) * LEGACY_BLOCK_MINUTES
            for r in receipts
            if r.get("recorded")
        ),
        default=0,
    )
