# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Tests for plc_lab.deck: deck names, stable ids, tags, the written package."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
import zipfile

from plc_lab.cards import TOPICS, Card
from plc_lab.deck import (
    ROOT_DECK,
    build_model,
    build_note,
    build_package,
    deck_name,
    stable_id,
    tags,
    write_package,
)

if TYPE_CHECKING:
    from pathlib import Path


def make(cid: str, stem: str = "ladder") -> Card:
    topic = next(t for t in TOPICS if t.stem == stem)
    return Card(
        id=cid,
        front="Q <b>?",
        back="A & B",
        source="https://www.example.org/page?a=1&b=2",
        excerpt='a "quoted" excerpt',
        topic=topic,
    )


def test_stable_id_is_deterministic_and_31_bit() -> None:
    assert stable_id("x") == stable_id("x")
    assert stable_id("x") != stable_id("y")
    assert 0 <= stable_id("x") < 1 << 31


def test_every_subdeck_is_under_the_automation_root() -> None:
    """anki-guard's automation quota counts Automation and its subdecks only."""
    assert ROOT_DECK == "Automation"
    assert deck_name(make("ld-a")) == "Automation::Ladder logic"


def test_tags_name_the_topic_and_the_source_host() -> None:
    assert tags(make("ld-a")) == ["topic::ladder", "src::example.org"]


def test_note_escapes_html_and_keys_its_guid_on_the_card_id() -> None:
    model = build_model()
    note = build_note(make("ld-a"), model)
    front, back, source = note.fields
    assert front == "Q &lt;b&gt;?"
    assert back == "A &amp; B"
    assert "&quot;quoted&quot;" in source
    assert 'href="https://www.example.org/page?a=1&amp;b=2"' in source
    assert note.guid == build_note(make("ld-a"), model).guid
    assert note.guid != build_note(make("ld-b"), model).guid


def test_package_has_one_deck_per_topic() -> None:
    package = build_package([make("ld-a"), make("ld-b"), make("net-a", "protocols")])
    names = sorted(d.name for d in package.decks)
    assert names == ["Automation::Ladder logic", "Automation::Protocols"]
    ladder = next(d for d in package.decks if d.name.endswith("Ladder logic"))
    assert len(ladder.notes) == 2


def test_write_package_produces_an_importable_apkg(tmp_path: Path) -> None:
    out = write_package([make("ld-a")], tmp_path / "build" / "deck.apkg")
    with zipfile.ZipFile(out) as apkg:
        apkg.extract("collection.anki2", tmp_path)
    with sqlite3.connect(tmp_path / "collection.anki2") as db:
        assert db.execute("SELECT count(*) FROM notes").fetchone() == (1,)
    db.close()
