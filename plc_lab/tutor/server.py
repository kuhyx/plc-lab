# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The local web page: a small Starlette app bound to 127.0.0.1 only."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
import traceback
from typing import TYPE_CHECKING, Any, Final

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from plc_lab.tutor import diagrams, feedback, feedback_snapshot, images
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.session import SessionError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine

    from starlette.requests import Request

_logger = logging.getLogger(__name__)
STATIC: Final = Path(__file__).parent / "static"
_SAFE_NAME: Final = re.compile(r"^[0-9a-f]{16}(-\d)?\.(png|jpg|svg)$")


def create_app(
    engine: Engine | None = None, *, media_dirs: tuple[Path, Path] | None = None
) -> Starlette:
    """Build the app; ``engine`` and ``media_dirs`` are injectable for tests."""
    eng = engine or Engine()
    image_dir, diagram_dir = media_dirs or (images.cache_dir(), diagrams.cache_dir())

    async def index(_: Request) -> Response:
        return FileResponse(STATIC / "index.html")

    async def state(_: Request) -> Response:
        return JSONResponse(eng.state())

    async def cards(_: Request) -> Response:
        return JSONResponse(eng.cards())

    async def start(request: Request) -> Response:
        body = await _json(request)
        return await _guard(eng.start(body.get("card_id")))

    async def message(request: Request) -> Response:
        body = await _json(request)
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "empty message"}, status_code=400)
        msg_id = str(body.get("msg_id", ""))[:64]
        return await _guard(eng.reply(text, float(body.get("advance_s", 0)), msg_id))

    async def media(request: Request) -> Response:
        name = request.path_params["name"]
        if not _SAFE_NAME.match(name):
            return Response(status_code=404)
        folder = diagram_dir if name.endswith(".svg") else image_dir
        path = folder / name
        return FileResponse(path) if path.is_file() else Response(status_code=404)

    routes = [
        Route("/", index),
        Route("/api/state", state),
        Route("/api/cards", cards),
        Route("/api/start", start, methods=["POST"]),
        Route("/api/message", message, methods=["POST"]),
        Route("/api/feedback", _feedback_route(eng), methods=["POST"]),
        Route("/media/{name}", media),
        Mount("/static", StaticFiles(directory=STATIC)),
    ]

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        yield
        await eng.close()

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.engine = eng
    return app


def _feedback_route(eng: Engine) -> Callable[[Request], Awaitable[Response]]:
    """POST /api/feedback, bound to ``eng``."""

    async def report(request: Request) -> Response:
        return await _report(eng, await _json(request))

    return report


async def _report(eng: Engine, body: dict[str, Any]) -> Response:
    """Store developer feedback; never touches the conversation or clock."""
    try:
        entry = _feedback_entry(eng, body)
    except ValueError as err:
        _logger.warning("feedback refused: %s", err)
        return JSONResponse(_error_body(err), status_code=400)
    try:
        stored = await run_in_threadpool(feedback.record, entry)
    # Broad: whatever it was, the page shows it to paste back.
    except Exception as err:  # pylint: disable=broad-exception-caught
        _logger.exception("could not store feedback")
        return JSONResponse(_error_body(err), status_code=500)
    return JSONResponse({"id": stored["id"], "markdown": feedback.to_markdown(stored)})


def _feedback_entry(eng: Engine, body: dict[str, Any]) -> dict[str, Any]:
    """The report to store; snapshots come from the server's own messages."""
    scoped = body.get("message_index") is not None
    if scoped and body.get("session_id") != eng.session_id:
        msg = "the session changed since this message was shown; reload the page"
        raise ValueError(msg)
    category, text, index = feedback.validate(body, len(eng.messages))
    entry: dict[str, Any] = {
        "category": category,
        "text": text,
        "session_id": eng.session_id or None,
        "card_id": eng.card.id if eng.card else None,
        "page_url": str(body.get("page_url", ""))[:500],
        "user_agent": str(body.get("user_agent", ""))[:500],
    }
    if index is not None:
        entry["message_index"] = index
        entry["snapshot"] = feedback_snapshot.snapshot(eng.messages, index)
    return entry


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as err:
        _logger.warning("%s body is not JSON: %s", request.url.path, err)
        return {}
    return body if isinstance(body, dict) else {}


async def _guard(call: Coroutine[Any, Any, dict[str, Any]]) -> Response:
    try:
        return JSONResponse(await call)
    except (SessionError, ValueError, RuntimeError, TimeoutError) as err:
        _logger.warning("tutor call failed: %s", err)
        return JSONResponse(_error_body(err), status_code=502)
    # Broad: whatever it was, the page shows it to paste back.
    except Exception as err:  # pylint: disable=broad-exception-caught
        _logger.exception("unhandled tutor error")
        return JSONResponse(_error_body(err), status_code=500)


def _error_body(err: BaseException) -> dict[str, str]:
    """Error JSON with the traceback: bound to 127.0.0.1, so only kuhy sees it."""
    return {
        "error": str(err) or type(err).__name__,
        "type": type(err).__name__,
        "traceback": "".join(traceback.format_exception(err)),
    }
