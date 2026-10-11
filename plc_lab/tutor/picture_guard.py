# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The guard on unseen pictures: a message never refers to one that is not there."""

from __future__ import annotations

import re
from typing import Final

NO_PICTURE_NOTICE: Final = (
    "(No picture could be shown with this message, so ignore any mention of "
    "one and answer from the text.)"
)
_PICTURE: Final = re.compile(
    r"\b(pictures?|images?|photos?|photographs?|pics?|illustrations?)\b",
    re.IGNORECASE,
)
_DIAGRAM: Final = re.compile(r"\bdiagrams?\b", re.IGNORECASE)
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")


def unseen_picture_guard(text: str, *, diagram_shown: bool) -> str:
    """``text`` made safe to send with no picture attached.

    Sentences that mention a picture/image/photo (or a diagram, unless a
    code-drawn one is attached) are removed. If that would leave nothing or
    drop the closing question, the text is kept and :data:`NO_PICTURE_NOTICE`
    is appended instead, so the learner is told no picture is there.
    """

    def mentions(part: str) -> bool:
        return bool(_PICTURE.search(part)) or (
            not diagram_shown and bool(_DIAGRAM.search(part))
        )

    if not mentions(text):
        return text
    lines = []
    for line in text.split("\n"):
        kept = [s for s in _SENTENCE_END.split(line) if not mentions(s)]
        if kept or not line.strip():
            lines.append(" ".join(kept))
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not cleaned or ("?" in text and "?" not in cleaned):
        return f"{text}\n\n{NO_PICTURE_NOTICE}"
    return cleaned
