# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The ``python -m plc_lab.tutor.feedback`` command line."""

from __future__ import annotations

import json
import runpy
import sys

import pytest

from plc_lab.tutor import feedback
from plc_lab.tutor.feedback import main, record


def seed() -> None:
    record({"category": "ui", "text": "first", "status": "open"})
    record({"category": "other", "text": "second"})
    feedback.resolve(1)


def test_empty_listing_says_so_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no open feedback in" in captured.err
    assert main(["--all"]) == 0
    assert "no feedback in" in capsys.readouterr().err


def test_default_lists_open_only(capsys: pytest.CaptureFixture[str]) -> None:
    seed()
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "#2 (open)" in out
    assert "#1" not in out
    assert main(["--open"]) == 0
    assert capsys.readouterr().out == out


def test_all_lists_resolved_too_separated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed()
    assert main(["--all"]) == 0
    out = capsys.readouterr().out
    assert out.index("#1 (resolved)") < out.index("#2 (open)")
    assert "\n\n---\n\n" in out


def test_json_prints_one_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    seed()
    assert main(["--all", "--json"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["id"] for r in rows] == [1, 2]


def test_resolve_found_and_missing(capsys: pytest.CaptureFixture[str]) -> None:
    seed()
    assert main(["--resolve", "2"]) == 0
    assert capsys.readouterr().out == "feedback #2 resolved\n"
    assert main(["--resolve", "7"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no feedback #7 in" in captured.err


def test_run_as_a_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seed()
    monkeypatch.setattr(sys, "argv", ["feedback", "--json"])
    monkeypatch.delitem(sys.modules, "plc_lab.tutor.feedback")
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("plc_lab.tutor.feedback", run_name="__main__")
    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["id"] == 2
