# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""One session's in-memory state: what the engine keeps and ``resume`` rebuilds.

The engine and the transcript replay apply the same events in the same way,
so the check and card bookkeeping lives here once instead of being mirrored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from plc_lab.tutor.clock import EngagementClock

# One check is graded at most this many times: "not yet" earns one re-teach and
# a second try at the same question, then the check closes either way.
MAX_CHECK_ATTEMPTS: Final = 2
_DROPPED: Final = (
    "Your check last turn was NOT opened: that check already had its "
    f"{MAX_CHECK_ATTEMPTS} attempts and is closed. Do not pose it again; teach "
    "the gap briefly and move on."
)


@dataclass
class CheckState:
    """The current card's check: open, passes, last resolution and attempt."""

    open: bool = False
    # Checks passed on the CURRENT card (reset by ``switch_card``).
    passed: int = 0
    # Active seconds when the last check resolved ("minutes since last check").
    mark: float = 0.0
    # Which answer of the open check is awaited (1..MAX_CHECK_ATTEMPTS), else 0.
    attempt: int = 0


@dataclass
class Resumption:
    """What survives a restart of the model CLI or the server."""

    # After a restart: the transcript primer the next model call starts with.
    note: str = ""
    # The session's ``restarts`` already primed for (a CLI death mid-session).
    restarts_seen: int = 0
    # Id of the last learner message answered; a resend after a dropped
    # connection (the page retries through a restart) is not asked twice.
    answered_id: str = ""


@dataclass
class Conversation:
    """Messages, receipts, check state and engine notes of the live session."""

    session_id: str
    card_id: str
    clock: EngagementClock
    messages: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    check: CheckState = field(default_factory=CheckState)
    # App notes for the model's next turn (image misses, diagram errors).
    notes: list[str] = field(default_factory=list)
    resumed: Resumption = field(default_factory=Resumption)
    # The card is finished and the learner's Next card / Stop here is pending.
    card_done: bool = False
    # The learner chose Stop here: the session is over and is never resumed.
    stopped: bool = False
    # Every card studied in this session, in order, and those finished.
    cards: list[str] = field(default_factory=list)
    cards_done: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """The session starts on its first card."""
        if not self.cards:
            self.cards = [self.card_id]

    def pose_check(self, t: float) -> None:
        """The tutor posed a comprehension check at ``t``."""
        self.clock.check_posed(t)
        self.check.open = True

    def resolve_check(self, t: float, *, passed: bool) -> None:
        """The open check was graded at ``t``."""
        self.clock.check_result(t, passed=passed)
        self.check.open = False
        self.check.mark = self.clock.active_seconds
        self.check.passed += int(passed)

    def apply_checks(self, turn: dict[str, Any], t: float) -> bool:
        """A tutor turn's grading first, then any new check it poses.

        Returns ``False`` when the turn's ``check`` was refused (the caller
        must not show it). A grade of "not yet" on attempt 1 lets the same turn
        re-pose the question as attempt 2; a pass or a failed attempt 2 closes
        the check, and a ``check`` posed in that same turn is refused rather
        than opened as a third attempt. A grade with no open check (the learner
        had already said it) counts, but a failed one never starts a retry.
        """
        prior, was_open = self.check.attempt, self.check.open
        graded = turn.get("check_result") is not None
        passed = graded and bool(turn["check_result"].get("passed"))
        if graded:
            self.resolve_check(t, passed=passed)
            self.check.attempt = 0
        failed_open = graded and was_open and not passed
        retry = failed_open and prior < MAX_CHECK_ATTEMPTS
        if turn.get("check") is None:
            return True
        if failed_open and not retry:
            self.notes.append(_DROPPED)
            return False
        self.pose_check(t)
        self.check.attempt = prior + 1 if retry else max(self.check.attempt, 1)
        return True

    def mark_card_done(self) -> bool:
        """The live card is finished; ``True`` the first time (to record it once)."""
        first = not self.card_done
        self.card_done = True
        if self.card_id not in self.cards_done:
            self.cards_done.append(self.card_id)
        return first

    def set_done(self, card_id: str, *, done: bool) -> None:
        """A manual override for one of this session's cards (live and replay)."""
        if done and card_id in self.cards and card_id not in self.cards_done:
            self.cards_done.append(card_id)
        if card_id == self.card_id:
            self.card_done = done

    def switch_card(self, card_id: str, front: str) -> dict[str, Any]:
        """Move to the next card of the same session; returns the page divider.

        The clock carries on; everything per-card starts over, including the
        restart bookkeeping (the new model process starts at zero restarts and
        must not be primed with the old card's transcript).
        """
        self.card_id = card_id
        self.cards.append(card_id)
        self.clock.check_dropped()
        self.check.open, self.check.attempt = False, 0
        self.check.passed, self.card_done = 0, False
        self.check.mark = self.clock.active_seconds
        self.notes, self.resumed.note, self.resumed.restarts_seen = [], "", 0
        divider = {"role": "card", "text": front, "card_id": card_id}
        self.messages.append(divider)
        return divider
