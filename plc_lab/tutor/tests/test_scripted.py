# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The scripted learner against a fake tutor API and a fake learner model."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import TYPE_CHECKING, Any, ClassVar, Self

import pytest

from plc_lab.tutor import scripted
from plc_lab.tutor.session import Prompt, Reply

if TYPE_CHECKING:
    from collections.abc import Callable
    import urllib.request

    from claude_agent_sdk import ClaudeAgentOptions


def state(
    *,
    done: bool = False,
    recorded: bool = False,
    check_open: bool = False,
    tutor: str = "Tutor says hi",
    **message: Any,
) -> dict[str, Any]:
    """An /api state whose last message is the tutor's."""
    return {
        "messages": [{"text": tutor, "card_done": done, **message}],
        "receipts": [{"recorded": recorded}],
        "check_open": check_open,
        "session_id": "sess-1",
        "credited_minutes": 10,
        "target_minutes": 20,
    }


class Api:
    """Fake ``scripted._call``: serves queued states and records every request."""

    def __init__(
        self, *states: dict[str, Any], events: list[str] | None = None
    ) -> None:
        self.states = list(states)
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.events = events if events is not None else []

    def __call__(self, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((url, body))
        self.events.append("call")
        if url.endswith("/api/stop"):
            return {}  # the stopped state is empty; the run returns the one before
        return self.states.pop(0)


class FakeLearner:
    """Replaces ``TutorSession`` for the learner: canned replies, counts close."""

    instances: ClassVar[list[FakeLearner]] = []

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.prompts: list[Prompt] = []
        self.closed = 0
        FakeLearner.instances.append(self)

    async def ask_raw(self, prompt: Prompt) -> Reply:
        self.prompts.append(prompt)
        return Reply(None, f"  learner reply {len(self.prompts)} \n", {}, 0, 0.0)

    async def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def fake_learner(monkeypatch: pytest.MonkeyPatch) -> type[FakeLearner]:
    """Route the learner model to the fake."""
    FakeLearner.instances = []
    monkeypatch.setattr(scripted, "TutorSession", FakeLearner)
    return FakeLearner


def run(
    api: Api, max_turns: int, hook: tuple[int, str] | None = None
) -> dict[str, Any]:
    return asyncio.run(scripted.run("http://t", "card-1", max_turns, 55.0, hook))


def test_stops_when_card_done_and_a_block_is_recorded(
    monkeypatch: pytest.MonkeyPatch, fake_learner: type[FakeLearner]
) -> None:
    api = Api(state(), state(), state(done=True, recorded=True, tutor="bye"))
    monkeypatch.setattr(scripted, "_call", api)
    final = run(api, 22)
    assert final["messages"][-1]["text"] == "bye"
    assert api.calls == [
        ("http://t/api/start", {"card_id": "card-1"}),
        ("http://t/api/message", {"text": "learner reply 1", "advance_s": 55.0}),
        ("http://t/api/message", {"text": "learner reply 2", "advance_s": 55.0}),
        ("http://t/api/stop", {}),
    ]
    learner = fake_learner.instances[0]
    assert learner.closed == 1
    assert learner.options.model == scripted.LEARNER_MODEL
    assert learner.options.output_format is None
    assert learner.options.effort == "low"


def test_forced_filler_turns_and_max_turns_exhaustion(
    monkeypatch: pytest.MonkeyPatch, fake_learner: type[FakeLearner]
) -> None:
    # card_done without a recorded block never stops the run early.
    api = Api(*[state(done=True) for _ in range(8)])
    monkeypatch.setattr(scripted, "_call", api)
    run(api, 7)
    sent = [body["text"] for _, body in api.calls[1:] if body]
    assert sent == [
        "learner reply 1",
        "learner reply 2",
        "ok",
        "learner reply 3",
        "learner reply 4",
        "idk",
        "learner reply 5",
    ]
    assert len(fake_learner.instances[0].prompts) == 5
    assert not api.states


def test_first_answer_to_an_open_check_is_the_wrong_attempt(
    monkeypatch: pytest.MonkeyPatch, fake_learner: type[FakeLearner]
) -> None:
    api = Api(*[state(check_open=True) for _ in range(3)])
    monkeypatch.setattr(scripted, "_call", api)
    run(api, 2)
    sent = [body["text"] for _, body in api.calls[1:] if body]
    assert sent == [scripted.WRONG_FIRST, "learner reply 1"]
    assert len(fake_learner.instances[0].prompts) == 1


def test_learner_prompt_carries_tutor_words_and_page_notes(
    monkeypatch: pytest.MonkeyPatch, fake_learner: type[FakeLearner]
) -> None:
    first = state(tutor="Look at this", images=[{"title": "Relay"}], diagrams=[1])
    api = Api(first, state())
    monkeypatch.setattr(scripted, "_call", api)
    run(api, 1)
    prompt = fake_learner.instances[0].prompts[0]
    assert isinstance(prompt, str)
    assert prompt.startswith("Tutor says:\nLook at this\n[picture on the page: Relay]")
    assert prompt.endswith("\nYour reply:")


def test_hook_runs_at_the_hook_turn_before_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    api = Api(*[state() for _ in range(4)], events=events)
    monkeypatch.setattr(scripted, "_call", api)
    runs: list[tuple[list[str], bool]] = []

    def fake_run(cmd: list[str], *, check: bool) -> None:
        events.append("hook")
        runs.append((cmd, check))

    monkeypatch.setattr(subprocess, "run", fake_run)
    run(api, 3, hook=(1, "echo shot"))
    assert runs == [(["/bin/bash", "-c", "echo shot"], False)]
    assert events == ["call", "call", "hook", "call", "call", "call"]


def test_page_notes_images_and_diagrams() -> None:
    assert scripted._page_notes({}) == ""
    both = {
        "images": [{"title": "A"}, {"title": "B"}],
        "diagrams": [{}],
        "diagram_title": "Coil circuit",
    }
    assert scripted._page_notes(both) == (
        "[picture on the page: A]\n[picture on the page: B]\n"
        "[circuit diagram on the page: Coil circuit]"
    )
    assert scripted._page_notes({"diagrams": [{}]}) == (
        "[circuit diagram on the page: ]"
    )


class FakeResponse:
    """What ``urlopen`` returns: a context manager with ``read``."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def fake_urlopen(
    seen: list[tuple[urllib.request.Request, float]],
) -> Callable[..., FakeResponse]:
    def urlopen(req: urllib.request.Request, timeout: float) -> FakeResponse:
        seen.append((req, timeout))
        return FakeResponse({"ok": True})

    return urlopen


def test_call_get_and_post(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[urllib.request.Request, float]] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen(seen))
    assert scripted._call("http://127.0.0.1:8779/api/state?x=1") == {"ok": True}
    assert scripted._call("http://localhost/api/start", {"card_id": "c"}) == {
        "ok": True
    }
    get, post = seen
    assert get[0].full_url == "http://127.0.0.1:8779/api/state?x=1"
    assert post[0].full_url == "http://localhost/api/start"
    assert get[0].get_method() == "GET"
    assert get[0].data is None
    assert get[1] == 420
    assert post[0].get_method() == "POST"
    assert post[0].data == b'{"card_id": "c"}'


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8779/api/state",
        "file:///etc/passwd",
        "http://example.test/api/state",
    ],
)
def test_call_refuses_anything_but_the_local_tutor(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    seen: list[tuple[urllib.request.Request, float]] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen(seen))
    with pytest.raises(ValueError, match="local http tutor"):
        scripted._call(url)
    assert seen == []
