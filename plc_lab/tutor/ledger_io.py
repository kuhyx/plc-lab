# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Where the tutor's signed ledger lives, and reading / writing it safely.

Paths resolve at call time: ``AUTOMATION_TUTOR_DATA`` moves the data dir,
``AUTOMATION_TUTOR_KEY`` the key. The real key is root-owned and only read.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

_REAL_KEY: Final = Path("/etc/workout-locker/hmac.key")
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Paths:
    """Where the tutor's ledger lives and which key signs it."""

    data_dir: Path
    key_file: Path

    @property
    def ledger(self) -> Path:
        """The signed credit ledger the earner reads."""
        return self.data_dir / "ledger.json"

    @property
    def lock(self) -> Path:
        """Serialises writers, e.g. two browser tabs crediting at once."""
        return self.data_dir / "ledger.lock"


def default_paths() -> Paths:
    """The active locations, honouring the sandbox environment variables."""
    data = os.environ.get("AUTOMATION_TUTOR_DATA")
    key = os.environ.get("AUTOMATION_TUTOR_KEY")
    return Paths(
        data_dir=Path(data) if data else Path.home() / ".local/share/automation_tutor",
        key_file=Path(key) if key else _REAL_KEY,
    )


class LedgerError(Exception):
    """The ledger exists but is not a ledger -- never silently emptied."""


def read_key(key_file: Path) -> bytes | None:
    """The signing key, or ``None`` when it is unreadable or empty."""
    try:
        return key_file.read_bytes().strip() or None
    except OSError as exc:
        _logger.warning("signing key %s unreadable: %s", key_file, exc)
        return None


def read_rows(ledger: Path) -> list[object]:
    """The raw ``entries`` array; a missing file is empty.

    Raises:
        LedgerError: The file is unreadable, not JSON, or has no entries array.
    """
    if not ledger.exists():
        return []
    try:
        raw = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"{ledger} is unreadable: {exc}"
        raise LedgerError(msg) from exc
    rows = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        msg = f"{ledger} has no entries array"
        raise LedgerError(msg)
    return rows


def write_rows(ledger: Path, rows: list[object]) -> None:
    """Atomically replace the ledger: readers see the old file or the new one."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ledger.parent, suffix=".tmp", delete=False
    ) as handle:
        json.dump({"entries": rows}, handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    Path(handle.name).replace(ledger)


@contextmanager
def exclusive(lock_file: Path) -> Iterator[None]:
    """Hold the ledger write lock; the kernel drops it if the holder dies."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
