# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The session's card list and the manual card-done override."""

from __future__ import annotations

from plc_lab.tutor.clock import EngagementClock
from plc_lab.tutor.conversation import Conversation

T0 = 1_800_000_000.0


def test_a_given_card_list_is_kept() -> None:
    conv = Conversation("s", "b", EngagementClock(T0), cards=["a", "b"])
    assert conv.cards == ["a", "b"]


def test_set_done_on_an_earlier_card_leaves_the_current_one() -> None:
    conv = Conversation("s", "b", EngagementClock(T0), cards=["a", "b"])
    conv.set_done("a", done=True)
    assert conv.cards_done == ["a"]
    assert conv.card_done is False
    conv.set_done("a", done=True)  # already done: not listed twice
    assert conv.cards_done == ["a"]
