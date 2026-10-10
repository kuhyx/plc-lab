# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""One-off repair: cards the tutor finished while a gate dropped the result.

Until 2026-10-10 the engine ignored a tutor ``card_done`` unless a check had
passed (session ``20261010-153545-b193``: the card was never recorded done and
"next unfinished card" served it again). The transcripts still hold the
tutor's word, so this marks those cards done from them, by code. It runs once
per data dir (``Store.mark_repaired``): after that the manual override
(``POST /api/card_done``) owns the state, and a restart must not undo it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.store import Store

_logger = logging.getLogger(__name__)
NAME: Final = "tutor-card-done-v1"


def _tutor_done(path: Path) -> list[str]:
    """Card ids a tutor turn of this transcript finished, in order."""
    card, found = "", []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            # A line cut short by a kill: skip it, the rest still counts.
            _logger.warning("repair: unreadable line in %s skipped: %s", path.name, exc)
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") in {"start", "next_card"}:
            card = str(event.get("card", ""))
        elif event.get("type") == "tutor" and (event.get("turn") or {}).get(
            "card_done"
        ):
            found.append(card)
    return found


def repair_done_cards(store: Store) -> list[tuple[str, str]]:
    """Mark every tutor-finished card that is not done yet; ``[(card, session)]``."""
    if store.repaired(NAME):
        return []
    marked: list[tuple[str, str]] = []
    for path in sorted((store.root / "sessions").glob("*.jsonl")):
        for card in _tutor_done(path):
            if card and card not in store.progress()["cards_done"]:
                store.finish_card(card, path.stem)
                marked.append((card, path.stem))
                _logger.info("repair: marked %s done from session %s", card, path.stem)
    store.mark_repaired(NAME)
    return marked
