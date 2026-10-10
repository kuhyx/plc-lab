# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The session engine: model turns in, clock / credit / store / media wired up.

Every event goes to the engagement clock the moment it happens; the model only
supplies the per-reply ``low_effort`` flag and each check's pass/fail. Credit
is written for each active minute the clock releases (``unit_credit`` holds the
ledger seam), and the UI only claims it once the ledger read-back says it is
recorded. Card end, Next card, Stop and ``state`` live in ``cardflow``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Final
import uuid

from plc_lab import cards as cards_mod
from plc_lab.tutor import backfill, media, repair, resume, unit_credit
from plc_lab.tutor.cardflow import CardFlow
from plc_lab.tutor.clock import EngagementClock
from plc_lab.tutor.conversation import Conversation
from plc_lab.tutor.prompt import engine_note, system_prompt, wrap_learner
from plc_lab.tutor.session import TutorSession, isolated_options
from plc_lab.tutor.store import Store

if TYPE_CHECKING:
    from collections.abc import Callable

    from plc_lab.tutor.clock import BlockReady

DECK_DIR: Final = Path(__file__).resolve().parents[2] / "deck"


class Engine(CardFlow):
    """One study session at a time, for one learner."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        now: Callable[[], float] = time.time,
        credit_fn: Callable[[list[BlockReady], str], list[dict[str, Any]]]
        | None = None,
        session_factory: Callable[[str], TutorSession] | None = None,
        simulated_time: bool = False,
    ) -> None:
        """Wire the collaborators; ``simulated_time`` lets a driver skip ahead."""
        self.store = store or Store()
        self._now = now
        self._credit = credit_fn or (
            lambda units, sid: unit_credit.credit_units(units, sid, now=self.time())
        )
        self._factory = session_factory or (
            lambda prompt: TutorSession(isolated_options(prompt))
        )
        self.simulated = simulated_time
        self._offset = 0.0
        self._lock = asyncio.Lock()
        self.deck = cards_mod.load_deck(DECK_DIR)
        self.card: cards_mod.Card | None = None
        self.minutes_today = 0
        self._session: TutorSession | None = None
        self._conv: Conversation | None = None

    @property
    def session_id(self) -> str:
        """The live session's id, or ``""`` before the first start."""
        return self._conv.session_id if self._conv else ""

    @property
    def messages(self) -> list[dict[str, Any]]:
        """The page messages of the live session, oldest first."""
        return self._conv.messages if self._conv else []

    @property
    def receipts(self) -> list[dict[str, Any]]:
        """One row per credit attempt of the live session."""
        return self._conv.receipts if self._conv else []

    def time(self) -> float:
        """The engine's clock (wall time plus any simulated skip)."""
        return self._now() + self._offset

    def cards(self) -> list[dict[str, Any]]:
        """Every card with whether it is done, for the picker."""
        done = self.store.progress()["cards_done"]
        return [
            {"id": c.id, "front": c.front, "topic": c.topic.title, "done": c.id in done}
            for c in self.deck
        ]

    async def start(self, card_id: str | None = None) -> dict[str, Any]:
        """Begin a session on ``card_id`` (default: first card not yet done)."""
        async with self._lock:
            if self._session is not None:
                await self._session.close()
            done = self.store.progress()["cards_done"]
            pool = [c for c in self.deck if c.id == card_id] if card_id else self.deck
            card = next((c for c in pool if card_id or c.id not in done), None)
            if card is None:
                msg = f"unknown card {card_id!r}"
                raise ValueError(msg)
            self.card = card
            self._conv = Conversation(
                session_id=f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}",
                card_id=card.id,
                clock=EngagementClock(self.time()),
            )
            self._session = self._factory(system_prompt(card, self.store.mastered()))
            self.store.log(self.session_id, {"type": "start", "card": card.id})
            await self._turn("Begin the session.", learner_text=None)
        return self.state()

    def repair_done_cards(self) -> list[tuple[str, str]]:
        """Run the one-off card_done repair (see ``repair``)."""
        return repair.repair_done_cards(self.store)

    def backfill_today(self) -> None:
        """Credit minutes today's transcripts earned but never got paid (idempotent)."""
        paid = backfill.backfill_day(
            self.store.root / "sessions",
            time.strftime("%Y%m%d"),
            self._credit,
            self.store.log,
        )
        self.minutes_today = max(self.minutes_today, paid)

    def resume_latest(self) -> bool:
        """Pick today's newest session back up after a restart (see ``resume``).

        Nothing is spawned here: the model process starts on the next reply,
        primed with the transcript. ``False`` when there is nothing to resume.
        """
        path = resume.latest_today(
            self.store.root / "sessions", time.strftime("%Y%m%d")
        )
        state = resume.replay(path) if path else None
        conv = state.conversation if state else None
        card = next((c for c in self.deck if conv and c.id == conv.card_id), None)
        if state is None or conv is None or card is None or conv.stopped:
            return False
        self.card, self._conv = card, conv
        self.minutes_today = unit_credit.minutes_today(conv.receipts)
        self._session = self._factory(system_prompt(card, self.store.mastered()))
        conv.resumed.note = resume.primer(conv.messages)
        self.store.log(self.session_id, {"type": "resume"})
        # Top-up: minutes no row paid yet; a span's entry id is deterministic,
        # so a retry rewrites the same row and never doubles.
        self._record(state.unrecorded)
        return True

    async def reply(
        self, text: str, advance_s: float = 0.0, msg_id: str = ""
    ) -> dict[str, Any]:
        """The learner answers; returns the new state (a resent ``msg_id``: no-op)."""
        async with self._lock:
            _, conv, _ = self._live()
            if msg_id and msg_id == conv.resumed.answered_id:
                return self.state()
            if self.simulated:
                self._offset += max(0.0, advance_s)
            await self._turn(text, learner_text=text, msg_id=msg_id)
            conv.resumed.answered_id = msg_id
        return self.state()

    async def close(self) -> None:
        """Stop the model process."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _live(self) -> tuple[TutorSession, Conversation, cards_mod.Card]:
        """The running session, or RuntimeError before any start."""
        if self._session is None or self._conv is None or self.card is None:
            msg = "no session started"
            raise RuntimeError(msg)
        return self._session, self._conv, self.card

    async def _turn(
        self, prompt_text: str, *, learner_text: str | None, msg_id: str = ""
    ) -> None:
        session, conv, _ = self._live()
        resume.reprime(conv, session.restarts)
        t_learner = self.time()
        active = conv.clock.active_seconds
        note = engine_note(
            active,
            active - conv.check.mark,
            check_open=conv.check.open,
            notes=conv.notes,
            attempt=conv.check.attempt or 1,
        )
        body = (
            wrap_learner(prompt_text.replace("</learner", "< /learner"))
            if learner_text
            else prompt_text
        )
        if conv.resumed.note:
            body = f"{conv.resumed.note}\n{body}"
        if learner_text is not None:
            event = {"type": "learner", "text": learner_text, "note": note}
            self.store.log(self.session_id, {**event, "t": t_learner, "msg_id": msg_id})
        turn, _ = await session.ask(f"{note}\n{body}")
        # Only now: a failed ask leaves no learner bubble (the page keeps the
        # text for a retry) and keeps the notes and primer for that retry.
        conv.notes, conv.resumed.note = [], ""
        if learner_text is not None:
            conv.messages.append({"role": "learner", "text": learner_text})
        message = media.page_message(turn)
        await media.attach(media.Turn(session, conv, self.store), turn, message)
        # Stamped when the final message (after any image check) is ready, so
        # the check's model call never eats into the learner's reply window.
        t_tutor = self.time()
        if learner_text is not None:
            conv.clock.user_reply(t_learner, learner_text, low_effort=turn.low_effort)
        conv.clock.tutor_message(t_tutor)
        self._apply(turn, t_tutor, message)
