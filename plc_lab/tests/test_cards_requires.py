# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Tests for the optional ``requires`` field: its shape, ids and cycles."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.cards import TOPICS, CardError, load_deck, load_topic
from plc_lab.cli import DECK_DIR
from plc_lab.deck import build_model, build_note
from plc_lab.tests.test_cards import LADDER, card, full_deck, write

if TYPE_CHECKING:
    from pathlib import Path


def ladder(tmp_path: Path, *cards: dict[str, Any]) -> Path:
    """A full deck whose ladder file holds ``cards`` (fundamentals stays one card)."""
    root = full_deck(tmp_path)
    write(root / "ladder.json", list(cards))
    return root


def test_requires_loads_as_a_tuple(tmp_path: Path) -> None:
    root = ladder(
        tmp_path, card(id="ld-a"), card(id="ld-b", requires=[" ld-a ", "fund-x"])
    )
    write(root / "fundamentals.json", [card(id="fund-x")])
    cards = {c.id: c for c in load_deck(root)}
    assert cards["ld-b"].requires == ("ld-a", "fund-x")
    assert cards["ld-a"].requires == ()


def test_an_empty_requires_list_is_allowed(tmp_path: Path) -> None:
    [loaded] = load_topic(write(tmp_path / "l.json", [card(requires=[])]), LADDER)
    assert loaded.requires == ()


@pytest.mark.parametrize(
    "bad", ["ld-a", [""], ["  "], [1], [{"id": "ld-a"}], ["ld-a", "ld-a"], None]
)
def test_requires_must_be_distinct_id_strings(tmp_path: Path, bad: object) -> None:
    path = write(tmp_path / "l.json", [card(requires=bad)])
    with pytest.raises(CardError, match="requires must be a list of distinct card"):
        load_topic(path, LADDER)


def test_an_unknown_extra_key_is_still_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "l.json", [card(needs=["ld-a"])])
    with pytest.raises(CardError, match="optionally 'requires'"):
        load_topic(path, LADDER)


def test_a_card_cannot_require_itself(tmp_path: Path) -> None:
    path = write(tmp_path / "l.json", [card(requires=["ld-seal-in"])])
    with pytest.raises(CardError, match="cannot require itself"):
        load_topic(path, LADDER)


def test_every_required_id_must_exist(tmp_path: Path) -> None:
    root = ladder(tmp_path, card(id="ld-a", requires=["ld-gone"]))
    with pytest.raises(
        CardError, match=r"ld-a requires unknown card\(s\) \['ld-gone'\]"
    ):
        load_deck(root)


def test_a_requires_cycle_is_rejected(tmp_path: Path) -> None:
    root = ladder(
        tmp_path,
        card(id="ld-a", requires=["ld-b"]),
        card(id="ld-b", requires=["ld-c"]),
        card(id="ld-c", requires=["ld-a"]),
    )
    with pytest.raises(CardError, match="requires cycle: ld-a -> ld-b -> ld-c -> ld-a"):
        load_deck(root)


def test_a_shared_prerequisite_is_not_a_cycle(tmp_path: Path) -> None:
    root = ladder(
        tmp_path,
        card(id="ld-base"),
        card(id="ld-left", requires=["ld-base"]),
        card(id="ld-right", requires=["ld-base"]),
        card(id="ld-top", requires=["ld-left", "ld-right"]),
    )
    assert len(load_deck(root)) == len(TOPICS) + 3


def test_the_real_deck_gates_five_languages_on_the_ten_language_cards() -> None:
    cards = {c.id: c for c in load_deck(DECK_DIR)}
    needs = cards["fund-five-languages"].requires
    assert len(needs) == 10
    assert all(cards[n].topic.stem == "languages" for n in needs)
    assert cards["fund-five-languages"].front == (
        "Name the five PLC programming languages defined by IEC 61131-3 up to its "
        "third edition."
    )


def test_the_anki_note_ignores_requires() -> None:
    gated = next(c for c in load_deck(DECK_DIR) if c.requires)
    model = build_model()
    with_req, without = (
        build_note(gated, model),
        build_note(replace(gated, requires=()), model),
    )
    assert with_req.guid == without.guid
    assert with_req.fields == without.fields
    assert with_req.tags == without.tags
