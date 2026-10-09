# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The session engine: model turns in, clock / credit / store / media wired up.

Every event goes to the engagement clock the moment it happens; the model only
supplies the per-reply ``low_effort`` flag and each check's pass/fail. Credit
is written for each block the clock releases, and the UI only claims a block
once the ledger read-back says it is recorded.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Final
import uuid

from plc_lab import cards as cards_mod
from plc_lab.tutor import credit, media, resume
from plc_lab.tutor.clock import EngagementClock
from plc_lab.tutor.conversation import Conversation
from plc_lab.tutor.prompt import engine_note, system_prompt, wrap_learner
from plc_lab.tutor.session import TutorSession, isolated_options
from plc_lab.tutor.store import Store

if TYPE_CHECKING:
    from collections.abc import Callable

    from plc_lab.tutor.clock import BlockReady
    from plc_lab.tutor.models import TutorTurn

DECK_DIR: Final = Path(__file__).resolve().parents[2] / "deck"
TARGET_MINUTES: Final = 60
BLOCK_MINUTES: Final = 15


class Engine:
    """One study session at a time, for one learner."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        now: Callable[[], float] = time.time,
        credit_fn: Callable[[BlockReady, str], credit.CreditReceipt] | None = None,
        session_factory: Callable[[str], TutorSession] | None = None,
        simulated_time: bool = False,
    ) -> None:
        """Wire the collaborators; ``simulated_time`` lets a driver skip ahead."""
        self.store = store or Store()
        self._now = now
        self._credit = credit_fn or (
            lambda block, sid: credit.credit_block(block, sid, now=self.time())
        )
        self._factory = session_factory or (
            lambda prompt: TutorSession(isolated_options(prompt))
        )
        self.simulated = simulated_time
        self._offset = 0.0
        self._lock = asyncio.Lock()
        self.deck = cards_mod.load_deck(DECK_DIR)
        self.card: cards_mod.Card | None = None
        self.units_today = 0
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
        if state is None or conv is None or card is None:
            return False
        self.card, self._conv = card, conv
        recorded = [r for r in conv.receipts if r.get("recorded")]
        self.units_today = max((int(r["units_today"]) for r in recorded), default=0)
        self._session = self._factory(system_prompt(card, self.store.mastered()))
        conv.resume_note = resume.primer(conv.messages)
        self.store.log(self.session_id, {"type": "resume"})
        for block in state.unrecorded:
            self._record(block)  # entry ids are unique, so this never doubles
        return True

    async def reply(
        self, text: str, advance_s: float = 0.0, msg_id: str = ""
    ) -> dict[str, Any]:
        """The learner answers; returns the new state (a resent ``msg_id``: no-op)."""
        async with self._lock:
            _, conv, _ = self._live()
            if msg_id and msg_id == conv.answered_id:
                return self.state()
            if self.simulated:
                self._offset += max(0.0, advance_s)
            await self._turn(text, learner_text=text, msg_id=msg_id)
            conv.answered_id = msg_id
        return self.state()

    async def close(self) -> None:
        """Stop the model process."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def state(self) -> dict[str, Any]:
        """Everything the page needs to draw itself."""
        snap = self._conv.clock.snapshot(self.time()) if self._conv else {}
        card = self.card
        credited = min(self.units_today * BLOCK_MINUTES, TARGET_MINUTES)
        return {
            "session_id": self.session_id,
            "card": {"id": card.id, "front": card.front} if card else None,
            "messages": self.messages,
            "clock": snap,
            "credited_minutes": credited,
            "target_minutes": TARGET_MINUTES,
            "receipts": self.receipts,
            "mastered": self.store.mastered(),
            "check_open": bool(self._conv and self._conv.check_open),
        }

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
        t_learner = self.time()
        active = conv.clock.active_seconds
        note = engine_note(
            active,
            active - conv.check_mark,
            check_open=conv.check_open,
            notes=conv.notes,
        )
        body = (
            wrap_learner(prompt_text.replace("</learner", "< /learner"))
            if learner_text
            else prompt_text
        )
        if conv.resume_note:
            body = f"{conv.resume_note}\n{body}"
        if learner_text is not None:
            event = {"type": "learner", "text": learner_text, "note": note}
            self.store.log(self.session_id, {**event, "t": t_learner, "msg_id": msg_id})
        turn, _ = await session.ask(f"{note}\n{body}")
        # Only now: a failed ask leaves no learner bubble (the page keeps the
        # text for a retry) and keeps the notes and primer for that retry.
        conv.notes, conv.resume_note = [], ""
        if learner_text is not None:
            conv.messages.append({"role": "learner", "text": learner_text})
        message = media.page_message(turn)
        await media.attach(media.Turn(session, conv, self.store), turn, message)
        # Stamped when the final message (after any image check) is ready, so
        # the check's model call never eats into the learner's reply window.
        t_tutor = self.time()
        if learner_text is not None:
            conv.clock.user_reply(t_learner, learner_text, turn.low_effort)
        conv.clock.tutor_message(t_tutor)
        self._apply(turn, t_tutor, message)

    def _apply(self, turn: TutorTurn, t: float, message: dict[str, Any]) -> None:
        _, conv, card = self._live()
        logged = asdict(turn)
        conv.apply_checks(logged, t)
        if not turn.low_effort and turn.concepts_mastered:
            names = [c.strip().lower() for c in turn.concepts_mastered if c.strip()]
            message["mastered_new"] = self.store.master(names, card.id, self.session_id)
        if turn.card_done and conv.checks_passed:
            self.store.finish_card(card.id, self.session_id)
            message["card_done"] = True
        conv.messages.append(message)
        self.store.log(
            self.session_id, {"type": "tutor", "turn": logged, "ui": message, "t": t}
        )
        for block in conv.clock.ready_blocks():
            self._record(block)

    def _record(self, block: BlockReady) -> None:
        receipt = self._credit(block, self.session_id)
        if receipt.recorded:
            self.units_today = max(self.units_today, receipt.units_today)
        row = {"block": block.block, **asdict(receipt)}
        self.receipts.append(row)
        self.store.log(self.session_id, {"type": "credit", **row})
