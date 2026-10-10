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

## status after session 1 (2026-10-10 ~16:10) -- read this first

Built and DEPLOYED (release 20261010-160529), uncommitted in this tree:
items 1-6 above, plus later kuhy decisions (all settled, don't re-ask):
- Credit is PER ACTIVE MINUTE, not 15-min blocks (`UNIT_SECONDS` 60, 60/session;
  daily cap 60 enforced by the ledger). One ledger row per engine turn,
  `detail.minutes`, entry id `<sid>-m<last minute>`; paid minutes are read
  from the LEDGER (`credit.session_minutes`). `backfill_today` pays today's
  unpaid minutes at server start (done: 50bc +12, b193 +10, 37a4 +8).
- earned_time 0.8.0 (per-minute tutor) is released (tag pushed) and installed
  on the host; screen-locker stamp migrated 1 -> 15; consumers restarted;
  side-by-side showed the bonus pass adds nothing.
- card_done has NO check gate; `POST /api/card_done` manual override (Mark
  card done / Mark done / Mark not done); repair marked relay-panel done (b193).
- Next card = END this session + start a NEW one (one card, one session).
- Archive: `POST /api/archive`, progress.json `archived`; no-reply sessions
  auto-archived; live session can't be archived; "Show archived (N)".
- Layout: chat and side panel scroll separately; composer always visible;
  wheel anywhere outside the side panel scrolls the chat (`static/wheel.js`).
- daily-limits reinstalled: bar shows still-earnable minutes (live).
- Prompt: checks only on the card's answer; an own-words answer = pass +
  card_done same turn; no re-asking / no drilling once answered; scope
  objections aren't low effort; never mention engine notes.
- Scripted run (sandboxed) passed a,b,d,e,f,g,h; c (diagram) failed once
  (model variance, pre-existing item).

Remaining, in order:
1. DONE: kuhy confirmed the live tutor works (2026-10-10).
2. DONE: daily-limits 68fc2c4 (still-earnable minutes, done rows hide their
   amounts like the bar, earned_time 0.8.0, installed, CI green). CI needed
   the stale `pub-3.47.7-Linux-*` cache deleted: utils `flutter-setup`'s
   prefix `restore-keys` restores an old pub cache that breaks `pub get`
   after a git-dep bump ("package_graph.json: dependencies for X missing").
STATUS 2026-10-10 ~16:35 (session 2, cut off by usage limit):
- plc-lab .venv now earned_time 0.8.0 (pin bumped in pyproject), redeployed.
- 5b DONE (uncommitted): tutor_deploy.sh checks every <script> the page loads.
- 5 DONE: locker-earner SKILL.md updated (per minute, 0.8.0 row contract).
- 3 PARTIAL: test agent for adjudicate/scripted/main/prompt/server/history/
  routes_sessions finished (100%, 113 pass). Agents for clock/credit/
  unit_credit/ledger_io/backfill and engine/resume/cardflow/repair/store/
  _fakes were STOPPED mid-way: their test files are half-edited; rerun the
  full suite and finish those modules.
- 4 PARTIAL (uncommitted): pins bumped in screen-locker (3 files, .venv on
  0.8.0) and steam-backlog-enforcer (.pre-commit-config; its other 5 dirty
  files are the 0.8.0 change). screen-locker gate fails 1 test:
  tests/test_gate_bonus.py::test_the_real_tutor_rung_pays_15_per_block_then_nothing
  (written for 0.7.0; rewrite for 0.8.0 legacy-block = 15 min, cap 60).
  steam-backlog-enforcer not yet gated/committed.
3. plc-lab tests to 100% branch coverage: fix the failing old tests (clock,
   credit, engine, resume, adjudicate, scripted, main, server; 18 mypy errors
   all under tests/) and cover new modules (cardflow, unit_credit, ledger_io,
   backfill, repair, history, routes_sessions). Use coverage-grinder agents.
   Pin earned-time v0.8.0 in pyproject.toml (dependency-freshness gate).
   Pre-commit, rerun the program, commit with `~/.claude/scripts/finish_auto.sh`.
4. Re-pin earned-time v0.8.0 in screen-locker (pyproject, requirements,
   .pre-commit-config + .venv reinstall), steam-backlog-enforcer (same three
   files ONLY; its tree is dirty with 66 unrelated files), daily-limits.
5. Update `~/.claude/skills/locker-earner/SKILL.md` ("15 per block x 4" ->
   per minute, 0.8.0, detail.minutes contract).
5b. `scripts/tutor_deploy.sh` smoke `node --check`s only app/report/net.js: check every `static/*.js` (session, history, wheel are unchecked).
6. Remove worktrees: `~/src/utils-earned-0.8` (branch earned-time-0.8.0,
   merged) and `.claude/worktrees/agent-a4a8ba8a291a683a6`.
7. Delete this file when done.

REMOVE ME AFTER FINISH
