# Sorting line

The README Phase 2 exercise: the same sorting logic written twice for
OpenPLC v4, once as a CASE state machine in Structured Text and once in
ladder logic, both driving the Godot plant in `sim/`. The two programs, the
counter screenshots and a short video go in this directory.

Done: the plant runs 20 boxes (`--boxes=20 --seed=1`) with 0 missorted and
0 jammed, once under the ST program and once under the ladder program.

## The plant

`sim/` is a Godot 2D scene that acts as Modbus TCP **remote I/O**: a server
on `127.0.0.1:1502`, unit 1. It serves its sensors and buttons as read-only
discrete inputs and takes its motors, diverter and lamps as coils. If no
request arrives for 0.5 s, every coil drops to off and the scene shows
"PLC offline".

- Run against OpenPLC: `godot --path sim -- --seed=1 --boxes=20`
- Run with the built-in reference PLC instead: `godot --path sim -- --mock --autostart`
- Keys: hold S to start, hold X to stop, E toggles the e-stop. The buttons on
  screen also take mouse clicks.

## Address map

The plant's addresses, as defined in `sim/scripts/io_map.gd`.
`sim/tests/unit/test_io_map.gd` fails if this table and `IoMap` drift apart.
NC contacts read 1 while they are *not* pressed, so a broken wire reads as a
stop.

| kind | address | name | meaning |
|---|---|---|---|
| DI | 0 | start | start button, NO: 1 while pressed |
| DI | 1 | stop_ok | stop button, NC: 0 while pressed |
| DI | 2 | estop_ok | e-stop, NC: 0 while latched in |
| DI | 3 | low_beam | low photo-eye blocked (any box) |
| DI | 4 | high_beam | high photo-eye blocked (tall box only) |
| DI | 5 | at_diverter | a box at the diverter |
| DI | 6 | diverter_out | diverter fully extended |
| DI | 7 | diverter_home | diverter fully retracted |
| DI | 8 | main_exit | a box at the end of the main belt |
| DI | 9 | side_exit | a box at the end of the side belt |
| coil | 0 | main_motor | main belt motor |
| coil | 1 | side_motor | side belt motor |
| coil | 2 | diverter | 1 = extend, 0 = retract |
| coil | 3 | run_lamp | run lamp |
| coil | 4 | fault_lamp | fault lamp |

The required behaviour: stop and e-stop always win over start; tall boxes
go to the side belt and short boxes run to the main exit; a box that the
diverter catches half-way jams the line.

## OpenPLC v4 runbook

OpenPLC is the Modbus master and the plant is its Remote Device
([remote device docs](https://github.com/Autonomy-Logic/user-docs/blob/main/docs/openplc-editor/communication/modbus/client.md)).

1. Start the runtime on the host network, so that `127.0.0.1` inside the
   container is this PC's loopback, where the plant listens. The upstream
   `docker run` uses `-p 8443:8443`, which gives the container its own
   loopback, so it would not reach the plant.

   ```bash
   docker run -d --name openplc-runtime --network host \
     --cap-add=SYS_NICE --cap-add=SYS_RESOURCE \
     -v openplc-runtime-data:/var/run/runtime \
     ghcr.io/autonomy-logic/openplc-runtime:latest
   ```

2. Start the plant: `godot --path sim -- --seed=1 --boxes=20`. It shows
   "PLC offline" until the runtime polls it.
3. In the editor project, click **+**, choose **Remote Device**, set the
   protocol to **Modbus**, and name it `plant`. Then set the transport:
   **TCP/IP**, IP `127.0.0.1`, port `1502`, slave ID `1`, timeout `1000` ms.
4. Add the I/O groups:
   - `sensors`: **Read Discrete Inputs (FC 2)**, offset 0, length 10, error
     handling **Set to zero**. If the link fails, the NC stop and e-stop
     inputs then read as pressed, so the program stops the line.
   - One **Write Single Coil (FC 5)** group per coil: `main_motor` at offset 0,
     `side_motor` at 1, `diverter` at 2, `run_lamp` at 3 and `fault_lamp` at 4,
     each with length 1. FC 5 writes one bit per cycle, and the editor offers
     no FC 15.
   - Leave the cycle times at 100 ms. All six groups then poll well inside
     the plant's 0.5 s watchdog.
5. Expand each group and give every point an **alias** from the table
   (`start`, `stop_ok`, ..., `fault_lamp`). The programs use the aliases,
   never bare `%IX`/`%QX` addresses, because the editor assigns those and
   they move when the groups change.
6. Upload the program and start the runtime. The plant's status line turns to
   "PLC online (Modbus master)". Hold S to start the line.

## Open questions

- Read the local `%IX`/`%QX` addresses off the expanded groups (or the
  editor's generated config), not from the docs alone: the docs and the
  runtime code disagree on `qxBits` (800 vs 8192).
- The address map may grow once the first program is written, e.g. with a
  box-present sensor at the head of the belt. Change `io_map.gd` and this
  table together.
