# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Helpers shared by the media tests: a live turn, a run and a log reader."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from plc_lab.tutor import images, media
from plc_lab.tutor.clock import EngagementClock
from plc_lab.tutor.conversation import Conversation
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.models import TutorTurn

DRAFT = "The picture shows a coil on a nail. What happens when current flows?"


def picture(term: str, title: str) -> images.CommonsImage:
    return images.CommonsImage(
        term, title, f"{title}.jpg", "A. Author", "CC BY", "", f"https://c/{title}"
    )


def live(tmp_path: Path, *replies: TutorTurn | Exception) -> media.Turn:
    conv = Conversation("s1", "card", EngagementClock(0.0))
    return media.Turn(FakeSession(*replies), conv, Store(tmp_path / "data"))


def run(where: media.Turn, draft: TutorTurn) -> dict[str, Any]:
    message = media.page_message(draft)
    asyncio.run(media.attach(where, draft, message))
    return message


def log(where: media.Turn) -> str:
    return (where.store.root / "sessions" / "s1.jsonl").read_text()
