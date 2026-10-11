# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Card editing for the tutor: validate, source-check and write one card.

The live server runs from a frozen release copy (``scripts/tutor_deploy.sh``),
which the next deploy replaces, so an edit written only there would vanish.
A save therefore goes to the repo deck named by ``AUTOMATION_TUTOR_DECK_SRC``
(the source of truth) and to the server's own copy; with the variable unset the
editor is read-only. The edited topic file is read from the repo deck, so its
other uncommitted edits are kept. Nothing is committed and nothing reaches
Anki: the next build/import does that. Ids are never renamed and cards are
never deleted (either would orphan the Anki note).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Final

from plc_lab import cards, sources

DECK_SRC_ENV: Final = "AUTOMATION_TUTOR_DECK_SRC"
MAX_LINES: Final = 250
FIELDS: Final = ("front", "back", "source", "excerpt")
# New ids only (every existing id already matches): lowercase words and dashes.
_SAFE_ID: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TOPICS: Final = {t.stem: t for t in cards.TOPICS}
_logger = logging.getLogger(__name__)


class EditError(ValueError):
    """A save that was refused; nothing was written."""


@dataclass(frozen=True)
class Dirs:
    """Where a save goes: the repo deck (``src``) and the server's copy."""

    src: Path | None
    live: Path

    @classmethod
    def from_env(cls, live: Path) -> Dirs:
        """``src`` from ``AUTOMATION_TUTOR_DECK_SRC`` (unset or empty: none)."""
        value = os.environ.get(DECK_SRC_ENV, "").strip()
        return cls(Path(value) if value else None, live)

    def read_only_reason(self) -> str:
        """Why nothing can be saved, or ``""`` when saving is possible."""
        if self.src is None:
            return (
                f"Read-only: {DECK_SRC_ENV} is not set, so a save could not reach"
                " the repo deck (this server runs from a release copy that the"
                " next deploy replaces). Restart it with scripts/tutor_deploy.sh"
                " or ./run.sh, which set it."
            )
        if not self.src.is_dir():
            return f"Read-only: {DECK_SRC_ENV}={self.src} is not a directory."
        return ""

    def targets(self) -> list[Path]:
        """The dirs a save writes, each once (src first)."""
        out: list[Path] = []
        for found in (self.src, self.live):
            if found is not None and found.resolve() not in {d.resolve() for d in out}:
                out.append(found)
        return out


@dataclass(frozen=True)
class Edit:
    """One save request: an existing card's new fields, or a new card."""

    card_id: str
    new: bool
    topic: str
    fields: dict[str, str]
    requires: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """A checked save: the topic file's new text and the card it holds."""

    stem: str
    text: str
    card: cards.Card


def parse(body: dict[str, Any]) -> Edit:
    """The request body as an ``Edit``; wrong types are refused here."""
    card_id, topic, needs = body.get("id"), body.get("topic", ""), body.get("requires")
    if not isinstance(card_id, str) or not card_id.strip():
        msg = "id must be a non-empty string"
        raise EditError(msg)
    if not all(isinstance(body.get(key), str) for key in FIELDS):
        msg = f"{', '.join(FIELDS)} must all be strings"
        raise EditError(msg)
    if needs is None:
        needs = []
    if not isinstance(needs, list) or not all(isinstance(n, str) for n in needs):
        msg = "requires must be a list of card ids"
        raise EditError(msg)
    return Edit(
        card_id=card_id.strip(),
        new=body.get("new") is True,
        topic=topic if isinstance(topic, str) else "",
        fields={key: str(body[key]).strip() for key in FIELDS},
        requires=tuple(n.strip() for n in needs if n.strip()),
    )


def render(raw: list[Any]) -> str:
    """A topic file's text, formatted exactly like the deck files."""
    return json.dumps(raw, indent=2, ensure_ascii=False) + "\n"


