# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""POST /api/feedback: validation, scoping to a message, failure mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from plc_lab.tutor import credit, feedback
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.server import create_app
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady


def paid(_block: BlockReady, sid: str) -> credit.CreditReceipt:
    return credit.CreditReceipt(True, 1, f"{sid}-b1", None)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    fake = FakeSession(turn("Begin"), turn("Next"))
    return Engine(
        store=Store(tmp_path / "data"),
        now=ManualClock(),
        credit_fn=paid,
        session_factory=lambda _prompt: fake,
    )


@pytest.fixture
def client(engine: Engine, tmp_path: Path) -> Iterator[TestClient]:
    folders = (tmp_path / "img", tmp_path / "svg")
    with TestClient(create_app(engine, media_dirs=folders)) as c:
        yield c


def report(**fields: Any) -> dict[str, Any]:
    return {"category": "response", "text": "wrong answer", **fields}


def test_unscoped_report_before_any_session(client: TestClient) -> None:
    response = client.post(
        "/api/feedback", json=report(page_url="u" * 600, user_agent="UA")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert "### Tutor feedback #1 (open): Tutor's response" in body["markdown"]
    (stored,) = feedback.load()
    assert stored["session_id"] is None
    assert stored["card_id"] is None
    assert len(stored["page_url"]) == 500
    assert "snapshot" not in stored


def test_scoped_report_stores_the_servers_snapshot(client: TestClient) -> None:
    started = client.post("/api/start", json={}).json()
    client.post("/api/message", json={"text": "my answer"})
    response = client.post(
        "/api/feedback",
        json=report(session_id=started["session_id"], message_index=2),
    )
    assert response.status_code == 200
    (stored,) = feedback.load()
    assert stored["session_id"] == started["session_id"]
    assert stored["card_id"] == started["card"]["id"]
    assert stored["message_index"] == 2
    assert stored["snapshot"]["message"]["text"] == "Next"
    assert [p["index"] for p in stored["snapshot"]["preceding"]] == [0, 1]


def test_session_mismatch_is_a_400(client: TestClient) -> None:
    client.post("/api/start", json={})
    response = client.post(
        "/api/feedback", json=report(session_id="old", message_index=0)
    )
    assert response.status_code == 400
    assert "session changed" in response.json()["error"]
    assert feedback.load() == []


@pytest.mark.parametrize(
    "fields",
    [{"category": "bogus"}, {"text": " "}, {"session_id": "", "message_index": 0}],
)
def test_invalid_report_is_a_400(client: TestClient, fields: dict[str, Any]) -> None:
    response = client.post("/api/feedback", json=report(**fields))
    assert response.status_code == 400
    assert response.json()["type"] == "ValueError"
    assert feedback.load() == []


def test_bad_json_is_a_400(client: TestClient) -> None:
    assert client.post("/api/feedback", content="nope").status_code == 400


def test_store_failure_is_a_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_entry: dict[str, Any]) -> dict[str, Any]:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(feedback, "record", broken)
    response = client.post("/api/feedback", json=report())
    assert response.status_code == 500
    assert response.json()["error"] == "disk full"
    assert response.json()["type"] == "OSError"


def test_corrupt_store_is_a_500(client: TestClient) -> None:
    path = feedback.feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"text": "no id"}\n', encoding="utf-8")
    response = client.post("/api/feedback", json=report())
    assert response.status_code == 500
    assert response.json()["type"] == "KeyError"


def test_unexpected_store_error_reaches_the_app_handler(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_entry: dict[str, Any]) -> dict[str, Any]:
        msg = "not serialisable"
        raise TypeError(msg)

    monkeypatch.setattr(feedback, "record", broken)
    app = create_app(engine, media_dirs=(tmp_path / "img", tmp_path / "svg"))
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.post("/api/feedback", json=report())
    assert response.status_code == 500
    assert response.json()["error"] == "not serialisable"
    assert response.json()["type"] == "TypeError"
