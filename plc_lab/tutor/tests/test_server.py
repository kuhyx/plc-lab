# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The web app: pages, state, start / message routes, error mapping, media."""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_agent_sdk import ProcessError
import pytest
from starlette.testclient import TestClient

from plc_lab.tutor import credit, server
from plc_lab.tutor.engine import Engine
from plc_lab.tutor.server import create_app
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from plc_lab.tutor.clock import BlockReady

NAME = "0123456789abcdef"


class Rig:
    def __init__(self, root: Path, fake: FakeSession) -> None:
        self.fake = fake
        self.images = root / "img"
        self.svgs = root / "svg"
        self.images.mkdir()
        self.svgs.mkdir()
        self.engine = Engine(
            store=Store(root / "data"),
            now=ManualClock(),
            credit_fn=self.credit,
            session_factory=lambda _prompt: fake,
        )

    @staticmethod
    def credit(_block: BlockReady, sid: str) -> credit.CreditReceipt:
        return credit.CreditReceipt(True, 1, f"{sid}-b1", None)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    replies = [turn("Begin"), turn("Next"), turn("Third"), turn("Fourth")]
    return Rig(tmp_path, FakeSession(*replies))


@pytest.fixture
def client(rig: Rig) -> Iterator[TestClient]:
    with TestClient(create_app(rig.engine, media_dirs=(rig.images, rig.svgs))) as c:
        yield c
    assert rig.engine._session is None


def test_index_and_static_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "<html" in response.text.lower()
    assert client.get("/static/nothing-here.js").status_code == 404


def test_page_and_scripts_are_revalidated(client: TestClient) -> None:
    # A plain reload must never run a cached app.js against a newer page.
    page = client.get("/")
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "ctrlKey || e.metaKey" in script.text  # Enter is a newline
    for response in (page, script):
        assert response.headers["cache-control"] == "no-cache"
    etag = script.headers["etag"]
    again = client.get("/static/app.js", headers={"if-none-match": etag})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


def test_state_and_cards(client: TestClient, rig: Rig) -> None:
    assert client.get("/api/state").json()["session_id"] == ""
    cards = client.get("/api/cards").json()
    assert [c["id"] for c in cards] == [c.id for c in rig.engine.deck]
    assert not any(c["done"] for c in cards)


def test_start_then_message(client: TestClient, rig: Rig) -> None:
    card = rig.engine.deck[0].id
    started = client.post("/api/start", json={"card_id": card})
    assert started.status_code == 200
    assert started.json()["card"]["id"] == card
    reply = client.post("/api/message", json={"text": " hello ", "msg_id": "m1"})
    assert reply.status_code == 200
    texts = [m["text"] for m in reply.json()["messages"]]
    assert texts == ["Begin", "hello", "Next"]


def test_leaving_the_app_closes_the_model_session(rig: Rig) -> None:
    with TestClient(create_app(rig.engine, media_dirs=(rig.images, rig.svgs))) as c:
        c.post("/api/start", json={})
        assert rig.fake.closed == 0
    assert rig.fake.closed == 1


def test_start_defaults_to_the_first_open_card(client: TestClient) -> None:
    assert client.post("/api/start", json={}).status_code == 200


def test_unknown_card_is_a_502_with_a_traceback(client: TestClient) -> None:
    response = client.post("/api/start", json={"card_id": "no-such-card"})
    assert response.status_code == 502
    body = response.json()
    assert body["type"] == "ValueError"
    assert "unknown card" in body["error"]
    assert "Traceback" in body["traceback"]


@pytest.mark.parametrize("raw", ["not json {", "[1, 2]", "7"])
def test_start_survives_a_bad_body(client: TestClient, raw: str) -> None:
    response = client.post(
        "/api/start", content=raw, headers={"content-type": "application/json"}
    )
    assert response.status_code == 200


def test_empty_message_is_a_400(client: TestClient) -> None:
    response = client.post("/api/message", json={"text": "  "})
    assert response.status_code == 400
    assert response.json() == {"error": "empty message"}
    assert client.post("/api/message", content="oops").status_code == 400


def test_message_before_start_is_a_502(client: TestClient) -> None:
    response = client.post("/api/message", json={"text": "hi"})
    assert response.status_code == 502
    assert response.json()["error"] == "no session started"


def test_resent_msg_id_is_answered_once(client: TestClient, rig: Rig) -> None:
    client.post("/api/start", json={})
    first = client.post("/api/message", json={"text": "hi", "msg_id": "m" * 100})
    again = client.post("/api/message", json={"text": "hi", "msg_id": "m" * 100})
    assert again.json()["messages"] == first.json()["messages"]
    assert len(rig.fake.prompts) == 2
    assert rig.engine._conv is not None
    assert rig.engine._conv.answered_id == "m" * 64


def test_unexpected_error_is_a_500_with_the_error_body(rig: Rig) -> None:
    # No route maps a KeyError: the app-level handler answers, then Starlette
    # re-raises for uvicorn's log (hence raise_server_exceptions=False).
    app = create_app(rig.engine, media_dirs=(rig.images, rig.svgs))
    with TestClient(app, raise_server_exceptions=False) as c:
        c.post("/api/start", json={})
        rig.fake.replies.insert(0, KeyError("boom"))
        response = c.post("/api/message", json={"text": "hi"})
    assert response.status_code == 500
    body = response.json()
    assert body["type"] == "KeyError"
    assert body["error"] == "'boom'"
    assert "KeyError: 'boom'" in body["traceback"]


def test_sdk_error_is_a_502(client: TestClient, rig: Rig) -> None:
    client.post("/api/start", json={})
    rig.fake.replies.insert(0, ProcessError("cli exited", exit_code=1))
    response = client.post("/api/message", json={"text": "hi"})
    assert response.status_code == 502
    assert response.json()["type"] == "ProcessError"


def test_media_serves_images_and_diagrams(client: TestClient, rig: Rig) -> None:
    (rig.images / f"{NAME}.png").write_bytes(b"PNGDATA")
    (rig.svgs / f"{NAME}.svg").write_text("<svg/>", encoding="utf-8")
    assert client.get(f"/media/{NAME}.png").content == b"PNGDATA"
    assert client.get(f"/media/{NAME}.svg").text == "<svg/>"


@pytest.mark.parametrize("name", ["..%2Fsecret.png", "short.png", f"{NAME}.exe"])
def test_media_unsafe_name_is_404(client: TestClient, name: str) -> None:
    assert client.get(f"/media/{name}").status_code == 404


def test_media_missing_file_is_404(client: TestClient) -> None:
    assert client.get(f"/media/{NAME}.png").status_code == 404
    assert client.get(f"/media/{NAME}-1.svg").status_code == 404


def test_create_app_builds_its_own_engine(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "Engine", lambda: rig.engine)
    cache = tmp_path / "images"
    cache.mkdir()
    (cache / f"{NAME}.jpg").write_bytes(b"JPG")
    with TestClient(create_app()) as c:
        assert c.get("/api/cards").status_code == 200
        assert c.get(f"/media/{NAME}.jpg").content == b"JPG"
        assert rig.engine.deck
