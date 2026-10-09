# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""``python -m plc_lab.tutor``: port guard, resume, and the uvicorn call."""

from __future__ import annotations

import runpy
import socket
import sys
from typing import Any, ClassVar

import pytest
import uvicorn

from plc_lab.tutor import __main__ as tutor_main

APP = object()


class FakeEngine:
    """Records construction and answers ``resume_latest`` as scripted."""

    resumes = True
    built: ClassVar[list[FakeEngine]] = []

    def __init__(self, *, simulated_time: bool = False) -> None:
        self.simulated_time = simulated_time
        self.resume_calls = 0
        self.session_id = "20261009-sess"
        FakeEngine.built.append(self)

    def resume_latest(self) -> bool:
        self.resume_calls += 1
        return FakeEngine.resumes


class Recorder:
    """Stands in for ``uvicorn.run`` and ``create_app``."""

    def __init__(self) -> None:
        self.runs: list[tuple[object, dict[str, Any]]] = []
        self.apps: list[object] = []

    def run(self, app: object, **kwargs: Any) -> None:
        self.runs.append((app, kwargs))

    def create_app(self, engine: object) -> object:
        self.apps.append(engine)
        return APP


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    """Port free, engine and app faked, uvicorn recorded."""
    rec = Recorder()
    FakeEngine.built = []
    FakeEngine.resumes = True
    monkeypatch.setattr(tutor_main, "_port_busy", lambda _port: False)
    monkeypatch.setattr(tutor_main, "Engine", FakeEngine)
    monkeypatch.setattr(tutor_main, "create_app", rec.create_app)
    monkeypatch.setattr(uvicorn, "run", rec.run)
    return rec


def test_busy_port_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tutor_main, "_port_busy", lambda _port: True)
    monkeypatch.setattr(tutor_main, "Engine", FakeEngine)
    FakeEngine.built = []
    assert tutor_main.main(["--port", "18999"]) == 1
    assert "port 18999 is already in use" in capsys.readouterr().err
    assert not FakeEngine.built


def test_serves_on_localhost_and_reports_resume(
    served: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tutor_main.main(["--port", "18999"]) == 0
    assert served.runs == [
        (APP, {"host": "127.0.0.1", "port": 18999, "log_level": "warning"})
    ]
    err = capsys.readouterr().err
    assert "resumed session 20261009-sess" in err
    assert "http://127.0.0.1:18999/" in err
    engine = FakeEngine.built[0]
    assert served.apps == [engine]
    assert engine.simulated_time is False
    assert engine.resume_calls == 1


def test_no_resume_message_when_nothing_to_resume(
    served: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeEngine.resumes = False
    assert tutor_main.main(["--port", "18999"]) == 0
    assert "resumed" not in capsys.readouterr().err
    assert len(served.runs) == 1


def test_fresh_skips_resume_and_simulate_time_is_passed(served: Recorder) -> None:
    assert tutor_main.main(["--port", "18999", "--fresh", "--simulate-time"]) == 0
    engine = FakeEngine.built[0]
    assert engine.resume_calls == 0
    assert engine.simulated_time is True
    assert len(served.runs) == 1


def test_default_port_is_the_documented_one() -> None:
    assert tutor_main.DEFAULT_PORT == 8772


def test_port_busy_sees_a_listening_socket() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert tutor_main._port_busy(listener.getsockname()[1]) is True


def test_port_busy_is_false_for_a_closed_port() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert tutor_main._port_busy(port) is False


def test_module_runs_as_a_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setattr(sys, "argv", ["tutor", "--port", str(port)])
        monkeypatch.delitem(sys.modules, "plc_lab.tutor.__main__", raising=False)
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module("plc_lab.tutor.__main__", run_name="__main__")
    assert exit_info.value.code == 1
    assert "already in use" in capsys.readouterr().err
