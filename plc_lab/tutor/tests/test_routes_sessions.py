# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Session routes: Next card, Stop here, card_done, history and archiving."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from plc_lab.tutor.engine import Engine
from plc_lab.tutor.server import create_app
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeCredit, FakeSession, ManualClock, turn
from plc_lab.tutor.tests.test_history import NEW, OLD, SILENT, make_session

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class Rig:
    """An engine over a tmp data dir with a scripted model and a fake ledger."""

    def __init__(self, root: Path) -> None:
        self.fake = FakeSession(*[turn(f"Reply {i}") for i in range(4)])
        self.credit = FakeCredit()
        self.store = Store(root / "data")
        self.engine = Engine(
            store=self.store,
            now=ManualClock(),
            credit_fn=self.credit,
            session_factory=lambda _prompt: self.fake,
        )

    @property
    def card(self) -> str:
        return self.engine.deck[0].id


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


@pytest.fixture
def client(rig: Rig, tmp_path: Path) -> Iterator[TestClient]:
    folders = (tmp_path / "img", tmp_path / "svg")
    with TestClient(create_app(rig.engine, media_dirs=folders)) as c:
        yield c


def listed(client: TestClient) -> dict[str, dict[str, object]]:
    """``GET /api/sessions`` keyed by session id."""
    response = client.get("/api/sessions")
    assert response.status_code == 200
    return {row["session_id"]: row for row in response.json()}


def test_session_view_is_read_only(client: TestClient, rig: Rig) -> None:
    make_session(rig.store, OLD)
    before = (rig.store.root / "sessions" / f"{OLD}.jsonl").read_bytes()
    response = client.get(f"/api/session/{OLD}")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == OLD
    assert [m["text"] for m in body["messages"]] == ["Hi", "a controller", "Right"]
    assert body["cards"][0]["id"] == "fund-plc-definition"
    assert (rig.store.root / "sessions" / f"{OLD}.jsonl").read_bytes() == before
    assert not rig.store.progress_path.exists()
    assert rig.credit.calls == []
    assert rig.fake.prompts == []


@pytest.mark.parametrize(
    "session_id", [NEW, "x", f"{OLD}.jsonl", "2026101-093000-cd34"]
)
def test_session_view_404_for_bad_or_missing_ids(
    client: TestClient, rig: Rig, session_id: str
) -> None:
    make_session(rig.store, OLD)
    response = client.get(f"/api/session/{session_id}")
    assert response.status_code == 404
    assert response.json() == {"error": "no such session"}


def test_sessions_list_includes_archived_and_the_live_one(
    client: TestClient, rig: Rig
) -> None:
    make_session(rig.store, OLD)
    make_session(rig.store, SILENT, reply=False)
    live = client.post("/api/start", json={"card_id": rig.card}).json()["session_id"]
    rows = listed(client)
    assert set(rows) == {OLD, SILENT, live}
    assert rows[OLD]["archived"] is False
    assert (rows[SILENT]["archived"], rows[SILENT]["auto_archived"]) == (True, True)
    assert (rows[live]["live"], rows[live]["archived"]) == (True, False)


def test_archive_hides_and_shows_a_session(client: TestClient, rig: Rig) -> None:
    make_session(rig.store, OLD)
    hidden = client.post("/api/archive", json={"session_id": OLD, "archived": True})
    assert hidden.status_code == 200
    assert [r["archived"] for r in hidden.json() if r["session_id"] == OLD] == [True]
    assert OLD in rig.store.archived()
    assert (rig.store.root / "sessions" / f"{OLD}.jsonl").is_file()
    shown = client.post("/api/archive", json={"session_id": OLD, "archived": False})
    assert [r["archived"] for r in shown.json() if r["session_id"] == OLD] == [False]
    assert rig.store.archived() == {}


def test_the_live_session_cannot_be_archived(client: TestClient, rig: Rig) -> None:
    live = client.post("/api/start", json={"card_id": rig.card}).json()["session_id"]
    response = client.post("/api/archive", json={"session_id": live, "archived": True})
    assert response.status_code == 400
    assert response.json() == {"error": "the live session cannot be archived"}
    assert rig.store.archived() == {}


@pytest.mark.parametrize(
    ("body", "status", "error"),
    [
        ({"archived": True}, 404, "no such session"),
        ({"session_id": 7, "archived": True}, 404, "no such session"),
        ({"session_id": NEW, "archived": True}, 404, "no such session"),
        ({"session_id": "../x", "archived": "bad"}, 404, "no such session"),
        ({"session_id": OLD}, 400, "archived must be true or false"),
        ({"session_id": OLD, "archived": 1}, 400, "archived must be true or false"),
    ],
)
def test_archive_rejects_bad_requests(
    client: TestClient,
    rig: Rig,
    body: dict[str, object],
    status: int,
    error: str,
) -> None:
    make_session(rig.store, OLD)
    response = client.post("/api/archive", json=body)
    assert response.status_code == status
    assert response.json() == {"error": error}
    assert rig.store.archived() == {}


def test_card_done_marks_and_unmarks_a_card(client: TestClient, rig: Rig) -> None:
    done = client.post("/api/card_done", json={"card_id": rig.card})
    assert done.status_code == 200
    assert rig.card in rig.store.progress()["cards_done"]
    assert rig.store.progress()["cards_done"][rig.card]["session"] == "manual"
    undone = client.post("/api/card_done", json={"card_id": rig.card, "done": False})
    assert undone.status_code == 200
    assert rig.store.progress()["cards_done"] == {}


def test_card_done_on_the_live_card_opens_the_choice(
    client: TestClient, rig: Rig
) -> None:
    client.post("/api/start", json={"card_id": rig.card})
    state = client.post("/api/card_done", json={"card_id": rig.card}).json()
    assert state["card_done"] is True
    assert rig.credit.calls == []  # a manual override never touches credit


@pytest.mark.parametrize("body", [{}, {"card_id": "nope"}, {"card_id": None}])
def test_card_done_rejects_unknown_cards(
    client: TestClient, body: dict[str, object]
) -> None:
    response = client.post("/api/card_done", json=body)
    assert response.status_code == 400
    assert "unknown card" in response.json()["error"]


def test_next_card_ends_this_session_and_starts_another(
    client: TestClient, rig: Rig
) -> None:
    first = client.post("/api/start", json={"card_id": rig.card}).json()
    second = client.post("/api/next").json()
    assert second["session_id"] != first["session_id"]
    assert second["card"]["id"] != rig.card
    old = listed(client)[first["session_id"]]
    assert old["stopped"] is True
    assert old["live"] is False


def test_next_card_with_none_left_is_a_502_and_keeps_the_session(
    client: TestClient, rig: Rig
) -> None:
    first = client.post("/api/start", json={"card_id": rig.card}).json()
    for card in rig.engine.deck[1:]:
        rig.store.finish_card(card.id, "x")
    response = client.post("/api/next")
    assert response.status_code == 502
    assert "no unfinished card" in response.json()["error"]
    assert client.get("/api/state").json()["session_id"] == first["session_id"]


def test_stop_ends_the_live_session(client: TestClient, rig: Rig) -> None:
    first = client.post("/api/start", json={"card_id": rig.card}).json()
    state = client.post("/api/stop").json()
    assert state["session_id"] == ""
    assert listed(client)[first["session_id"]]["stopped"] is True
    assert client.post("/api/stop").status_code == 200  # nothing live: a no-op
