# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The scripted learner's CLI: argument parsing, summary line, script entry."""

from __future__ import annotations

import runpy
import sys
from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor import scripted, session
from plc_lab.tutor.tests.test_scripted import FakeLearner, FakeResponse, state

if TYPE_CHECKING:
    import urllib.request

FINAL = state()


class RunRecorder:
    """Stands in for ``scripted.run``: records its arguments."""

    def __init__(self) -> None:
        self.args: list[tuple[Any, ...]] = []

    async def __call__(self, *args: Any) -> dict[str, Any]:
        self.args.append(args)
        return FINAL


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RunRecorder:
    rec = RunRecorder()
    monkeypatch.setattr(scripted, "run", rec)
    return rec


def test_main_defaults_without_a_hook(
    monkeypatch: pytest.MonkeyPatch,
    recorder: RunRecorder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["scripted"])
    assert scripted.main() == 0
    assert recorder.args == [
        ("http://127.0.0.1:8779", "io-24vdc-relay-coil", 22, 110.0, None)
    ]
    assert capsys.readouterr().out == (
        "session sess-1: 1 messages, credited 10/20 min\n"
    )


def test_main_passes_the_hook_and_options(
    monkeypatch: pytest.MonkeyPatch, recorder: RunRecorder
) -> None:
    argv = ["scripted", "--url", "http://h:1", "--card", "c", "--max-turns", "3"]
    argv += ["--hook-after", "4", "--hook-cmd", "echo x", "--advance", "5"]
    monkeypatch.setattr(sys, "argv", argv)
    assert scripted.main() == 0
    assert recorder.args == [("http://h:1", "c", 3, 5.0, (4, "echo x"))]


def test_main_ignores_hook_after_without_a_command(
    monkeypatch: pytest.MonkeyPatch, recorder: RunRecorder
) -> None:
    monkeypatch.setattr(sys, "argv", ["scripted", "--hook-after", "4"])
    assert scripted.main() == 0
    assert recorder.args[0][-1] is None


def test_module_runs_as_a_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    urls: list[str] = []

    def urlopen(req: urllib.request.Request, timeout: float) -> FakeResponse:
        urls.append(req.full_url)
        return FakeResponse(FINAL)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(session, "TutorSession", FakeLearner)
    monkeypatch.setattr(sys, "argv", ["scripted", "--max-turns", "0"])
    monkeypatch.delitem(sys.modules, "plc_lab.tutor.scripted")
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("plc_lab.tutor.scripted", run_name="__main__")
    assert exit_info.value.code == 0
    assert urls == ["http://127.0.0.1:8779/api/start"]
    assert "session sess-1" in capsys.readouterr().out
