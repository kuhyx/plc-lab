# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Pictures and diagrams for one tutor turn, and the guard on unseen pictures.

The model names image search terms while writing blind; the pictures found
are shown back to it (:func:`check_images`) and only text written after
seeing them ships with them. A message that ends up with no picture never
refers to one (:func:`unseen_picture_guard`).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Any, Final

from claude_agent_sdk import ClaudeSDKError

from plc_lab.tutor import diagrams, images
from plc_lab.tutor.picture_guard import unseen_picture_guard
from plc_lab.tutor.prompt import image_check

if TYPE_CHECKING:
    from plc_lab.tutor.conversation import Conversation
    from plc_lab.tutor.models import TutorTurn
    from plc_lab.tutor.session import TutorSession
    from plc_lab.tutor.store import Store

# Seconds one term may take (search + download) before it counts as a miss.
FETCH_DEADLINE: Final = 30.0
# What a vision check can fail with: the model (SessionError is a
# RuntimeError), the CLI transport, a timeout (an OSError) or a cached file.
_CHECK_ERRORS: Final = (ClaudeSDKError, RuntimeError, OSError, ValueError)
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    """What attaching media needs: the live session, its state and the store."""

    session: TutorSession
    conv: Conversation
    store: Store


def image_key(image: dict[str, Any]) -> str:
    """One Commons file, however many search terms led to it."""
    return str(image.get("page_url") or image.get("file") or "")


def page_message(turn: TutorTurn) -> dict[str, Any]:
    """The page message for a turn, before media is attached."""
    # The check has its own box: a copy of it in `questions` would be a second.
    check = (turn.check or {}).get("question")
    return {
        "role": "tutor",
        "text": turn.message,
        "questions": [q for q in turn.questions if q != check],
        "low_effort": turn.low_effort,
        "check": turn.check,
        "check_result": turn.check_result,
        "images": [],
        "diagrams": [],
    }


async def attach(live: Turn, turn: TutorTurn, message: dict[str, Any]) -> None:
    """Render the turn's diagram, find and vet its pictures, guard the text."""
    if turn.diagram is not None:
        try:
            names = await asyncio.to_thread(diagrams.render, turn.diagram)
            message["diagrams"] = names
            message["diagram_title"] = turn.diagram.get("title", "")
        except diagrams.DiagramError as err:
            _logger.warning("diagram rejected: %s", err)
            live.conv.notes.append(f"diagram rejected: {err}")
    found = await _find(live, turn)
    if found:
        await check_images(live, turn, found, message)
    if turn.images and not message["images"]:
        _guard(live, message)


def _guard(live: Turn, message: dict[str, Any]) -> None:
    """No picture ships with this message: strip any claim that one does.

    The questions are guarded too: "look at the picture and say what the lever
    is for" is as dangling as a sentence of the prose.
    """
    draft, drawn = message["text"], bool(message["diagrams"])
    sent = unseen_picture_guard(draft, diagram_shown=drawn)
    asked = [unseen_picture_guard(q, diagram_shown=drawn) for q in message["questions"]]
    if sent == draft and asked == message["questions"]:
        return
    _logger.warning("message mentioned a picture none was shown with; edited")
    message["text"], message["questions"] = sent, asked
    live.conv.notes.append(
        "no picture was shown with your last message, but it mentioned one; "
        "the app removed those sentences before the learner saw it"
    )
    live.store.log(
        live.conv.session_id,
        {"type": "picture_guard", "draft": draft, "sent": sent, "questions": asked},
    )


async def _fetch_term(term: str, notes: list[str]) -> images.CommonsImage | None:
    """One term's picture, or None (a miss or a failure, noted for the model)."""
    try:
        image = await asyncio.wait_for(
            asyncio.to_thread(images.fetch, term), FETCH_DEADLINE
        )
    except (OSError, ValueError) as err:  # TimeoutError is an OSError
        _logger.warning("image search %r failed: %s", term, err)
        notes.append(f"image search {term!r} failed: {err}")
        return None
    if image is None:
        notes.append(f"image search {term!r} found nothing")
    return image


