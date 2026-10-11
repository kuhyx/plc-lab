# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Deck progress and progress over time, for the side panel and ``#progress``.

Cards done come from ``progress.json`` (``cards_done[id].at``; a card marked
not done again loses its date, so the history only ever shows cards done
now). Minutes per day come from the ledger's verified credit rows, the same
rows the earner pays, capped per local day like it.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from plc_lab.tutor.credit import local_day
from plc_lab.tutor.ledger_io import LedgerError, default_paths, read_key, read_rows
from plc_lab.tutor.ledger_pay import DAILY_CAP_MINUTES, paying

if TYPE_CHECKING:
    from plc_lab.cards import Card
    from plc_lab.tutor.ledger_io import Paths

_logger = logging.getLogger(__name__)


def deck_summary(deck: list[Card], done: set[str]) -> dict[str, Any]:
    """Done / pending / percent overall and per topic, in deck order."""
    topics: dict[str, dict[str, Any]] = {}
    for card in deck:
        row = topics.setdefault(
            card.topic.title, {"title": card.topic.title, "done": 0, "total": 0}
        )
        row["total"] += 1
        row["done"] += card.id in done
    total = len(deck)
    finished = sum(row["done"] for row in topics.values())
    return {
        "total": total,
        "done": finished,
        "pending": total - finished,
        "percent": round(100 * finished / total) if total else 0,
        "topics": list(topics.values()),
    }


def ledger_minutes_by_day(paths: Paths | None = None) -> dict[str, int]:
    """Local day -> verified credited minutes (capped); empty if unreadable."""
    where = paths or default_paths()
    key = read_key(where.key_file)
    if key is None:
        return {}
    try:
        rows = read_rows(where.ledger)
    except LedgerError as exc:
        _logger.warning("ledger unreadable, no minutes per day: %s", exc)
        return {}
    per_day: Counter[str] = Counter()
    for ended, minutes in paying(rows, key).values():
        per_day[local_day(ended)[0]] += minutes
    return {day: min(m, DAILY_CAP_MINUTES) for day, m in per_day.items()}


def timeline(
    cards_done: dict[str, dict[str, Any]], minutes: dict[str, int], today: str
) -> list[dict[str, Any]]:
    """One row per day from the first recorded day to ``today``, none skipped."""
    done_per_day: Counter[str] = Counter()
    for info in cards_done.values():
        at = info.get("at")
        if isinstance(at, str):
            done_per_day[
                datetime.fromisoformat(at).astimezone().date().isoformat()
            ] += 1
    days = [*done_per_day, *minutes, today]
    day, last = date.fromisoformat(min(days)), date.fromisoformat(today)
    rows, running = [], 0
    while day <= last:
        key = day.isoformat()
        running += done_per_day[key]
        rows.append(
            {
                "day": key,
                "cards_done": done_per_day[key],
                "cards_done_total": running,
                "minutes": minutes.get(key, 0),
            }
        )
        day += timedelta(days=1)
    return rows
