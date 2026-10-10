# Tutor: adjudication item c (diagram) still fails

Everything else from the 2026-10-10 tutor scope/credit/sessions work is done
and committed (plc-lab 5c66c96, daily-limits 68fc2c4, screen-locker 5eb18b9,
steam-backlog-enforcer c518c44). One done-criterion is unmet.

## what
`scripts/tutor_scripted_run.sh` passes a, b, d, e, f, g, h but fails
**c. >=1 Commons image with attribution and >=1 code-drawn diagram** — twice
in a row on 2026-10-10 (sessions before and after the refactor; last run
`20261010-182508-cc32`: 1 image, 0 diagrams).

## evidence
- The model never TRIED: every tutor turn has `"diagram": null`; no diagram
  error in `build/tutor-run/server.log`. Rendering is not the problem.
- The diagram rule is unchanged (`plc_lab/tutor/prompt.py:57`, "diagram
  whenever you explain how parts connect"). The 2026-10-10 prompt additions
  (checks only on the card, no drilling, own-words answer ends the card) may
  crowd it out; not proven.

## must
- kuhy decides first: accept c as model variance (then drop c from the
  scripted run's required set, or make it advisory), or tighten the prompt
  so a relay/coil explanation always carries a `diagram`.
- must not: weaken item c's check to make it pass.

## done
`scripts/tutor_scripted_run.sh` reports PASS for c in 2 consecutive runs, or
kuhy has accepted c as advisory and the script no longer requires it.

REMOVE ME AFTER FINISH
