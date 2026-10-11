# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Alternative search terms, concurrency and the questions guard per turn."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from plc_lab.tutor import images, media
from plc_lab.tutor.picture_guard import NO_PICTURE_NOTICE
from plc_lab.tutor.tests._fakes import FakeSession, turn
from plc_lab.tutor.tests._media_support import DRAFT, live, log, picture, run

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def alternatives(*terms: str) -> tuple[tuple[str, ...], ...]:
    return (terms,)


def test_alternatives_resolve_in_order_and_one_picture_per_request(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons.update(
        {
            "relay symbol": None,
            "relay": picture("relay", "Relay"),
            "relay cutaway": picture("relay cutaway", "Cutaway"),
            "rack": picture("rack", "Rack"),
        }
    )
    both = turn("Pictures 1 and 2 show a relay. Why?", images=(("1",), ("2",)))
    where = live(tmp_path, both)
    request = (("relay symbol", "relay", "relay cutaway"), ("rack",))
    message = run(where, turn(DRAFT, images=request))
    # The model kept 1 and 2, both alternatives of request 1: only the first counts.
    assert [i["title"] for i in message["images"]] == ["Relay"]
    assert "image search 'relay symbol' found nothing" in where.conv.notes
    assert isinstance(where.session, FakeSession)
    content = where.session.prompts[0]
    assert isinstance(content, list)
    assert "picture 1: request 1, search term 'relay'" in content[0]["text"]
    assert "picture 3: request 2, search term 'rack'" in content[0]["text"]


def test_second_alternative_is_used_when_the_first_is_dropped(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons.update(
        {"relay": picture("relay", "Relay"), "relay cutaway": picture("c", "Cutaway")}
    )
    where = live(tmp_path, turn("Picture 2 is a cutaway.", images=(("2",),)))
    message = run(where, turn(DRAFT, images=alternatives("relay", "relay cutaway")))
    assert [i["title"] for i in message["images"]] == ["Cutaway"]


def test_same_file_from_two_terms_is_offered_once(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    same = picture("relay", "Relay")
    commons.update({"relay": same, "relay switch": same})
    where = live(tmp_path, turn("Picture 1 is a relay.", images=(("1",),)))
    message = run(where, turn(DRAFT, images=alternatives("relay", "relay switch")))
    assert [i["title"] for i in message["images"]] == ["Relay"]
    assert "not repeated" in where.conv.notes[0]


def test_kept_picture_can_reword_the_questions_but_not_the_check(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons["relay"] = picture("relay", "Relay")
    check = {"question": "Why 24 V?", "concept": "coil"}
    reworded = turn(
        "Picture 1 shows a relay.",
        images=(("1",),),
        questions=("What do you think this device is?", "Why 24 V?"),
    )
    where = live(tmp_path, reworded)
    draft = turn(DRAFT, images=alternatives("relay"), check=check, questions=("What?",))
    message = run(where, draft)
    assert message["questions"] == ["What do you think this device is?"]
    # Dropped: the drafted questions stay, whatever the check reply carried.
    where = live(tmp_path, turn("No picture.", questions=("Other?",)))
    assert run(where, draft)["questions"] == ["What?"]


def test_terms_are_fetched_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = threading.Barrier(3, timeout=5)

    def fetch(term: str) -> images.CommonsImage:
        barrier.wait()  # only passes if all three run at once
        return picture(term, term.title())

    monkeypatch.setattr(images, "fetch", fetch)
    monkeypatch.setattr(images, "content_block", lambda img: {"file": img.file})
    where = live(tmp_path, turn("Pictures 1-3.", images=(("1",), ("2",), ("3",))))
    message = run(where, turn(DRAFT, images=(("a",), ("b",), ("c",))))
    assert len(message["images"]) == 3


def test_a_term_that_hangs_is_a_miss_not_a_stall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media, "FETCH_DEADLINE", 0.05)
    monkeypatch.setattr(images, "fetch", lambda _t: time.sleep(0.4))
    where = live(tmp_path)
    message = run(where, turn(DRAFT, images=(("slow",),)))
    assert message["images"] == []
    assert where.conv.notes[0].startswith("image search 'slow' failed")


def test_unshipped_picture_is_stripped_from_the_questions_too(
    tmp_path: Path, commons: dict[str, Any]
) -> None:
    commons["lever"] = None
    where = live(tmp_path)
    draft = turn(
        "A limit switch senses position.",
        images=(("lever",),),
        questions=("Look at the picture: what is the lever for?", "What is a switch?"),
    )
    message = run(where, draft)
    assert message["questions"][1] == "What is a switch?"
    assert message["questions"][0] == (
        f"Look at the picture: what is the lever for?\n\n{NO_PICTURE_NOTICE}"
    )
    assert '"questions"' in log(where)
