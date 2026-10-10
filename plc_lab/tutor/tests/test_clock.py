# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The engagement clock: what counts, what does not, and when blocks release."""

from __future__ import annotations

import json

import pytest

from plc_lab.tutor.clock import (
    BLOCK_SECONDS,
    GENERATION_CAP,
    LOW_EFFORT,
    MAX_BLOCKS,
    REPLY_TIMEOUT,
    STALLED,
    TUTOR_OVERDUE,
    BlockReady,
    EngagementClock,
    is_filler,
    normalise,
)

T0 = 1_000_000.0
ANSWER = "the coil energises and the contact closes"


def exchange(clock: EngagementClock, t: float, think: float, gen: float = 0.0) -> float:
    """Tutor speaks at ``t``, learner answers after ``think``; returns next t."""
    clock.tutor_message(t)
    clock.user_reply(t + think, ANSWER, low_effort=False)
    return t + think + gen


def study(clock: EngagementClock, t: float, seconds: float) -> float:
    """Accrue exactly ``seconds`` in 100 s replies; the tutor answers instantly."""
    while seconds > 0:
        step = min(100.0, seconds)
        clock.tutor_message(t)
        clock.user_reply(t + step, ANSWER, low_effort=False)
        t += step
        seconds -= step
    return t


def test_reply_within_timeout_counts_in_full() -> None:
    clock = EngagementClock(T0)
    exchange(clock, T0, 120)
    assert clock.active_seconds == 120
    assert clock.snapshot()["paused"] is False


def test_late_reply_earns_nothing_and_pauses() -> None:
    clock = EngagementClock(T0)
    exchange(clock, T0, REPLY_TIMEOUT + 1)
    snap = clock.snapshot()
    assert clock.active_seconds == 0
    assert snap["paused"] is True
    assert snap["paused_reason"] == STALLED


def test_five_minutes_of_thinking_counts_in_full() -> None:
    # 2026-10-10: 3 min cut off real design thinking; the window is 6 min.
    assert REPLY_TIMEOUT == 360
    assert STALLED == "no reply for 6 min"
    clock = EngagementClock(T0)
    exchange(clock, T0, 300)
    assert clock.active_seconds == 300
    assert clock.snapshot()["paused"] is False


def test_late_substantive_reply_still_earns_tutor_time() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.user_reply(T0 + 400, ANSWER, low_effort=False)
    clock.tutor_message(T0 + 430)
    assert clock.active_seconds == 30


def test_generation_time_is_capped() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.user_reply(T0 + 10, ANSWER, low_effort=False)
    clock.tutor_message(T0 + 10 + 500)
    assert clock.active_seconds == 10 + GENERATION_CAP


def test_tutor_flagged_low_effort_earns_nothing() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.user_reply(T0 + 90, "the thing does the thing", low_effort=True)
    assert clock.active_seconds == 0
    assert clock.snapshot()["paused_reason"] == LOW_EFFORT


def test_filler_loop_accrues_zero_including_generation() -> None:
    clock = EngagementClock(T0)
    t = T0
    for word in ("ok", "k", "hmm", "idk", "?", "OK!!", "okkk", "  ", "👍", "..."):
        clock.tutor_message(t)
        clock.user_reply(t + 30, word, low_effort=False)
        t += 80
    clock.tutor_message(t)
    assert clock.active_seconds == 0


def test_yes_no_is_filler_only_without_open_check() -> None:
    clock = EngagementClock(T0)
    exchange(clock, T0, 50)
    clock.tutor_message(T0 + 60)  # +10 tutor time
    clock.user_reply(T0 + 70, "yes", low_effort=False)  # no check open: filler
    assert clock.active_seconds == 60
    clock.check_posed(T0 + 80)
    clock.tutor_message(T0 + 80)  # no credited reply pending: +0
    clock.user_reply(T0 + 100, "No.", low_effort=False)  # answers the check: +20
    assert clock.active_seconds == 80
    clock.check_result(T0 + 101, passed=False)  # closes the check
    clock.tutor_message(T0 + 110)  # +10 tutor time
    clock.user_reply(T0 + 120, "no", low_effort=False)  # filler again
    assert clock.active_seconds == 90


