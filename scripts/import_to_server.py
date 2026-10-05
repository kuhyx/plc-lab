#!/usr/bin/python3
# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Import ``build/automation.apkg`` into the self-hosted Anki sync server.

Run with the SYSTEM python3 (anki 25.09.2 and anki_guard importable), not the
dev venv. It works in a throwaway collection: full-download the account,
import the package, then push the import back with a NORMAL sync. It never
does a full upload: that would replace the server's review history, which is
what anki-guard's credits are computed from. Any sync that asks for one stops
the run instead.

    python3 scripts/import_to_server.py --dry-run   # import locally, no push
    python3 scripts/import_to_server.py             # import and sync
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import TYPE_CHECKING, Final

from anki.collection import (
    Collection,
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
)
from anki.import_export_pb2 import ImportAnkiPackageUpdateCondition
from anki.sync_pb2 import SyncCollectionResponse
from anki_guard._paths import paths
from anki_guard._snapshot import snapshot
from anki_guard._studied import deck_ids

if TYPE_CHECKING:
    from anki.collection import SyncAuth

REPO_DIR: Final = Path(__file__).resolve().parent.parent
PACKAGE: Final = REPO_DIR / "build" / "automation.apkg"
ENV_FILE: Final = Path.home() / ".config" / "anki_guard" / "syncserver.env"
ENDPOINT: Final = "http://127.0.0.1:8780/"
DECK: Final = "Automation"
_Required = SyncCollectionResponse.ChangesRequired
_ALWAYS: Final = (
    ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS
)
_logger: Final = logging.getLogger("import_to_server")


class ImportStoppedError(RuntimeError):
    """The run stopped before it could do something unsafe."""


@dataclass(frozen=True)
class Counts:
    """What the import must change (deck cards) and must not (reviews)."""

    deck_cards: int
    reviews: int


def _credentials() -> tuple[str, str]:
    """The sync account from ``SYNC_USER1=user:pass``; never printed."""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "SYNC_USER1" and ":" in value:
            user, _, password = value.strip().partition(":")
            return user, password
    msg = f"no SYNC_USER1=user:pass line in {ENV_FILE}"
    raise ImportStoppedError(msg)


def _count(db: sqlite3.Connection) -> Counts:
    decks = deck_ids(db, DECK)
    # Filtered in Python: a static query, and ~20k rows is nothing.
    cards = sum(1 for (did,) in db.execute("SELECT did FROM cards") if did in decks)
    (reviews,) = db.execute("SELECT count(*) FROM revlog").fetchone()
    return Counts(deck_cards=cards, reviews=reviews)


def server_counts() -> Counts:
    """Counts read from a consistent copy of the server's live collection."""
    with snapshot(paths().collection) as copy:
        db = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            return _count(db)
        finally:
            db.close()


def _first_sync(col: Collection, auth: SyncAuth) -> None:
    """Bring the empty local collection level with the server, download only."""
    out = col.sync_collection(auth, sync_media=False)
    if out.new_endpoint:
        auth.endpoint = out.new_endpoint
    if out.required in (_Required.FULL_DOWNLOAD, _Required.FULL_SYNC):
        # Downloading only replaces this throwaway copy, never the server.
        col.close_for_full_sync()
        col.full_upload_or_download(
            auth=auth, server_usn=out.server_media_usn, upload=False
        )
        col.reopen(after_full_sync=True)
    elif out.required == _Required.FULL_UPLOAD:
        msg = "the server asks for a full UPLOAD on the first sync; refusing"
        raise ImportStoppedError(msg)


def _import(col: Collection) -> int:
    request = ImportAnkiPackageRequest(
        package_path=str(PACKAGE),
        options=ImportAnkiPackageOptions(
            with_scheduling=False,
            with_deck_configs=False,
            merge_notetypes=False,
            update_notes=_ALWAYS,
            update_notetypes=_ALWAYS,
        ),
    )
    log = col.import_anki_package(request).log
    return len(log.new) + len(log.updated) + len(log.duplicate)


def _push(col: Collection, auth: SyncAuth) -> None:
    """Send the import with a NORMAL sync; a full-sync demand stops the run."""
    out = col.sync_collection(auth, sync_media=False)
    if out.required not in (_Required.NO_CHANGES, _Required.NORMAL_SYNC):
        name = _Required.Name(out.required)
        msg = f"second sync demands {name}; stopped, nothing was uploaded"
        raise ImportStoppedError(msg)


def run(*, dry_run: bool) -> int:
    """Import the package; the exit code is 0 only when the server has it."""
    if not PACKAGE.is_file():
        msg = f"{PACKAGE} is missing: run `python3 -m plc_lab build` first"
        raise ImportStoppedError(msg)
    before = server_counts()
    print(f"server before: {before.deck_cards} {DECK} cards, {before.reviews} reviews")
    user, password = _credentials()
    local = Counts(deck_cards=-1, reviews=-1)
    with tempfile.TemporaryDirectory(prefix="plc-lab-import-") as tmp:
        col = Collection(str(Path(tmp) / "collection.anki2"))
        try:
            auth = col.sync_login(user, password, ENDPOINT)
            _first_sync(col, auth)
            print(f"imported {_import(col)} notes into a local copy")
            local = Counts(
                deck_cards=len(col.find_cards(f'deck:"{DECK}"')),
                reviews=col.db.scalar("SELECT count(*) FROM revlog"),
            )
            print(
                f"local copy: {local.deck_cards} {DECK} cards, {local.reviews} reviews"
            )
            if dry_run:
                print("dry run: nothing was sent to the server")
                return 0
            _push(col, auth)
        finally:
            col.close(downgrade=False)
    after = server_counts()
    print(f"server after: {after.deck_cards} {DECK} cards, {after.reviews} reviews")
    if after.reviews < before.reviews or after.deck_cards != local.deck_cards:
        msg = "server counts are wrong after the sync; check the collection"
        raise ImportStoppedError(msg)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="import locally only")
    args = parser.parse_args(argv)
    try:
        return run(dry_run=args.dry_run)
    except ImportStoppedError as error:
        _logger.critical("stopped: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
