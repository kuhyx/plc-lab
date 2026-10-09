# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The model session against a fake SDK client (no CLI is ever spawned)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar, Self

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, SystemMessage
import pytest

from plc_lab.tutor import session
from plc_lab.tutor.session import (
    Reply,
    SessionError,
    TutorSession,
    _collect,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

RAW_TURN = {
    "message": "What is a coil?",
    "low_effort": False,
    "check": None,
    "check_result": None,
    "images": [],
    "diagram": None,
    "concepts_mastered": [],
    "card_done": False,
}


def result(**fields: Any) -> ResultMessage:
    """A successful ResultMessage; any field can be overridden."""
    base: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 1,
        "session_id": "x",
        "structured_output": None,
        "result": "",
        "total_cost_usd": 0.5,
    }
    base.update(fields)
    return ResultMessage(**base)


def init_msg(**data: Any) -> SystemMessage:
    """The SDK's init system message."""
    return SystemMessage(subtype="init", data=data)


class FakeClient:
    """Replaces ``ClaudeSDKClient``: replays one scripted message list per query."""

    scripts: ClassVar[list[list[Any] | Exception]] = []
    instances: ClassVar[list[FakeClient]] = []

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.prompts: list[Any] = []
        self.exited = False
        FakeClient.instances.append(self)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.exited = True

    async def query(self, prompt: Any) -> None:
        if isinstance(prompt, str):
            self.prompts.append(prompt)
        else:
            self.prompts.append([m async for m in prompt])

    async def receive_response(self) -> AsyncIterator[Any]:
        item = FakeClient.scripts.pop(0)
        if isinstance(item, Exception):
            raise item
        for msg in item:
            yield msg


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    """Route the session to the fake client with an empty script."""
    FakeClient.scripts = []
    FakeClient.instances = []
    monkeypatch.setattr(session, "ClaudeSDKClient", FakeClient)
    return FakeClient


def test_collect_reads_init_hooks_and_result() -> None:
    reply = _collect(
        [
            init_msg(tools=[]),
            SystemMessage(subtype="hook_started", data={}),
            SystemMessage(subtype="hook_response", data={}),
            SystemMessage(subtype="status", data={}),
            object(),
            result(structured_output={"a": 1}, result="text"),
        ]
    )
    assert reply == Reply({"a": 1}, "text", {"tools": []}, 2, 0.5)


def test_collect_defaults_when_cost_and_text_missing() -> None:
    reply = _collect([result(total_cost_usd=None, result=None)])
    assert reply == Reply(None, "", {}, 0, 0.0)


def test_collect_raises_on_error_result() -> None:
    err = result(subtype="error_during_execution", is_error=True, errors=["boom"])
    with pytest.raises(SessionError, match=r"error_during_execution.*boom"):
        _collect([err])


def test_ask_uses_structured_output(fake_client: type[FakeClient]) -> None:
    fake_client.scripts = [[init_msg(v=1), result(structured_output=RAW_TURN)]]
    turn, reply = asyncio.run(_ask_then_close(TutorSession(ClaudeAgentOptions()), "hi"))
    assert turn.message == "What is a coil?"
    assert reply.cost_usd == 0.5
    assert fake_client.instances[0].prompts == ["hi"]


def test_ask_falls_back_to_json_text(fake_client: type[FakeClient]) -> None:
    text = '{"message": "Hi", "low_effort": true, "check": null, "check_result": null, '
    text += (
        '"images": [], "diagram": null, "concepts_mastered": [], "card_done": false}'
    )
    fake_client.scripts = [[result(result=text)]]
    turn, _ = asyncio.run(_ask_then_close(TutorSession(ClaudeAgentOptions()), "hi"))
    assert turn.message == "Hi"
    assert turn.low_effort is True


def test_ask_rejects_non_json_text(fake_client: type[FakeClient]) -> None:
    fake_client.scripts = [[result(result="plain words, not json")]]
    with pytest.raises(SessionError, match=r"no structured output.*plain words"):
        asyncio.run(_ask_then_close(TutorSession(ClaudeAgentOptions()), "hi"))


def test_ask_rejects_an_invalid_turn(fake_client: type[FakeClient]) -> None:
    fake_client.scripts = [[result(structured_output={"message": "x"})]]
    with pytest.raises(SessionError, match="missing"):
        asyncio.run(_ask_then_close(TutorSession(ClaudeAgentOptions()), "hi"))


async def _ask_then_close(sess: TutorSession, prompt: Any) -> Any:
    try:
        return await sess.ask(prompt)
    finally:
        await sess.close()
