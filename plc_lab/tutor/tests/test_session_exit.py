# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The session task's failure paths: relayed turns, a dying CLI, late replies."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeAgentOptions
import pytest

from plc_lab.tutor import session
from plc_lab.tutor.session import SessionError, TutorSession
from plc_lab.tutor.tests.test_session import FakeClient, result
from plc_lab.tutor.tests.test_session_task import DeadOnStart

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    """Route the session to the fake client with an empty script."""
    FakeClient.scripts = []
    FakeClient.instances = []
    monkeypatch.setattr(session, "ClaudeSDKClient", FakeClient)
    return FakeClient


def test_a_model_error_turn_is_relayed_and_the_process_kept(
    fake_client: type[FakeClient],
) -> None:
    fake_client.scripts = [
        [result(is_error=True, subtype="error_during_execution")],
        [result(result="again")],
    ]

    async def go() -> str:
        sess = TutorSession(ClaudeAgentOptions())
        try:
            with pytest.raises(SessionError, match="model error"):
                await sess.ask_raw("first")
            return (await sess.ask_raw("second")).text
        finally:
            await sess.close()

    assert asyncio.run(go()) == "again"
    assert len(fake_client.instances) == 1


def test_a_cli_dying_mid_turn_fails_the_caller_fast_and_restarts(
    fake_client: type[FakeClient],
) -> None:
    fake_client.scripts = [RuntimeError("cli died"), [result(result="fresh")]]

    async def go() -> str:
        sess = TutorSession(ClaudeAgentOptions())
        with pytest.raises(RuntimeError, match="cli died"):
            await asyncio.wait_for(sess.ask_raw("first"), 5)
        assert sess.restarts == 1  # counted before the caller was failed
        await asyncio.sleep(0)  # let _on_exit run
        assert sess._task is None
        assert sess._inflight is None
        reply = await sess.ask_raw("second")
        await sess.close()
        return reply.text

    assert asyncio.run(go()) == "fresh"
    assert len(fake_client.instances) == 2
    assert fake_client.instances[0].exited
    assert fake_client.instances[1].prompts == ["second"]


class Gated(FakeClient):
    """Each reply waits for ``gate``; the test opens it after the caller gave up."""

    gate: asyncio.Event | None = None

    async def receive_response(self) -> AsyncIterator[Any]:
        assert Gated.gate is not None
        await Gated.gate.wait()
        async for msg in super().receive_response():
            yield msg


@pytest.mark.parametrize(
    "late",
    [[result(result="late")], [result(is_error=True, subtype="error_max_turns")]],
)
def test_a_reply_after_the_caller_timed_out_is_dropped(
    monkeypatch: pytest.MonkeyPatch, late: list[Any]
) -> None:
    monkeypatch.setattr(session, "ClaudeSDKClient", Gated)
    monkeypatch.setattr(session, "_TURN_TIMEOUT", 0.05)
    FakeClient.scripts = [late, [result(result="next")]]

    async def go() -> str:
        Gated.gate = asyncio.Event()
        sess = TutorSession(ClaudeAgentOptions())
        with pytest.raises(TimeoutError):
            await sess.ask_raw("slow")
        Gated.gate.set()
        reply = await sess.ask_raw("next")  # the task survived the late reply
        await sess.close()
        return reply.text

    assert asyncio.run(go()) == "next"
    assert len(FakeClient.instances) == 1


def _task_of(sess: TutorSession) -> asyncio.Task[None] | None:
    """Read ``_task`` afresh (mypy keeps the narrowing from an assignment)."""
    return sess._task


def _waiter(loop: asyncio.AbstractEventLoop) -> asyncio.Future[session.Reply]:
    return loop.create_future()


def test_callers_queued_behind_a_dead_process_fail_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    DeadOnStart.failures = 1
    monkeypatch.setattr(session, "ClaudeSDKClient", DeadOnStart)

    async def scenario() -> None:
        sess = TutorSession(ClaudeAgentOptions())
        fut = _waiter(asyncio.get_running_loop())
        await sess._queue.put(None)  # a sentinel left in the queue is skipped
        await sess._queue.put(("queued", fut))
        with pytest.raises(OSError, match="CLI not found"):
            await sess.ask_raw("one")
        with pytest.raises(OSError, match="CLI not found"):
            await fut
        assert sess._queue.empty()

    asyncio.run(scenario())


def test_a_clean_exit_fails_callers_left_waiting(
    fake_client: type[FakeClient],
) -> None:
    async def scenario() -> None:
        sess = TutorSession(ClaudeAgentOptions())
        loop = asyncio.get_running_loop()
        inflight, queued = _waiter(loop), _waiter(loop)
        sess._inflight = inflight
        await sess._queue.put(("queued", queued))
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        sess._on_exit(task)
        for fut in (inflight, queued):
            with pytest.raises(SessionError, match="closed before replying"):
                await fut

    asyncio.run(scenario())
    assert fake_client.instances == []


def test_a_cancelled_task_cancels_its_callers() -> None:
    async def scenario() -> None:
        sess = TutorSession(ClaudeAgentOptions())
        fut = _waiter(asyncio.get_running_loop())
        await sess._queue.put(("queued", fut))
        task = asyncio.create_task(asyncio.sleep(10))
        sess._task = task
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait({task})
        sess._on_exit(task)
        assert fut.cancelled()
        assert sess._task is None

    asyncio.run(scenario())


def test_an_old_task_exiting_leaves_its_replacement_alone() -> None:
    async def scenario() -> None:
        sess = TutorSession(ClaudeAgentOptions())
        old = asyncio.create_task(asyncio.sleep(0))
        await old
        current = asyncio.create_task(asyncio.sleep(0))
        sess._task = current
        sess._on_exit(old)  # clean exit, nobody waiting: nothing to do
        assert sess._task is current
        assert sess.restarts == 0  # a stale task is not the live process
        await current

    asyncio.run(scenario())


def test_close_after_the_task_died_puts_no_sentinel() -> None:
    async def scenario() -> None:
        sess = TutorSession(ClaudeAgentOptions())
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        sess._task = task  # dead, and _on_exit has not run yet
        await sess.close()
        assert _task_of(sess) is None
        assert sess._queue.empty()

    asyncio.run(scenario())


def test_close_when_on_exit_already_cleared_the_task(
    fake_client: type[FakeClient],
) -> None:
    fake_client.scripts = [RuntimeError("cli died")]

    async def scenario() -> None:
        sess = TutorSession(ClaudeAgentOptions())
        task = asyncio.create_task(sess._run())
        task.add_done_callback(sess._on_exit)
        sess._task = task
        await sess._queue.put(("x", _waiter(asyncio.get_running_loop())))
        await asyncio.wait({task})  # died; _on_exit is scheduled, not run yet
        await sess.close()
        assert sess._task is None

    asyncio.run(scenario())
