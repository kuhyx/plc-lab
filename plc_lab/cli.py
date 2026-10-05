# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""CLI: check every excerpt against its source, then write the ``.apkg``.

``python3 -m plc_lab check [FILE...]`` checks the whole deck (or the given
topic files); ``python3 -m plc_lab build`` checks first and refuses to write
a package while any card's excerpt is missing from its source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Final

from plc_lab.cards import CardError, load_deck
from plc_lab.deck import write_package
from plc_lab.sources import check_excerpt

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_DIR: Final = Path(__file__).resolve().parent.parent
DECK_DIR: Final = REPO_DIR / "deck"
DEFAULT_OUT: Final = REPO_DIR / "build" / "automation.apkg"


def _check(cards: Iterable[tuple[str, str, str]]) -> int:
    """Check (id, source, excerpt) triples; print failures, return their count."""
    bad = total = 0
    for card_id, source, excerpt in cards:
        total += 1
        miss = check_excerpt(card_id, source, excerpt)
        if miss is not None:
            bad += 1
            print(f"FAIL {miss.card_id}: {miss.reason} ({miss.url})")
    print(f"{total - bad}/{total} excerpts found in their sources")
    return bad


def _raw_triples(files: list[Path]) -> list[tuple[str, str, str]]:
    """Triples straight from topic files: a research helper, no validation."""
    return [
        (card["id"], card["source"], card["excerpt"])
        for path in files
        for card in json.loads(path.read_text(encoding="utf-8"))
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plc_lab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check excerpts against their sources")
    check.add_argument("files", nargs="*", type=Path, help="topic files (default: all)")
    build = sub.add_parser("build", help="check, then write the .apkg")
    build.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; the exit code is 0 only when every check passed."""
    args = _parser().parse_args(argv)
    if args.command == "check" and args.files:
        return 1 if _check(_raw_triples(args.files)) else 0
    try:
        cards = load_deck(DECK_DIR)
    except CardError as error:
        print(f"invalid deck: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    if _check((c.id, c.source, c.excerpt) for c in cards):
        return 1
    if args.command == "build":
        out = write_package(cards, args.out)
        print(f"wrote {len(cards)} cards to {out}")
    return 0
