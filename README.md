# plc-lab

A home lab for learning PLC / industrial automation, and later OT (operational
technology) security. It holds the roadmap, the practice projects and a
source-checked Anki deck. Weekly practice shows up as a commit here: that
is a milestone to aim for, not a lock.

## Roadmap

| Phase | When | What | Done when |
| --- | --- | --- | --- |
| 1. Soft PLC | now | the OpenPLC v4 runtime on this PC, driven by a self-built Godot 2D plant over Modbus TCP | a Godot scene runs from a program I wrote |
| 2. First project | months 1-2 | the Godot sorting line in Structured Text **and** ladder logic | both versions sort correctly; the code and a short video are in `projects/` |
| 3. Real hardware | after ~2 months | OpenPLC on a Raspberry Pi Pico 2 with real 24 V buttons, sensor and lamps (~310 PLN, one-off, ordered) | the sorting line's ST program runs on the Pico 2, with the real I/O standing in for the Godot plant |
| 4. OT security | alongside 2-3 | the ISA/IEC 62443 Cybersecurity Fundamentals Specialist certificate | the certificate is issued |

Study runs the whole time: the `Automation` Anki deck (`deck/`). It is a
separate quota in anki-guard (60 min Mon/Fri/Sat/Sun, 20 min Tue-Thu).

### Phase 1: OpenPLC v4 + a Godot plant

Linux and free tools only: no Windows, no subscriptions.

