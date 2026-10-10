# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Test doubles: a scripted model session and a manual clock (no real model)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeAgentOptions

from plc_lab.tutor.models import TutorTurn
from plc_lab.tutor.session import Prompt, Reply, TutorSession

if TYPE_CHECKING:
    from plc_lab.tutor.clock import BlockReady


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


class FakeCredit:
    """An injected ``credit_fn``: one row per call, no ledger touched.

    ``error`` makes every row a refusal (nothing recorded, nothing paid).
    """

    def __init__(self, *, error: str | None = None) -> None:
        """Pay nothing and record nothing until called."""
        self.error = error
        self.calls: list[list[BlockReady]] = []
        self.sessions: list[str] = []
        self.total = 0

    def __call__(self, units: list[BlockReady], sid: str) -> list[dict[str, Any]]:
        """Remember the call; return the receipt row the real writer would."""
        self.calls.append(list(units))
        self.sessions.append(sid)
        last = units[-1]
        paid = 0 if self.error else len(units)
        self.total += paid
        return [
            {
                "block": last.block,
                "span": len(units),
                "checks_passed": last.checks_passed,
                "recorded": self.error is None,
                "minutes": paid,
                "minutes_today": self.total,
                "entry_id": f"{sid}-m{last.block}",
                "error": self.error,
            }
        ]

    @property
    def blocks(self) -> list[list[int]]:
        """The minute numbers of each call."""
        return [[u.block for u in call] for call in self.calls]
