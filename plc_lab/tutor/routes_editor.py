# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Card editor routes: ``GET /api/editor`` and ``POST /api/editor/save``.

The logic (validation, the excerpt check, the write) is ``deck_edit``; this
module is the HTTP side and the in-memory reload, so the picker and the target
card show a save at once. The model's prompt for a live session keeps the old
card text until the next start or Next card.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any, Final

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from plc_lab import cards
from plc_lab.tutor import deck_edit

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from plc_lab.tutor.engine import Engine

ReadJson = Callable[["Request"], Awaitable[dict[str, Any]]]
_JSON: Final = "application/json"
_logger = logging.getLogger(__name__)


def editor_routes(
    eng: Engine, dirs: deck_edit.Dirs, read_json: ReadJson
) -> list[Route]:
    """The editor's two routes, bound to ``eng`` and the deck dirs."""
    lock = asyncio.Lock()  # one save at a time: each is read-modify-write

    async def view(_: Request) -> Response:
        return JSONResponse(await run_in_threadpool(overview, dirs, eng.deck))

    async def save(request: Request) -> Response:
        # JSON only: a cross-site page can POST text/plain to 127.0.0.1
        # without a CORS preflight, but never application/json.
        kind = request.headers.get("content-type", "").split(";")[0].strip()
        if kind != _JSON:
            return JSONResponse({"error": f"send the card as {_JSON}"}, status_code=415)
        body = await read_json(request)
        async with lock:
            return await _save(eng, dirs, body)

    return [
        Route("/api/editor", view),
        Route("/api/editor/save", save, methods=["POST"]),
    ]


async def _save(eng: Engine, dirs: deck_edit.Dirs, body: dict[str, Any]) -> Response:
    """Check (off the event loop: the source fetch blocks), write, reload."""
    try:
        planned = await run_in_threadpool(
            deck_edit.prepare, dirs, deck_edit.parse(body)
        )
    except deck_edit.EditError as err:
        _logger.warning("deck edit refused: %s", err)
        return JSONResponse({"error": str(err)}, status_code=400)
    try:
        deck_edit.write(dirs, planned)
        deck = cards.load_deck(dirs.live)
    except (OSError, ValueError) as err:
        _logger.exception("deck edit: write or reload failed")
        return JSONResponse({"error": f"save failed: {err}"}, status_code=500)
    eng.deck = deck
    if eng.card is not None:
        eng.card = next((c for c in deck if c.id == eng.card.id), eng.card)
    return JSONResponse(
        {
            "saved": planned.card.id,
            "note": saved_note(planned.stem),
            "card": card_row(planned.card),
        }
    )


def saved_note(stem: str) -> str:
    """The one line the page shows after a save."""
    return (
        f"Saved to deck/{stem}.json (uncommitted; Anki updates on next build/import)."
    )


def card_row(card: cards.Card) -> dict[str, Any]:
    """One card with every editable field, for the editor's list and form."""
    return {
        "id": card.id,
        "topic": card.topic.stem,
        **{key: getattr(card, key) for key in deck_edit.FIELDS},
        "requires": list(card.requires),
    }


def overview(dirs: deck_edit.Dirs, deck: list[cards.Card]) -> dict[str, Any]:
    """The cards to edit (the repo deck when writable) and the topics."""
    reason = dirs.read_only_reason()
    shown = deck
    if not reason and dirs.src is not None:
        try:
            shown = cards.load_deck(dirs.src)
        except (OSError, ValueError) as err:
            _logger.warning("deck edit: the repo deck does not load: %s", err)
            reason = f"Read-only: the repo deck does not load: {err}"
    base = dirs.src if dirs.src is not None and not reason else dirs.live
    return {
        "writable": not reason,
        "reason": reason,
        "max_lines": deck_edit.MAX_LINES,
        "topics": [
            {
                "stem": t.stem,
                "title": t.title,
                "prefixes": list(t.prefixes),
                "lines": _lines(base / f"{t.stem}.json"),
            }
            for t in cards.TOPICS
        ],
        "cards": [card_row(c) for c in shown],
    }


def _lines(path: Path) -> int:
    return path.read_text(encoding="utf-8").count("\n") if path.is_file() else 0
