# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Credit the active minutes today's transcripts earned but no row paid yet.

The tutor's credit is pure code over what was logged: replay every transcript
of the day (stopped and older ones included) through the engagement clock and
credit, per session, the minutes the replayed time earned minus the minutes
its recorded rows already paid (a legacy 15-minute row pays 15). Nothing is
hand-written. It is idempotent: a credit it writes is itself a ``credit`` row
in that transcript, so the next run finds the minutes paid, and a row the
ledger refused for the daily cap counts as dealt with. It stops at the first
daily-cap refusal, since no later minute of the day can be credited either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plc_lab.tutor import credit, resume

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady


def backfill_day(
    sessions_dir: Path,
    day_prefix: str,
    credit_fn: Callable[[list[BlockReady], str], list[dict[str, Any]]],
    log: Callable[[str, dict[str, Any]], None],
) -> int:
    """Credit the unpaid minutes of every ``day_prefix`` transcript, oldest first.

    ``log(session_id, event)`` appends to that session's transcript. Returns
    the newest ledger total of today's minutes the writes saw (0: none written).
    """
    today = 0
    for path in sorted(sessions_dir.glob(f"{day_prefix}-*.jsonl")):
        replayed = resume.replay(path)
        if replayed is None or not replayed.unrecorded:
            continue
        sid = replayed.conversation.session_id
        for row in credit_fn(replayed.unrecorded, sid):
            log(sid, {"type": "credit", **row})
            if row["recorded"]:
                today = max(today, row["minutes_today"])
            elif row["error"] == credit.DAILY_CAP_ERROR:
                return today
    return today
