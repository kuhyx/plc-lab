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
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Final

from plc_lab.tutor import commons

# A day: Commons gains files, and the model has up to three other wordings.
NEGATIVE_TTL: Final = 24 * 3600.0
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


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _write(path: Path, data: bytes) -> None:
    """Write via temp file + rename: other processes and threads share the cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
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
    hit = commons.search(term)
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
        _write(cache / name, commons.get(info["thumburl"]))
    image = CommonsImage(
        term=term,
        title=title,
        file=name,
        author=commons.meta(info, "Artist") or "see file page",
        licence=commons.meta(info, "LicenseShortName") or "see file page",
        licence_url=commons.meta(info, "LicenseUrl"),
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
