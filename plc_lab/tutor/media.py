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
import re
import time
from typing import TYPE_CHECKING, Any, Final

from claude_agent_sdk import ClaudeSDKError

from plc_lab.tutor import diagrams, images
from plc_lab.tutor.prompt import image_check

if TYPE_CHECKING:
    from plc_lab.tutor.conversation import Conversation
    from plc_lab.tutor.models import TutorTurn
    from plc_lab.tutor.session import TutorSession
    from plc_lab.tutor.store import Store

MAX_IMAGES: Final = 2
NO_PICTURE_NOTICE: Final = (
    "(No picture could be shown with this message, so ignore any mention of "
    "one and answer from the text.)"
)
_PICTURE: Final = re.compile(
    r"\b(pictures?|images?|photos?|photographs?|pics?|illustrations?)\b",
    re.IGNORECASE,
)
_DIAGRAM: Final = re.compile(r"\bdiagrams?\b", re.IGNORECASE)
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")
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
    return {
        "role": "tutor",
        "text": turn.message,
        "low_effort": turn.low_effort,
        "check": turn.check,
        "check_result": turn.check_result,
        "images": [],
        "diagrams": [],
    }


def unseen_picture_guard(text: str, *, diagram_shown: bool) -> str:
    """``text`` made safe to send with no picture attached.

    Sentences that mention a picture/image/photo (or a diagram, unless a
    code-drawn one is attached) are removed. If that would leave nothing or
    drop the closing question, the text is kept and :data:`NO_PICTURE_NOTICE`
    is appended instead, so the learner is told no picture is there.
    """

    def mentions(part: str) -> bool:
        return bool(_PICTURE.search(part)) or (
            not diagram_shown and bool(_DIAGRAM.search(part))
        )

    if not mentions(text):
        return text
    lines = []
    for line in text.split("\n"):
        kept = [s for s in _SENTENCE_END.split(line) if not mentions(s)]
        if kept or not line.strip():
            lines.append(" ".join(kept))
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not cleaned or ("?" in text and "?" not in cleaned):
        return f"{text}\n\n{NO_PICTURE_NOTICE}"
    return cleaned


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
    """No picture ships with this message: strip any claim that one does."""
    draft = message["text"]
    sent = unseen_picture_guard(draft, diagram_shown=bool(message["diagrams"]))
    if sent == draft:
        return
    _logger.warning("message mentioned a picture none was shown with; edited")
    message["text"] = sent
    live.conv.notes.append(
        "no picture was shown with your last message, but it mentioned one; "
        "the app removed those sentences before the learner saw it"
    )
    live.store.log(
        live.conv.session_id, {"type": "picture_guard", "draft": draft, "sent": sent}
    )


async def _find(live: Turn, turn: TutorTurn) -> list[images.CommonsImage]:
    """Up to :data:`MAX_IMAGES` new Commons pictures; misses become notes."""
    notes = live.conv.notes
    shown = {image_key(i) for m in live.conv.messages for i in m.get("images", [])}
    found: list[images.CommonsImage] = []
    for term in turn.images[:MAX_IMAGES]:
        try:
            image = await asyncio.to_thread(images.fetch, term)
        except (OSError, ValueError) as err:
            _logger.warning("image search %r failed: %s", term, err)
            notes.append(f"image search {term!r} failed: {err}")
            continue
        if image is None:
            notes.append(f"image search {term!r} found nothing")
        elif image_key(image.to_json()) in shown:
            notes.append(
                f"image for {term!r} not repeated: {image.title!r} was "
                "already shown; refer back to it"
            )
        else:
            shown.add(image_key(image.to_json()))
            found.append(image)
    return found


async def _offer(found: list[images.CommonsImage]) -> list[dict[str, Any]]:
    """The user message that shows the model its pictures."""
    head, ask = image_check(
        [f"search term {i.term!r}, file {i.title!r}" for i in found]
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": head}]
    for number, image in enumerate(found, 1):
        block = await asyncio.to_thread(images.content_block, image)
        content += [{"type": "text", "text": f"picture {number}:"}, block]
    content.append({"type": "text", "text": ask})
    return content


async def check_images(
    live: Turn,
    turn: TutorTurn,
    found: list[images.CommonsImage],
    message: dict[str, Any],
) -> None:
    """Show the model its pictures; only text written after seeing them ships.

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
    keep = {"".join(c for c in item if c.isdigit()) for item in checked.images}
    kept = [img for n, img in enumerate(found, 1) if str(n) in keep]
    message["text"] = checked.message
    message["images"] = [img.to_json() for img in kept]
    for img in found:
        verdict = "shown" if img in kept else "dropped after you looked at it"
        live.conv.notes.append(f"image {verdict} for {img.term!r}: {img.title}")
    live.store.log(
        live.conv.session_id,
        {
            "type": "image_check",
            "draft": turn.message,
            "offered": [img.title for img in found],
            "kept": [img.title for img in kept],
            "seconds": round(time.monotonic() - started, 1),
            "session_cost_usd": reply.cost_usd,  # cumulative, per the CLI
        },
    )
