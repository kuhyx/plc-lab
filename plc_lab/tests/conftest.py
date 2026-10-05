# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Shared fixtures: a private source cache and a fake web, so no test fetches."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from plc_lab import sources

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the source cache at a per-test directory."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(sources, "CACHE_DIR", cache)
    return cache


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[bytes, str]]:
    """URL -> (body, content type); a missing URL raises like a dead host."""
    pages: dict[str, tuple[bytes, str]] = {}

    def fake_download(url: str) -> tuple[bytes, str]:
        if url not in pages:
            msg = f"no route to {url}"
            raise OSError(msg)
        return pages[url]

    monkeypatch.setattr(sources, "_download", fake_download)
    return pages
