# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Read-only views of past sessions, rebuilt from their transcripts.

Everything here goes through ``resume.replay`` and never credits, logs or
touches the ledger: opening a URL or the history list must not change
anything. Ids are validated against the transcript file-name pattern before a
path is built from them.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any, Final

from plc_lab.tutor import resume, unit_credit

if TYPE_CHECKING:
    from pathlib import Path

    from plc_lab.tutor.conversation import Conversation

# ASCII only: ``\d`` alone would also match other scripts' digits.
SESSION_ID: Final = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}", re.ASCII)


@dataclass(frozen=True)
class View:
    """What a session view needs besides its transcript, all read NOW."""

    fronts: dict[str, str]  # card id -> front
    live: str  # the live session id ("" when none)
    done_now: set[str]  # cards done in progress.json
    archived: set[str]  # session ids archived by hand


def transcript_path(sessions_dir: Path, session_id: str) -> Path | None:
    """The transcript of ``session_id``, or ``None`` (bad id or no such file)."""
    if not SESSION_ID.fullmatch(session_id):
        return None
    path = sessions_dir / f"{session_id}.jsonl"
    return path if path.is_file() else None


def _cards(
    conv: Conversation, fronts: dict[str, str], done_now: set[str]
) -> list[dict[str, Any]]:
    """Each card studied in the session, in order.

    ``done`` is the card's state in progress.json NOW (what the manual override
    toggles); ``done_here`` is whether a card_done (tutor or manual) happened
    for it in this session.
    """
    seen: list[str] = []
    for card_id in conv.cards:
        if card_id not in seen:
            seen.append(card_id)
    return [
        {
            "id": card_id,
            "front": fronts.get(card_id, card_id),
            "done": card_id in done_now,
            "done_here": card_id in conv.cards_done,
        }
        for card_id in seen
    ]


def _summary(conv: Conversation, view: View) -> dict[str, Any]:
    is_live = conv.session_id == view.live
    # No learner reply: nothing worth revisiting, hidden without a click. The
    # live session is never archived (it may simply not be answered yet).
    auto = not is_live and not any(m.get("role") == "learner" for m in conv.messages)
    return {
        "session_id": conv.session_id,
        "live": is_live,
        "archived": auto or (not is_live and conv.session_id in view.archived),
        "auto_archived": auto,
        "stopped": conv.stopped,
        "cards": _cards(conv, view.fronts, view.done_now),
        "active_seconds": conv.clock.active_seconds,
        "credited_minutes": unit_credit.paid_minutes(conv.receipts),
    }


def session_view(
    sessions_dir: Path, session_id: str, view: View
) -> dict[str, Any] | None:
    """One session's transcript for ``GET /api/session/<id>``; ``None`` -> 404."""
    path = transcript_path(sessions_dir, session_id)
    replayed = resume.replay(path) if path else None
    if replayed is None:
        return None
    conv = replayed.conversation
    return {
        **_summary(conv, view),
        "messages": conv.messages,
        "receipts": conv.receipts,
    }


def sessions_list(sessions_dir: Path, view: View) -> list[dict[str, Any]]:
    """Every replayable session, newest first, for ``GET /api/sessions``."""
    out: list[dict[str, Any]] = []
    for path in sorted(sessions_dir.glob("*.jsonl"), reverse=True):
        if not SESSION_ID.fullmatch(path.stem):
            continue
        replayed = resume.replay(path)
        if replayed is None:
            continue
        info = _summary(replayed.conversation, view)
        sid = info["session_id"]
        out.append(
            {
                "session_id": sid,
                # The id is local time: slice, do not parse (no timezone to guess).
                "started": f"{sid[:4]}-{sid[4:6]}-{sid[6:8]} {sid[9:11]}:{sid[11:13]}",
                "cards": info["cards"],
                "active_minutes": int(info["active_seconds"] // 60),
                "credited_minutes": info["credited_minutes"],
                "live": info["live"],
                "archived": info["archived"],
                "auto_archived": info["auto_archived"],
                "stopped": info["stopped"],
            }
        )
    return out