- **OpenPLC v4** ([Autonomy Logic](https://autonomylogic.com)). v3 reached
  end of life and was archived on 2026-04-04, so skip v3-era tutorials.
  - [Runtime](https://github.com/autonomy-logic/openplc-runtime): Docker
    images for amd64, arm64 and armv7 (`ghcr.io/autonomy-logic/openplc-runtime`).
    There is no web UI as in v3; the editor talks to an HTTPS REST API on
    :8443 and the runtime compiles the program on the device.
  - [Editor](https://github.com/autonomy-logic/openplc-editor): ships a
    Linux AppImage (x86-64 and ARM64).
  - Languages: LD, FBD, ST, SFC (desktop editor only) and IL.
  - Protocols: Modbus TCP (server and client), Modbus RTU (master), OPC UA,
    S7comm and EtherCAT. There is no DNP3 or EtherNet/IP in v4.
  - Docs: [user-docs](https://github.com/autonomy-logic/user-docs).
- **Modbus server.** It is off until the project adds one in the editor;
  the editor's default port is 502
  ([server docs](https://github.com/Autonomy-Logic/user-docs/blob/main/docs/openplc-editor/communication/modbus/server.md)).
  Run the container with `--network host` (as the install script does) or
  publish 502 as well, or the plant cannot reach it.
- **The plant is a Godot 2D scene** that is the Modbus TCP *client*: it
  reads coils (%QX: motors, diverters) and writes discrete inputs (%IX:
  photo-eyes, buttons). Godot has no Modbus addon, so the client is a small
  GDScript class over
  [StreamPeerTCP](https://docs.godotengine.org/en/stable/classes/class_streampeertcp.html).

### Phase 2: the sorting line

- A conveyor carries boxes of two heights past a photo-eye pair; a diverter
  pushes tall boxes to a side belt. Start/stop buttons, a stop that always
  wins, and a count of each kind.
- Write it twice: once as a CASE state machine in Structured Text, once in
  ladder logic with seal-ins, timers and edge detection. Both go in
  `projects/sorting-line/`, along with the Modbus address map and a short
  video.
- The plant lives in `sim/`; its spec is `TODO-sim.md`.

### Phase 3: a Pico 2 with real 24 V I/O

- **The controller is a Raspberry Pi Pico 2**, not a Pi. The v4 runtime
  ships no free Pi GPIO driver: GPIO comes as a closed vendor package, and the
  open [libgpiod plugin](https://github.com/Autonomy-Logic/openplc-runtime/pull/80)
  is unmerged. The editor lists the "Raspberry Pico 2", and for such boards
  "The firmware is uploaded directly to the board via USB"
  ([board selection](https://github.com/Autonomy-Logic/user-docs/blob/main/docs/openplc-editor/hardware-configuration/board-selection.md)).
- **Levels** ([Pico 2 datasheet](https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf)):
  GPIO is fixed at 3.3 V, and VBUS (pin 40) is the 5 V USB input, which
  feeds the relay coils.
- **Wiring rules:**
  - 24 V signals reach the Pico only through the PC817 opto board; its
    output side runs from the Pico's 3.3 V. The board is rated from 3.6 V,
    so bench-test one channel first.
  - The relay board: remove the JD-VCC jumper, coils (JD-VCC) from VBUS,
    logic (VCC) from 3.3 V. Its inputs are active-low.
  - Keep the 24 V 0 V apart from the Pico's GND; the opto and relay boards
    isolate the two.
  - The sensor is PNP NO: its output goes to an opto input's IN+, 0 V to IN-.
- **Parts**, ordered 2026-10-05 from two shops (no single shop stocks
  all of them). 310.60 PLN with shipping.

| Part | Shop | Qty | PLN |
| --- | --- | --- | --- |
| [Raspberry Pi Pico 2 H](https://kamami.pl/plytki-bazowe-z-rp2040-i-rp235x/1196679-raspberry-pi-pico-2-h-ze-zlaczami-rp2350-arm-cortex-m33-risc-v-hazard3.html) (headers soldered) | Kamami | 1 | 29.05 |
| [PC817 opto board](https://kamami.pl/en/electronic-modules/1183108-pc817-module-with-8-optocouplers.html), 8 ch, 3.6-24 V in | Kamami | 1 | 11.67 |
| [Relay board](https://kamami.pl/moduly-z-wyjsciami-mocy/1200540-modul-przekaznikow-4-kanaly-z-optoizolacja-10-a-250-v-ac-cewka-5-v-5902186331518.html), 4 ch, opto-isolated, 5 V coils | Kamami | 1 | 18.27 |
| [Kradex Z74J box](https://kamami.pl/obudowy/1180010-z74j-ps-obudowa-plastikowa-5905275011629.html) | Kamami | 1 | 16.84 |
| [F-F jumpers](https://kamami.pl/przewody-f-f/204596--przewody-polaczeniowe-f-f-roznokolorowe-17-cm-40-szt-5906623440849.html), 17 cm, 40 pcs | Kamami | 1 | 5.69 |
| [Silicone wire 16 AWG](https://kamami.pl/przewody-jednozylowe/588149-przewod-jednozylowy-silikonowy-16awg-4m-czerwony-5906623475766.html), per metre | Kamami | 3 | 24.03 |
| [Wago 221-413](https://kamami.pl/en/quick-couplers/1180759-compact-installation-coupler-3-wire-4mm-221-413-5906623436842.html), 3-way | Kamami | 4 | 11.60 |
| [Step drill 4-22 mm](https://kamami.pl/wiertla-do-metalu/1186564-wiertlo-stopniowe-4-22mm-yato-yt-44741-5906083013270.html), for the lid holes | Kamami | 1 | 16.35 |
| [DR-30-24 PSU](https://jccentrum.pl/produkt/zasilacz-na-szyne-dr-30-24-30w-24v-130a/), 24 V 1.3 A DIN | JC Centrum | 1 | 62.00 |
| [M12 inductive sensor](https://jccentrum.pl/produkt/czujnik-zblizeniowy-indukcyjny-m12-pnp-no-sn-4/), PNP NO, Sn 4 mm | JC Centrum | 1 | 27.00 |
| [XB5AA momentary button](https://jccentrum.pl/produkt/przycisk-sterowniczy-xb5az21-bistabilny-on-off-czarny/), 22 mm: green NO + red NC | JC Centrum | 2 | 30.00 |
| [E-stop](https://jccentrum.pl/produkt/przycisk-awaryjny-bezpieczenstwa-nonc-stop-22mm/), 22 mm mushroom, NO+NC | JC Centrum | 1 | 24.00 |
| [AD16-22DS lamp](https://jccentrum.pl/produkt/lampka-led-sygnalizacyjna-tablicowa-24v-ac-dc-ad16-22ds/), 24 V AC/DC: green + red | JC Centrum | 2 | 11.20 |
| Shipping | both | | 22.90 |
| **Total** | | | **310.60** |

The Kamami relay page does not state 3.3 V control (Botland's listing of the
same board does); check it with one channel before wiring the rest.

### Phase 4: ISA/IEC 62443 Cybersecurity Fundamentals Specialist

- The certificate needs course **IC32** and its exam. The course comes in
  four forms: classroom (2 days), IC32V (virtual), IC32E (8 weeks online) and
  IC32M (self-paced).
  - The course fee includes the exam: 90 multiple-choice questions in 2 hours.
  - You can take the exam online.
  - Cost: $1,728 for ISA members, $2,160 for non-members.
  - It never needs renewal.
  - Source: [ISA](https://www.isa.org/certification/certificate-programs/cybersecurity).
- The certificates that follow it: Risk Assessment, Design and Maintenance
  Specialist. Holding all four makes you an *Expert*.
- Free preparation:
  - [CISA ICS Virtual Learning Portal](https://www.cisa.gov/resources-tools/training/ics-virtual-learning-portal):
    100W and the 210W series.
  - [ICS300](https://www.cisa.gov/resources-tools/training/advanced-cybersecurity-industrial-control-systems-ics300).
  - [NIST SP 800-82r3](https://doi.org/10.6028/NIST.SP.800-82r3).

## The deck

`deck/<topic>.json` holds 157 cards across six topics: fundamentals,
ladder logic, Structured Text/SFC, field devices, protocols and OT security.
Each card has:

- `source`: the URL it was written from.
- `excerpt`: verbatim text from that page that supports the answer.

The answers are paraphrased. Only the excerpt is quoted, and it is shown with
a link to its source.

```bash
scripts/setup_dev.sh
.venv/bin/python -m plc_lab check   # every excerpt must be in its source
.venv/bin/python -m plc_lab build   # -> build/automation.apkg (Automation::<topic>)
```

`check` fetches each source once into `~/.cache/plc-lab/sources`, reduces it
to plain text (PDFs go through `pdftotext`) and requires the excerpt to
appear in it. `build` refuses to write a package while any excerpt is
missing. Note ids are stable, so re-importing an updated package updates
the cards in place.

## Licence

- The code is under the MIT licence (`LICENSE`).
- The card text is under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
  because many excerpts are quoted from Wikipedia.
- Every other excerpt is a short attributed quotation that stays its
  owner's. Each card links to its source.
