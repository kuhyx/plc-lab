# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The system prompt, the image-check text and the per-turn engine note."""

from __future__ import annotations

from plc_lab.cards import Card, Topic
from plc_lab.tutor.conversation import MAX_CHECK_ATTEMPTS
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


def test_a_check_question_is_never_repeated_in_the_message() -> None:
    # 2026-10-10: the model put the question in both `message` and `check`,
    # and the page printed it twice.
    text = " ".join(system_prompt(CARD, []).split())
    assert "`message` must NOT state or paraphrase the question" in text
    assert "put the whole question only in `check.question`" in text
    assert "its question appears only there, never also in `message`" in text


def test_every_question_goes_in_questions_never_in_the_message() -> None:
    # 2026-10-11: several questions per turn sat in the prose and the learner
    # had to copy each one out to answer it.
    text = " ".join(system_prompt(CARD, []).split())
    assert "EVERY question or task for the learner goes in `questions`" in text
    assert "one per entry, and NEVER in `message`" in text
    assert "one entry in `questions` per term" in text
    assert "`questions` (each question or task, one per entry)" in text
    assert "exactly one question" not in text


def test_a_check_never_asks_more_than_the_card_front() -> None:
    text = " ".join(system_prompt(CARD, []).split())
    assert "A check never asks for more than the card's front asks" in text
    assert '"Name the five languages"' in text
    assert 'not "and describe each"' in text


def test_image_check_keeps_questions_out_of_the_message() -> None:
    _, ask = image_check(["search term 'a'"])
    assert "put no question in `message`" in ask
    assert "`questions` too" in ask
    assert "alternatives for ONE picture" in ask
    assert "never by the numbers above" in ask


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
    assert "check_open: yes - attempt 1 of 2: grade the learner's answer" in note
    assert "re-pose the SAME core question in `check`" in note
    assert note.endswith("images_shown: 1\nextra\n[/engine note]")


def test_engine_note_last_attempt_closes_the_check() -> None:
    note = engine_note(30, 0, check_open=True, notes=[], attempt=MAX_CHECK_ATTEMPTS)
    assert f"attempt {MAX_CHECK_ATTEMPTS} of {MAX_CHECK_ATTEMPTS}, the last" in note
    assert "do NOT pose it again" in note
    assert "re-pose" not in note


def test_wrap_learner_fences_the_words() -> None:
    assert wrap_learner("hi") == "<learner>\nhi\n</learner>"


def test_visuals_rule_demands_images_and_names_working_terms() -> None:
    text = system_prompt(CARD, [])
    assert "MUST request at least one image" in text
    assert "NO cap" in text
    assert '{"terms": [...]}' in text
    for good in ("relay internal", "photoelectric switch", "remote io module"):
        assert f'"{good}"' in text
    assert '"relay cutaway"' not in text
