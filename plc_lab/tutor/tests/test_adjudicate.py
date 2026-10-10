# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Acceptance verdicts over synthetic session transcripts."""

from __future__ import annotations

import json
import runpy
import sys
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor import adjudicate
from plc_lab.tutor.adjudicate import (
    MIN_UNCHECKED_BLOCK,
    anchors,
    load,
    message_indices,
    verdicts,
)
from plc_lab.tutor.models import REQUIRED_FIELDS

if TYPE_CHECKING:
    from pathlib import Path

IMAGE = {"title": "Relay", "author": "A", "licence": "CC0", "page_url": "https://x"}
DIAGRAM = {"title": "circuit"}


def tutor_event(message: str, ui: dict[str, Any] | None = None, **fields: Any) -> Any:
    """One tutor transcript event with every structured field."""
    turn: dict[str, Any] = dict.fromkeys(REQUIRED_FIELDS)
    turn.update(message=message, low_effort=False, check=None, check_result=None)
    turn.update(fields)
    return {"type": "tutor", "turn": turn, "ui": ui or {}}


def good() -> list[dict[str, Any]]:
    """A transcript that satisfies every acceptance item."""
    return [
        tutor_event("What do you know about voltage, current, DC, coil, relay?"),
        tutor_event(
            "Voltage pushes current; DC flows one way; a coil in a relay.",
            ui={"images": [IMAGE], "diagrams": [DIAGRAM]},
            check={"question": "q", "concept": "coil"},
        ),
        tutor_event(
            "Right: typically 24 V.",
            ui={"card_done": True},
            check_result={"passed": True, "feedback": "ok"},
            low_effort=True,
        ),
        {"type": "learner", "text": "ok"},
        {"type": "credit", "recorded": True, "block": 20, "checks_passed": 0},
        {"type": "next_card"},
    ]


def results(events: list[dict[str, Any]]) -> dict[str, bool]:
    """Item letter to pass/fail."""
    return {item[0]: ok for item, ok, _ in verdicts(events)}


def test_good_transcript_passes_everything() -> None:
    assert results(good()) == dict.fromkeys("abcdefgh", True)


def test_empty_transcript_fails_everything() -> None:
    assert results([]) == dict.fromkeys("abcdefgh", False)


def test_a_fails_without_question_or_terms_or_when_answering() -> None:
    no_ask = good()
    no_ask[0] = tutor_event("Voltage current DC coil relay.")
    assert not results(no_ask)["a"]
    few_terms = good()
    few_terms[0] = tutor_event("What do you know about voltage?")
    assert not results(few_terms)["a"]
    answers = good()
    answers[0] = tutor_event("Voltage current DC coil relay? Typically 24 V.")
    assert not results(answers)["a"]


def test_a_accepts_an_imperative_instead_of_a_question_mark() -> None:
    events = good()
    events[0] = tutor_event("Tell me about voltage, current, DC, coil, relay.")
    assert results(events)["a"]


def test_b_fails_when_a_term_is_never_taught_before_the_answer() -> None:
    events = good()
    events[1] = tutor_event("Voltage pushes current through a coil.")
    assert not results(events)["b"]
    late = good()
    late[1], late[2] = late[2], late[1]
    assert not results(late)["b"]


@pytest.mark.parametrize("missing", ["author", "licence", "page_url"])
def test_c_fails_on_unattributed_image(missing: str) -> None:
    events = good()
    events[1]["ui"]["images"] = [{**IMAGE, missing: ""}]
    assert not results(events)["c"]


def test_c_fails_without_images_or_diagrams() -> None:
    no_image = good()
    no_image[1]["ui"] = {"diagrams": [DIAGRAM]}
    assert not results(no_image)["c"]
    no_diagram = good()
    no_diagram[1]["ui"] = {"images": [IMAGE]}
    assert not results(no_diagram)["c"]