def _read(deck_dir: Path) -> dict[str, list[Any]]:
    """Every topic file of ``deck_dir`` as parsed JSON arrays."""
    raw: dict[str, list[Any]] = {}
    for stem in _TOPICS:
        try:
            items = json.loads((deck_dir / f"{stem}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            msg = f"cannot read {deck_dir / stem}.json: {err}"
            raise EditError(msg) from err
        raw[stem] = items if isinstance(items, list) else []
    return raw


def _entry(edit: Edit) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": edit.card_id, **edit.fields}
    if edit.requires:
        entry["requires"] = list(edit.requires)
    return entry


def _place(raw: dict[str, list[Any]], edit: Edit) -> str:
    """Put the edited or new card into ``raw``; returns its topic's stem."""
    ids = {c.get("id") for items in raw.values() for c in items if isinstance(c, dict)}
    if edit.new:
        topic = _TOPICS.get(edit.topic)
        if topic is None:
            msg = f"unknown topic {edit.topic!r}; pick one of {sorted(_TOPICS)}"
            raise EditError(msg)
        if not _SAFE_ID.fullmatch(edit.card_id) or not edit.card_id.startswith(
            topic.prefixes
        ):
            msg = (
                f"id {edit.card_id!r} must start with {' or '.join(topic.prefixes)}"
                " and use only a-z, 0-9 and single dashes (e.g. "
                f"{topic.prefixes[0]}my-card)"
            )
            raise EditError(msg)
        if edit.card_id in ids:
            msg = f"id {edit.card_id!r} is already taken; ids must be unique"
            raise EditError(msg)
        raw[topic.stem].append(_entry(edit))
        return topic.stem
    for stem, items in raw.items():
        for i, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == edit.card_id:
                items[i] = _entry(edit)
                return stem
    msg = f"unknown card {edit.card_id!r} (ids cannot be renamed)"
    raise EditError(msg)


def _staged(base: Path, stem: str, text: str, label: str) -> list[cards.Card]:
    """``cards.load_deck`` over ``base`` with ``stem``'s file replaced by ``text``.

    Every validator the build runs applies: fields, word counts, the id
    prefix, unique ids, and ``requires`` (ids exist, no self, no cycle).
    """
    with tempfile.TemporaryDirectory(prefix="plc-lab-edit-") as tmp:
        staged = Path(tmp)
        for other in _TOPICS:
            if other == stem:
                (staged / f"{stem}.json").write_text(text, encoding="utf-8")
            elif (base / f"{other}.json").is_file():
                shutil.copyfile(base / f"{other}.json", staged / f"{other}.json")
        try:
            return cards.load_deck(staged)
        except ValueError as err:  # CardError, or a file that is not JSON
            msg = f"{label}{err}".replace(f"{staged}/", "deck/")
            raise EditError(msg) from err


def plan(dirs: Dirs, edit: Edit) -> Plan:
    """Validate a save against the repo deck and the server's copy; no writes."""
    reason = dirs.read_only_reason()
    if reason or dirs.src is None:
        raise EditError(reason)
    raw = _read(dirs.src)
    stem = _place(raw, edit)
    text = render(raw[stem])
    lines = text.count("\n")
    if lines > MAX_LINES:
        msg = (
            f"deck/{stem}.json would be {lines} lines, over the {MAX_LINES}-line"
            " cap: add a topic in cards.TOPICS instead of growing this one"
        )
        raise EditError(msg)
    deck = _staged(dirs.src, stem, text, "")
    if len(dirs.targets()) > 1:
        _staged(
            dirs.live,
            stem,
            text,
            "the server's deck copy differs from the repo deck; deploy first: ",
        )
    card = next(c for c in deck if c.id == edit.card_id)
    return Plan(stem, text, card)


def check_source(card: cards.Card) -> None:
    """Refuse a card whose excerpt is not in its source (fetched, cached)."""
    mismatch = sources.check_excerpt(card.id, card.source, card.excerpt)
    if mismatch is not None:
        msg = f"excerpt check failed for {card.source}: {mismatch.reason}"
        raise EditError(msg)


def prepare(dirs: Dirs, edit: Edit) -> Plan:
    """``plan`` then ``check_source``: everything a save needs before writing."""
    planned = plan(dirs, edit)
    check_source(planned.card)
    return planned


def write(dirs: Dirs, planned: Plan) -> None:
    """Write the topic file to every target dir (temp file, then rename)."""
    for target in dirs.targets():
        path = target / f"{planned.stem}.json"
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(planned.text, encoding="utf-8")
        tmp.replace(path)
        _logger.info("deck edit: wrote %s (%s)", path, planned.card.id)
