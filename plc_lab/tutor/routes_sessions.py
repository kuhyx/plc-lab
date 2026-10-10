# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Session routes: Next card, Stop here, card_done, history and archiving."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from plc_lab.tutor import history

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

    from plc_lab.tutor.engine import Engine

Guard = Callable[[Coroutine[Any, Any, dict[str, Any]]], Awaitable[Response]]
ReadJson = Callable[["Request"], Awaitable[dict[str, Any]]]


def session_routes(eng: Engine, _guard: Guard, _json: ReadJson) -> list[Route]:
    """Next card / Stop here, plus the read-only views of past sessions."""

    async def next_card(_: Request) -> Response:
        return await _guard(eng.next_card())

    async def stop(_: Request) -> Response:
        return await _guard(eng.stop())

    async def card_done(request: Request) -> Response:
        body = await _json(request)
        card_id = str(body.get("card_id", ""))
        if not any(c.id == card_id for c in eng.deck):
            return JSONResponse({"error": f"unknown card {card_id!r}"}, status_code=400)
        return await _guard(
            eng.set_card_done(card_id, done=bool(body.get("done", True)))
        )

    async def session(request: Request) -> Response:
        found = await run_in_threadpool(
            history.session_view,
            _sessions_dir(eng),
            request.path_params["session_id"],
            _view(eng),
        )
        if found is None:
            return JSONResponse({"error": "no such session"}, status_code=404)
        return JSONResponse(found)

    async def sessions(_: Request) -> Response:
        return await _listed(eng)

    async def archive(request: Request) -> Response:
        return await _archive(eng, await _json(request))

    return [
        Route("/api/next", next_card, methods=["POST"]),
        Route("/api/stop", stop, methods=["POST"]),
        Route("/api/card_done", card_done, methods=["POST"]),
        Route("/api/sessions", sessions),
        Route("/api/archive", archive, methods=["POST"]),
        Route("/api/session/{session_id}", session),
    ]


def _sessions_dir(eng: Engine) -> Path:
    return eng.store.root / "sessions"


def _view(eng: Engine) -> history.View:
    """Everything a session view reads from the engine and progress.json now."""
    return history.View(
        fronts={c.id: c.front for c in eng.deck},
        live=eng.session_id,
        done_now=set(eng.store.progress()["cards_done"]),
        archived=set(eng.store.archived()),
    )


async def _listed(eng: Engine) -> Response:
    """The ``/api/sessions`` reply (every session, archived ones included)."""
    view = _view(eng)
    listed = await run_in_threadpool(history.sessions_list, _sessions_dir(eng), view)
    return JSONResponse(listed)


async def _archive(eng: Engine, body: dict[str, Any]) -> Response:
    """Hide or show a session in History; transcripts and credit stay as-is.

    The store write runs on the event loop like the engine's own: progress.json
    is read-modify-write and must not interleave with them.
    """
    sid, flag = body.get("session_id"), body.get("archived")
    if not isinstance(sid, str) or not history.transcript_path(_sessions_dir(eng), sid):
        return JSONResponse({"error": "no such session"}, status_code=404)
    if not isinstance(flag, bool):
        return JSONResponse(
            {"error": "archived must be true or false"}, status_code=400
        )
    if sid == eng.session_id:
        return JSONResponse(
            {"error": "the live session cannot be archived"}, status_code=400
        )
    if flag:
        eng.store.archive(sid)
    else:
        eng.store.unarchive(sid)
    return await _listed(eng)
