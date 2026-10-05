# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Tests for plc_lab.cards: the topic-file format and its validation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.cards import TOPICS, CardError, load_deck, load_topic

if TYPE_CHECKING:
    from pathlib import Path

LADDER = next(t for t in TOPICS if t.stem == "ladder")


def card(**over: Any) -> dict[str, Any]:
    base = {
        "id": "ld-seal-in",
        "front": "What keeps a motor running after Start is released?",
        "back": "A seal-in contact of the motor's own output in parallel with Start.",
        "source": "https://en.wikipedia.org/wiki/Ladder_logic",
        "excerpt": "one two three four five six seven",
    }
    return base | over


def write(path: Path, cards: object) -> Path:
    path.write_text(json.dumps(cards), encoding="utf-8")
    return path


def full_deck(tmp_path: Path) -> Path:
    for topic in TOPICS:
        cid = f"{topic.prefixes[0]}{topic.stem}"
        write(tmp_path / f"{topic.stem}.json", [card(id=cid)])
    return tmp_path


class TestLoadTopic:
    def test_a_valid_card_loads(self, tmp_path: Path) -> None:
        [loaded] = load_topic(write(tmp_path / "ladder.json", [card()]), LADDER)
        assert loaded.id == "ld-seal-in"
        assert loaded.topic is LADDER
        assert loaded.source_host == "en.wikipedia.org"

    def test_www_is_dropped_from_the_host(self, tmp_path: Path) -> None:
        path = write(tmp_path / "l.json", [card(source="https://www.modbus.org/x")])
        assert load_topic(path, LADDER)[0].source_host == "modbus.org"

    def test_the_file_must_be_an_array(self, tmp_path: Path) -> None:
        with pytest.raises(CardError, match="JSON array"):
            load_topic(write(tmp_path / "l.json", {"id": "x"}), LADDER)

    @pytest.mark.parametrize(
        "bad",
        [card() | {"extra": "x"}, {"id": "ld-x"}, "not an object"],
    )
    def test_exact_keys(self, tmp_path: Path, bad: object) -> None:
        with pytest.raises(CardError, match="exactly"):
            load_topic(write(tmp_path / "l.json", [bad]), LADDER)

    def test_fields_must_be_non_empty_strings(self, tmp_path: Path) -> None:
        with pytest.raises(CardError, match="non-empty string"):
            load_topic(write(tmp_path / "l.json", [card(back="  ")]), LADDER)

    @pytest.mark.parametrize(
        ("over", "problem"),
        [
            ({"id": "fund-x"}, "id must start"),
            ({"source": "http://example.org"}, "https URL"),
            ({"source": "https://"}, "https URL"),
            ({"front": "w " * 26}, "front is over"),
            ({"back": "w " * 31}, "back is over"),
            ({"excerpt": "too short"}, "excerpt must be"),
            ({"excerpt": "w " * 41}, "excerpt must be"),
        ],
    )
    def test_each_rule(
        self, tmp_path: Path, over: dict[str, str], problem: str
    ) -> None:
        with pytest.raises(CardError, match=problem):
            load_topic(write(tmp_path / "l.json", [card(**over)]), LADDER)


class TestLoadDeck:
    def test_every_topic_in_order(self, tmp_path: Path) -> None:
        cards = load_deck(full_deck(tmp_path))
        assert [c.topic.stem for c in cards] == [t.stem for t in TOPICS]

    def test_a_missing_topic_file_is_an_error(self, tmp_path: Path) -> None:
        (full_deck(tmp_path) / "protocols.json").unlink()
        with pytest.raises(CardError, match="missing topic file"):
            load_deck(tmp_path)

    def test_ids_are_unique_across_the_deck(self, tmp_path: Path) -> None:
        deck = full_deck(tmp_path)
        write(deck / "ladder.json", [card(), card()])
        with pytest.raises(CardError, match="duplicate card id ld-seal-in"):
            load_deck(deck)
