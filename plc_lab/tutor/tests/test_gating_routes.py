# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Gating over HTTP: /api/cards shows the lock; start and card_done refuse it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from plc_lab.tutor.engine import Engine
from plc_lab.tutor.server import create_app
from plc_lab.tutor.store import Store
from plc_lab.tutor.tests._fakes import FakeCredit, FakeSession, ManualClock, turn

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

GATED = "fund-five-languages"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = Engine(
        store=Store(tmp_path / "data"),
        now=ManualClock(),
        credit_fn=FakeCredit(),
        session_factory=lambda _prompt: FakeSession(turn("Hi")),
    )
    with TestClient(create_app(engine)) as c:
        yield c


def test_cards_route_exposes_requires_locked_and_missing(client: TestClient) -> None:
    rows = {r["id"]: r for r in client.get("/api/cards").json()}
    gated = rows[GATED]
    assert gated["locked"] is True
    assert gated["missing"] == gated["requires"]
    assert len(gated["requires"]) == 10
    assert rows["lang-ld-describe"]["locked"] is False
    assert rows["lang-ld-describe"]["requires"] == []


def test_start_route_refuses_a_locked_card(client: TestClient) -> None:
    response = client.post("/api/start", json={"card_id": GATED})
    assert response.status_code == 502
    assert f"cannot start '{GATED}': locked until lang-" in response.json()["error"]
    assert client.get("/api/state").json()["session_id"] == ""


def test_card_done_route_refuses_a_locked_card(client: TestClient) -> None:
    response = client.post("/api/card_done", json={"card_id": GATED, "done": True})
    assert response.status_code == 502
    assert f"cannot mark done '{GATED}'" in response.json()["error"]
    rows = {r["id"]: r for r in client.get("/api/cards").json()}
    assert rows[GATED]["done"] is False
