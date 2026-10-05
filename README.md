# plc-lab

A home lab for learning PLC / industrial automation, and later OT (operational
technology) security. It holds the roadmap, the practice projects and a
source-checked Anki deck. Weekly practice shows up as a commit here: that
is a milestone to aim for, not a lock.

## Roadmap

| Phase | When | What | Done when |
| --- | --- | --- | --- |
| 1. Soft PLC | now | OpenPLC on a Raspberry Pi, driven by Factory I/O | a Factory I/O scene runs from a program I wrote |
| 2. First project | months 1-2 | a Factory I/O sorting line in Structured Text **and** ladder logic | both versions sort correctly; the code and a short video are in `projects/` |
| 3. Real hardware | after ~2 months | a Siemens S7-1200 (G2) starter kit with TIA Portal STEP 7 Basic | the sorting line runs on the S7-1200 |
| 4. OT security | alongside 2-3 | the ISA/IEC 62443 Cybersecurity Fundamentals Specialist certificate | the certificate is issued |

Study runs the whole time: the `Automation` Anki deck (`deck/`). It is a
separate quota in anki-guard (60 min Mon/Fri/Sat/Sun, 20 min Tue-Thu).

### Phase 1: OpenPLC + Factory I/O

- **OpenPLC v4** ([Autonomy Logic](https://autonomylogic.com)). v3 reached
  end of life and was archived on 2026-04-04, so skip v3-era tutorials (v4
  has no web UI on :8080).
  - [Runtime](https://github.com/autonomy-logic/openplc-runtime): prebuilt
    binaries for amd64, arm64 and armv7, so it runs on a Pi.
  - [Editor](https://github.com/autonomy-logic/openplc-editor): ships a
    Linux AppImage.
  - Languages: LD, FBD, ST, SFC and IL.
  - Protocols: Modbus TCP/RTU (server and client), OPC UA, S7comm and
    EtherCAT. There is no DNP3 or EtherNet/IP in v4.
  - Docs: [user-docs](https://github.com/autonomy-logic/user-docs).
- **Factory I/O** ([Real Games](https://factoryio.com)) is the 3D plant
  simulator. It talks to OpenPLC as a Modbus TCP *client*, with OpenPLC as
  the server.
  - **⚠ Windows only** ("Windows 7 SP1+ or higher", a DX10+ GPU). There is no
    Linux build, and there are no Wine reports (no WineHQ AppDB entry, not on
    Steam). It needs a Windows machine next to the Arch box.
  - **⚠ Edition matters.** The €40/yr Starter edition has no Modbus driver.
    Reaching OpenPLC needs *Modbus & OPC* (€158/yr) or *Ultimate* (€278/yr).
    Ultimate also has the S7-1200 and PLCSIM drivers, so one licence covers
    phases 1-3. There is a 30-day full trial ([editions](https://factoryio.com/editions)).

### Phase 2: the sorting line

- Scenes: [Sorting by Height (Basic)](https://docs.factoryio.com/manual/scenes/)
  first, then *Sorting by Height (Advanced)* and *Sorting Station* (colour,
  with a vision sensor).
- Write it twice: once as a CASE state machine in Structured Text, once in
  ladder logic with seal-ins, timers and edge detection. Both go in
  `projects/sorting-line/`, along with the Modbus address map and a short
  video.

### Phase 3: Siemens S7-1200 G2

- The S7-1200 **G2** is the current generation. It needs **TIA Portal V20**
  or newer ([Siemens, 2024-11-07](https://press.siemens.com/global/en/pressrelease/tia-portal-version-20-enabling-peak-performance-and-efficiency)).
- A typical starter kit is a CPU 1212C plus STEP 7 Basic.
- **⚠ TIA Portal runs on Windows 10/11 only.** There is a 21-day trial of
  STEP 7 + PLCSIM, which needs a free Siemens account.

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
