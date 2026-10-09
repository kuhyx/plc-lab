# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""A simulated learner who knows nothing, driving the tutor over its HTTP API.

Run against a server started with ``--simulate-time`` and a sandboxed
``AUTOMATION_TUTOR_DATA`` / ``AUTOMATION_TUTOR_KEY`` (``scripts/tutor_scripted_run.sh``
does all of it), so no real gaming time is ever minted. The learner is a cheap
isolated model; two replies are forced to filler so ``low_effort`` is exercised.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from typing import Any, Final
import urllib.request

from plc_lab.tutor.session import TutorSession, isolated_options

LEARNER_MODEL: Final = "claude-haiku-5-5"
FORCED: Final = {2: "ok", 5: "idk"}
_PERSONA: Final = """\
You role-play a learner in a tutoring chat. You are a software engineer who \
knows NOTHING about electricity or industrial automation: you do not really \
know what voltage, current, DC, AC, a coil or a relay is (you have only heard \
the words; you think voltage is "the number on a wall socket"). Rules: reply \
in 1-3 plain sentences, first person, as the learner would type. When asked \
what you know, say honestly what little you know and that you are lost on the \
rest. Make real attempts when asked to predict, even if wrong at first. After \
the tutor explains something clearly, restate it in your own words, \
imperfectly. When given a comprehension check, answer it fully in your own \
words using what you were taught. Never mention being an AI or a role-play.
"""


def _call(url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=420) as resp:
        parsed: dict[str, Any] = json.loads(resp.read())
    return parsed


def _page_notes(message: dict[str, Any]) -> str:
    """What the page shows beside the tutor's words (the learner model is text-only)."""
    notes = [f"[picture on the page: {i['title']}]" for i in message.get("images", [])]
    if message.get("diagrams"):
        notes.append(
            f"[circuit diagram on the page: {message.get('diagram_title', '')}]"
        )
    return "\n".join(notes)


async def run(
    base: str,
    card_id: str,
    max_turns: int,
    advance_s: float,
    hook: tuple[int, str] | None = None,
) -> dict[str, Any]:
    """Drive one session; stop when the card is done and a block is recorded."""
    learner = TutorSession(
        isolated_options(_PERSONA, model=LEARNER_MODEL, structured=False, effort="low")
    )
    state = await asyncio.to_thread(_call, f"{base}/api/start", {"card_id": card_id})
    try:
        for turn in range(max_turns):
            tutor_text = state["messages"][-1]["text"]
            done = any(m.get("card_done") for m in state["messages"])
            if done and any(r["recorded"] for r in state["receipts"]):
                break
            if turn in FORCED:
                text = FORCED[turn]
            else:
                shown = _page_notes(state["messages"][-1])
                prompt = f"Tutor says:\n{tutor_text}\n{shown}\nYour reply:"
                text = (await learner.ask_raw(prompt)).text.strip()
            if hook and turn == hook[0]:
                await asyncio.to_thread(
                    subprocess.run, ["/bin/bash", "-c", hook[1]], check=False
                )
            print(f"[{turn}] learner: {text[:100]!r}", file=sys.stderr)
            state = await asyncio.to_thread(
                _call, f"{base}/api/message", {"text": text, "advance_s": advance_s}
            )
    finally:
        await learner.close()
    return state


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8779")
    parser.add_argument("--card", default="io-24vdc-relay-coil")
    parser.add_argument("--max-turns", type=int, default=22)
    parser.add_argument(
        "--hook-after", type=int, help="turn after which to run --hook-cmd"
    )
    parser.add_argument(
        "--hook-cmd", help="shell command run mid-session (a screenshot)"
    )
    parser.add_argument("--advance", type=float, default=110.0)
    args = parser.parse_args()
    hook = (args.hook_after, args.hook_cmd) if args.hook_cmd else None
    state = asyncio.run(run(args.url, args.card, args.max_turns, args.advance, hook))
    print(
        f"session {state['session_id']}: {len(state['messages'])} messages, "
        f"credited {state['credited_minutes']}/{state['target_minutes']} min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