def test_d_fails_unless_posed_graded_after_and_recorded() -> None:
    no_check = good()
    no_check[1]["turn"]["check"] = None
    assert not results(no_check)["d"]
    no_grade = good()
    no_grade[2]["turn"]["check_result"] = None
    assert not results(no_grade)["d"]
    wrong_order = good()
    wrong_order[1]["turn"]["check"] = None
    wrong_order[2]["turn"]["check"] = {"question": "q", "concept": "c"}
    wrong_order[1]["turn"]["check_result"] = {"passed": True, "feedback": ""}
    wrong_order[2]["turn"]["check_result"] = None
    assert not results(wrong_order)["d"]
    unrecorded = good()
    unrecorded[4]["recorded"] = False
    assert not results(unrecorded)["d"]


def test_e_fails_on_a_missing_field() -> None:
    events = good()
    del events[1]["turn"]["diagram"]
    assert not results(events)["e"]


def test_f_fails_without_low_effort_after_the_first_turn() -> None:
    events = good()
    events[2]["turn"]["low_effort"] = False
    events[0]["turn"]["low_effort"] = True
    assert not results(events)["f"]


def test_anchors_point_at_first_image_first_diagram_and_last() -> None:
    events = good()
    events[2]["ui"] = {"images": [IMAGE]}
    assert anchors(events) == {"last": "m2", "image": "m1", "diagram": "m1"}
    events[1]["ui"] = {}
    assert anchors(events) == {"last": "m2", "image": "m2", "diagram": "m0"}


def test_g_needs_a_recorded_unchecked_credit_after_15_minutes() -> None:
    early = good()
    early[4]["block"] = MIN_UNCHECKED_BLOCK - 1
    assert not results(early)["g"]
    checked = good()
    checked[4]["checks_passed"] = 1
    assert not results(checked)["g"]
    unrecorded = good()
    unrecorded[4]["recorded"] = False
    assert not results(unrecorded)["g"]
    legacy = good()
    del legacy[4]["checks_passed"]
    assert not results(legacy)["g"]


def test_h_needs_a_choice_after_every_card_done() -> None:
    no_done = good()
    no_done[2]["ui"] = {}
    assert not results(no_done)["h"]
    no_choice = good()
    del no_choice[5]
    assert not results(no_choice)["h"]
    stopped = good()
    stopped[5] = {"type": "stop"}
    assert results(stopped)["h"]
    second_done = good()
    second_done.insert(5, tutor_event("again", ui={"card_done": True}))
    assert results(second_done)["h"]
    second_done.insert(6, {"type": "learner", "text": "x"})
    del second_done[-1]
    assert not results(second_done)["h"]


def test_message_indices_follow_the_page_message_count() -> None:
    events = [
        tutor_event("first"),
        {"type": "learner", "text": "a"},
        tutor_event("second"),
        {"type": "learner", "text": "unanswered"},
        {"type": "next_card", "ui": {"title": "divider"}},
        tutor_event("new card"),
        {"type": "next_card"},
        tutor_event("after a bare next_card"),
    ]
    assert message_indices(events) == [0, 2, 4, 5]


def write_jsonl(path: Path, events: list[dict[str, Any]]) -> Path:
    """Write a transcript, with a blank line the loader must skip."""
    body = "\n".join(json.dumps(e) for e in events) + "\n\n"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_skips_blank_lines(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "s.jsonl", good())
    assert load(path) == good()


def test_main_passes_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_jsonl(tmp_path / "ok.jsonl", good())
    assert adjudicate.main(["prog", str(path)]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS") == len("abcdefgh")
    assert "FAIL" not in out
    bad = write_jsonl(tmp_path / "bad.jsonl", good()[:1])
    assert adjudicate.main(["prog", str(bad)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_anchors_prints_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_jsonl(tmp_path / "s.jsonl", good())
    assert adjudicate.main(["prog", "--anchors", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "last": "m2",
        "image": "m1",
        "diagram": "m1",
    }


def test_module_runs_as_a_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = write_jsonl(tmp_path / "s.jsonl", good())
    monkeypatch.setattr(sys, "argv", ["adjudicate", str(path)])
    monkeypatch.delitem(sys.modules, "plc_lab.tutor.adjudicate")
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("plc_lab.tutor.adjudicate", run_name="__main__")
    assert exit_info.value.code == 0
    assert "PASS" in capsys.readouterr().out
