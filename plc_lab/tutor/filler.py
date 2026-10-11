# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Deterministic filler: replies that carry no engagement on their own.

The engagement clock (``clock``) pauses on these whatever the model says.
"""

from __future__ import annotations

import re
from typing import Final

# Normalised (see normalise) replies that carry no engagement on their own.
# fmt: off
FILLER: Final = frozenset({
    "", "?", "k", "kk", "ok", "oki", "okay", "ok ok", "ok thanks", "ok got it",
    "yes ok", "ok yes", "ok sure", "sure", "fine", "cool", "nice", "great",
    "got it", "gotcha", "i see", "right", "alright", "mhm", "hm", "um", "uh",
    "idk", "i dont know", "dunno", "no idea", "whatever", "idc", "lol", "lmao",
    "thanks", "thx", "ty", "continue", "go on", "next", "more", "and",
})
# fmt: on
# Legitimate answers to an open check, filler otherwise.
SHORT_ANSWERS: Final = frozenset({"yes", "no", "yep", "yeah", "ya", "nope", "y", "n"})

_STRIP: Final = re.compile(r"[^\w\s?]")
_REPEAT: Final = re.compile(r"(.)\1+")
_SPACE: Final = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, drop punctuation but ``?``, squeeze runs ("okkk"/"hmmm"/"??")."""
    stripped = _STRIP.sub("", text.lower()).replace("_", "")
    squeezed = _REPEAT.sub(r"\1", stripped)
    return _SPACE.sub(" ", squeezed).strip()


_FILLER_NORMALISED: Final = frozenset(normalise(item) for item in FILLER)
_SHORT_NORMALISED: Final = frozenset(normalise(item) for item in SHORT_ANSWERS)


def is_filler(text: str, *, check_open: bool) -> bool:
    """Whether ``text`` is deterministic filler; bare yes/no answers an open check."""
    norm = normalise(text)
    if norm in _SHORT_NORMALISED:
        return not check_open
    return norm in _FILLER_NORMALISED
