# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Pictures and diagrams per turn: dedupe, the vision check, the unseen guard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plc_lab.tutor import diagrams, media
from plc_lab.tutor.session import SessionError
from plc_lab.tutor.tests._fakes import FakeSession, turn
from plc_lab.tutor.tests._media_support import DRAFT, live, log, picture, run

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_page_message_carries_questions_but_not_a_copy_of_the_check() -> None:
    check = {"question": "Why 24 V?", "concept": "coil"}
    message = media.page_message(
        turn("Look.", questions=("A?", "Why 24 V?"), check=check)
    )
    assert message["questions"] == ["A?"]  # the check has its own box
    assert message["check"] == check
    assert media.page_message(turn("Look."))["questions"] == []


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
        {
            "coil": picture("coil", "Coil"),
            "relay": picture("relay", "Relay"),
            "third": picture("third", "Third"),
        }
    )
    checked = turn(
        "Picture 1 shows copper wire wound on a core. Why?", images=(("1",),)
    )
    where = live(tmp_path, checked)
    # No cap: all three requests are looked up and offered in ONE check call.
    message = run(where, turn(DRAFT, images=(("coil",), ("relay",), ("third",))))
    assert message["text"] == checked.message
    assert [i["title"] for i in message["images"]] == ["Coil"]
    assert isinstance(where.session, FakeSession)
    content = where.session.prompts[0]
    assert isinstance(content, list)
    assert [b["type"] for b in content].count("image") == 3
    assert len(where.session.prompts) == 1
    assert where.conv.notes == [
        "image shown for 'coil': Coil",
        "image dropped after you looked at it for 'relay': Relay",
        "image dropped after you looked at it for 'third': Third",
    ]
    assert '"kept": ["Coil"]' in log(where)


def test_search_misses_and_repeats_become_notes_and_the_draft_is_guarded(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons.update({"coil": OSError("timed out"), "relay": None})
    where = live(tmp_path)
    message = run(where, turn(DRAFT, images=(("coil",), ("relay",))))
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
    message = run(where, turn("A coil is wound wire. Why?", images=(("coil",),)))
    assert where.conv.notes == [
        "image for 'coil' not repeated: 'Coil' was already shown; refer back to it"
    ]
    assert message["text"] == "A coil is wound wire. Why?"


def test_failed_vision_check_ships_no_pictures_and_no_claim(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons["coil"] = picture("coil", "Coil")
    where = live(tmp_path, SessionError("model timed out"))
    message = run(where, turn(DRAFT, images=(("coil",),)))
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
    message = run(where, turn(DRAFT, images=(("coil",),)))
    assert message["images"] == []
    assert message["text"] == "What does a coil do?"


def test_image_key_prefers_the_page_url() -> None:
    assert media.image_key({"page_url": "p", "file": "f"}) == "p"
    assert media.image_key({"file": "f"}) == "f"
    assert media.image_key({}) == ""
