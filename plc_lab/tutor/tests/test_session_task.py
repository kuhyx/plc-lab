# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The session's background task, block prompts, close, and isolated options."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Self

from claude_agent_sdk import ClaudeAgentOptions
import pytest

from plc_lab.tutor import session
from plc_lab.tutor.models import TURN_SCHEMA
from plc_lab.tutor.session import (
    TutorSession,
    isolated_options,
    sandbox_dir,
)
from plc_lab.tutor.tests.test_session import FakeClient, init_msg, result

if TYPE_CHECKING:
    from pathlib import Path

BLOCKS: list[dict[str, Any]] = [
    {"type": "text", "text": "look"},
    {"type": "image", "source": {}},
]


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    """Route the session to the fake client with an empty script."""
    FakeClient.scripts = []
    FakeClient.instances = []
    monkeypatch.setattr(session, "ClaudeSDKClient", FakeClient)
    return FakeClient


async def two_asks(sess: TutorSession) -> tuple[str, str]:
    first = await sess.ask_raw("one")
    task = sess._task
    second = await sess.ask_raw(BLOCKS)
    assert sess._task is task
    await sess.close()
    return first.text, second.text


def test_ask_raw_reuses_one_task_and_streams_blocks(
    fake_client: type[FakeClient],
) -> None:
    fake_client.scripts = [
        [init_msg(v=1), result(result="a")],
        [result(result="b")],
    ]
    sess = TutorSession(ClaudeAgentOptions())
    assert asyncio.run(two_asks(sess)) == ("a", "b")
    assert len(fake_client.instances) == 1
    client = fake_client.instances[0]
    assert client.exited
    assert client.prompts[0] == "one"
    assert client.prompts[1] == [
        {
            "type": "user",
            "message": {"role": "user", "content": BLOCKS},
            "parent_tool_use_id": None,
        }
    ]
    assert sess.last_init == {"v": 1}
    assert sess._task is None


def test_last_init_is_kept_when_a_reply_has_none(
    fake_client: type[FakeClient],
) -> None:
    fake_client.scripts = [[init_msg(v=1), result()], [result()]]
    sess = TutorSession(ClaudeAgentOptions())
    assert sess.last_init == {}

    async def go() -> None:
        await sess.ask_raw("a")
        await sess.ask_raw("b")
        await sess.close()

    asyncio.run(go())
    assert sess.last_init == {"v": 1}


def test_close_without_a_started_task_is_a_noop(
    fake_client: type[FakeClient],
) -> None:
    sess = TutorSession(ClaudeAgentOptions())
    asyncio.run(sess.close())
    assert fake_client.instances == []


def test_sandbox_dir_is_under_the_redirected_home(tutor_sandbox: Path) -> None:
    assert sandbox_dir() == (
        tutor_sandbox / "home/.local/share/automation_tutor/sandbox"
    )


def test_isolated_options_structured_by_default(tutor_sandbox: Path) -> None:
    opts = isolated_options("be a tutor")
    assert opts.system_prompt == "be a tutor"
    assert opts.model == session.MODEL
    assert opts.tools == []
    assert opts.allowed_tools == []
    assert opts.setting_sources == []
    assert opts.strict_mcp_config is True
    assert opts.mcp_servers == {}
    assert opts.include_hook_events is True
    assert opts.effort == "medium"
    assert opts.output_format == {"type": "json_schema", "schema": TURN_SCHEMA}
    assert opts.cwd == sandbox_dir()
    assert sandbox_dir().is_dir()
    assert str(sandbox_dir()).startswith(str(tutor_sandbox / "home"))
    assert opts.extra_args == {
        "disable-slash-commands": None,
        "no-session-persistence": None,
    }


def test_isolated_options_free_text_explicit_cwd_and_effort(tmp_path: Path) -> None:
    cwd = tmp_path / "work" / "dir"
    opts = isolated_options("x", model="other", structured=False, cwd=cwd, effort="low")
    assert opts.output_format is None
    assert opts.model == "other"
    assert opts.effort == "low"
    assert opts.cwd == cwd
    assert cwd.is_dir()


class DeadOnStart(FakeClient):
    """The first CLI process fails to start; later ones work."""

    failures = 1

    async def __aenter__(self) -> Self:
        if DeadOnStart.failures:
            DeadOnStart.failures -= 1
            msg = "claude CLI not found"
            raise OSError(msg)
        return self


def test_a_cli_that_fails_to_start_fails_the_caller_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    DeadOnStart.failures = 1
    monkeypatch.setattr(session, "ClaudeSDKClient", DeadOnStart)
    FakeClient.scripts = [[result(result="second try")]]

    async def scenario() -> str:
        sess = TutorSession(ClaudeAgentOptions())
        with pytest.raises(OSError, match="CLI not found"):
            await asyncio.wait_for(sess.ask_raw("one"), 5)
        assert sess._task is None
        reply = await sess.ask_raw("two")  # a fresh process this time
        await sess.close()
        return reply.text

    assert asyncio.run(scenario()) == "second try"
    assert FakeClient.instances[-1].prompts == ["two"]
