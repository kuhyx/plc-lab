# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Developer feedback about the tutor: what looked wrong, for a later fix.

Kept in ``<data dir>/feedback.jsonl``, one report per line, apart from the
session transcripts on purpose: ``resume`` replays ``sessions/*.jsonl`` into
the model's primer, and a report must never reach the tutor or its clock.

``python -m plc_lab.tutor.feedback [--all|--open] [--json] [--resolve ID]``
lists reports oldest first (newest last) or marks one resolved.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
import sys
from typing import TYPE_CHECKING, Any, Final

from plc_lab.tutor.store import data_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

CATEGORIES: Final = {
    "ui": "UI",
    "response": "Tutor's response",
    "experience": "Overall experience",
    "other": "Other",
}
MAX_TEXT: Final = 4000


def feedback_path() -> Path:
    """Where reports live; follows ``AUTOMATION_TUTOR_DATA`` at call time."""
    return data_dir() / "feedback.jsonl"


@contextmanager
def _locked() -> Iterator[Path]:
    """Serialise writers (server append vs CLI rewrite) on a side lock file.

    The lock is not the data file itself: ``--resolve`` replaces that inode,
    and a writer holding a lock on the old one would append into the void.
    """
    path = feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / "feedback.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield path
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load() -> list[dict[str, Any]]:
    """Every report, oldest first."""
    return _read(feedback_path())


def validate(body: dict[str, Any], message_count: int) -> tuple[str, str, int | None]:
    """``(category, text, message_index)`` from a request body, or ValueError."""
    category = body.get("category")
    if category not in CATEGORIES:
        msg = f"unknown category {category!r}; expected one of {sorted(CATEGORIES)}"
        raise ValueError(msg)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        msg = "describe the problem: text is required"
        raise ValueError(msg)
    if len(text) > MAX_TEXT:
        msg = f"text is {len(text)} characters; the limit is {MAX_TEXT}"
        raise ValueError(msg)
    index = body.get("message_index")
    if index is not None and (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < message_count
    ):
        msg = f"message_index {index!r} is not a message in this session"
        raise ValueError(msg)
    return category, text.strip(), index


def record(entry: dict[str, Any]) -> dict[str, Any]:
    """Append ``entry`` with a fresh sequential id; returns the stored report."""
    with _locked() as path:
        next_id = max((int(e["id"]) for e in _read(path)), default=0) + 1
        stored = {
            "id": next_id,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "status": "open",
            **entry,
        }
        line = json.dumps(stored, ensure_ascii=False) + "\n"
        # One write on an O_APPEND handle: a crash leaves either the whole
        # line or none of it, never half a report glued to the next.
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    return stored


def resolve(report_id: int) -> bool:
    """Mark one report resolved; ``False`` if there is no such id."""
    with _locked() as path:
        entries = _read(path)
        hit = next((e for e in entries if e["id"] == report_id), None)
        if hit is None:
            return False
        hit["status"] = "resolved"
        hit["resolved_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
        tmp.replace(path)
    return True


def _quote(text: str) -> list[str]:
    return [f"> {line}" if line else ">" for line in text.splitlines()] or [">"]


def to_markdown(entry: dict[str, Any]) -> str:
    """A paste-ready block for a Claude coding session."""
    lines = [
        (
            f"### Tutor feedback #{entry['id']} ({entry.get('status', 'open')}): "
            f"{CATEGORIES.get(entry.get('category', ''), entry.get('category'))}"
        ),
        "",
        *_quote(entry.get("text", "")),
        "",
        f"- When: {entry.get('created_at')}",
        f"- Session: {entry.get('session_id') or '-'}",
        f"- Card: {entry.get('card_id') or '-'}",
    ]
    shot = entry.get("snapshot")
    if shot:
        msg = shot["message"]
        lines.append(
            f"- Reported message: #{entry.get('message_index')} ({msg.get('role')})"
        )
        lines.extend(
            f"  - image: {img.get('title')} ({img.get('url')})"
            for img in msg.get("images", [])
        )
        lines.extend(f"  - diagram: {d}" for d in msg.get("diagrams", []))
    lines += [
        f"- Page: {entry.get('page_url') or '-'}",
        f"- Browser: {entry.get('user_agent') or '-'}",
        f"- Stored in: {feedback_path()}",
    ]
    if shot:
        for prev in shot.get("preceding", []):
            lines += [
                "",
                f"Message #{prev['index']} ({prev['role']}), trimmed:",
                *_quote(prev["text"]),
            ]
        lines += [
            "",
            f"Reported message #{entry.get('message_index')}:",
            *_quote(msg.get("text", "")),
        ]
    return "\n".join(lines)


def _say(text: str, *, err: bool = False) -> None:
    (sys.stderr if err else sys.stdout).write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    """List reports (open by default) or resolve one."""
    parser = argparse.ArgumentParser(
        prog="python -m plc_lab.tutor.feedback", description=__doc__
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--all", action="store_true", help="include resolved reports")
    which.add_argument(
        "--open", action="store_true", help="only open reports (default)"
    )
    which.add_argument(
        "--resolve", type=int, metavar="ID", help="mark report ID resolved"
    )
    parser.add_argument("--json", action="store_true", help="one JSON object per line")
    args = parser.parse_args(argv)
    if args.resolve is not None:
        if not resolve(args.resolve):
            _say(f"no feedback #{args.resolve} in {feedback_path()}", err=True)
            return 1
        _say(f"feedback #{args.resolve} resolved")
        return 0
    entries = [e for e in load() if args.all or e.get("status", "open") == "open"]
    if not entries:
        scope = "" if args.all else "open "
        _say(f"no {scope}feedback in {feedback_path()}", err=True)
        return 0
    if args.json:
        _say("\n".join(json.dumps(e, ensure_ascii=False) for e in entries))
    else:
        _say("\n\n---\n\n".join(to_markdown(e) for e in entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
