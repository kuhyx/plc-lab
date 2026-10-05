# plc-lab -- notes for agents

Read README.md first. These are the invariants that are easy to break.

## Invariants

- **Every card is checked against its source by code.** `source` is the URL
  the card was written from and `excerpt` is verbatim text from that page.
  `python3 -m plc_lab check` must report N/N before a build; `build` refuses
  otherwise. Never hand-edit an excerpt to "make it pass" -- re-read the page.
- **Answers are paraphrased.** Only `excerpt` is quoted. IEC 62443 itself is
  paywalled: cite ISA's public pages, never a copy of the standard.
- **The deck is `Automation`.** anki-guard's `automation` quota counts the
  `Automation` deck and its subdecks only, so every topic is
  `Automation::<title>` (`plc_lab/deck.py`).
- **Ids are stable.** Model, deck and note GUIDs derive from fixed keys and
  the card `id`. Renaming an `id` makes a new note on the phone; keep ids.
- **Topic files stay under 250 lines.** Add a topic in `cards.TOPICS` rather
  than growing a file past the cap.

## Layout

- `deck/<topic>.json` -- the cards (one array per topic, `cards.TOPICS`).
- `plc_lab/sources.py` -- fetch (cached in `~/.cache/plc-lab/sources`),
  HTML/PDF to text, normalise, check.
- `plc_lab/deck.py` -- genanki package; `plc_lab/cli.py` -- `check`/`build`.

## Commands

- run: `.venv/bin/python -m plc_lab build`
- test: `.venv/bin/python -m pytest -q`
- test-changed: `scripts/test_changed.sh`
- lint: `.venv/bin/ruff check . && .venv/bin/python -m mypy plc_lab`
- coverage: `.venv/bin/python -m pytest -q --cov-report=lcov:coverage.lcov`
- coverage-gaps: `coverage-gaps coverage.lcov`
