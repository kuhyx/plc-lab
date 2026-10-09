# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The system prompt, the image-check text and the per-turn engine note."""

from __future__ import annotations

from plc_lab.cards import Card, Topic
from plc_lab.tutor.prompt import (
    CHECK_EVERY_SECONDS,
    engine_note,
    image_check,
    system_prompt,
    wrap_learner,
)

CARD = Card(
    id="io-24vdc-relay-coil",
    front="Typical relay coil voltage?",
    back="24 V DC",
    source="https://example.org/relay",
    excerpt="coils are usually 24 V DC",
    topic=Topic(stem="io", title="Field I/O", prefixes=("io",)),
)


def test_system_prompt_without_mastered() -> None:
    text = system_prompt(CARD, [])
    assert "topic: Field I/O" in text
    assert "id: io-24vdc-relay-coil" in text
    assert "question: Typical relay coil voltage?" in text
    assert "answer (do not reveal early): 24 V DC" in text
    assert "source: https://example.org/relay" in text
    assert "verbatim excerpt: coils are usually 24 V DC" in text
    assert text.endswith("# Already mastered concepts\n(none yet)\n")


def test_system_prompt_lists_mastered_concepts() -> None:
    text = system_prompt(CARD, ["voltage", "coil"])
    assert text.endswith("# Already mastered concepts\nvoltage, coil\n")
    assert "(none yet)" not in text


def test_image_check_labels_each_picture() -> None:
    head, ask = image_check(["search term 'a', file 'x.jpg'", "search term 'b'"])
    assert "picture 1: search term 'a', file 'x.jpg'" in head
    assert "picture 2: search term 'b'" in head
    assert head.startswith("[engine note]")
    assert head.endswith("[/engine note]")
    assert "`images`" in ask


def test_engine_note_check_due() -> None:
    note = engine_note(
        CHECK_EVERY_SECONDS * 2, CHECK_EVERY_SECONDS, check_open=False, notes=[]
    )
    assert "active_minutes: 20.0" in note
    assert "minutes_since_last_check: 10.0" in note
    assert "check_due: yes - pose one now" in note
    assert "check_open: no" in note


def test_engine_note_not_due_before_threshold() -> None:
    note = engine_note(60, CHECK_EVERY_SECONDS - 1, check_open=False, notes=[])
    assert "check_due: no" in note


def test_engine_note_check_open_suppresses_due_and_adds_notes() -> None:
    note = engine_note(
        30, CHECK_EVERY_SECONDS, check_open=True, notes=["images_shown: 1", "extra"]
    )
    assert "check_due: no" in note
    assert "check_open: yes - grade the learner answer in check_result" in note
    assert note.endswith("images_shown: 1\nextra\n[/engine note]")


def test_wrap_learner_fences_the_words() -> None:
    assert wrap_learner("hi") == "<learner>\nhi\n</learner>"