@pytest.mark.parametrize(
    ("text", "check_open", "expected"),
    [
        ("Hmmm...", False, True),
        ("I don't know", False, True),
        ("yes", True, False),
        ("yes", False, True),
        ("yes because the PLC scans inputs first", False, False),
        ("PLC", False, False),
    ],
)
def test_is_filler(text: str, check_open: bool, expected: bool) -> None:
    assert is_filler(text, check_open=check_open) is expected


def test_normalise_squeezes_and_strips() -> None:
    assert normalise("  OKKK!!  got   IT ") == "ok got it"
    assert normalise("???") == "?"


def test_reply_without_tutor_message_earns_nothing() -> None:
    clock = EngagementClock(T0)
    clock.user_reply(T0 + 5, ANSWER, low_effort=False)
    clock.user_reply(T0 + 9, ANSWER, low_effort=False)
    clock.tutor_message(T0 + 20)
    assert clock.active_seconds == 0


def test_backwards_time_earns_zero_without_raising() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.user_reply(T0 - 50, ANSWER, low_effort=False)
    clock.tutor_message(T0 - 100)
    assert clock.active_seconds == 0


def test_block_waits_for_a_passed_check() -> None:
    clock = EngagementClock(T0)
    t = study(clock, T0, BLOCK_SECONDS)
    assert clock.ready_blocks() == []
    assert clock.snapshot()["blocks_pending_check"] == 1
    clock.check_result(t, passed=False)
    assert clock.ready_blocks() == []
    clock.check_result(t + 1, passed=True)
    (block,) = clock.ready_blocks()
    assert block == BlockReady(1, BLOCK_SECONDS, t + 1, 1, 2)
    assert clock.ready_blocks() == []


def test_pass_before_threshold_releases_at_threshold() -> None:
    clock = EngagementClock(T0)
    clock.check_result(T0, passed=True)
    t = study(clock, T0, BLOCK_SECONDS)
    (block,) = clock.ready_blocks()
    assert block.ended_at == t
    assert (block.checks_passed, block.checks_total) == (1, 1)


def test_one_pass_cannot_earn_two_blocks() -> None:
    clock = EngagementClock(T0)
    clock.check_result(T0, passed=True)
    t = study(clock, T0, 2 * BLOCK_SECONDS)
    assert [b.block for b in clock.ready_blocks()] == [1]
    snap = clock.snapshot()
    assert (snap["blocks_earned"], snap["blocks_pending_check"]) == (1, 1)
    clock.check_result(t, passed=True)
    assert [b.block for b in clock.ready_blocks()] == [2]


def test_never_more_than_max_blocks() -> None:
    clock = EngagementClock(T0)
    t = T0
    for _ in range(MAX_BLOCKS + 2):
        clock.check_result(t, passed=True)
        t = study(clock, t, BLOCK_SECONDS)
    blocks = clock.ready_blocks()
    assert [b.block for b in blocks] == list(range(1, MAX_BLOCKS + 1))
    assert clock.snapshot()["blocks_pending_check"] == 0
    assert clock.active_seconds == (MAX_BLOCKS + 2) * BLOCK_SECONDS


def test_snapshot_is_json_and_sees_live_pauses() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    assert clock.snapshot(T0 + 100)["paused"] is False
    assert clock.snapshot(T0 + REPLY_TIMEOUT + 1)["paused_reason"] == STALLED
    clock.user_reply(T0 + 20, ANSWER, low_effort=False)
    assert clock.snapshot(T0 + 50)["paused"] is False
    clock.tutor_message(T0 + 30)
    clock.user_reply(T0 + 40, "ok", low_effort=False)
    assert clock.snapshot(T0 + 45)["paused_reason"] == LOW_EFFORT
    clock.tutor_message(T0 + 50)
    assert clock.snapshot()["paused_reason"] == LOW_EFFORT  # sticky without now
    assert clock.snapshot(T0 + 60)["paused"] is False  # live window is running
    clock.user_reply(T0 + 60, ANSWER, low_effort=False)
    assert clock.snapshot(T0 + 200)["paused_reason"] == TUTOR_OVERDUE
    assert set(json.loads(json.dumps(clock.snapshot()))) == {
        "active_seconds",
        "blocks_earned",
        "blocks_pending_check",
        "paused",
        "paused_reason",
    }
