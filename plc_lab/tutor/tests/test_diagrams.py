# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Circuit diagrams: spec validation, SVG rendering and the render cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from plc_lab.tutor import diagrams
from plc_lab.tutor.diagrams import DiagramError

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = {"kind": "dc_source", "label": "24 V"}
LAMP = {"kind": "lamp", "label": "H1"}


def circuit(**fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"source": SOURCE, "elements": [LAMP]}
    out.update(fields)
    return out


def test_cache_dir_follows_home(tutor_sandbox: Path) -> None:
    expected = tutor_sandbox / "home" / ".cache" / "plc-lab" / "tutor-diagrams"
    assert diagrams.cache_dir() == expected


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ("not a dict", "1-2 circuits"),
        ({}, "1-2 circuits"),
        ({"circuits": "x"}, "1-2 circuits"),
        ({"circuits": []}, "1-2 circuits"),
        ({"circuits": [circuit()] * 3}, "1-2 circuits"),
        ({"circuits": ["nope"]}, "object with an elements list"),
        ({"circuits": [{"source": SOURCE, "elements": "x"}]}, "elements list"),
        ({"circuits": [circuit(elements=[LAMP] * 7)]}, "at most 6 elements"),
        ({"circuits": [{"elements": [LAMP]}]}, "unknown element kind None"),
        ({"circuits": [circuit(source={"kind": "bogus"})]}, "unknown element kind"),
        ({"circuits": [circuit(elements=["lamp"])]}, "unknown element kind None"),
        ({"circuits": [circuit(elements=[{"kind": "x"}])]}, "'x'"),
    ],
)
def test_check_rejects(spec: object, reason: str) -> None:
    with pytest.raises(DiagramError, match=reason):
        diagrams._check(spec)


def test_check_accepts_and_defaults_elements() -> None:
    spec = {"circuits": [circuit(), {"source": SOURCE}]}
    assert diagrams._check(spec) == spec["circuits"]


def test_render_writes_svgs(tmp_path: Path) -> None:
    spec = {
        "circuits": [
            circuit(name="Loop A"),
            circuit(elements=[{"kind": "switch", "label": "S1"}, LAMP]),
        ]
    }
    cache = tmp_path / "svg"
    names = diagrams.render(spec, cache)
    assert len(names) == 2
    assert names[0].endswith("-0.svg")
    for name in names:
        assert (cache / name).read_text(encoding="utf-8").lstrip().startswith("<")
    assert "Loop A" in (cache / names[0]).read_text(encoding="utf-8")


def test_render_reuses_cached_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {"circuits": [circuit()]}
    names = diagrams.render(spec, tmp_path)
    marker = tmp_path / names[0]
    marker.write_text("cached", encoding="utf-8")

    def boom(_c: dict[str, Any], _p: Path) -> None:
        msg = "must not redraw"
        raise AssertionError(msg)

    monkeypatch.setattr(diagrams, "_draw", boom)
    assert diagrams.render(spec, tmp_path) == names
    assert marker.read_text(encoding="utf-8") == "cached"


def test_render_default_cache_is_under_home(tutor_sandbox: Path) -> None:
    names = diagrams.render({"circuits": [circuit()]})
    cache = tutor_sandbox / "home" / ".cache" / "plc-lab" / "tutor-diagrams"
    assert (cache / names[0]).is_file()


@pytest.mark.parametrize("exc", [TypeError, ValueError, AttributeError])
def test_draw_failure_becomes_diagram_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: type[Exception]
) -> None:
    def broken(_c: dict[str, Any], _p: Path) -> None:
        msg = "bad geometry"
        raise exc(msg)

    monkeypatch.setattr(diagrams, "_draw", broken)
    with pytest.raises(DiagramError, match="could not draw circuit 0: bad geometry"):
        diagrams.render({"circuits": [circuit()]}, tmp_path)


def test_render_invalid_spec_writes_nothing(tmp_path: Path) -> None:
    cache = tmp_path / "svg"
    with pytest.raises(DiagramError):
        diagrams.render({"circuits": []}, cache)
    assert not cache.exists()
