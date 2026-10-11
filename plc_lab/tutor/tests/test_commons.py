# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Commons search: ranking, shortening, HTTP plumbing."""

from __future__ import annotations

import io
import json
from typing import Any
import urllib.request

import pytest

from plc_lab.tutor import commons


def page(
    title: str,
    index: int | None = 1,
    mime: str = "image/png",
    thumb: str | None = "https://x/t.png",
    about: str = "",
) -> dict[str, Any]:
    """A Commons query page; ``index`` None leaves the key out."""
    info: dict[str, Any] = {"mime": mime}
    if about:
        info["extmetadata"] = {"ImageDescription": {"value": f"<p>{about}</p>"}}
    if thumb:
        info["thumburl"] = thumb
    out: dict[str, Any] = {"title": f"File:{title}", "imageinfo": [info]}
    if index is not None:
        out["index"] = index
    return out


class Resp(io.BytesIO):
    """A urlopen() response: a context manager with read()."""


def test_get_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(req: urllib.request.Request, timeout: int) -> Resp:
        seen["agent"] = req.get_header("User-agent")
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return Resp(b"payload")

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    url = "https://upload.wikimedia.org/a/b.png?width=800"
    assert commons.get(url) == b"payload"
    assert seen == {"agent": commons.USER_AGENT, "url": url, "timeout": 20}
    assert commons.get("https://commons.wikimedia.org/w/api.php") == b"payload"
    assert seen["url"] == "https://commons.wikimedia.org/w/api.php"
    thumb = "https://thumb.wikimedia.org/a/b.png"
    assert commons.get(thumb) == b"payload"
    assert seen["url"] == thumb


@pytest.mark.parametrize(
    "url",
    [
        "http://upload.wikimedia.org/a.png",
        "file:///etc/passwd",
        "https://example.test/a.png",
        "https://upload.wikimedia.org.evil.test/a.png",
    ],
)
def test_get_refuses_anything_but_https_commons(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    def never(*_: object, **__: object) -> Resp:
        raise AssertionError

    monkeypatch.setattr(urllib.request, "urlopen", never)
    with pytest.raises(ValueError, match="not an https Commons URL"):
        commons.get(url)


def test_query_parses_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    body = {"query": {"pages": {"1": {"title": "a"}, "2": {"title": "b"}}}}

    def fake_get(url: str) -> bytes:
        urls.append(url)
        return json.dumps(body).encode()

    monkeypatch.setattr(commons, "get", fake_get)
    assert commons._query("relay coil") == [{"title": "a"}, {"title": "b"}]
    assert urls[0].startswith(commons.API)
    assert "relay+coil+filetype" in urls[0]


def test_query_without_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commons, "get", lambda _u: b"{}")
    assert commons._query("nothing") == []


def test_plain_and_meta_strip_html() -> None:
    assert commons.plain(" <b>A &amp; B</b> ") == "A & B"
    info = {"extmetadata": {"Artist": {"value": "<a>Ann</a>"}}}
    assert commons.meta(info, "Artist") == "Ann"
    assert commons.meta(info, "Missing") == ""
    assert commons.meta({}, "Artist") == ""


def test_search_prefers_more_title_words(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [page("Relay coil diagram.png", 1), page("Relay coil.png", 2)]
    monkeypatch.setattr(commons, "_query", lambda _t: pages)
    hit = commons.search("relay coil")
    assert hit is not None
    assert hit["title"] == "File:Relay coil diagram.png"


def test_search_ties_use_commons_order(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [page("Relay B.png", 5), page("Relay A.png", 2), page("Relay C.png", None)]
    monkeypatch.setattr(commons, "_query", lambda _t: pages)
    hit = commons.search("relay")
    assert hit is not None
    assert hit["title"] == "File:Relay A.png"


def test_search_skips_unusable_and_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        page("Relay coil.pdf", 1, mime="application/pdf"),
        page("Relay coil.png", 2, thumb=None),
        {"title": "File:Relay coil.png", "index": 3},
        page("Relay only.png", 4),
        page("Relays and coils.png", 5),
    ]
    monkeypatch.setattr(commons, "_query", lambda _t: pages)
    hit = commons.search("relay coil")
    assert hit is not None
    assert hit["title"] == "File:Relays and coils.png"
    assert hit["info"]["mime"] == "image/png"


def test_search_shortens_long_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def fake(term: str) -> list[dict[str, Any]]:
        asked.append(term)
        return [page("Relay coil.png")] if term == "relay coil" else []

    monkeypatch.setattr(commons, "_query", fake)
    hit = commons.search("relay coil wiring diagram")
    assert hit is not None
    assert asked == ["relay coil wiring diagram", "relay coil wiring", "relay coil"]


def test_search_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def fake(term: str) -> list[dict[str, Any]]:
        asked.append(term)
        return []

    monkeypatch.setattr(commons, "_query", fake)
    assert commons.search("a b c") is None
    assert asked == ["a b c", "a b"]
    asked.clear()
    assert commons.search("solo") is None
    assert asked == ["solo"]
    assert commons.search("") is None


def test_tokens_keep_short_meaningful_words() -> None:
    assert commons.tokens("remote I/O") == {"remote", "io"}
    assert commons.tokens("4-20 mA loop") == {"4", "20", "ma", "loop"}
    assert commons.tokens("The ms of relays and an HMI") == {"ms", "relay", "hmi"}


def test_search_asks_commons_for_io_not_i_slash_o(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    def fake(term: str) -> list[dict[str, Any]]:
        asked.append(term)
        return [page("Remote IO rack.png")]

    monkeypatch.setattr(commons, "_query", fake)
    hit = commons.search("remote I/O")
    assert hit is not None
    assert asked == ["remote IO"]


def test_search_accepts_words_found_in_the_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [page("IMG_0042.jpg", 1, about="A remote IO rack"), page("Other.png", 2)]
    monkeypatch.setattr(commons, "_query", lambda _t: pages)
    hit = commons.search("remote io")
    assert hit is not None
    assert hit["title"] == "File:IMG_0042.jpg"


def test_search_prefers_a_title_match_from_a_shorter_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(term: str) -> list[dict[str, Any]]:
        if term == "remote io rack":
            return [page("Gear racks.jpg", 1, about="remote IO")]
        return [page("Remote IO.png", 1)]

    monkeypatch.setattr(commons, "_query", fake)
    hit = commons.search("remote io rack")
    assert hit is not None
    assert hit["title"] == "File:Remote IO.png"


def test_search_falls_back_to_the_description_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(term: str) -> list[dict[str, Any]]:
        if term == "remote io rack":
            return [
                page("Unusable.pdf", 1, mime="application/pdf", about="remote io rack"),
                page("Gear racks.jpg", 2, about="remote IO"),
                page("Later.jpg", 3, about="remote IO"),
            ]
        return []

    monkeypatch.setattr(commons, "_query", fake)
    hit = commons.search("remote io rack")
    assert hit is not None
    assert hit["title"] == "File:Gear racks.jpg"


def test_search_ignores_a_term_with_no_words(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commons, "_query", lambda _t: [page("Anything.png")])
    assert commons.search("the") is None
