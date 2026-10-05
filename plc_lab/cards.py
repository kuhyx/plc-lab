# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Load and validate the deck's topic files.

One JSON file per topic under ``deck/``. Each card names the URL it was written
from and a verbatim excerpt of that page; ``sources.check_excerpt`` is what
proves the excerpt is really there.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Topic:
    """A topic file: its subdeck title and the prefix every card id carries."""

    stem: str
    title: str
    prefixes: tuple[str, ...]


TOPICS: Final = (
    Topic("fundamentals", "Fundamentals", ("fund-",)),
    Topic("ladder", "Ladder logic", ("ld-",)),
    Topic("structured_text", "Structured Text and SFC", ("st-", "sfc-")),
    Topic("field_devices", "Field devices", ("io-",)),
    Topic("protocols", "Protocols", ("net-",)),
    Topic("ot_security", "OT security", ("sec-",)),
)
_KEYS: Final = frozenset({"id", "front", "back", "source", "excerpt"})
_MAX_FRONT_WORDS: Final = 25
_MAX_BACK_WORDS: Final = 30
_EXCERPT_WORDS: Final = (6, 40)


class CardError(ValueError):
    """A topic file breaks the card format."""


@dataclass(frozen=True)
class Card:
    """One note: a question, its answer and the evidence for it."""

    id: str
    front: str
    back: str
    source: str
    excerpt: str
    topic: Topic

    @property
    def source_host(self) -> str:
        """The source's host without ``www.``, used as the card's source tag."""
        return (urlsplit(self.source).hostname or "").removeprefix("www.")


def _words(text: str) -> int:
    return len(text.split())


def _validate(raw: object, topic: Topic, where: str) -> Card:
    """Build a card from one JSON object, or say exactly what is wrong."""
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        msg = f"{where}: a card must be an object with exactly {sorted(_KEYS)}"
        raise CardError(msg)
    if not all(isinstance(raw[key], str) and raw[key].strip() for key in _KEYS):
        msg = f"{where}: every field must be a non-empty string"
        raise CardError(msg)
    card = Card(topic=topic, **{key: raw[key].strip() for key in _KEYS})
    problems = []
    if not card.id.startswith(topic.prefixes):
        problems.append(f"id must start with one of {topic.prefixes}")
    if urlsplit(card.source).scheme != "https" or not urlsplit(card.source).hostname:
        problems.append("source must be an https URL")
    if _words(card.front) > _MAX_FRONT_WORDS:
        problems.append(f"front is over {_MAX_FRONT_WORDS} words")
    if _words(card.back) > _MAX_BACK_WORDS:
        problems.append(f"back is over {_MAX_BACK_WORDS} words")
    low, high = _EXCERPT_WORDS
    if not low <= _words(card.excerpt) <= high:
        problems.append(f"excerpt must be {low}-{high} words")
    if problems:
        msg = f"{where} ({card.id}): " + "; ".join(problems)
        raise CardError(msg)
    return card


def load_topic(path: Path, topic: Topic) -> list[Card]:
    """Every card in one topic file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = f"{path.name}: the file must hold a JSON array of cards"
        raise CardError(msg)
    return [_validate(item, topic, f"{path.name}[{i}]") for i, item in enumerate(raw)]


def load_deck(deck_dir: Path) -> list[Card]:
    """Every card of every topic, with ids unique across the whole deck."""
    cards: list[Card] = []
    for topic in TOPICS:
        path = deck_dir / f"{topic.stem}.json"
        if not path.is_file():
            msg = f"missing topic file {path}"
            raise CardError(msg)
        cards.extend(load_topic(path, topic))
    seen: set[str] = set()
    for card in cards:
        if card.id in seen:
            msg = f"duplicate card id {card.id}"
            raise CardError(msg)
        seen.add(card.id)
    return cards
