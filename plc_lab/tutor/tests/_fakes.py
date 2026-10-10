# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Test doubles: a scripted model session and a manual clock (no real model)."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from plc_lab.tutor.models import TutorTurn
from plc_lab.tutor.session import Prompt, Reply, TutorSession


def turn(message: str = "What do you know about a coil?", **fields: Any) -> TutorTurn:
    """A valid tutor turn; any field can be overridden."""
    fields.setdefault("low_effort", False)
    return TutorTurn(message=message, **fields)


class CliDiedError(RuntimeError):
    """A scripted reply: the CLI dies mid-turn (counted as ``_on_exit`` does)."""


class FakeSession(TutorSession):
    """Answers each ``ask`` with the next scripted turn (or raises it)."""

    def __init__(self, *replies: TutorTurn | Exception) -> None:
        """Queue the replies; nothing is spawned."""
        super().__init__(ClaudeAgentOptions())
        self.replies = list(replies)
        self.prompts: list[Prompt] = []
        self.closed = 0

    async def ask(self, prompt: Prompt) -> tuple[TutorTurn, Reply]:
        """The next scripted reply."""
        self.prompts.append(prompt)
        item = self.replies.pop(0)
        if isinstance(item, CliDiedError):
            self.restarts += 1  # before the caller sees the failure
        if isinstance(item, Exception):
            raise item
        return item, Reply(None, item.message, {}, 0, 0.25)

    async def close(self) -> None:
        """Count closes."""
        self.closed += 1


class ManualClock:
    """``now`` for the engine: starts at ``t`` and moves only when told to."""

    def __init__(self, t: float = 1_800_000_000.0) -> None:
        """Start at ``t``."""
        self.t = t

    def __call__(self) -> float:
        """The current time."""
        return self.t

    def advance(self, seconds: float) -> None:
        """Move time forward."""
        self.t += seconds
