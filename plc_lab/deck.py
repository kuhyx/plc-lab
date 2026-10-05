# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Turn validated cards into a genanki package under the ``Automation`` deck.

anki-guard's ``automation`` quota counts exactly the ``Automation`` deck and
its subdecks, so every topic lands in ``Automation::<topic title>``. Model,
deck and note ids are derived from stable keys, so re-importing an updated
package updates the cards in place instead of duplicating them.
"""

from __future__ import annotations

import hashlib
from html import escape
from typing import TYPE_CHECKING, Final

import genanki

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.cards import Card

ROOT_DECK: Final = "Automation"
_ID_SPACE: Final = 1 << 31
CSS: Final = """
.card { font-family: system-ui, sans-serif; font-size: 20px; text-align: left;
  color: #e6e6e6; background: #1b1d21; padding: 12px; }
.source { margin-top: 14px; font-size: 14px; color: #9aa0a6; }
.source a { color: #8ab4f8; }
.excerpt { font-style: italic; }
"""


def stable_id(key: str) -> int:
    """Deterministic 31-bit id, so a re-import updates instead of duplicating."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % _ID_SPACE


def build_model() -> genanki.Model:
    """The one note type: question, answer, and the source it came from."""
    return genanki.Model(
        stable_id("plc_lab:model:v1"),
        "Automation card (plc-lab)",
        fields=[{"name": "Front"}, {"name": "Back"}, {"name": "Source"}],
        templates=[
            {
                "name": "Card",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}{{Source}}',
            }
        ],
        css=CSS,
    )


def deck_name(card: Card) -> str:
    """The subdeck a card belongs to, e.g. ``Automation::Ladder logic``."""
    return f"{ROOT_DECK}::{card.topic.title}"


def tags(card: Card) -> list[str]:
    """Topic and source host, so a card is findable by where it came from."""
    return [f"topic::{card.topic.stem}", f"src::{card.source_host}"]


def _source_html(card: Card) -> str:
    url = escape(card.source, quote=True)
    return (
        f'<div class="source"><span class="excerpt">"{escape(card.excerpt)}"</span>'
        f'<br><a href="{url}">{escape(card.source_host)}</a></div>'
    )


def build_note(card: Card, model: genanki.Model) -> genanki.Note:
    """One note; its GUID is the card id, so edits update it on re-import."""
    return genanki.Note(
        model=model,
        fields=[escape(card.front), escape(card.back), _source_html(card)],
        tags=tags(card),
        guid=genanki.guid_for("plc_lab", card.id),
    )


def build_package(cards: list[Card]) -> genanki.Package:
    """Every card in its topic subdeck, all under ``Automation``."""
    model = build_model()
    decks: dict[str, genanki.Deck] = {}
    for card in cards:
        name = deck_name(card)
        if name not in decks:
            decks[name] = genanki.Deck(stable_id(f"plc_lab:deck:{name}"), name)
        decks[name].add_note(build_note(card, model))
    return genanki.Package(list(decks.values()))


def write_package(cards: list[Card], out: Path) -> Path:
    """Write the ``.apkg`` to ``out`` and return it."""
    out.parent.mkdir(parents=True, exist_ok=True)
    build_package(cards).write_to_file(str(out))
    return out
