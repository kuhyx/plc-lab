# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Card gating: a card whose ``requires`` are not all done is locked.

The deck says which cards a card builds on (``cards.Card.requires``); the
tutor alone enforces it, since Anki has no gating. A locked card is skipped by
every auto-pick, refused when started by id, and never marked done, whether by
the tutor's ``card_done`` or by hand. ``cards.load_deck`` already proved the
ids exist and never loop, so some unfinished card is always open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection

    from plc_lab.cards import Card


def missing(card: Card, done: Collection[str]) -> list[str]:
    """The ids ``card`` requires that are not done yet (empty: it is open)."""
    return [need for need in card.requires if need not in done]


def refuse_locked(card: Card, done: Collection[str], action: str) -> None:
    """Raise ``ValueError`` naming what is missing when ``card`` is locked."""
    need = missing(card, done)
    if need:
        msg = f"cannot {action} {card.id!r}: locked until {', '.join(need)} are done"
        raise ValueError(msg)


def first_open(deck: list[Card], done: Collection[str], skip: str = "") -> Card | None:
    """The first card that is neither done, ``skip``, nor locked."""
    return next(
        (c for c in deck if c.id not in done and c.id != skip and not missing(c, done)),
        None,
    )


def pick(deck: list[Card], done: Collection[str], card_id: str | None) -> Card:
    """The card a start opens: ``card_id`` if open, else the first open card."""
    if not card_id:
        card = first_open(deck, done)
        if card is None:
            msg = "no unfinished card left"
            raise ValueError(msg)
        return card
    card = next((c for c in deck if c.id == card_id), None)
    if card is None:
        msg = f"unknown card {card_id!r}"
        raise ValueError(msg)
    refuse_locked(card, done, "start")
    return card


def listing(deck: list[Card], done: Collection[str]) -> list[dict[str, Any]]:
    """``/api/cards``: every card, done or not, and what still locks it."""
    return [
        {
            "id": c.id,
            "front": c.front,
            "topic": c.topic.title,
            "done": c.id in done,
            "requires": list(c.requires),
            "missing": missing(c, done),
            "locked": bool(missing(c, done)),
        }
        for c in deck
    ]


def refused_note(card: Card, need: list[str]) -> str:
    """The engine note when the tutor ends a card that is still locked."""
    return (
        f"card_done refused: {card.id} stays open until the learner has done "
        f"{', '.join(need)}; keep teaching, the learner can switch cards."
    )
