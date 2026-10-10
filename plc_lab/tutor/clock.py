# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The deterministic engagement clock: how much of a session was real study.

Pass/fail is code, never a model's opinion. The only model inputs are the
per-reply ``low_effort`` flag and each comprehension check's pass/fail; the
rest is arithmetic over event times, so "did those minutes count?" has one
answer that the learner can watch accrue instead of discovering afterwards.

Time accrues in two kinds of gap:

* **Learner gap** -- tutor message to the learner's reply. Counts in full if
  the reply arrives within :data:`REPLY_TIMEOUT` and is not low effort
  (tutor-flagged or deterministic filler); otherwise the gap earns nothing.
  It is measured from the *latest* tutor message; a reply with no unanswered
  tutor message before it earns nothing.
* **Tutor gap** -- a credited reply to the next tutor message, capped at
  :data:`GENERATION_CAP` so a hung model cannot farm time. A reply that earned
  nothing earns no tutor gap either ("ok" -> tutor -> "ok" accrues zero).

Gaps that would be negative (the wall clock stepped back) earn zero.

A block is :data:`BLOCK_SECONDS` of active time *and* at least one passed check
since the previous block; time without a pass leaves a block "pending check".
At most :data:`MAX_BLOCKS` per session. Pure: no I/O, time is injected.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

REPLY_TIMEOUT: Final = 180.0
GENERATION_CAP: Final = 60.0
BLOCK_SECONDS: Final = 900.0
MAX_BLOCKS: Final = 4

STALLED: Final = "no reply for 3 min"
LOW_EFFORT: Final = "low-effort reply"
TUTOR_OVERDUE: Final = "tutor not responding"

# Normalised (see normalise) replies that carry no engagement on their own.
# fmt: off
FILLER: Final = frozenset({
    "", "?", "k", "kk", "ok", "oki", "okay", "ok ok", "ok thanks", "ok got it",
    "yes ok", "ok yes", "ok sure", "sure", "fine", "cool", "nice", "great",
    "got it", "gotcha", "i see", "right", "alright", "mhm", "hm", "um", "uh",
    "idk", "i dont know", "dunno", "no idea", "whatever", "idc", "lol", "lmao",
    "thanks", "thx", "ty", "continue", "go on", "next", "more", "and",
})
# fmt: on
# Legitimate answers to an open check, filler otherwise.
SHORT_ANSWERS: Final = frozenset({"yes", "no", "yep", "yeah", "ya", "nope", "y", "n"})

