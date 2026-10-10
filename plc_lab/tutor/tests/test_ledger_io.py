# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Ledger paths, key reading, atomic row writes and the writer lock."""

from __future__ import annotations

import fcntl
import json
import logging
from pathlib import Path

import pytest

from plc_lab.tutor.ledger_io import (
    LedgerError,
    Paths,
    default_paths,
    exclusive,
    read_key,
    read_rows,
    write_rows,
)

_logger = logging.getLogger(__name__)


def test_default_paths_follow_the_sandbox_environment(tmp_path: Path) -> None:
    where = default_paths()
    assert where.data_dir == tmp_path / "data"
    assert where.key_file == tmp_path / "hmac.key"
    assert where.ledger == tmp_path / "data" / "ledger.json"
    assert where.lock == tmp_path / "data" / "ledger.lock"


def test_default_paths_without_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOMATION_TUTOR_DATA")
    monkeypatch.delenv("AUTOMATION_TUTOR_KEY")
    where = default_paths()
    assert where.ledger == Path.home() / ".local/share/automation_tutor/ledger.json"
    assert where.key_file == Path("/etc/workout-locker/hmac.key")


def test_read_key_strips_the_newline(tmp_path: Path) -> None:
    key = tmp_path / "k"
    key.write_bytes(b"secret\n")
    assert read_key(key) == b"secret"


def test_read_key_is_none_when_empty_or_missing(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.write_bytes(b" \n")
    assert read_key(empty) is None
    assert read_key(tmp_path / "missing") is None


def test_read_rows_of_a_missing_ledger_is_empty(tmp_path: Path) -> None:
    assert read_rows(tmp_path / "ledger.json") == []


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    ledger = tmp_path / "deep" / "dir" / "ledger.json"
    rows: list[object] = [{"kind": "credit", "n": 1}, "text"]
    write_rows(ledger, rows)
    assert read_rows(ledger) == rows
    assert json.loads(ledger.read_text(encoding="utf-8")) == {"entries": rows}
    assert [p.name for p in ledger.parent.iterdir()] == ["ledger.json"]


def test_write_rows_replaces_the_previous_file(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    write_rows(ledger, [1])
    write_rows(ledger, [2, 3])
    assert read_rows(ledger) == [2, 3]


@pytest.mark.parametrize("content", ["{not json", '{"rows": []}', "[]", "{}"])
def test_read_rows_refuses_what_is_not_a_ledger(tmp_path: Path, content: str) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(content, encoding="utf-8")
    with pytest.raises(LedgerError):
        read_rows(ledger)


def test_read_rows_reports_an_unreadable_file(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.mkdir()
    with pytest.raises(LedgerError, match="unreadable"):
        read_rows(ledger)


@pytest.fixture
def lock_file(tmp_path: Path) -> Path:
    return tmp_path / "locks" / "ledger.lock"


def _try_lock(lock_file: Path) -> bool:
    """Whether another handle can take the lock right now."""
    with lock_file.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            _logger.warning("lock held elsewhere: %s", exc)
            return False
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True


def test_exclusive_holds_the_lock_and_releases_it(lock_file: Path) -> None:
    with exclusive(lock_file):
        assert lock_file.exists()  # parent directory was created
        assert not _try_lock(lock_file)
    assert _try_lock(lock_file)


def _fail_inside(lock_file: Path) -> None:
    with exclusive(lock_file):
        msg = "boom"
        raise RuntimeError(msg)


def test_exclusive_releases_the_lock_when_the_body_raises(lock_file: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        _fail_inside(lock_file)
    assert _try_lock(lock_file)


def test_paths_is_a_value() -> None:
    assert Paths(Path("a"), Path("k")) == Paths(Path("a"), Path("k"))
