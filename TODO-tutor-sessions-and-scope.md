# Keep the tutor on its card, credit plain active time, link every session

Agreed with kuhy on 2026-10-10 in the run.sh / earned_time 0.7.0 session.
Every decision below is already settled: build it, don't re-ask.

## what
Session `20261010-145758-50bc` went off track. The card was "What is a PLC,
in one sentence?", but its one graded check (a packaging-jam design task)
was failed, then drilled into scan-cycle pseudocode for 15+ minutes. No check
passed, so 21 active minutes credited nothing and the card could never be
done. Fix the scope, the crediting and the card end, and make sessions
addressable by URL.

## must
1. **Credit = active time, no check gate.** Every 15 active minutes is a
   credited block (`clock.py`: drop "at least one passed check since the
   previous block"; `ready_blocks()` / `blocks_pending_check`). Blocks stay
   15 min (earned_time pays per 15-min unit, max 4). Keep the 6 min reply
   window and the filler/low-effort rules. Header status, plain:
   `Active 21 min · credited 15 · next 15 at 30 min`. Remove "waiting for a
   passed check" and every other check wording from the clock status
   (`app.js:124`).
2. **Checks test the target card only** (`prompt.py` rule 5 + `engine_note`).
   For a definition card the check is "state/explain the card's answer in your
   own words", not an open design task. Pass bar = the card's answer.
3. **One check never holds the session open.** After "not yet": re-teach the
   gap once, re-ask the same core question; the check closes on the next
   answer either way (`conversation.apply_checks`, `engine_note` check_open).
4. **Card end.** When a passed check covers the card's answer, the tutor says
   the card is done and the page shows "Card done ✓" with **Next card** (same
   session, the clock carries on) and **Stop here**. `engine.py:231` already
   sets `message["card_done"]`; `app.js` renders nothing for it today.
5. **Session URL.** `http://127.0.0.1:8778/#<session_id>` opens that session:
   the live one interactive, a past one read-only (transcript from
   `~/.local/share/automation_tutor/sessions/<id>.jsonl`). The page shows the
   id in the header and keeps `location.hash` in sync. Add a read-only
   `GET /api/session/<id>` (id validated against the file-name pattern) so a
   Claude session can fetch a transcript from a URL kuhy pastes.
6. **History panel.** It lists past sessions (date, card, active and credited
   minutes, done or not); a click opens `#<id>`. **Repeat** starts a fresh
   session on the same card. No editing or deleting of transcripts.
- must not: forge or back-fill ledger rows (21 min of `20261010-145758-50bc`
  stays uncredited unless the new clock credits it on resume by itself);
  change earned_time; touch the HMAC key.
- Already uncommitted in the tree: `prompt.py` + `tests/test_prompt.py`
  ("check question only in `check`, never also in `message`"). It is deployed,
  but no real check has been seen since the change. Verify it, then commit it
  with item 2.

## done
- `.venv/bin/python -m pytest -q` passes at 100 % coverage, and
  `.venv/bin/ruff check . && .venv/bin/python -m mypy plc_lab` exit 0.
- `scripts/tutor_scripted_run.sh` (sandboxed): adjudication passes, a block
  credits with no passed check after 15 active minutes, and the transcript
  shows `card_done` followed by the Next card / Stop here choice.
- `curl -s http://127.0.0.1:8778/api/session/20261010-145758-50bc | jq -e
  '.messages | length > 0'` exits 0 after deploy.

## verify
Deploy with `scripts/tutor_deploy.sh` (never serve the working tree). Then
kuhy runs one real card at `http://127.0.0.1:8778/` and confirms: the
status reads plainly, checks stay on the card, the card ends with the choice,
and the `#<id>` URL reopens the session. Behaviour first, tests after
(kuhy's workflow), then commit with `~/.claude/scripts/finish_auto.sh`.

## read first
- `plc_lab/tutor/clock.py` (module docstring = the crediting rules)
- `plc_lab/tutor/prompt.py` rules 5, 7, 10, 11
- `plc_lab/tutor/engine.py` `_apply`, `plc_lab/tutor/resume.py`
- `plc_lab/tutor/static/app.js` (status line ~124, renderMessage)
- earned_time `AUTOMATION_TUTOR` (15 min units, max 4), `~/src/utils`

REMOVE ME AFTER FINISH
