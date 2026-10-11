# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The editor over HTTP: JSON only, refusals write nothing, a save reloads."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from plc_lab import sources
from plc_lab.tutor import deck_edit
from plc_lab.tutor.deck_edit import Dirs
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.server import create_app
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeCredit, FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_DECK = Path(__file__).resolve().parents[3] / "deck"
CARD = "fund-plc-definition"
NOTE = (
    "Saved to deck/fundamentals.json (uncommitted; Anki updates on next build/import)."
)


@pytest.fixture(autouse=True)
def source_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "check_excerpt", lambda *_: None)


def _engine(tmp_path: Path) -> Engine:
    return Engine(
        store=Store(tmp_path / "data"),
        now=ManualClock(),
        credit_fn=FakeCredit(),
        session_factory=lambda _prompt: FakeSession(turn("Hi")),
    )


def _client(tmp_path: Path, dirs: Dirs) -> Iterator[TestClient]:
    with TestClient(create_app(_engine(tmp_path), deck_dirs=dirs)) as c:
        yield c


@pytest.fixture
def dirs(tmp_path: Path) -> Dirs:
    src, live = tmp_path / "src", tmp_path / "live"
    shutil.copytree(REPO_DECK, src)
    shutil.copytree(REPO_DECK, live)
    return Dirs(src, live)


@pytest.fixture
def client(tmp_path: Path, dirs: Dirs) -> Iterator[TestClient]:
    yield from _client(tmp_path, dirs)


def _body(**change: Any) -> dict[str, Any]:
    raw = json.loads((REPO_DECK / "fundamentals.json").read_text(encoding="utf-8"))
    return {**next(c for c in raw if c["id"] == CARD), **change}


def test_overview_lists_the_repo_deck(client: TestClient, dirs: Dirs) -> None:
    assert dirs.src is not None
    path = dirs.src / "fundamentals.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[0]["front"] = "Only in the repo deck?"
    path.write_text(deck_edit.render(raw), encoding="utf-8")
    data = client.get("/api/editor").json()
    assert data["writable"] is True
    assert data["reason"] == ""
    assert data["max_lines"] == 250
    assert data["topics"][0] == {
        "stem": "fundamentals",
        "title": "Fundamentals",
        "prefixes": ["fund-"],
        "lines": 189,
    }
    row = next(c for c in data["cards"] if c["id"] == CARD)
    assert row["front"] == "Only in the repo deck?"
    assert set(row) == {"id", "topic", "front", "back", "source", "excerpt", "requires"}


def test_overview_read_only_without_a_deck_source(tmp_path: Path) -> None:
    for c in _client(tmp_path, Dirs(None, tmp_path / "gone")):
        data = c.get("/api/editor").json()
        assert data["writable"] is False
        assert "AUTOMATION_TUTOR_DECK_SRC is not set" in data["reason"]
        assert {t["lines"] for t in data["topics"]} == {0}
        assert len(data["cards"]) > 100  # the server's own deck, read-only
        refused = c.post("/api/editor/save", json=_body())
        assert refused.status_code == 400
        assert "is not set" in refused.json()["error"]


def test_overview_read_only_when_the_repo_deck_does_not_load(
    client: TestClient, dirs: Dirs
) -> None:
    assert dirs.src is not None
    (dirs.src / "ladder.json").write_text("[{}]", encoding="utf-8")
    data = client.get("/api/editor").json()
    assert data["writable"] is False
    assert data["reason"].startswith("Read-only: the repo deck does not load:")
    assert data["topics"][0]["lines"] == 189  # counted in the server's copy


def test_save_needs_json(client: TestClient, dirs: Dirs) -> None:
    before = (dirs.live / "fundamentals.json").read_bytes()
    response = client.post("/api/editor/save", content=json.dumps(_body(front="X?")))
    assert response.status_code == 415
    assert client.get("/api/editor/save").status_code == 405
    assert (dirs.live / "fundamentals.json").read_bytes() == before


def test_save_writes_both_and_reloads_the_live_card(
    client: TestClient, dirs: Dirs
) -> None:
    client.post("/api/start", json={"card_id": CARD})
    response = client.post("/api/editor/save", json=_body(front="Edited front?"))
    assert response.status_code == 200
    assert response.json()["note"] == NOTE
    assert response.json()["card"]["front"] == "Edited front?"
    assert client.get("/api/state").json()["card"]["front"] == "Edited front?"
    fronts = {c["id"]: c["front"] for c in client.get("/api/cards").json()}
    assert fronts[CARD] == "Edited front?"
    for target in dirs.targets():
        assert "Edited front?" in (target / "fundamentals.json").read_text("utf-8")


def test_save_keeps_another_live_card(client: TestClient) -> None:
    client.post("/api/start", json={"card_id": "fund-scan-cycle-order"})
    assert client.post("/api/editor/save", json=_body(front="E?")).status_code == 200
    assert client.get("/api/state").json()["card"]["id"] == "fund-scan-cycle-order"


def test_new_card_with_requires_is_locked_in_the_picker(client: TestClient) -> None:
    body = _body(id="fund-added", new=True, topic="fundamentals", requires=[CARD])
    assert client.post("/api/editor/save", json=body).json()["saved"] == "fund-added"
    row = next(c for c in client.get("/api/cards").json() if c["id"] == "fund-added")
    assert (row["locked"], row["missing"]) == (True, [CARD])


def test_a_refused_save_writes_nothing(client: TestClient, dirs: Dirs) -> None:
    before = (dirs.src or dirs.live).joinpath("fundamentals.json").read_bytes()
    lang = json.loads((REPO_DECK / "languages.json").read_text("utf-8"))[1]
    cycle = {**lang, "requires": ["fund-five-languages"]}  # which requires lang-*
    response = client.post("/api/editor/save", json=cycle)
    assert response.status_code == 400
    assert response.json()["error"].startswith("requires cycle: ")
    for target in dirs.targets():
        assert (target / "fundamentals.json").read_bytes() == before


def test_a_failed_write_is_a_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(deck_edit, "write", broken)
    response = client.post("/api/editor/save", json=_body(front="E?"))
    assert response.status_code == 500
    assert response.json()["error"] == "save failed: disk full"
