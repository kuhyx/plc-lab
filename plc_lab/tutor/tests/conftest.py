# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Every tutor test runs in a private HOME and data dir, with no network.

HOME moves too, so a fallback to ``~/.local/share/automation_tutor`` (the real
ledger), ``~/.cache`` or ``~/.claude`` can only ever land in ``tmp_path``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import urllib.request

import pytest

if TYPE_CHECKING:
    from pathlib import Path

KEY = b"tutor-test-key-not-the-real-one"


def _offline(*_: object, **__: object) -> object:
    msg = "network disabled in tests"
    raise OSError(msg)


@pytest.fixture(autouse=True)
def tutor_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME, the data dir, the key and the image cache; block urlopen."""
    home = tmp_path / "home"
    home.mkdir()
    key = tmp_path / "hmac.key"
    key.write_bytes(KEY + b"\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUTOMATION_TUTOR_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOMATION_TUTOR_KEY", str(key))
    monkeypatch.setenv("AUTOMATION_TUTOR_IMAGE_CACHE", str(tmp_path / "images"))
    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    return tmp_path