_STRIP: Final = re.compile(r"[^\w\s?]")
_REPEAT: Final = re.compile(r"(.)\1+")
_SPACE: Final = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, drop punctuation but ``?``, squeeze runs ("okkk"/"hmmm"/"??")."""
    stripped = _STRIP.sub("", text.lower()).replace("_", "")
    squeezed = _REPEAT.sub(r"\1", stripped)
    return _SPACE.sub(" ", squeezed).strip()


_FILLER_NORMALISED: Final = frozenset(normalise(item) for item in FILLER)
_SHORT_NORMALISED: Final = frozenset(normalise(item) for item in SHORT_ANSWERS)


def is_filler(text: str, *, check_open: bool) -> bool:
    """Whether ``text`` is deterministic filler; bare yes/no answers an open check."""
    norm = normalise(text)
    if norm in _SHORT_NORMALISED:
        return not check_open
    return norm in _FILLER_NORMALISED


@dataclass(frozen=True)
class BlockReady:
    """One newly earned 15-minute block, ready to be credited.

    Attributes:
        block: Which block of the session, 1..MAX_BLOCKS.
        active_seconds: The session's *cumulative* active seconds at the moment
            the block was earned (>= block * BLOCK_SECONDS).
        ended_at: Unix time of the event that earned it.
        checks_passed: Checks passed since the previous block was earned.
        checks_total: Checks resolved (passed or failed) in the same span.
    """

    block: int
    active_seconds: float
    ended_at: float
    checks_passed: int
    checks_total: int


@dataclass(slots=True)
class _Turn:
    """Where the conversation stands: what is awaiting an answer."""

    tutor_at: float | None = None  # unanswered tutor message
    reply_at: float | None = None  # credited reply awaiting the tutor
    check_open: bool = False


@dataclass(slots=True)
class _Tally:
    """Checks resolved since the previous block was earned."""

    passed: int = 0
    total: int = 0


class EngagementClock:
    """Accrues active seconds from chat events and releases check-gated blocks."""

    def __init__(self, now: float) -> None:
        """Start a session at unix time ``now``; the start itself earns nothing."""
        del now
        self._active = 0.0
        self._turn = _Turn()
        self._tally = _Tally()
        self._earned: list[BlockReady] = []
        self._released = 0
        self._paused_reason: str | None = None

    @property
    def active_seconds(self) -> float:
        """Seconds of engagement credited so far."""
        return self._active

    def tutor_message(self, t: float) -> None:
        """The tutor finished a message at ``t`` (call once it is fully shown)."""
        if self._turn.reply_at is not None:
            self._accrue(min(t - self._turn.reply_at, GENERATION_CAP), t)
            self._turn.reply_at = None
        self._turn.tutor_at = t

    def user_reply(
        self,
        t: float,
        text: str,
        *,
        low_effort: bool,
    ) -> None:
        """The learner replied at ``t``; ``low_effort`` is the tutor's verdict."""
        if self._turn.tutor_at is None:
            return
        gap = t - self._turn.tutor_at
        self._turn.tutor_at = None
        if low_effort or is_filler(text, check_open=self._turn.check_open):
            self._paused_reason = LOW_EFFORT
            return
        # A substantive reply earns the tutor's answer time even when late.
        self._turn.reply_at = t
        if gap > REPLY_TIMEOUT:
            self._paused_reason = STALLED
            return
        self._paused_reason = None
        self._accrue(gap, t)

    def check_posed(self, t: float) -> None:
        """The tutor posed a comprehension check at ``t``; bare yes/no now counts."""
        del t
        self._turn.check_open = True

    def check_result(
        self,
        t: float,
        *,
        passed: bool,
    ) -> None:
        """The open check resolved at ``t``; a pass may release a pending block."""
        self._turn.check_open = False
        self._tally.total += 1
        if passed:
            self._tally.passed += 1
        self._release(t)

    def ready_blocks(self) -> list[BlockReady]:
        """Blocks earned since the previous call; each is returned exactly once."""
        fresh = self._earned[self._released :]
        self._released = len(self._earned)
        return fresh

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        """JSON-able state.

        Without ``now``, ``paused_reason`` says why the most recent gap earned
        nothing (sticky until a gap is credited). With ``now``, an open window
        is judged live: running (``None``), stalled, or tutor overdue.
        """
        reason = self._paused_reason
        turn = self._turn
        if now is not None and turn.tutor_at is not None:
            reason = STALLED if now - turn.tutor_at > REPLY_TIMEOUT else None
        elif now is not None and turn.reply_at is not None:
            reason = TUTOR_OVERDUE if now - turn.reply_at > GENERATION_CAP else None
        earned = len(self._earned)
        by_time = min(MAX_BLOCKS, int(self._active // BLOCK_SECONDS))
        return {
            "active_seconds": self._active,
            "blocks_earned": earned,
            "blocks_pending_check": max(0, by_time - earned),
            "paused": reason is not None,
            "paused_reason": reason,
        }

    def _accrue(self, seconds: float, t: float) -> None:
        """Add a non-negative gap, then see whether it completed a block."""
        self._active += max(0.0, seconds)
        self._release(t)

    def _release(self, t: float) -> None:
        """Earn the next block if its time is in and a check passed since the last."""
        nxt = len(self._earned) + 1
        if nxt > MAX_BLOCKS or self._tally.passed < 1:
            return
        if self._active < nxt * BLOCK_SECONDS:
            return
        self._earned.append(
            BlockReady(
                block=nxt,
                active_seconds=self._active,
                ended_at=t,
                checks_passed=self._tally.passed,
                checks_total=self._tally.total,
            )
        )
        self._tally = _Tally()
