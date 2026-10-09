# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The canary proof: PASS/FAIL logic, cleanup, and the script entry point."""

from __future__ import annotations

import asyncio
import runpy
import sys
from typing import TYPE_CHECKING, ClassVar

import pytest

from plc_lab.tutor import isolation, session
from plc_lab.tutor.session import Reply, isolated_options
from plc_lab.tutor.tests.test_session import FakeClient, result

if TYPE_CHECKING:
    from pathlib import Path

    from claude_agent_sdk import ClaudeAgentOptions

Answer = tuple[str, dict[str, object], int]


class Canary:
    """Fake ``isolation._ask``: records options, reads the canary like a model."""

    def __init__(
        self, tutor_text: str, tutor_hooks: int, *, control_sees: bool
    ) -> None:
        self.tutor_text = tutor_text
        self.tutor_hooks = tutor_hooks
        self.control_sees = control_sees
        self.options: list[ClaudeAgentOptions] = []
        self.canary_seen: list[bool] = []

    async def __call__(self, options: ClaudeAgentOptions) -> Answer:
        self.options.append(options)
        path = isolation.canary_file()
        self.canary_seen.append(path.is_file())
        if len(self.options) == 1:
            token = path.read_text(encoding="utf-8").split()[1]
            return (token if self.control_sees else "NONE"), {}, 3
        init: dict[str, object] = {"tools": [], "claude_code_version": "9.9"}
        token = path.read_text(encoding="utf-8").split()[1]
        return self.tutor_text.replace("TOKEN", token), init, self.tutor_hooks


@pytest.fixture(autouse=True)
def rules_dir(tutor_sandbox: Path) -> Path:
    """``~/.claude/rules`` in the redirected HOME (the canary writer assumes it)."""
    rules = tutor_sandbox / "home/.claude/rules"
    rules.mkdir(parents=True)
    return rules


def run_with(monkeypatch: pytest.MonkeyPatch, fake: Canary) -> int:
    monkeypatch.setattr(isolation, "_ask", fake)
    return asyncio.run(isolation.run_canary())


def test_canary_file_lives_under_the_redirected_home(tutor_sandbox: Path) -> None:
    assert isolation.canary_file() == (
        tutor_sandbox / "home/.claude/rules/canary-tutor.md"
    )


def test_pass_when_control_sees_token_and_tutor_sees_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Canary(" NONE ", 0, control_sees=True)
    assert run_with(monkeypatch, fake) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    assert "cli: 9.9" in out
    assert "tutor hook events: 0  (control: 3)" in out
    assert fake.canary_seen == [True, True]
    assert fake.options[0].allowed_tools == []
    assert fake.options[0].max_turns == 1
    assert fake.options[1].setting_sources == []
    assert not isolation.canary_file().exists()


@pytest.mark.parametrize(
    ("tutor_text", "hooks", "control_sees"),
    [
        ("NONE", 1, True),
        ("something else", 0, True),
        ("NONE", 0, False),
        ("NONE leaked TOKEN", 0, True),
    ],
)
def test_fail_cases(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tutor_text: str,
    hooks: int,
    control_sees: bool,
) -> None:
    fake = Canary(tutor_text, hooks, control_sees=control_sees)
    assert run_with(monkeypatch, fake) == 1
    assert "RESULT: FAIL" in capsys.readouterr().out
    assert not isolation.canary_file().exists()


def test_canary_is_deleted_even_when_ask_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []

    async def boom(_options: ClaudeAgentOptions) -> Answer:
        seen.append(isolation.canary_file().is_file())
        msg = "cli exploded"
        raise RuntimeError(msg)

    monkeypatch.setattr(isolation, "_ask", boom)
    with pytest.raises(RuntimeError, match="cli exploded"):
        asyncio.run(isolation.run_canary())
    assert seen == [True]
    assert not isolation.canary_file().exists()


class FakeSession:
    """Replaces ``TutorSession`` inside ``isolation._ask``."""

    instances: ClassVar[list[FakeSession]] = []

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.prompts: list[str] = []
        self.closed = False
        self.fail = False
        FakeSession.instances.append(self)

    async def ask_raw(self, prompt: str) -> Reply:
        self.prompts.append(prompt)
        if self.fail:
            msg = "no reply"
            raise RuntimeError(msg)
        return Reply(None, "  CANARYabc \n", {"k": 1}, 2, 0.0)

    async def close(self) -> None:
        self.closed = True


def test_ask_returns_stripped_text_init_and_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSession.instances = []
    monkeypatch.setattr(isolation, "TutorSession", FakeSession)
    options = isolated_options("x", structured=False)
    assert asyncio.run(isolation._ask(options)) == ("CANARYabc", {"k": 1}, 2)
    session = FakeSession.instances[0]
    assert session.options is options
    assert session.prompts == [isolation._ASK]
    assert session.closed


def test_ask_closes_the_session_when_the_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSession.instances = []

    class Failing(FakeSession):
        def __init__(self, options: ClaudeAgentOptions) -> None:
            super().__init__(options)
            self.fail = True

    monkeypatch.setattr(isolation, "TutorSession", Failing)
    with pytest.raises(RuntimeError, match="no reply"):
        asyncio.run(isolation._ask(isolated_options("x")))
    assert FakeSession.instances[0].closed


def test_module_runs_as_a_script_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClient.scripts = [[result(result="NONE")], [result(result="NONE")]]
    FakeClient.instances = []
    monkeypatch.setattr(session, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr("claude_agent_sdk.ClaudeSDKClient", FakeClient)
    monkeypatch.delitem(sys.modules, "plc_lab.tutor.isolation")
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("plc_lab.tutor.isolation", run_name="__main__")
    assert exit_info.value.code == 1
    assert len(FakeClient.instances) == 2
    assert not isolation.canary_file().exists()
