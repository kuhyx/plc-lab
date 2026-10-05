# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Tests for plc_lab.sources: text extraction, normalisation, cache, check."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from plc_lab import sources
from plc_lab.sources import Mismatch, check_excerpt, html_text, normalise, page_text

if TYPE_CHECKING:
    from pathlib import Path

URL = "https://example.org/plc"
PAGE = (
    b"<html><head><style>.x{}</style><script>var hidden = 1;</script></head>"
    b"<body><p>A <b>programmable</b> logic controller[3] is a \xe2\x80\x9crugged\xe2\x80\x9d"
    b"&nbsp;computer.</p><noscript>nojs</noscript></body></html>"
)


class TestNormalise:
    def test_folds_typography_footnotes_case_and_space(self) -> None:
        assert normalise("A “B”—C[12] [ 3 ]  \n D&amp;E") == 'a "b"-c d&e'

    def test_drops_soft_hyphens(self) -> None:
        assert normalise("con­troller") == "controller"


class TestHtmlText:
    def test_keeps_visible_text_only(self) -> None:
        text = html_text(PAGE.decode())
        assert "programmable" in text
        assert "hidden" not in text
        assert "nojs" not in text
        assert ".x{}" not in text

    def test_an_unbalanced_end_tag_is_harmless(self) -> None:
        assert "after" in html_text("</script><p>after</p>")


class TestPageText:
    def test_html_is_fetched_once_then_cached(
        self, web: dict[str, tuple[bytes, str]], cache_dir: Path
    ) -> None:
        web[URL] = (PAGE, "text/html")
        first = page_text(URL)
        del web[URL]
        assert page_text(URL) == first
        assert len(list(cache_dir.iterdir())) == 1

    def test_pdf_goes_through_pdftotext(
        self, web: dict[str, tuple[bytes, str]]
    ) -> None:
        web[URL] = (b"%PDF-1.7 ...", "application/octet-stream")
        done = MagicMock(stdout=b"Function code 03 reads holding registers")
        with patch("plc_lab.sources.subprocess.run", return_value=done) as run:
            assert "holding registers" in page_text(URL)
        assert run.call_args.args[0] == [sources.PDFTOTEXT, "-", "-"]

    def test_pdf_content_type_is_enough(
        self, web: dict[str, tuple[bytes, str]]
    ) -> None:
        web[URL] = (b"not a magic header", "application/pdf")
        with patch(
            "plc_lab.sources.subprocess.run", return_value=MagicMock(stdout=b"text")
        ):
            assert page_text(URL) == "text"


class TestCheckExcerpt:
    def test_found_after_normalisation(self, web: dict[str, tuple[bytes, str]]) -> None:
        web[URL] = (PAGE, "text/html")
        assert (
            check_excerpt("c1", URL, 'logic controller is a "RUGGED" computer') is None
        )

    def test_missing_excerpt_is_reported(
        self, web: dict[str, tuple[bytes, str]]
    ) -> None:
        web[URL] = (PAGE, "text/html")
        assert check_excerpt("c1", URL, "a relay panel") == Mismatch(
            "c1", URL, "excerpt not found in the page text"
        )

    def test_unreachable_source_is_reported(
        self, web: dict[str, tuple[bytes, str]]
    ) -> None:
        miss = check_excerpt("c1", URL, "anything")
        assert miss is not None
        assert miss.reason.startswith("cannot fetch: no route")

    def test_a_broken_pdf_is_reported(self, web: dict[str, tuple[bytes, str]]) -> None:
        web[URL] = (b"%PDF broken", "application/pdf")
        error = subprocess.CalledProcessError(1, ["pdftotext"])
        with patch("plc_lab.sources.subprocess.run", side_effect=error):
            miss = check_excerpt("c1", URL, "anything")
        assert miss is not None
        assert miss.reason.startswith("cannot fetch:")


def test_download_sends_the_user_agent() -> None:
    response = MagicMock()
    response.read.return_value = b"body"
    response.headers.get_content_type.return_value = "text/html"
    opened = MagicMock()
    opened.__enter__.return_value = response
    with patch(
        "plc_lab.sources.urllib.request.urlopen", return_value=opened
    ) as urlopen:
        assert sources._download(URL) == (b"body", "text/html")
    request = urlopen.call_args.args[0]
    assert request.get_header("User-agent").startswith("plc-lab-source-check")
