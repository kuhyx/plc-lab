# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Wikimedia Commons images with attribution; nothing else is ever fetched.

The tutor names search terms; this module asks the Commons API, downloads the
PNG/JPEG thumbnail (never a raw SVG) into a local cache, and keeps the author,
licence and file-page link so the UI can show them under the picture.

Two caches, both on disk so they survive restarts:

* ``terms/<sha(term)>.json`` -- what a search term resolved to, or that it
  found nothing. Hits never expire; a miss is retried after
  :data:`NEGATIVE_TTL` (Commons gains files). Network errors are not cached.
* ``<sha(file title)>.jpg|png`` -- the thumbnail, named by the Commons file, so
  two terms that land on the same file share one download.

The older layout (``<sha(term)>.json`` + image, written by earlier versions and
still read by any older running process) is read as a hit, never rewritten.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from functools import partial
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Final
import urllib.parse
import urllib.request

API: Final = "https://commons.wikimedia.org/w/api.php"
NEGATIVE_TTL: Final = 7 * 24 * 3600.0
USER_AGENT: Final = (
    "plc-lab-tutor/0.1 (https://github.com/kuhyx/plc-lab; local study tool)"
)
_MIMES: Final = ("image/jpeg", "image/png", "image/svg+xml", "image/webp")
_TAG: Final = re.compile(r"<[^>]+>")
_TIMEOUT: Final = 20
_log = logging.getLogger(__name__)


def cache_dir() -> Path:
    """The image cache: ``AUTOMATION_TUTOR_IMAGE_CACHE``, resolved at call time."""
    return Path(
        os.environ.get("AUTOMATION_TUTOR_IMAGE_CACHE")
        or Path.home() / ".cache" / "plc-lab" / "tutor-images"
    )


@dataclass(frozen=True)
class CommonsImage:
    """A cached Commons image and the credit it must be shown with."""

    term: str
    title: str
    file: str
    author: str
    licence: str
    licence_url: str
    page_url: str

    def to_json(self) -> dict[str, str]:
        """JSON for the UI (``file`` is served under ``/media/``)."""
        return asdict(self)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data: bytes = resp.read()
    return data


def _plain(value: str) -> str:
    """Strip HTML from a Commons metadata field."""
    return html.unescape(_TAG.sub("", value)).strip()


def _meta(info: dict[str, Any], key: str) -> str:
    return _plain(str(info.get("extmetadata", {}).get(key, {}).get("value", "")))


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens with a trailing plural 's' folded away."""
    return {w.removesuffix("s") for w in re.findall(r"[a-z0-9]{3,}", text.lower())}


def _rank(term: str, page: dict[str, Any]) -> tuple[int, int]:
    """Sort key: more whole query words in the title first, then Commons order."""
    hits = len(_tokens(term) & _tokens(page["title"]))
    return (-hits, page.get("index", 99))


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
    data = json.loads(_get(f"{API}?{query}"))
    return list(data.get("query", {}).get("pages", {}).values())


def search(term: str) -> dict[str, Any] | None:
    """Best image page for ``term``, or None.

    Commons search needs every word to match, so a long term is shortened one
    word at a time (down to two) until something comes back. A page only
    counts if every query word appears whole in its title; otherwise a stemmed
    near-miss ("electromagnetic radiations" for "electromagnet") would be
    shown as if it were right.
    """
    words = term.split()
    for count in range(len(words), max(1, min(2, len(words))) - 1, -1):
        short = " ".join(words[:count])
        ranked = sorted(_query(short), key=partial(_rank, short))
        for page in ranked:
            info = (page.get("imageinfo") or [{}])[0]
            usable = info.get("mime") in _MIMES and info.get("thumburl")
            if usable and -_rank(short, page)[0] >= len(_tokens(short)):
                return {"title": page["title"], "info": info}
    return None


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _write(path: Path, data: bytes) -> None:
    """Write via a temp file + rename: other tutor processes share the cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _cached(term: str, cache: Path, now: float) -> tuple[bool, CommonsImage | None]:
    """``(known, image)`` from the term cache; ``known`` False means ask Commons."""
    record = cache / "terms" / f"{_key(' '.join(term.lower().split()))}.json"
    if record.is_file():
        entry = json.loads(record.read_text(encoding="utf-8"))
        if entry["image"] is None:
            return now - float(entry["at"]) < NEGATIVE_TTL, None
        image = CommonsImage(**entry["image"])
        if (cache / image.file).is_file():
            return True, image
    legacy = cache / f"{_key(term.lower())}.json"
    if legacy.is_file():
        image = CommonsImage(**json.loads(legacy.read_text(encoding="utf-8")))
        if (cache / image.file).is_file():
            return True, image
    return False, None


def _remember(term: str, image: CommonsImage | None, cache: Path, now: float) -> None:
    entry = {"at": now, "image": image.to_json() if image else None}
    record = cache / "terms" / f"{_key(' '.join(term.lower().split()))}.json"
    _write(record, json.dumps(entry).encode())


def fetch(
    term: str, cache: Path | None = None, now: float | None = None
) -> CommonsImage | None:
    """The best Commons image for ``term``; each term and file is fetched once."""
    cache = cache or cache_dir()
    now = time.time() if now is None else now
    known, image = _cached(term, cache, now)
    if known:
        _log.info("image cache hit %r -> %s", term, image.title if image else None)
        return image
    _log.info("image cache miss %r: searching Commons", term)
    hit = search(term)
    if hit is None:
        _remember(term, None, cache, now)
        return None
    info = hit["info"]
    title = hit["title"].removeprefix("File:")
    ext = ".png" if info["thumburl"].lower().split("?")[0].endswith(".png") else ".jpg"
    name = f"{_key(title)}{ext}"
    if (cache / name).is_file():
        _log.info("image file reused %r for %r", title, term)
    else:
        _log.info("image download %r", title)
        _write(cache / name, _get(info["thumburl"]))
    image = CommonsImage(
        term=term,
        title=title,
        file=name,
        author=_meta(info, "Artist") or "see file page",
        licence=_meta(info, "LicenseShortName") or "see file page",
        licence_url=_meta(info, "LicenseUrl"),
        page_url=info.get("descriptionurl", ""),
    )
    _remember(term, image, cache, now)
    return image


def _media_type(data: bytes) -> str:
    """Sniff the real format: a ``.jpg`` thumbnail may be PNG/WebP/GIF inside."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"


def content_block(image: CommonsImage, cache: Path | None = None) -> dict[str, Any]:
    """The cached picture as a base64 image block the model can look at."""
    data = ((cache or cache_dir()) / image.file).read_bytes()
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": _media_type(data),
            "data": base64.b64encode(data).decode("ascii"),
        },
    }
