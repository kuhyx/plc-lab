# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Tests for plc_lab.cli and the ``python3 -m plc_lab`` entry point."""

from __future__ import annotations

import json
import runpy
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from plc_lab import cli
from plc_lab.cards import TOPICS
from plc_lab.sources import Mismatch

if TYPE_CHECKING:
    from pathlib import Path

URL = "https://example.org/page"
EXCERPT = "a programmable logic controller is a rugged computer"


@pytest.fixture
def deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A one-card-per-topic deck the CLI reads instead of the real one."""
    deck_dir = tmp_path / "deck"
    deck_dir.mkdir()
    for topic in TOPICS:
        card = {
            "id": f"{topic.prefixes[0]}one",
            "front": "What is a PLC?",
            "back": "A rugged industrial computer.",
            "source": URL,
            "excerpt": EXCERPT,
        }
        (deck_dir / f"{topic.stem}.json").write_text(json.dumps([card]))
    monkeypatch.setattr(cli, "DECK_DIR", deck_dir)
    return deck_dir


def found(*_args: str) -> None:
    return None


def missing(card_id: str, url: str, _excerpt: str) -> Mismatch:
    return Mismatch(card_id, url, "excerpt not found in the page text")


def test_check_passes_when_every_excerpt_is_found(
    deck: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("plc_lab.cli.check_excerpt", side_effect=found):
        assert cli.main(["check"]) == 0
    assert f"{len(TOPICS)}/{len(TOPICS)} excerpts found" in capsys.readouterr().out


def test_check_fails_and_names_the_card(
    deck: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("plc_lab.cli.check_excerpt", side_effect=missing):
        assert cli.main(["check"]) == 1
    assert "FAIL fund-one: excerpt not found" in capsys.readouterr().out


def test_check_given_files_skips_validation(
    deck: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = deck / "draft.json"
    raw.write_text(json.dumps([{"id": "draft", "source": URL, "excerpt": "x"}]))
    with patch("plc_lab.cli.check_excerpt", side_effect=missing):
        assert cli.main(["check", str(raw)]) == 1
    with patch("plc_lab.cli.check_excerpt", side_effect=found):
        assert cli.main(["check", str(raw)]) == 0
    assert "1/1 excerpts found" in capsys.readouterr().out


def test_an_invalid_deck_exits_2(
    deck: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (deck / "ladder.json").write_text("{}")
    with pytest.raises(SystemExit) as exited:
        cli.main(["check"])
    assert exited.value.code == 2
    assert "invalid deck:" in capsys.readouterr().err


def test_build_refuses_while_an_excerpt_is_missing(deck: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.apkg"
    with patch("plc_lab.cli.check_excerpt", side_effect=missing):
        assert cli.main(["build", "--out", str(out)]) == 1
    assert not out.exists()


def test_build_writes_the_package(
    deck: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.apkg"
    with patch("plc_lab.cli.check_excerpt", side_effect=found):
        assert cli.main(["build", "--out", str(out)]) == 0
    assert out.is_file()
    assert f"wrote {len(TOPICS)} cards" in capsys.readouterr().out


def test_module_entry_point_exits_with_main(deck: Path) -> None:
    with (
        patch("sys.argv", ["plc_lab", "check"]),
        patch("plc_lab.cli.check_excerpt", side_effect=found),
        pytest.raises(SystemExit) as exited,
    ):
        runpy.run_module("plc_lab", run_name="__main__")
    assert exited.value.code == 0


def test_importing_the_entry_module_runs_nothing() -> None:
    import plc_lab.__main__ as entry

    assert entry.main is cli.main
