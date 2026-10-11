# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The unseen-picture guard: sentences that mention a picture that is not there."""

from __future__ import annotations

from plc_lab.tutor.picture_guard import NO_PICTURE_NOTICE, unseen_picture_guard
from plc_lab.tutor.tests._media_support import DRAFT


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
