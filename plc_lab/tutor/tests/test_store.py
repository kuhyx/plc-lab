# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The progress file and per-session transcripts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from plc_lab.tutor.store import Store, data_dir

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_data_dir_prefers_the_env_override(tutor_sandbox: Path) -> None:
    assert data_dir() == tutor_sandbox / "data"


def test_data_dir_defaults_under_home(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTOMATION_TUTOR_DATA")
    assert data_dir() == tutor_sandbox / "home/.local/share/automation_tutor"


def test_default_store_uses_the_data_dir(tutor_sandbox: Path) -> None:
    store = Store()
    assert store.root == tutor_sandbox / "data"
    assert store.progress_path == tutor_sandbox / "data/progress.json"


def test_progress_empty_when_no_file(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    assert store.progress() == {"mastered": {}, "cards_done": {}}
    assert store.mastered() == []
    assert not (tmp_path / "s").exists()


def test_progress_non_dict_json_is_treated_as_empty(tmp_path: Path) -> None:
    store = Store(tmp_path)
    (tmp_path / "progress.json").write_text("[1, 2]", encoding="utf-8")
    assert store.progress() == {"mastered": {}, "cards_done": {}}


def test_progress_reads_an_existing_file(tmp_path: Path) -> None:
    store = Store(tmp_path)
    (tmp_path / "progress.json").write_text(
        json.dumps({"mastered": {"coil": {}}, "extra": 1}), encoding="utf-8"
    )
    data = store.progress()
    assert data["extra"] == 1
    assert data["cards_done"] == {}
    assert store.mastered() == ["coil"]


def test_master_returns_only_fresh_concepts_and_saves(tmp_path: Path) -> None:
    store = Store(tmp_path / "root")
    assert store.master(["voltage", "coil"], "card-1", "sess-1") == ["voltage", "coil"]
    assert store.master(["coil", "relay"], "card-2", "sess-2") == ["relay"]
    data = store.progress()
    assert list(data["mastered"]) == ["voltage", "coil", "relay"]
    assert data["mastered"]["relay"]["card"] == "card-2"
    assert data["mastered"]["coil"]["session"] == "sess-1"
    assert store.mastered() == ["voltage", "coil", "relay"]
    assert not (tmp_path / "root/progress.tmp").exists()


def test_master_with_nothing_fresh_does_not_write(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert store.master([], "c", "s") == []
    assert not store.progress_path.exists()
    store.master(["coil"], "c", "s")
    before = store.progress_path.stat().st_mtime_ns
    assert store.master(["coil"], "c", "s") == []
    assert store.progress_path.stat().st_mtime_ns == before


def test_finish_card_records_the_card(tmp_path: Path) -> None:
    store = Store(tmp_path / "root")
    store.finish_card("card-1", "sess-1")
    done = store.progress()["cards_done"]["card-1"]
    assert done["session"] == "sess-1"
    assert done["at"]


def test_log_appends_jsonl_lines(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.log("sess", {"type": "start", "text": "zażółć"})
    store.log("sess", {"type": "resume"})
    lines = (tmp_path / "sessions/sess.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["type"] for e in events] == ["start", "resume"]
    assert events[0]["text"] == "zażółć"
    assert events[0]["logged_at"]


def test_unfinish_and_unarchive_of_unknown_ids_write_nothing(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.unfinish_card("nope")
    store.unarchive("nope")
    assert not store.progress_path.exists()


def test_archive_twice_keeps_the_first_time(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.archive("s1")
    first = store.archived()["s1"]
    store.archive("s1")
    assert store.archived() == {"s1": first}