async def _find(live: Turn, turn: TutorTurn) -> list[list[images.CommonsImage]]:
    """New Commons pictures per request (its alternatives that resolved).

    Every term of the turn is fetched at once. A request whose alternatives
    all missed or were already shown on the page has no group.
    """
    notes = live.conv.notes
    shown = {image_key(i) for m in live.conv.messages for i in m.get("images", [])}
    terms = [term for request in turn.images for term in request]
    fetched = iter(await asyncio.gather(*(_fetch_term(t, notes) for t in terms)))
    groups: list[list[images.CommonsImage]] = []
    for request in turn.images:
        group: list[images.CommonsImage] = []
        for term in request:
            image = next(fetched)
            if image is None:
                continue
            if image_key(image.to_json()) in shown:
                notes.append(
                    f"image for {term!r} not repeated: {image.title!r} was "
                    "already shown; refer back to it"
                )
                continue
            shown.add(image_key(image.to_json()))
            group.append(image)
        if group:
            groups.append(group)
    return groups


async def _offer(groups: list[list[images.CommonsImage]]) -> list[dict[str, Any]]:
    """The user message that shows the model its pictures, numbered in order."""
    found = [(n, i) for n, group in enumerate(groups, 1) for i in group]
    head, ask = image_check(
        [f"request {n}, search term {i.term!r}, file {i.title!r}" for n, i in found]
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": head}]
    for number, (_, image) in enumerate(found, 1):
        block = await asyncio.to_thread(images.content_block, image)
        content += [{"type": "text", "text": f"picture {number}:"}, block]
    content.append({"type": "text", "text": ask})
    return content


def _kept(
    groups: list[list[images.CommonsImage]], keep: set[str]
) -> list[images.CommonsImage]:
    """The first picture of each request whose number the model kept."""
    kept: list[images.CommonsImage] = []
    number = 0
    for group in groups:
        chosen = None
        for image in group:
            number += 1
            if chosen is None and str(number) in keep:
                chosen = image
        if chosen is not None:
            kept.append(chosen)
    return kept


async def check_images(
    live: Turn,
    turn: TutorTurn,
    found: list[list[images.CommonsImage]],
    message: dict[str, Any],
) -> None:
    """Show the model its pictures; only text written after seeing them ships.

    One call covers every candidate of the turn. For each request the first
    alternative the model keeps is used; later ones are dropped.

    The draft was written blind (the prompt forbids describing a picture
    there), so on any failure the draft goes out with no pictures at all.
    """
    started = time.monotonic()
    try:
        checked, reply = await live.session.ask(await _offer(found))
    except _CHECK_ERRORS as err:
        _logger.warning("image check failed, no pictures shown: %s", err)
        live.conv.notes.append(
            f"image check failed ({err}); no pictures were shown and your "
            "message went out as drafted"
        )
        live.store.log(live.conv.session_id, {"type": "image_check", "error": str(err)})
        return
    keep = {"".join(c for c in n if c.isdigit()) for r in checked.images for n in r}
    kept = _kept(found, keep)
    offered = [img for group in found for img in group]
    message["text"] = checked.message
    message["images"] = [img.to_json() for img in kept]
    if kept and checked.questions:  # reworded to point at a kept picture
        own = (turn.check or {}).get("question")
        message["questions"] = [q for q in checked.questions if q != own]
    for img in offered:
        verdict = "shown" if img in kept else "dropped after you looked at it"
        live.conv.notes.append(f"image {verdict} for {img.term!r}: {img.title}")
    live.store.log(
        live.conv.session_id,
        {
            "type": "image_check",
            "draft": turn.message,
            "offered": [img.title for img in offered],
            "kept": [img.title for img in kept],
            "seconds": round(time.monotonic() - started, 1),
            "session_cost_usd": reply.cost_usd,  # cumulative, per the CLI
        },
    )
