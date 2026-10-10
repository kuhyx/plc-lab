# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""What the learner has mastered and what was said, kept across sessions.

Layout under the data dir (``AUTOMATION_TUTOR_DATA``, else
``~/.local/share/automation_tutor``, the same dir the credit ledger uses):
``progress.json`` and ``sessions/<session_id>.jsonl`` (one event per line).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    """The tutor's data directory, resolved at call time."""
    override = os.environ.get("AUTOMATION_TUTOR_DATA")
    return Path(override) if override else Path.home() / ".local/share/automation_tutor"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    """``progress.json`` plus one transcript file per session."""

    def __init__(self, root: Path | None = None) -> None:
        """Use ``root`` (default: the data dir); created on first write."""
        self.root = root or data_dir()
        self.progress_path = self.root / "progress.json"

    def progress(self) -> dict[str, Any]:
        """The saved progress, or an empty one (no file yet: a first session)."""
        raw: dict[str, Any] = {}
        if self.progress_path.is_file():
            loaded = json.loads(self.progress_path.read_text(encoding="utf-8"))
            raw = loaded if isinstance(loaded, dict) else {}
        raw.setdefault("mastered", {})
        raw.setdefault("cards_done", {})
        return raw

    def mastered(self) -> list[str]:
        """Mastered concept names, oldest first."""
        return list(self.progress()["mastered"])

    def master(self, concepts: list[str], card_id: str, session_id: str) -> list[str]:
        """Record new concepts; return the ones that were new."""
        data = self.progress()
        fresh = [c for c in concepts if c not in data["mastered"]]
        for concept in fresh:
            data["mastered"][concept] = {
                "at": _now(),
                "card": card_id,
                "session": session_id,
            }
        if fresh:
            self._save(data)
        return fresh

    def finish_card(self, card_id: str, session_id: str) -> None:
        """Mark a card as understood."""
        data = self.progress()
        data["cards_done"][card_id] = {"at": _now(), "session": session_id}
        self._save(data)

    def unfinish_card(self, card_id: str) -> None:
        """Take a card back out of the done set (the manual override)."""
        data = self.progress()
        if data["cards_done"].pop(card_id, None) is not None:
            self._save(data)

    def archived(self) -> dict[str, dict[str, str]]:
        """Sessions hidden from History by hand: id -> ``{"at": iso}``."""
        found = self.progress().get("archived", {})
        return found if isinstance(found, dict) else {}

    def archive(self, session_id: str) -> None:
        """Hide a session from History; its transcript and credit stay as-is."""
        data = self.progress()
        archived = data.setdefault("archived", {})
        if session_id not in archived:  # re-archiving keeps the first time
            archived[session_id] = {"at": _now()}
            self._save(data)

    def unarchive(self, session_id: str) -> None:
        """Show an archived session in History again."""
        data = self.progress()
        if data.get("archived", {}).pop(session_id, None) is not None:
            self._save(data)

    def repaired(self, name: str) -> bool:
        """Whether the one-off repair ``name`` already ran on this data dir."""
        return bool(self.progress().get("repairs", {}).get(name))

    def mark_repaired(self, name: str) -> None:
        """Remember that repair ``name`` ran, so a later restart skips it."""
        data = self.progress()
        data.setdefault("repairs", {})[name] = _now()
        self._save(data)

    def log(self, session_id: str, event: dict[str, Any]) -> None:
        """Append one event to the session transcript."""
        path = self.root / "sessions" / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"logged_at": _now(), **event}, ensure_ascii=False) + "\n"
            )

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.progress_path)
