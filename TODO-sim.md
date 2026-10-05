# Build the Godot sorting line (`sim/`) that OpenPLC drives over Modbus TCP

Draft spec, agreed with kuhy 2026-10-05. Phases 1-2 of the README roadmap.

## what

A Godot 2D plant in `sim/` that stands in for Factory I/O. It is a Modbus TCP
*server* (remote I/O) that the OpenPLC v4 runtime polls as a Remote Device:
FC 2 reads the plant's sensors into %IX and FC 5 writes %QX to the plant's
coils, which drive its actuators. The PLC program decides everything; the
plant only simulates. (Corrected 2026-10-05: a client cannot write discrete
inputs, and OpenPLC's remote device is the master.)

v1 scene:
- one conveyor, with boxes of two heights spawned at its head;
- a photo-eye pair (low and high beam) before a diverter;
- a diverter that pushes tall boxes onto a side belt; short boxes run to the
  end of the main belt;
- start (NO) and stop (NC) buttons, where stop always wins, and an e-stop;
- per-kind counters at both exits.

Out of scope for v1: colour sorting (vision), several stations, 3D.

## where

- `sim/` in this repo: `project.godot`, `scenes/`, `scripts/`, `tests/`.
- `sim/scripts/modbus_server.gd`: a small Modbus TCP server over
  `TCPServer` (Godot has no maintained Modbus addon). It serves FC 1 (read
  coils), 2 (read discrete inputs), 5 (write single coil) and 15 (write
  multiple coils); OpenPLC's remote device uses FC 2 and FC 5 only.
  `sim/scripts/modbus_client.gd` is the mock PLC's side.
- `projects/sorting-line/`: the ST and ladder programs, the Modbus address
  map, and a short video (README phase 2).

## stack

- Godot **4.7.2-stable** (latest stable on 2026-10-05), pinned for CI.
- GUT **v9.6.1** for tests, run headless (`--headless`, required in CI).
- OpenPLC v4 runtime in Docker with `--network host`; the plant added in
  the editor project as a Modbus TCP Remote Device at 127.0.0.1:1502
  (502 needs root).

## must

- Plant I/O is defined once in an address map (`sim/io_map.json` or a
  GDScript const), and the same map is the table in
  `projects/sorting-line/`. Coils (%QX0.x): conveyor motor, side belt motor,
  diverter, run lamp, fault lamp. Discrete inputs (%IX0.x): low beam, high
  beam, start, stop (NC: 1 = not pressed), e-stop (NC), exit sensors.
- Fail safe: if no request arrives for 0.5 s, every actuator goes off and the
  scene shows "PLC offline". Never keep the last command.
- Deterministic: box mix and spawn timing come from a seed; the physics tick
  is fixed, so a test run is reproducible.
- Every claim in the code comments about OpenPLC addressing cites
  user-docs (same bar as the cards).
- must not: no paid or Windows-only tool; no Factory I/O assets.
- optional: a speed slider, a jam injector (a box that sticks) to practise
  fault handling.

## done

- `godot --headless --path sim -s addons/gut/gut_cmdln.gd -gexit` exits 0
  and includes a run of **20 seeded boxes with 0 missorted and 0 jammed**
  against a mock PLC in CI.
  - The mock is a small Modbus TCP client (the master, like OpenPLC) that
    implements the reference sorting logic in GDScript, so CI needs no
    Python or Docker.
- The same 20-box run, by hand, against the real OpenPLC container: once with
  the ST program and once with the ladder program, both 0 missorted and 0
  jammed. Record the counter screenshots in `projects/sorting-line/`.
- CI: a `sim` workflow job runs the headless GUT suite; the existing four
  workflows stay green.

## verify

This PC (Arch), OpenPLC runtime in Docker with `--network host`. The
pre-commit and CI gates as in `CLAUDE.md`, plus the GUT job.

## open before building

- The address map is a draft until the first program is written; it may
  grow (e.g. a box-present sensor at the head).
- Confirm OpenPLC's Modbus coil and input offsets from the editor's
  generated config, not only from the docs: the docs disagree with the code
  on `qxBits` (800 vs 8192).

## read first

- README "Phase 1" and "Phase 2".
- https://github.com/Autonomy-Logic/user-docs/blob/main/docs/openplc-editor/communication/modbus/client.md
- https://docs.godotengine.org/en/stable/classes/class_tcpserver.html
- https://github.com/bitwes/Gut/releases/tag/v9.6.1

REMOVE ME AFTER FINISH
