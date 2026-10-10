# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""History views: id validation, session summaries, archive flags, read-only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plc_lab.tutor import history
from plc_lab.tutor.history import View
from plc_lab.tutor.store import Store

if TYPE_CHECKING:
    from pathlib import Path

T0 = 1_800_000_000.0
OLD = "20261009-101500-ab12"
NEW = "20261010-093000-cd34"
SILENT = "20261010-120000-ef56"
CARD = "fund-plc-definition"
OTHER = "fund-plc-vs-relay-panel"


def view(**fields: Any) -> View:
    """A view with nothing live, done or archived unless overridden."""
    base: dict[str, Any] = {
        "fronts": {CARD: "What is a PLC?"},
        "live": "",
        "done_now": set(),
        "archived": set(),
    }
    return View(**{**base, **fields})


def make_session(
    store: Store, sid: str, *, card: str = CARD, reply: bool = True
) -> None:
    """A transcript: start, a tutor opener and (optionally) one answered turn."""
    store.log(sid, {"type": "start", "card": card, "t": T0})
    opener = {"message": "Hi", "low_effort": False}
    store.log(sid, {"type": "tutor", "t": T0, "turn": opener})
    if reply:
        store.log(sid, {"type": "learner", "text": "a controller", "t": T0 + 150})
        turn = {"message": "Right", "low_effort": False, "card_done": True}
        store.log(sid, {"type": "tutor", "t": T0 + 150, "turn": turn})
        row = {"block": 2, "span": 2, "minutes": 2, "recorded": True}
        store.log(sid, {"type": "credit", **row})


def sessions_dir(store: Store) -> Path:
    return store.root / "sessions"


def test_transcript_path_validates_the_id_before_building_a_path(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    make_session(store, OLD)
    folder = sessions_dir(store)
    assert history.transcript_path(folder, OLD) == folder / f"{OLD}.jsonl"
    assert history.transcript_path(folder, NEW) is None  # right shape, no file
    for bad in ["", "../x", f"{OLD}.jsonl", f"{OLD}/..", "٢٠٢٦١٠٠٩-101500-ab12"]:
        assert history.transcript_path(folder, bad) is None


def test_session_view_has_messages_receipts_and_card_state(tmp_path: Path) -> None:
    store = Store(tmp_path)
    make_session(store, OLD)
    found = history.session_view(
        sessions_dir(store), OLD, view(done_now={CARD}, live=NEW)
    )
    assert found is not None
    assert [m["role"] for m in found["messages"]] == ["tutor", "learner", "tutor"]
    assert found["receipts"] == [
        {"block": 2, "span": 2, "minutes": 2, "recorded": True}
    ]
    assert found["session_id"] == OLD
    assert found["live"] is False
    assert found["archived"] is False
    assert found["stopped"] is False
    assert found["credited_minutes"] == 2
    assert found["active_seconds"] == 150
    assert found["cards"] == [
        {"id": CARD, "front": "What is a PLC?", "done": True, "done_here": True}
    ]


def test_session_view_is_none_for_bad_missing_or_unreplayable(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.log(SILENT, {"type": "stop"})  # no start event: nothing to replay
    folder = sessions_dir(store)
    assert history.session_view(folder, "../etc/passwd", view()) is None
    assert history.session_view(folder, NEW, view()) is None
    assert history.session_view(folder, SILENT, view()) is None


def test_cards_dedupe_fall_back_to_the_id_and_track_done_here(tmp_path: Path) -> None:
    store = Store(tmp_path)
    make_session(store, OLD, card=OTHER, reply=False)
    switch = {"type": "next_card", "card": CARD, "ui": {"text": "Next"}, "t": T0 + 5}
    store.log(OLD, switch)
    store.log(OLD, {**switch, "card": OTHER})  # back to the first card
    found = history.session_view(sessions_dir(store), OLD, view(done_now={CARD}))
    assert found is not None
    assert found["cards"] == [
        {"id": OTHER, "front": OTHER, "done": False, "done_here": False},
        {"id": CARD, "front": "What is a PLC?", "done": True, "done_here": False},
    ]


def test_live_session_is_never_archived_even_without_a_reply(tmp_path: Path) -> None:
    store = Store(tmp_path)
    make_session(store, SILENT, reply=False)
    live = view(live=SILENT, archived={SILENT})
    found = history.session_view(sessions_dir(store), SILENT, live)
    assert found is not None
    assert (found["live"], found["archived"], found["auto_archived"]) == (
        True,
        False,
        False,
    )


def test_archive_flags(tmp_path: Path) -> None:
    store = Store(tmp_path)
    make_session(store, OLD)
    make_session(store, SILENT, reply=False)
    by_hand = history.session_view(sessions_dir(store), OLD, view(archived={OLD}))
    auto = history.session_view(sessions_dir(store), SILENT, view())
    assert by_hand is not None
    assert (by_hand["archived"], by_hand["auto_archived"]) == (True, False)
    assert auto is not None
    assert (auto["archived"], auto["auto_archived"]) == (True, True)


def test_sessions_list_is_newest_first_and_skips_strays(tmp_path: Path) -> None:
    store = Store(tmp_path)
    make_session(store, OLD)
    make_session(store, NEW, reply=False)
    store.log("20261011-000000-0000", {"type": "stop"})  # not replayable
    folder = sessions_dir(store)
    (folder / "notes.jsonl").write_text("{}\n", encoding="utf-8")  # not a session
    store.log(NEW, {"type": "stop"})
    listed = history.sessions_list(folder, view(archived={OLD}, live=""))
    assert [row["session_id"] for row in listed] == [NEW, OLD]
    newest, oldest = listed
    assert newest["started"] == "2026-10-10 09:30"
    assert newest["stopped"] is True
    assert newest["auto_archived"] is True
    assert oldest == {
        "session_id": OLD,
        "started": "2026-10-09 10:15",
        "cards": [
            {"id": CARD, "front": "What is a PLC?", "done": False, "done_here": True}
        ],
        "active_minutes": 2,
        "credited_minutes": 2,
        "live": False,
        "archived": True,
        "auto_archived": False,
        "stopped": False,
    }


def test_nothing_here_writes_anything(tmp_path: Path) -> None:
    store = Store(tmp_path)
    make_session(store, OLD)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    history.sessions_list(sessions_dir(store), view())
    history.session_view(sessions_dir(store), OLD, view())
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    assert not store.progress_path.exists()
