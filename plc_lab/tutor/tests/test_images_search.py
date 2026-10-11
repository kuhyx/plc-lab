# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Image blocks for the vision check and the cache location."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from plc_lab.tutor import images
from plc_lab.tutor.images import CommonsImage

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_cache_dir_env_override(tutor_sandbox: Path) -> None:
    assert images.cache_dir() == tutor_sandbox / "images"


def test_cache_dir_home_default(
    tutor_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AUTOMATION_TUTOR_IMAGE_CACHE")
    expected = tutor_sandbox / "home" / ".cache" / "plc-lab" / "tutor-images"
    assert images.cache_dir() == expected


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
