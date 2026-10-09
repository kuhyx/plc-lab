# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""What a feedback report pins down: the reported message as the page showed it.

Taken from the server's own copy of the messages (never the page's), plus a
trimmed view of what came just before it.
"""

from __future__ import annotations

from typing import Any, Final

_CONTEXT_CHARS: Final = 400  # per preceding message
_CONTEXT_MESSAGES: Final = 2


def _trim(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def snapshot(messages: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """The reported message as the page showed it, plus what came just before."""
    msg = messages[index]
    shot: dict[str, Any] = {
        "role": msg.get("role"),
        "text": msg.get("text", ""),
        "images": [
            {
                "title": i.get("title"),
                "url": f"/media/{i.get('file')}",
                "page_url": i.get("page_url"),
            }
            for i in msg.get("images") or []
        ],
        "diagrams": [f"/media/{d}" for d in msg.get("diagrams") or []],
    }
    if msg.get("diagram_title"):
        shot["diagram_title"] = msg["diagram_title"]
    for key in ("check", "check_result", "low_effort"):
        if msg.get(key):
            shot[key] = msg[key]
    start = max(0, index - _CONTEXT_MESSAGES)
    return {
        "message": shot,
        "preceding": [
            {
                "index": n,
                "role": m.get("role"),
                "text": _trim(m.get("text", ""), _CONTEXT_CHARS),
            }
            for n, m in enumerate(messages[start:index], start)
        ],
    }
