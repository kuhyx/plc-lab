# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Pick an interrupted session back up from its transcript after a restart.

A server restart must not cost the learner their place (kuhy, 2026-10-09: a
restart mid-session wiped one). Everything the engine keeps in memory is
rebuilt from ``sessions/<id>.jsonl``: the messages, the check state, the
receipts, and the engagement clock, which is replayed event by event at the
logged times. The model process itself cannot be resumed, so the next model
call is primed with the transcript since the last card switch (:func:`primer`).
A ``stop`` event marks the session finished: it is replayed (history shows it)
but never resumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from typing import TYPE_CHECKING, Any

from plc_lab.tutor.clock import BlockReady, EngagementClock
from plc_lab.tutor.conversation import Conversation
from plc_lab.tutor.prompt import wrap_learner

if TYPE_CHECKING:
    from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass
class Replayed:
    """The engine's in-memory state, rebuilt from one transcript."""

    conversation: Conversation
    # Every unit (active minute) the replayed clock earned. Which of them the
    # ledger already pays is the ledger's to say (``credit_units`` asks it).
    unrecorded: list[BlockReady] = field(default_factory=list)


def latest_today(sessions_dir: Path, day_prefix: str) -> Path | None:
    """The newest transcript of a session started today (``YYYYMMDD`` prefix)."""
    found = sorted(sessions_dir.glob(f"{day_prefix}-*.jsonl"))
    return found[-1] if found else None


def _events(path: Path) -> list[dict[str, Any]]:
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as err:
            # A line cut short by a kill; everything before it stands.
            _logger.warning("%s:%d skipped, not JSON: %s", path, number, err)
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _time(event: dict[str, Any]) -> float:
    """The exact engine time if logged, else the (whole-second) log stamp."""
    if "t" in event:
        return float(event["t"])
    return datetime.fromisoformat(event["logged_at"]).timestamp()


def _ui(turn: dict[str, Any]) -> dict[str, Any]:
    """The page message for a turn logged before ``ui`` was (media is lost)."""
    return {
        "role": "tutor",
        "text": turn.get("message", ""),
        "low_effort": bool(turn.get("low_effort")),
        "check": turn.get("check"),
        "check_result": turn.get("check_result"),
        "images": [],
        "diagrams": [],
    }


def _replay_tutor(
    conv: Conversation, event: dict[str, Any], pending: dict[str, Any] | None
) -> None:
    """One logged tutor turn, with the learner message it answered (if any)."""
    turn = event.get("turn") or {}
    t = _time(event)
    if pending is not None:
        text = str(pending.get("text", ""))
        low = bool(turn.get("low_effort"))
        conv.clock.user_reply(_time(pending), text, low_effort=low)
        conv.messages.append({"role": "learner", "text": text})
        conv.resumed.answered_id = str(pending.get("msg_id", ""))
    conv.clock.tutor_message(t)
    conv.apply_checks(turn, t)
    ui = event.get("ui") or _ui(turn)
    if turn.get("card_done") or ui.get("card_done"):
        conv.mark_card_done()
    conv.messages.append(ui)


def _replay_next_card(conv: Conversation, event: dict[str, Any]) -> None:
    """Replay a Next card choice.

    With a ``ui`` divider it is an old in-session switch; without one the next
    card got its own session and the event only records the choice.
    """
    if ui := event.get("ui"):
        conv.switch_card(str(event.get("card", "")), str(ui.get("text", "")))


def replay(path: Path) -> Replayed | None:
    """Rebuild the state from ``path``; ``None`` if nothing resumable is in it.

    Mirrors ``Engine._turn``/``_apply``. A learner message with no tutor reply
    after it is dropped: its request failed, and the page still holds the text.
    """
    events = _events(path)
    start = next((e for e in events if e.get("type") == "start"), None)
    if start is None:
        return None
    conv = Conversation(
        session_id=path.stem,
        card_id=str(start.get("card", "")),
        clock=EngagementClock(_time(start)),
    )
    pending: dict[str, Any] | None = None
    for event in events:
        kind = event.get("type")
        if kind == "learner":
            pending = event
        elif kind == "tutor":
            _replay_tutor(conv, event, pending)
            pending = None
        elif kind == "next_card":
            pending = None  # a failed reply belongs to the card left behind
            _replay_next_card(conv, event)
        elif kind == "card_done_manual":
            conv.set_done(str(event.get("card", "")), done=bool(event.get("done")))
        elif kind == "stop":
            conv.stopped, pending = True, None
        elif kind == "credit":
            row = {k: v for k, v in event.items() if k not in {"type", "logged_at"}}
            conv.receipts.append(row)
    if not conv.messages:
        return None
    return Replayed(conv, conv.clock.ready_blocks())


def primer(messages: list[dict[str, Any]]) -> str:
    """The note that hands a fresh model process the conversation so far."""
    lines = []
    # Only the current card: the fresh process was never told about earlier ones.
    last = max(
        (i for i, m in enumerate(messages) if m.get("role") == "card"), default=-1
    )
    for message in messages[last + 1 :]:
        text = str(message.get("text", ""))
        if message.get("role") == "learner":
            lines.append(
                "LEARNER:\n" + wrap_learner(text.replace("</learner", "< /learner"))
            )
        else:
            lines.append("TUTOR:\n" + text)
    transcript = "\n\n".join(lines)
    return (
        "[app] The tutor app restarted in the middle of this session, so you are "
        "a fresh process. Below is the whole conversation so far, oldest first. "
        "Carry on as the same tutor from the last TUTOR message: do not greet "
        "again, restart the card or re-ask questions already answered. The "
        "learner's newest message follows the transcript.\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )


def reprime(conv: Conversation, restarts: int) -> None:
    """Prime the next call once per CLI death since the last one (session.py).

    Assigned, not appended: a retry that crashes again still sends one copy.
    The current learner text is not in ``messages`` yet, so it is not doubled.
    """
    if restarts > conv.resumed.restarts_seen:
        conv.resumed.restarts_seen = restarts
        if conv.messages:
            conv.resumed.note = primer(conv.messages)
