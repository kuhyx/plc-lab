# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""One session's in-memory state: what the engine keeps and ``resume`` rebuilds.

The engine and the transcript replay apply the same events in the same way,
so the check bookkeeping lives here once instead of being mirrored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plc_lab.tutor.clock import EngagementClock


@dataclass
class Conversation:
    """Messages, receipts, check state and engine notes of the live session."""

    session_id: str
    card_id: str
    clock: EngagementClock
    messages: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    check_open: bool = False
    checks_passed: int = 0
    # Active seconds when the last check resolved ("minutes since last check").
    check_mark: float = 0.0
    # App notes for the model's next turn (image misses, diagram errors).
    notes: list[str] = field(default_factory=list)
    # After a restart: the transcript primer the next model call starts with.
    resume_note: str = ""
    # The session's ``restarts`` already primed for (a CLI death mid-session).
    restarts_seen: int = 0
    # Id of the last learner message answered; a resend after a dropped
    # connection (the page retries through a restart) is not asked twice.
    answered_id: str = ""

    def pose_check(self, t: float) -> None:
        """The tutor posed a comprehension check at ``t``."""
        self.clock.check_posed(t)
        self.check_open = True

    def resolve_check(self, t: float, *, passed: bool) -> None:
        """The open check was graded at ``t``."""
        self.clock.check_result(t, passed=passed)
        self.check_open = False
        self.check_mark = self.clock.active_seconds
        self.checks_passed += int(passed)

    def apply_checks(self, turn: dict[str, Any], t: float) -> None:
        """A tutor turn's grading first, then any new check it poses."""
        if turn.get("check_result") is not None:
            self.resolve_check(t, passed=bool(turn["check_result"].get("passed")))
        if turn.get("check") is not None:
            self.pose_check(t)
