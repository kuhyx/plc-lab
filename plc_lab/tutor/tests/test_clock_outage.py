# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""A backend outage never counts against the learner (kuhy, 2026-10-11)."""

from __future__ import annotations

from plc_lab.tutor.clock import (
    OUTAGE_CAP,
    REPLY_TIMEOUT,
    SEND_GRACE,
    STALLED,
    EngagementClock,
    reply_time,
)

T0 = 1_000_000.0
ANSWER = "the rack holds the power supply, the CPU and the I/O cards"


def test_a_9_minute_reply_earns_and_an_11_minute_one_does_not() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.user_reply(T0 + 9 * 60, ANSWER, low_effort=False)
    assert clock.active_seconds == 9 * 60
    late = EngagementClock(T0)
    late.tutor_message(T0)
    late.user_reply(T0 + 11 * 60, ANSWER, low_effort=False)
    assert late.active_seconds == 0
    assert late.snapshot()["paused_reason"] == STALLED


def test_a_restart_inside_the_window_starts_it_over() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.server_restarted(T0 + 500)
    assert clock.snapshot(T0 + REPLY_TIMEOUT + 60)["paused"] is False
    assert clock.snapshot(T0 + 500 + REPLY_TIMEOUT + 1)["paused_reason"] == STALLED
    clock.user_reply(T0 + 1000, ANSWER, low_effort=False)
    assert clock.active_seconds == 1000  # the whole gap, outage included


def test_a_restart_excuse_is_capped() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.server_restarted(T0 + OUTAGE_CAP - 60)
    clock.user_reply(T0 + OUTAGE_CAP + 1, ANSWER, low_effort=False)
    assert clock.active_seconds == 0


def test_a_restart_with_no_open_window_excuses_nothing() -> None:
    clock = EngagementClock(T0)
    clock.server_restarted(T0)
    clock.tutor_message(T0 + 10)
    clock.user_reply(T0 + 10 + REPLY_TIMEOUT + 1, ANSWER, low_effort=False)
    assert clock.active_seconds == 0


def test_the_next_tutor_message_drops_an_old_restart() -> None:
    clock = EngagementClock(T0)
    clock.tutor_message(T0)
    clock.server_restarted(T0 + 100)
    clock.user_reply(T0 + 200, ANSWER, low_effort=False)
    clock.tutor_message(T0 + 210)
    assert clock.snapshot(T0 + 210 + REPLY_TIMEOUT + 1)["paused_reason"] == STALLED


def test_reply_time_trusts_the_first_send_press_only_within_grace() -> None:
    assert reply_time(T0, T0 - 100) == T0 - 100
    assert reply_time(T0, T0 - SEND_GRACE) == T0 - SEND_GRACE
    assert reply_time(T0, T0 - SEND_GRACE - 1) == T0
    assert reply_time(T0, T0 + 5) == T0  # a page clock ahead of the server
    assert reply_time(T0, None) == T0
