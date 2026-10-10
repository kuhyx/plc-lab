# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""What happens around a card inside one session: its end, the next one, stop.

One card, one session. When the learner gives the card's answer the tutor
sets ``card_done`` and the page offers Next card (this session ends and a new
one starts on the next unfinished card) or Stop here (the session ends and is
never resumed). Older transcripts may still hold an in-session ``next_card``
switch; replay keeps reading those. ``Engine`` mixes this in; the
attributes it needs are declared below for the type checker.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Final

from plc_lab.tutor import unit_credit

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from plc_lab import cards as cards_mod
    from plc_lab.tutor.clock import BlockReady
    from plc_lab.tutor.conversation import Conversation
    from plc_lab.tutor.models import TutorTurn
    from plc_lab.tutor.session import TutorSession
    from plc_lab.tutor.store import Store

TARGET_MINUTES: Final = 60


class CardFlow:
    """Turn application, crediting, ``next_card``, ``stop`` and ``state``."""

    if TYPE_CHECKING:
        store: Store
        deck: list[cards_mod.Card]
        card: cards_mod.Card | None
        minutes_today: int
        _session: TutorSession | None
        _conv: Conversation | None
        _lock: asyncio.Lock
        _factory: Callable[[str], TutorSession]
        _credit: Callable[[list[BlockReady], str], list[dict[str, Any]]]

        @property
        def session_id(self) -> str:
            """The live session's id (``Engine``)."""

        @property
        def messages(self) -> list[dict[str, Any]]:
            """The live session's page messages (``Engine``)."""

        @property
        def receipts(self) -> list[dict[str, Any]]:
            """The live session's credit rows (``Engine``)."""

        time: Callable[[], float]
        start: Callable[..., Awaitable[dict[str, Any]]]
        _live: Callable[[], tuple[TutorSession, Conversation, cards_mod.Card]]
        _turn: Callable[..., Awaitable[None]]

    async def next_card(self) -> dict[str, Any]:
        """End this session and start a NEW one on the next unfinished card.

        One card, one session (kuhy, 2026-10-10): the transcript, URL and
        history row each stay about a single card. The ended session logs the
        choice (``next_card``) and a ``stop``, so it is never resumed. Raises
        ``ValueError`` when no card is left, before anything changes.
        """
        async with self._lock:
            _, conv, card = self._live()
            done = self.store.progress()["cards_done"]
            nxt = next(
                (c for c in self.deck if c.id not in done and c.id != card.id), None
            )
            if nxt is None:  # before anything changes: the session stays intact
                msg = "no unfinished card left"
                raise ValueError(msg)
            self.store.log(conv.session_id, {"type": "next_card", "card": nxt.id})
            self.store.log(conv.session_id, {"type": "stop"})
        return await self.start(nxt.id)

    async def stop(self) -> dict[str, Any]:
        """End the live session for good (nothing live: a no-op)."""
        async with self._lock:
            if self._conv is not None:
                self.store.log(self._conv.session_id, {"type": "stop"})
            if self._session is not None:
                await self._session.close()
            self._session, self._conv, self.card = None, None, None
        return self.state()

    async def set_card_done(self, card_id: str, *, done: bool) -> dict[str, Any]:
        """Manual override: mark ``card_id`` done (or not); never touches credit.

        Raises ``ValueError`` for a card not in the deck. Done on the live card
        opens the Next card / Stop here choice, like the tutor's own
        ``card_done``. Logged in the live transcript when the card belongs to it.
        """
        async with self._lock:
            if not any(c.id == card_id for c in self.deck):
                msg = f"unknown card {card_id!r}"
                raise ValueError(msg)
            conv = self._conv
            if done:
                was = self.store.progress()["cards_done"].get(card_id) or {}
                sid = conv.session_id if conv else str(was.get("session", "manual"))
                self.store.finish_card(card_id, sid)
            else:
                self.store.unfinish_card(card_id)
            if conv is not None and card_id in conv.cards:
                conv.set_done(card_id, done=done)
                event = {"type": "card_done_manual", "card": card_id, "done": done}
                self.store.log(conv.session_id, event)
        return self.state()

    def state(self) -> dict[str, Any]:
        """Everything the page needs to draw itself."""
        conv = self._conv
        card = self.card
        return {
            "session_id": self.session_id,
            "card": {"id": card.id, "front": card.front} if card else None,
            "messages": self.messages,
            "clock": conv.clock.snapshot(self.time()) if conv else {},
            "credited_minutes": min(self.minutes_today, TARGET_MINUTES),
            "session_credited_minutes": unit_credit.paid_minutes(self.receipts),
            "target_minutes": TARGET_MINUTES,
            "receipts": self.receipts,
            "mastered": self.store.mastered(),
            "check_open": bool(conv and conv.check.open),
            "card_done": bool(conv and conv.card_done),
        }

    def _apply(self, turn: TutorTurn, t: float, message: dict[str, Any]) -> None:
        _, conv, card = self._live()
        logged = asdict(turn)
        if not conv.apply_checks(logged, t):
            message["check"] = None  # a refused third attempt is never shown
        if not turn.low_effort and turn.concepts_mastered:
            names = [c.strip().lower() for c in turn.concepts_mastered if c.strip()]
            message["mastered_new"] = self.store.master(names, card.id, self.session_id)
        if turn.card_done:  # the tutor's word is enough (b193: a gate dropped it)
            if conv.mark_card_done():
                self.store.finish_card(card.id, self.session_id)
            message["card_done"] = True
        conv.messages.append(message)
        self.store.log(
            self.session_id, {"type": "tutor", "turn": logged, "ui": message, "t": t}
        )
        self._record(conv.clock.ready_blocks())

    def _record(self, units: list[BlockReady]) -> None:
        """Credit the minutes a turn released: one ledger row per span of them."""
        for row in self._credit(units, self.session_id) if units else []:
            if row["recorded"]:
                self.minutes_today = max(self.minutes_today, row["minutes_today"])
            self.receipts.append(row)
            self.store.log(self.session_id, {"type": "credit", **row})
