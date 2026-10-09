# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""``images.fetch``: term cache, negative TTL, legacy layout, shared files."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor import images
from plc_lab.tutor.images import NEGATIVE_TTL, CommonsImage

if TYPE_CHECKING:
    from pathlib import Path

T0 = 1_000_000.0
THUMB = "https://upload.test/relay.png?width=800"


class Net:
    """Stands in for search() and _get(); counts what reached the network."""

    def __init__(self, hit: dict[str, Any] | None, error: bool = False) -> None:
        self.hit = hit
        self.error = error
        self.searches = 0
        self.downloads = 0

    def search(self, _term: str) -> dict[str, Any] | None:
        self.searches += 1
        if self.error:
            msg = "commons down"
            raise OSError(msg)
        return self.hit

    def get(self, _url: str) -> bytes:
        self.downloads += 1
        return b"IMG"


def make_hit(
    title: str = "Relay.png", thumb: str = THUMB, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "thumburl": thumb,
        "descriptionurl": "https://commons.test/File:Relay.png",
        "extmetadata": {
            "Artist": {"value": "<a>Ann</a>"},
            "LicenseShortName": {"value": "CC BY 4.0"},
            "LicenseUrl": {"value": "https://cc.test/by"},
        },
    }
    info.update(extra or {})
    return {"title": f"File:{title}", "info": info}


def wire(monkeypatch: pytest.MonkeyPatch, net: Net) -> None:
    monkeypatch.setattr(images, "search", net.search)
    monkeypatch.setattr(images, "_get", net.get)


def test_fetch_downloads_and_credits(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    net = Net(make_hit())
    wire(monkeypatch, net)
    image = images.fetch("Relay", now=T0)
    assert image is not None
    assert image.file.endswith(".png")
    assert (tutor_sandbox / "images" / image.file).read_bytes() == b"IMG"
    assert (image.title, image.author) == ("Relay.png", "Ann")
    assert (image.licence, image.licence_url) == ("CC BY 4.0", "https://cc.test/by")
    assert image.page_url == "https://commons.test/File:Relay.png"
    assert image.to_json()["term"] == "Relay"


def test_fetch_defaults_credit_and_jpg(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = {"title": "File:Bare.jpg", "info": {"thumburl": "https://x/b.JPG"}}
    wire(monkeypatch, Net(hit))
    image = images.fetch("bare", now=T0)
    assert image is not None
    assert image.file.endswith(".jpg")
    assert image.author == image.licence == "see file page"
    assert image.licence_url == image.page_url == ""


def test_fetch_uses_default_clock_and_cache(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(monkeypatch, Net(None))
    assert images.fetch("nothing") is None
    assert list((tutor_sandbox / "images" / "terms").glob("*.json"))


def test_term_cache_hit_never_requeries(monkeypatch: pytest.MonkeyPatch) -> None:
    net = Net(make_hit())
    wire(monkeypatch, net)
    first = images.fetch("Relay  Coil", now=T0)
    again = images.fetch("relay coil", now=T0 + 10 * NEGATIVE_TTL)
    assert again == first
    assert (net.searches, net.downloads) == (1, 1)


def test_cache_hit_with_missing_file_refetches(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    net = Net(make_hit())
    wire(monkeypatch, net)
    first = images.fetch("relay", now=T0)
    assert first is not None
    (tutor_sandbox / "images" / first.file).unlink()
    assert images.fetch("relay", now=T0) == first
    assert (net.searches, net.downloads) == (2, 2)


def test_negative_cache_within_ttl_then_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    net = Net(None)
    wire(monkeypatch, net)
    assert images.fetch("ghost", now=T0) is None
    assert images.fetch("ghost", now=T0 + NEGATIVE_TTL - 1) is None
    assert net.searches == 1
    net.hit = make_hit()
    found = images.fetch("ghost", now=T0 + NEGATIVE_TTL + 1)
    assert found is not None
    assert net.searches == 2
    assert images.fetch("ghost", now=T0 + NEGATIVE_TTL + 2) == found
    assert net.searches == 2


def test_network_error_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    net = Net(None, error=True)
    wire(monkeypatch, net)
    with pytest.raises(OSError, match="commons down"):
        images.fetch("relay", now=T0)
    net.error = False
    net.hit = make_hit()
    assert images.fetch("relay", now=T0) is not None
    assert net.searches == 2


def test_two_terms_share_one_download(monkeypatch: pytest.MonkeyPatch) -> None:
    net = Net(make_hit())
    wire(monkeypatch, net)
    first = images.fetch("relay", now=T0)
    second = images.fetch("electromechanical relay", now=T0)
    assert first is not None
    assert second is not None
    assert second.file == first.file
    assert second.term == "electromechanical relay"
    assert (net.searches, net.downloads) == (2, 1)


def test_legacy_layout_is_a_hit(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    net = Net(make_hit())
    wire(monkeypatch, net)
    cache = tutor_sandbox / "images"
    cache.mkdir()
    old = CommonsImage("Relay", "Old.png", "old.png", "Bob", "PD", "", "p")
    (cache / "old.png").write_bytes(b"OLD")
    (cache / f"{images._key('relay')}.json").write_text(json.dumps(old.to_json()))
    assert images.fetch("Relay", now=T0) == old
    assert net.searches == 0
    assert not (cache / "terms").exists()


def test_legacy_record_without_file_is_a_miss(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    net = Net(None)
    wire(monkeypatch, net)
    cache = tutor_sandbox / "images"
    cache.mkdir()
    old = CommonsImage("relay", "Old.png", "gone.png", "Bob", "PD", "", "p")
    (cache / f"{images._key('relay')}.json").write_text(json.dumps(old.to_json()))
    assert images.fetch("relay", now=T0) is None
    assert net.searches == 1
