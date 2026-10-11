# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The Wikimedia Commons side of image lookup: the guarded GET and the search.

Nothing but https on a Commons host is ever fetched. The caches and the credit
the UI shows live in :mod:`plc_lab.tutor.images`.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Final
import urllib.parse
import urllib.request

API: Final = "https://commons.wikimedia.org/w/api.php"
USER_AGENT: Final = (
    "plc-lab-tutor/0.1 (https://github.com/kuhyx/plc-lab; local study tool)"
)
MIMES: Final = ("image/jpeg", "image/png", "image/svg+xml", "image/webp")
_TAG: Final = re.compile(r"<[^>]+>")
TIMEOUT: Final = 20
# The API host and both thumbnail hosts; a thumburl from the JSON is untrusted.
_HOSTS: Final = frozenset(f"{h}.wikimedia.org" for h in ("commons", "upload", "thumb"))
# Words that say nothing about which picture is meant; every other word counts,
# however short ("I/O", "mA", "4-20" are the point of some searches).
_STOP: Final = frozenset(
    {"a", "an", "and", "of", "the", "in", "on", "for", "to", "with"}
)
_WORD: Final = re.compile(r"[a-z0-9]+")
_SLASHED: Final = re.compile(r"\b([a-z])/([a-z])\b", re.IGNORECASE)
_PLURAL_MIN: Final = 4  # "ms" and "mas" are not plurals


def get(url: str) -> bytes:
    """GET a Commons URL; anything but https on a Commons host raises ValueError.

    Rebuilt on a literal ``https://``: no ``file:`` or custom scheme reaches urlopen.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in _HOSTS:
        msg = f"not an https Commons URL: {url!r}"
        raise ValueError(msg)
    query = f"?{parts.query}" if parts.query else ""
    with urllib.request.urlopen(
        urllib.request.Request(
            f"https://{parts.netloc}{parts.path}{query}",
            headers={"User-Agent": USER_AGENT},
        ),
        timeout=TIMEOUT,
    ) as resp:
        data: bytes = resp.read()
    return data


def plain(value: str) -> str:
    """Strip HTML from a Commons metadata field."""
    return html.unescape(_TAG.sub("", value)).strip()


def meta(info: dict[str, Any], key: str) -> str:
    """One extmetadata field of an imageinfo block, as plain text."""
    return plain(str(info.get("extmetadata", {}).get(key, {}).get("value", "")))


def _squash(text: str) -> str:
    """Fold "I/O" to "IO": Commons titles and search treat the slash as a break."""
    return _SLASHED.sub(r"\1\2", text)


def tokens(text: str) -> set[str]:
    """Lowercase words (plural 's' folded away from words of 4+ letters)."""
    return {
        w.removesuffix("s") if len(w) >= _PLURAL_MIN else w
        for w in _WORD.findall(_squash(text).lower())
        if w not in _STOP
    }


def _context(page: dict[str, Any]) -> set[str]:
    """Words of the file's description and categories (the title is separate)."""
    info = (page.get("imageinfo") or [{}])[0]
    return tokens(" ".join(meta(info, k) for k in ("ImageDescription", "Categories")))


def _rank(term: str, page: dict[str, Any]) -> tuple[int, int, int] | None:
    """Sort key for a page, or None when a query word is nowhere on it.

    Every query word must appear whole. A page with all of them in its title
    beats one that only has them in its description or categories; then more
    title words, then Commons order.
    """
    query = tokens(term)
    if not query:
        return None
    title = tokens(page["title"])
    hits = len(query & title)
    if hits < len(query) and not query <= title | _context(page):
        return None
    return (int(hits < len(query)), -hits, page.get("index", 99))


def _query(term: str) -> list[dict[str, Any]]:
    """Image pages Commons returns for ``term`` (all words must match)."""
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{term} filetype:bitmap|drawing",
            "gsrnamespace": "6",
            "gsrlimit": "8",
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": "800",
        }
    )
    data = json.loads(get(f"{API}?{query}"))
    return list(data.get("query", {}).get("pages", {}).values())


def _usable(page: dict[str, Any]) -> dict[str, Any] | None:
    """The page as ``{"title", "info"}`` if it has a picture we can show."""
    info = (page.get("imageinfo") or [{}])[0]
    if info.get("mime") in MIMES and info.get("thumburl"):
        return {"title": page["title"], "info": info}
    return None


def search(term: str) -> dict[str, Any] | None:
    """Best image page for ``term``, or None.

    Commons search needs every word to match, so a long term is shortened one
    word at a time (down to two) until something comes back. A page only
    counts if every query word appears whole in its title, description or
    categories; otherwise a stemmed near-miss ("electromagnetic radiations"
    for "electromagnet") would be shown as if it were right. A page with all
    the words in its title ends the search; one that has some only in its
    description is kept as a fallback while shorter queries are tried. A wrong
    match that survives this is caught by the vision check.
    """
    words = _squash(term).split()
    fallback: dict[str, Any] | None = None
    for count in range(len(words), max(1, min(2, len(words))) - 1, -1):
        short = " ".join(words[:count])
        ranked = sorted(
            (key, index, page)
            for index, page in enumerate(_query(short))
            if (key := _rank(short, page)) is not None
        )
        for key, _index, page in ranked:
            if (found := _usable(page)) is None:
                continue
            if key[0] == 0:
                return found
            fallback = fallback or found
    return fallback
