# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Pictures and diagrams per turn: dedupe, the vision check, the unseen guard."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor import diagrams, images, media
from plc_lab.tutor.clock import EngagementClock
from plc_lab.tutor.conversation import Conversation
from plc_lab.tutor.media import NO_PICTURE_NOTICE, unseen_picture_guard
from plc_lab.tutor.session import SessionError
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, turn

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


@pytest.fixture
def commons(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """term -> CommonsImage, None, or an exception to raise."""
    found: dict[str, Any] = {}

    def fetch(term: str) -> Any:
        hit = found[term]
        if isinstance(hit, Exception):
            raise hit
        return hit

    monkeypatch.setattr(images, "fetch", fetch)
    monkeypatch.setattr(
        images, "content_block", lambda img: {"type": "image", "file": img.file}
    )
    return found


def test_guard_leaves_text_without_picture_words_alone() -> None:
    text = "A coil is wire wound round a core. What does current do in it?"
    assert unseen_picture_guard(text, diagram_shown=False) == text


def test_guard_drops_sentences_that_mention_a_picture() -> None:
    assert (
        unseen_picture_guard(DRAFT, diagram_shown=False)
        == "What happens when current flows?"
    )
    text = "See the photo.\n\nA relay is a switch.\n\nWhat moves it?"
    assert unseen_picture_guard(text, diagram_shown=False) == (
        "A relay is a switch.\n\nWhat moves it?"
    )


def test_guard_keeps_a_diagram_that_was_drawn() -> None:
    text = "The diagram has two loops. Which one has the lamp?"
    assert unseen_picture_guard(text, diagram_shown=True) == text
    assert unseen_picture_guard(text, diagram_shown=False) == "Which one has the lamp?"


def test_guard_appends_a_notice_when_stripping_would_lose_the_question() -> None:
    text = "A relay is a switch. What do you see in the image?"
    assert unseen_picture_guard(text, diagram_shown=False) == (
        f"{text}\n\n{NO_PICTURE_NOTICE}"
    )
    only = "Look at this picture."
    assert unseen_picture_guard(only, diagram_shown=False) == (
        f"{only}\n\n{NO_PICTURE_NOTICE}"
    )


def test_no_media_requested_changes_nothing(tmp_path: Path) -> None:
    where = live(tmp_path)
    message = run(where, turn(DRAFT))
    assert message["text"] == DRAFT  # no picture asked for: not a blind claim
    assert where.conv.notes == []


def test_diagram_rendered_or_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {"title": "Two loops", "circuits": []}
    monkeypatch.setattr(diagrams, "render", lambda _spec: ["abc-0.svg"])
    message = run(live(tmp_path), turn(diagram=spec))
    assert message["diagrams"] == ["abc-0.svg"]
    assert message["diagram_title"] == "Two loops"

    def reject(_spec: object) -> list[str]:
        msg = "bad kind"
        raise diagrams.DiagramError(msg)

    monkeypatch.setattr(diagrams, "render", reject)
    where = live(tmp_path)
    assert run(where, turn(diagram=spec))["diagrams"] == []
    assert where.conv.notes == ["diagram rejected: bad kind"]


def test_checked_pictures_ship_with_the_rewritten_text(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons.update(
        {"coil": picture("coil", "Coil"), "relay": picture("relay", "Relay")}
    )
    checked = turn("Picture 1 shows copper wire wound on a core. Why?", images=("1",))
    where = live(tmp_path, checked)
    message = run(where, turn(DRAFT, images=("coil", "relay", "third")))
    assert message["text"] == checked.message
    assert [i["title"] for i in message["images"]] == ["Coil"]
    assert isinstance(where.session, FakeSession)
    content = where.session.prompts[0]
    assert isinstance(content, list)
    assert [b["type"] for b in content].count("image") == 2
    assert where.conv.notes == [
        "image shown for 'coil': Coil",
        "image dropped after you looked at it for 'relay': Relay",
    ]
    assert '"kept": ["Coil"]' in log(where)


def test_search_misses_and_repeats_become_notes_and_the_draft_is_guarded(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons.update({"coil": OSError("timed out"), "relay": None})
    where = live(tmp_path)
    message = run(where, turn(DRAFT, images=("coil", "relay")))
    assert message["images"] == []
    assert message["text"] == "What happens when current flows?"
    assert where.conv.notes[:2] == [
        "image search 'coil' failed: timed out",
        "image search 'relay' found nothing",
    ]
    assert "removed those sentences" in where.conv.notes[2]
    assert '"type": "picture_guard"' in log(where)

    shown = picture("coil", "Coil")
    commons["coil"] = shown
    where = live(tmp_path)
    where.conv.messages.append({"role": "tutor", "images": [shown.to_json()]})
    message = run(where, turn("A coil is wound wire. Why?", images=("coil",)))
    assert where.conv.notes == [
        "image for 'coil' not repeated: 'Coil' was already shown; refer back to it"
    ]
    assert message["text"] == "A coil is wound wire. Why?"


def test_failed_vision_check_ships_no_pictures_and_no_claim(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons["coil"] = picture("coil", "Coil")
    where = live(tmp_path, SessionError("model timed out"))
    message = run(where, turn(DRAFT, images=("coil",)))
    assert message["images"] == []
    assert "picture" not in message["text"].lower()
    assert message["text"] == "What happens when current flows?"
    assert where.conv.notes[0].startswith("image check failed (model timed out)")
    assert '"error": "model timed out"' in log(where)


def test_check_that_drops_every_picture_is_guarded_too(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons["coil"] = picture("coil", "Coil")
    rewrite = turn("Sadly the image is unclear. What does a coil do?", images=())
    where = live(tmp_path, rewrite)
    message = run(where, turn(DRAFT, images=("coil",)))
    assert message["images"] == []
    assert message["text"] == "What does a coil do?"


def test_image_key_prefers_the_page_url() -> None:
    assert media.image_key({"page_url": "p", "file": "f"}) == "p"
    assert media.image_key({"file": "f"}) == "f"
    assert media.image_key({}) == ""
