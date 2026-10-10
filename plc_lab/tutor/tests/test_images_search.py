# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Commons search: ranking, shortening, HTTP plumbing and image blocks."""

from __future__ import annotations

import base64
import io
import json
from typing import TYPE_CHECKING, Any
import urllib.request

import pytest

from plc_lab.tutor import images
from plc_lab.tutor.images import CommonsImage

if TYPE_CHECKING:
    from pathlib import Path


def page(
    title: str,
    index: int | None = 1,
    mime: str = "image/png",
    thumb: str | None = "https://x/t.png",
) -> dict[str, Any]:
    """A Commons query page; ``index`` None leaves the key out."""
    info: dict[str, Any] = {"mime": mime}
    if thumb:
        info["thumburl"] = thumb
    out: dict[str, Any] = {"title": f"File:{title}", "imageinfo": [info]}
    if index is not None:
        out["index"] = index
    return out


class Resp(io.BytesIO):
    """A urlopen() response: a context manager with read()."""


def test_cache_dir_env_override(tutor_sandbox: Path) -> None:
    assert images.cache_dir() == tutor_sandbox / "images"


def test_cache_dir_home_default(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTOMATION_TUTOR_IMAGE_CACHE")
    expected = tutor_sandbox / "home" / ".cache" / "plc-lab" / "tutor-images"
    assert images.cache_dir() == expected


def test_get_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(req: urllib.request.Request, timeout: int) -> Resp:
        seen["agent"] = req.get_header("User-agent")
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return Resp(b"payload")

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    url = "https://upload.wikimedia.org/a/b.png?width=800"
    assert images._get(url) == b"payload"
    assert seen == {"agent": images.USER_AGENT, "url": url, "timeout": 20}
    assert images._get("https://commons.wikimedia.org/w/api.php") == b"payload"
    assert seen["url"] == "https://commons.wikimedia.org/w/api.php"


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
        images._get(url)


def test_query_parses_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    body = {"query": {"pages": {"1": {"title": "a"}, "2": {"title": "b"}}}}

    def fake_get(url: str) -> bytes:
        urls.append(url)
        return json.dumps(body).encode()

    monkeypatch.setattr(images, "_get", fake_get)
    assert images._query("relay coil") == [{"title": "a"}, {"title": "b"}]
    assert urls[0].startswith(images.API)
    assert "relay+coil+filetype" in urls[0]


def test_query_without_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "_get", lambda _u: b"{}")
    assert images._query("nothing") == []


def test_plain_and_meta_strip_html() -> None:
    assert images._plain(" <b>A &amp; B</b> ") == "A & B"
    info = {"extmetadata": {"Artist": {"value": "<a>Ann</a>"}}}
    assert images._meta(info, "Artist") == "Ann"
    assert images._meta(info, "Missing") == ""
    assert images._meta({}, "Artist") == ""


def test_search_prefers_more_title_words(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [page("Relay coil diagram.png", 1), page("Relay coil.png", 2)]
    monkeypatch.setattr(images, "_query", lambda _t: pages)
    hit = images.search("relay coil")
    assert hit is not None
    assert hit["title"] == "File:Relay coil diagram.png"


def test_search_ties_use_commons_order(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [page("Relay B.png", 5), page("Relay A.png", 2), page("Relay C.png", None)]
    monkeypatch.setattr(images, "_query", lambda _t: pages)
    hit = images.search("relay")
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
    monkeypatch.setattr(images, "_query", lambda _t: pages)
    hit = images.search("relay coil")
    assert hit is not None
    assert hit["title"] == "File:Relays and coils.png"
    assert hit["info"]["mime"] == "image/png"


def test_search_shortens_long_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def fake(term: str) -> list[dict[str, Any]]:
        asked.append(term)
        return [page("Relay coil.png")] if term == "relay coil" else []

    monkeypatch.setattr(images, "_query", fake)
    hit = images.search("relay coil wiring diagram")
    assert hit is not None
    assert asked == ["relay coil wiring diagram", "relay coil wiring", "relay coil"]


def test_search_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def fake(term: str) -> list[dict[str, Any]]:
        asked.append(term)
        return []

    monkeypatch.setattr(images, "_query", fake)
    assert images.search("a b c") is None
    assert asked == ["a b c", "a b"]
    asked.clear()
    assert images.search("solo") is None
    assert asked == ["solo"]
    assert images.search("") is None


def test_media_type_sniffing() -> None:
    assert images._media_type(b"\x89PNG\r\n") == "image/png"
    assert images._media_type(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert images._media_type(b"RIFF\0\0\0\0WAVEfmt ") == "image/jpeg"
    assert images._media_type(b"GIF89a") == "image/gif"
    assert images._media_type(b"\xff\xd8\xff") == "image/jpeg"


def test_content_block_base64(tutor_sandbox: Path) -> None:
    cache = tutor_sandbox / "images"
    cache.mkdir()
    (cache / "p.jpg").write_bytes(b"\x89PNGdata")
    image = CommonsImage("t", "T", "p.jpg", "a", "l", "u", "p")
    block = images.content_block(image)
    assert block == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(b"\x89PNGdata").decode(),
        },
    }
    other = tutor_sandbox / "elsewhere"
    other.mkdir()
    (other / "p.jpg").write_bytes(b"\xff\xd8")
    assert images.content_block(image, other)["source"]["media_type"] == "image/jpeg"
