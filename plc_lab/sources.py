# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Fetch a card's source and check that its excerpt really is in it.

Every card carries the URL it was written from and a verbatim excerpt that
supports its answer. This module is what makes that claim checkable by code
instead of by trust: the page is fetched once into a cache, reduced to plain
text, and the excerpt must appear in it after the same normalisation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html import unescape
from html.parser import HTMLParser
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Final
import urllib.request

CACHE_DIR: Final = Path(
    os.environ.get("PLC_LAB_CACHE", Path.home() / ".cache" / "plc-lab" / "sources")
)
_USER_AGENT: Final = "plc-lab-source-check/0.1 (https://github.com/kuhyx/plc-lab)"
_TIMEOUT_SECONDS: Final = 30
# Resolved once so the subprocess gets an absolute path; CI installs poppler-utils.
PDFTOTEXT: Final = shutil.which("pdftotext") or "/usr/bin/pdftotext"
_logger: Final = logging.getLogger(__name__)
_SKIPPED_TAGS: Final = frozenset({"script", "style", "noscript", "template"})
# Wikipedia footnote markers and similar: "[12]", "[a]", "[citation needed]".
_FOOTNOTE: Final = re.compile(r"\[\s*(?:\d+|[a-z]|citation needed|note \d+)\s*\]")
_TYPOGRAPHY: Final = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u00ad": None,
    }
)
_SPACE: Final = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """Collect the visible text of an HTML page, dropping scripts and styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def normalise(text: str) -> str:
    """Fold typography, footnote markers, case and whitespace for comparison."""
    text = unescape(text).translate(_TYPOGRAPHY)
    text = _FOOTNOTE.sub("", text)
    return _SPACE.sub(" ", text).strip().casefold()


def html_text(html: str) -> str:
    """The visible text of an HTML document."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return " ".join(parser.parts)


def _cache_path(url: str) -> Path:
    return CACHE_DIR / hashlib.sha256(url.encode()).hexdigest()[:24]


def _download(url: str) -> tuple[bytes, str]:
    """GET ``url``; returns the body and its content type."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read(), response.headers.get_content_type()


def _pdf_text(body: bytes) -> str:
    result = subprocess.run(
        [PDFTOTEXT, "-", "-"], input=body, capture_output=True, check=True
    )
    return result.stdout.decode("utf-8", errors="replace")


def page_text(url: str) -> str:
    """The plain text of ``url``, fetched once and cached on disk."""
    cached = _cache_path(url)
    if cached.is_file():
        return cached.read_text(encoding="utf-8")
    body, content_type = _download(url)
    if content_type == "application/pdf" or body.startswith(b"%PDF"):
        text = _pdf_text(body)
    else:
        text = html_text(body.decode("utf-8", errors="replace"))
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


@dataclass(frozen=True)
class Mismatch:
    """A card whose excerpt is not in its source."""

    card_id: str
    url: str
    reason: str


def check_excerpt(card_id: str, url: str, excerpt: str) -> Mismatch | None:
    """``None`` when ``excerpt`` is in ``url``'s text, else why not."""
    try:
        text = page_text(url)
    except (OSError, subprocess.CalledProcessError) as error:
        _logger.warning("%s: cannot fetch %s: %s", card_id, url, error)
        return Mismatch(card_id, url, f"cannot fetch: {error}")
    if normalise(excerpt) in normalise(text):
        return None
    return Mismatch(card_id, url, "excerpt not found in the page text")
