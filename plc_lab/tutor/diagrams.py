# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Circuit diagrams drawn by code from a small spec; the model never draws.

A spec is ``{"title", "circuits": [{"name", "source", "elements"}]}``: each
circuit is one series loop (source up the left side, elements along the top,
a wire back along the bottom). Element kinds are the closed set in
``models.ELEMENT_KINDS``, so a bad spec fails here with a reason the tutor
can read, and no model-written markup ever reaches the page.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import schemdraw
from schemdraw import elements as elm

from plc_lab.tutor.models import ELEMENT_KINDS


def cache_dir() -> Path:
    """Where rendered SVGs go; resolved at call time so HOME can move."""
    return Path.home() / ".cache" / "plc-lab" / "tutor-diagrams"


_MAX_CIRCUITS: Final = 2
_MAX_ELEMENTS: Final = 6
_FACTORY: Final = {
    "dc_source": elm.SourceV,
    "ac_source": elm.SourceSin,
    "switch": elm.Switch,
    "push_button": elm.Button,
    "resistor": elm.Resistor,
    "lamp": elm.Lamp,
    "led": elm.LED,
    "coil": elm.Inductor2,
    "relay_contact": elm.Switch,
    "capacitor": elm.Capacitor,
    "diode": elm.Diode,
    "fuse": elm.Fuse,
    "motor": elm.Motor,
}


class DiagramError(ValueError):
    """The spec cannot be drawn; the message goes back to the tutor."""


def _check(spec: object) -> list[dict[str, Any]]:
    """The spec's circuits, or :class:`DiagramError` saying what is wrong."""
    circuits = spec.get("circuits") if isinstance(spec, dict) else None
    if not isinstance(circuits, list) or not 1 <= len(circuits) <= _MAX_CIRCUITS:
        msg = f"diagram needs 1-{_MAX_CIRCUITS} circuits"
        raise DiagramError(msg)
    checked: list[dict[str, Any]] = []
    for circuit in circuits:
        elements = circuit.get("elements", []) if isinstance(circuit, dict) else None
        if not isinstance(circuit, dict) or not isinstance(elements, list):
            msg = "each circuit must be an object with an elements list"
            raise DiagramError(msg)
        if len(elements) > _MAX_ELEMENTS:
            msg = f"at most {_MAX_ELEMENTS} elements per circuit"
            raise DiagramError(msg)
        for item in [circuit.get("source", {}), *elements]:
            kind = item.get("kind") if isinstance(item, dict) else None
            if kind not in ELEMENT_KINDS:
                msg = f"unknown element kind {kind!r}; use one of {ELEMENT_KINDS}"
                raise DiagramError(msg)
        checked.append(circuit)
    return checked


def _draw(circuit: dict[str, Any], path: Path) -> None:
    schemdraw.use("svg")
    source = circuit["source"]
    with schemdraw.Drawing(show=False, unit=3) as drawing:
        drawing.config(fontsize=11)
        start = drawing.add(
            _FACTORY[source["kind"]]().up().label(source["label"], loc="left")
        )
        for item in circuit["elements"]:
            element = _FACTORY[item["kind"]]().right().label(item["label"], loc="top")
            drawing.add(element)
        drawing.add(elm.Line().down().toy(start.start))
        drawing.add(elm.Line().left().tox(start.start))
        if circuit.get("name"):
            drawing.add(
                elm.Label()
                .at((drawing.here[0] + 1.5, drawing.here[1] - 1.3))
                .label(circuit["name"])
            )
        drawing.save(str(path))


def render(spec: dict[str, Any], cache: Path | None = None) -> list[str]:
    """Render each circuit to an SVG in ``cache``; return the file names."""
    circuits = _check(spec)
    cache = cache or cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
    names = []
    for index, circuit in enumerate(circuits):
        name = f"{digest}-{index}.svg"
        if not (cache / name).is_file():
            try:
                _draw(circuit, cache / name)
            except (TypeError, ValueError, AttributeError) as err:
                msg = f"could not draw circuit {index}: {err}"
                raise DiagramError(msg) from err
        names.append(name)
    return names
